"""
Plan Separe — Módulo UI Manual para separaciones (anticipos de clientes).

Regla operacional:
  - Separe es UI manual, NO agente IA
  - SIN bloqueo de inventario
  - SIN facturación automática (Contador factura desde Loanbook)
  - request_with_verify() OBLIGATORIO en POST a Alegra
  - Si Alegra falla → NO guardar abono en MongoDB (retorna error)
  - SIN eventos al bus roddos_events

Journal pattern (al registrar abono):
  DÉBITO  Banco (5314 / 5315 / 5318 / 5319 / 5321 / 5322 / 5536)
  CRÉDITO 5370 (2805 Anticipos y avances recibidos)
  Concepto: "Plan Separe - Anticipo - CC {cliente} - {nombre}"

Cuando Contador factura la venta (flujo existente en Loanbook), el abono
previamente causado (pasivo 2805) se cruza contra la factura — NO se toca
acá.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from core.datetime_utils import now_bogota, today_bogota, now_iso_bogota

from fastapi import APIRouter, Body, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from core.auth import get_current_user
from core.database import get_db
from core.events import publish_event
from services.alegra.client import AlegraClient, AlegraError

logger = logging.getLogger("routers.plan_separe")

router = APIRouter(prefix="/api/plan-separe", tags=["plan-separe"])


# ═══════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════

CUENTA_ANTICIPOS = "5370"  # code 2805 — Anticipos y avances recibidos
MATRICULA_PROVISION = 580_000  # COP fijo

# Bancos — lookup table Spanish label → Alegra category ID
BANCOS_ID = {
    "bancolombia_2029": "5314",
    "bancolombia_2540": "5315",
    "bbva_0210": "5318",
    "bbva_0212": "5319",
    "davivienda_482": "5322",
    "banco_bogota": "5321",
    "global_66": "5536",
    "nequi": "5314",  # Nequi se concilia contra Bancolombia por default
    "efectivo": "5314",  # efectivo entra al Bancolombia principal
}

BANCOS_LABEL = {
    "bancolombia_2029": "Bancolombia 2029",
    "bancolombia_2540": "Bancolombia 2540",
    "bbva_0210": "BBVA 0210",
    "bbva_0212": "BBVA 0212",
    "davivienda_482": "Davivienda 482",
    "banco_bogota": "Banco de Bogotá",
    "global_66": "Global 66",
    "nequi": "Nequi (→ Bancolombia 2029)",
    "efectivo": "Efectivo (→ Bancolombia 2029)",
}

ESTADOS_SEPARE = {"activa", "completada", "facturada", "cancelada"}


# ═══════════════════════════════════════════
# Pydantic models
# ═══════════════════════════════════════════


class CrearSeparacionBody(BaseModel):
    cliente_cc: str
    cliente_nombre: str
    cliente_telefono: str = ""
    cliente_tipo_documento: str = "CC"
    moto_modelo: str
    cuota_inicial: float = Field(..., gt=0)
    moto_precio_venta: float | None = None
    notas: str | None = None


class EditarSeparacionBody(BaseModel):
    """Fields that are EDITABLE via PATCH. Anything else in the body → 422.

    Read-only (rejected with 422):
      separacion_id, estado, pagado, porcentaje_pagado, total_abonado,
      created_at, abonos, alegra_invoice_id, audit.
    """
    cliente_nombre: str | None = None
    cliente_documento_tipo: str | None = None  # CC | PPT | CE | TI
    cliente_documento_numero: str | None = None
    cliente_telefono: str | None = None
    moto_modelo: str | None = None
    cuota_inicial_esperada: float | None = None
    notas: str | None = None
    motivo: str | None = None  # Motivo del cambio (audit trail)


class RegistrarAbonoBody(BaseModel):
    monto: float = Field(..., gt=0)
    fecha: str | None = None  # yyyy-MM-dd
    banco: str
    referencia: str | None = None
    registrado_por: str | None = None


class CancelarBody(BaseModel):
    razon: str = ""


class NotificarContadorBody(BaseModel):
    notificado_por: str | None = None


class CambiarMotoBody(BaseModel):
    moto_modelo: str
    moto_precio_venta: float | None = None
    razon: str = ""


# ═══════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════


def _clean(doc: dict | None) -> dict | None:
    if doc:
        doc.pop("_id", None)
    return doc


def _compute_fields(doc: dict) -> dict:
    """Compute saldo_pendiente, porcentaje_pagado from abonos[]."""
    cuota_inicial = float(doc.get("moto", {}).get("cuota_inicial_requerida", 0) or 0)
    abonos = doc.get("abonos") or []
    total = sum(float(a.get("monto", 0) or 0) for a in abonos)
    saldo = max(cuota_inicial - total, 0)
    pct = round((total / cuota_inicial) * 100, 2) if cuota_inicial > 0 else 0
    doc["total_abonado"] = total
    doc["saldo_pendiente"] = saldo
    doc["porcentaje_pagado"] = pct
    return doc


async def _next_separacion_id(db: AsyncIOMotorDatabase) -> str:
    """Generate PS-YYYY-NNN sequential id."""
    year = today_bogota().year
    prefix = f"PS-{year}-"
    # Find last one
    last = await db.plan_separe_separaciones.find(
        {"separacion_id": {"$regex": f"^{prefix}"}}
    ).sort("separacion_id", -1).limit(1).to_list(length=1)
    next_num = 1
    if last:
        try:
            tail = last[0]["separacion_id"].split("-")[-1]
            next_num = int(tail) + 1
        except (ValueError, IndexError, KeyError):
            next_num = 1
    return f"{prefix}{next_num:03d}"


# ═══════════════════════════════════════════
# POST /crear
# ═══════════════════════════════════════════


@router.post("/crear", status_code=201)
async def crear_separacion(
    body: CrearSeparacionBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Create a new Plan Separe record (no Alegra call — just MongoDB)."""
    # Anti-dup: un cliente no puede tener 2 separaciones activas para el mismo modelo
    existing = await db.plan_separe_separaciones.find_one({
        "cliente.cc": body.cliente_cc,
        "moto.modelo": body.moto_modelo,
        "estado": {"$in": ["activa", "completada"]},
    })
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe separación {existing['separacion_id']} activa para este cliente y moto",
        )

    separacion_id = await _next_separacion_id(db)
    now = datetime.now(timezone.utc).isoformat()

    doc = {
        "separacion_id": separacion_id,
        "cliente": {
            "cc": body.cliente_cc,
            "tipo_documento": body.cliente_tipo_documento,
            "nombre": body.cliente_nombre,
            "telefono": body.cliente_telefono,
        },
        "moto": {
            "modelo": body.moto_modelo,
            "precio_venta": body.moto_precio_venta or 0,
            "cuota_inicial_requerida": body.cuota_inicial,
        },
        "abonos": [],
        "total_abonado": 0,
        "saldo_pendiente": body.cuota_inicial,
        "porcentaje_pagado": 0,
        "matricula_provision": MATRICULA_PROVISION,
        "estado": "activa",
        "fecha_creacion": now,
        "fecha_100porciento": None,
        "alegra_invoice_id": None,
        "notas": body.notas,
    }

    await db.plan_separe_separaciones.insert_one(doc)
    logger.info(f"Plan Separe creado: {separacion_id} cliente={body.cliente_cc}")

    return _clean(doc)


# ═══════════════════════════════════════════
# GET / (list)
# ═══════════════════════════════════════════


@router.get("")
async def listar_separaciones(
    estado: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """List separations with optional filters."""
    filtro: dict = {}
    if estado:
        if estado not in ESTADOS_SEPARE:
            raise HTTPException(status_code=400, detail=f"estado inválido. Use: {sorted(ESTADOS_SEPARE)}")
        filtro["estado"] = estado

    cursor = db.plan_separe_separaciones.find(filtro).sort("fecha_creacion", -1).skip(offset).limit(limit)
    items = await cursor.to_list(length=limit)
    for it in items:
        _clean(it)
        _compute_fields(it)

    total = await db.plan_separe_separaciones.count_documents(filtro)
    return {"count": len(items), "total": total, "separaciones": items}


# ═══════════════════════════════════════════
# GET /stats (for CFO widget)
# ═══════════════════════════════════════════


@router.get("/stats")
async def plan_separe_stats(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Summary stats for CFO widget.

    - total_retenido:        suma de abonos en activa/completada (dinero en caja)
    - total_esperado:        suma de cuota_inicial_requerida en activa/completada
    - dinero_pendiente:      total_esperado - total_retenido (falta por ingresar)
    - matriculas_provision_actual:     COUNT(completada) * 580_000
    - matriculas_provision_proyectada: COUNT(activa+completada) * 580_000
    - por_estado:            breakdown counts (incluye facturada y cancelada)
    """
    cursor = db.plan_separe_separaciones.find(
        {"estado": {"$in": ["activa", "completada"]}},
        {"abonos": 1, "estado": 1, "moto.cuota_inicial_requerida": 1},
    )
    total_retenido = 0
    total_esperado = 0
    completadas = 0
    activas = 0
    async for doc in cursor:
        abonos = doc.get("abonos") or []
        total_retenido += sum(float(a.get("monto", 0) or 0) for a in abonos)
        cuota = float(doc.get("moto", {}).get("cuota_inicial_requerida", 0) or 0)
        total_esperado += cuota
        if doc.get("estado") == "completada":
            completadas += 1
        else:
            activas += 1

    facturadas = await db.plan_separe_separaciones.count_documents({"estado": "facturada"})
    canceladas = await db.plan_separe_separaciones.count_documents({"estado": "cancelada"})

    dinero_pendiente = max(total_esperado - total_retenido, 0)

    return {
        "total_retenido": round(total_retenido),
        "total_esperado": round(total_esperado),
        "dinero_pendiente": round(dinero_pendiente),
        "matriculas_provision_actual": completadas * MATRICULA_PROVISION,
        "matriculas_provision_proyectada": (activas + completadas) * MATRICULA_PROVISION,
        "por_estado": {
            "activa": activas,
            "completada": completadas,
            "facturada": facturadas,
            "cancelada": canceladas,
        },
        "matricula_unit": MATRICULA_PROVISION,
    }


# ═══════════════════════════════════════════
# GET /{id}
# ═══════════════════════════════════════════


@router.get("/{separacion_id}")
async def get_separacion(
    separacion_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await db.plan_separe_separaciones.find_one({"separacion_id": separacion_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Separación {separacion_id} no encontrada")
    _clean(doc)
    _compute_fields(doc)
    return doc


# ═══════════════════════════════════════════
# POST /{id}/abono
# ═══════════════════════════════════════════


async def registrar_abono(
    separacion_id: str,
    body: "RegistrarAbonoBody",
    db: AsyncIOMotorDatabase,
    alegra: "AlegraClient | None" = None,
):
    """Register a partial payment. Creates Alegra journal (DEBIT bank / CREDIT 2805)
    with request_with_verify(). If Alegra fails, MongoDB is NOT updated.

    Internal function — not directly mounted to avoid FastAPI treating
    `alegra` as a body param. HTTP endpoint wraps this below.
    """
    doc = await db.plan_separe_separaciones.find_one({"separacion_id": separacion_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Separación {separacion_id} no encontrada")

    if doc.get("estado") in ("facturada", "cancelada"):
        raise HTTPException(
            status_code=400,
            detail=f"No se puede registrar abono en estado '{doc.get('estado')}'",
        )

    banco_key = (body.banco or "").lower().strip()
    if banco_key not in BANCOS_ID:
        raise HTTPException(
            status_code=400,
            detail=f"Banco inválido. Use: {sorted(BANCOS_ID.keys())}",
        )

    cuota_inicial = float(doc.get("moto", {}).get("cuota_inicial_requerida", 0) or 0)
    total_actual = sum(float(a.get("monto", 0) or 0) for a in (doc.get("abonos") or []))
    if body.monto + total_actual > cuota_inicial + 0.01:
        raise HTTPException(
            status_code=400,
            detail=f"Monto excede saldo pendiente. Saldo: {cuota_inicial - total_actual:,.0f}",
        )

    fecha_str = body.fecha or today_bogota().isoformat()
    try:
        date.fromisoformat(fecha_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="fecha inválida (use yyyy-MM-dd)")

    # ─── Build journal payload ─────────────────────────────────────
    cliente_nombre = doc.get("cliente", {}).get("nombre", "")
    cliente_cc = doc.get("cliente", {}).get("cc", "")
    observations = (
        f"Plan Separe - Anticipo - CC {cliente_cc} - {cliente_nombre} "
        f"[{separacion_id}] - {body.banco}"
        + (f" ref {body.referencia}" if body.referencia else "")
    )
    entries = [
        {"id": BANCOS_ID[banco_key], "debit": body.monto, "credit": 0},
        {"id": CUENTA_ANTICIPOS, "debit": 0, "credit": body.monto},
    ]
    payload = {
        "date": fecha_str,
        "entries": entries,
        "observations": observations,
    }

    # ─── Execute Alegra journal with request_with_verify (ROG-1) ──
    alegra_id = None
    if alegra is None:
        # Inline lazy construction — tests pass mock
        alegra = AlegraClient(db=db)
    try:
        result = await alegra.request_with_verify(
            endpoint="journals",
            method="POST",
            payload=payload,
        )
        alegra_id = str(result.get("_alegra_id") or result.get("id", ""))
    except AlegraError as e:
        logger.error(f"Alegra journal failed for {separacion_id}: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo registrar en Alegra: {str(e)}",
        )

    # ─── Append abono to MongoDB ──────────────────────────────────
    now = datetime.now(timezone.utc).isoformat()
    new_abono = {
        "abono_id": str(uuid.uuid4()),
        "fecha": fecha_str,
        "monto": body.monto,
        "banco": banco_key,
        "banco_label": BANCOS_LABEL.get(banco_key, banco_key),
        "referencia": body.referencia,
        "registrado_por": body.registrado_por,
        "alegra_journal_id": alegra_id,
        "timestamp": now,
    }

    new_total = total_actual + body.monto
    nuevo_estado = doc.get("estado", "activa")
    update: dict = {
        "$push": {"abonos": new_abono},
        "$set": {"updated_at": now},
    }
    if new_total >= cuota_inicial and doc.get("estado") == "activa":
        nuevo_estado = "completada"
        update["$set"]["estado"] = "completada"
        update["$set"]["fecha_100porciento"] = now

    await db.plan_separe_separaciones.update_one(
        {"separacion_id": separacion_id}, update
    )

    # ─── Return fresh computed fields ─────────────────────────────
    fresh = await db.plan_separe_separaciones.find_one({"separacion_id": separacion_id})
    _clean(fresh)
    _compute_fields(fresh)
    logger.info(
        f"Abono registrado: {separacion_id} monto={body.monto} banco={banco_key} "
        f"alegra={alegra_id} total={fresh.get('total_abonado')} estado={fresh.get('estado')}"
    )
    return {
        "separacion_id": separacion_id,
        "abono_id": new_abono["abono_id"],
        "alegra_journal_id": alegra_id,
        "total_abonado": fresh.get("total_abonado"),
        "saldo_pendiente": fresh.get("saldo_pendiente"),
        "porcentaje_pagado": fresh.get("porcentaje_pagado"),
        "estado": fresh.get("estado"),
    }


@router.post("/{separacion_id}/abono")
async def registrar_abono_endpoint(
    separacion_id: str,
    body: RegistrarAbonoBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """HTTP wrapper for registrar_abono (keeps FastAPI from seeing `alegra` as body)."""
    return await registrar_abono(separacion_id, body, db=db)


# ═══════════════════════════════════════════
# POST /{id}/notificar-contador
# ═══════════════════════════════════════════


@router.post("/{separacion_id}/notificar-contador")
async def notificar_contador(
    separacion_id: str,
    body: NotificarContadorBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Registra aviso al Contador (solo log). NO factura en Alegra."""
    doc = await db.plan_separe_separaciones.find_one({"separacion_id": separacion_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Separación no encontrada")

    if doc.get("estado") != "completada":
        raise HTTPException(
            status_code=400,
            detail=f"Solo aplica a separaciones completadas (estado actual: {doc.get('estado')})",
        )

    now = datetime.now(timezone.utc).isoformat()
    await db.plan_separe_notificaciones.insert_one({
        "separacion_id": separacion_id,
        "cliente_cc": doc.get("cliente", {}).get("cc"),
        "timestamp": now,
        "notificado_por": body.notificado_por,
    })

    return {
        "mensaje": "Aviso registrado. El Contador debe facturar manualmente desde Loanbook.",
        "instruccion_contador": (
            f"{separacion_id} | {doc.get('cliente', {}).get('nombre', '')} | "
            f"{doc.get('moto', {}).get('modelo', '')} | "
            f"${doc.get('moto', {}).get('cuota_inicial_requerida', 0):,.0f} pagados | "
            "Facturar cuando moto disponible"
        ),
        "timestamp": now,
    }


# ═══════════════════════════════════════════
# PUT /{id}/cancelar
# ═══════════════════════════════════════════


@router.put("/{separacion_id}/cancelar")
async def cancelar_separacion(
    separacion_id: str,
    body: CancelarBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await db.plan_separe_separaciones.find_one({"separacion_id": separacion_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Separación no encontrada")

    if doc.get("estado") == "facturada":
        raise HTTPException(
            status_code=400,
            detail="No se puede cancelar una separación ya facturada",
        )

    await db.plan_separe_separaciones.update_one(
        {"separacion_id": separacion_id},
        {"$set": {
            "estado": "cancelada",
            "razon_cancelacion": body.razon,
            "cancelada_en": datetime.now(timezone.utc).isoformat(),
        }},
    )
    return {"separacion_id": separacion_id, "estado": "cancelada"}


# ═══════════════════════════════════════════
# PUT /{id}/cambiar-moto
# ═══════════════════════════════════════════


@router.put("/{separacion_id}/cambiar-moto")
async def cambiar_moto(
    separacion_id: str,
    body: CambiarMotoBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await db.plan_separe_separaciones.find_one({"separacion_id": separacion_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Separación no encontrada")

    cuota_inicial = float(doc.get("moto", {}).get("cuota_inicial_requerida", 0) or 0)
    total = sum(float(a.get("monto", 0) or 0) for a in (doc.get("abonos") or []))
    pct = (total / cuota_inicial) * 100 if cuota_inicial > 0 else 0
    if pct >= 50:
        raise HTTPException(
            status_code=400,
            detail=f"No se puede cambiar moto con {pct:.0f}% pagado (>=50%). Cancela y crea otra separación.",
        )

    await db.plan_separe_separaciones.update_one(
        {"separacion_id": separacion_id},
        {"$set": {
            "moto.modelo": body.moto_modelo,
            "moto.precio_venta": body.moto_precio_venta if body.moto_precio_venta is not None else doc["moto"].get("precio_venta", 0),
            "moto.razon_cambio": body.razon,
            "moto_cambio_fecha": datetime.now(timezone.utc).isoformat(),
        }},
    )
    return {"separacion_id": separacion_id, "moto_modelo": body.moto_modelo}


# ═══════════════════════════════════════════
# PUT /{id}/marcar-facturada (llamado manual cuando Contador factura)
# ═══════════════════════════════════════════


class MarcarFacturadaBody(BaseModel):
    alegra_invoice_id: str
    observaciones: str | None = None


@router.put("/{separacion_id}/marcar-facturada")
async def marcar_facturada(
    separacion_id: str,
    body: MarcarFacturadaBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await db.plan_separe_separaciones.find_one({"separacion_id": separacion_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Separación no encontrada")
    if doc.get("estado") not in ("completada", "activa"):
        raise HTTPException(status_code=400, detail=f"Estado inválido: {doc.get('estado')}")

    await db.plan_separe_separaciones.update_one(
        {"separacion_id": separacion_id},
        {"$set": {
            "estado": "facturada",
            "alegra_invoice_id": body.alegra_invoice_id,
            "fecha_facturacion": datetime.now(timezone.utc).isoformat(),
            "observaciones_facturacion": body.observaciones,
        }},
    )
    return {"separacion_id": separacion_id, "estado": "facturada", "alegra_invoice_id": body.alegra_invoice_id}


# ═══════════════════════════════════════════
# PATCH /{id} — edición de separación con audit trail
# ═══════════════════════════════════════════

TIPO_DOC_VALIDOS = {"CC", "PPT", "CE", "TI"}

# Fields the operator CAN edit via PATCH. Everything else in the request body
# is rejected with HTTP 422.
_EDITABLE_FIELDS = {
    "cliente_nombre",
    "cliente_documento_tipo",
    "cliente_documento_numero",
    "cliente_telefono",
    "moto_modelo",
    "cuota_inicial_esperada",
    "notas",
    "motivo",  # audit-only, not persisted as a field
}

_READONLY_FIELDS = {
    "separacion_id", "estado", "pagado", "porcentaje_pagado",
    "total_abonado", "saldo_pendiente", "created_at", "abonos",
    "alegra_invoice_id", "audit",
}


def _diff_field(campo: str, anterior, nuevo) -> dict | None:
    """Return a diff entry when values actually change."""
    if anterior == nuevo:
        return None
    return {"campo": campo, "valor_anterior": anterior, "valor_nuevo": nuevo}


@router.patch("/{separacion_id}")
async def editar_separacion(
    separacion_id: str,
    raw: dict = Body(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Edit a separation (with audit trail + event).

    - Rejects read-only fields (422)
    - Rejects edits on status=facturada (423 Locked)
    - Validates cuota_inicial_esperada > 0 (422)
    - Validates new cedula uniqueness among active separaciones (422)
    - Appends entry to audit[] with user_email, campos_modificados, motivo
    - Publishes plan_separe.editada to roddos_events
    """
    # Reject read-only fields present in the body
    read_only_present = [k for k in raw.keys() if k in _READONLY_FIELDS]
    if read_only_present:
        raise HTTPException(
            status_code=422,
            detail=f"Campos read-only no editables: {read_only_present}",
        )

    # Reject unknown fields (anything that's not editable or readonly)
    unknown = [k for k in raw.keys() if k not in _EDITABLE_FIELDS and k not in _READONLY_FIELDS]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Campos no reconocidos: {unknown}",
        )

    doc = await db.plan_separe_separaciones.find_one({"separacion_id": separacion_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Separación no encontrada")

    # Lock edits on facturada (423 Locked)
    if doc.get("estado") == "facturada":
        raise HTTPException(
            status_code=423,
            detail="Separación ya facturada — no editable",
        )

    # Build diffs ────────────────────────────────────────────────
    cli = doc.get("cliente") or {}
    mot = doc.get("moto") or {}
    diffs: list[dict] = []
    set_updates: dict = {}

    if "cliente_nombre" in raw and raw["cliente_nombre"] is not None:
        new_v = raw["cliente_nombre"]
        d = _diff_field("cliente.nombre", cli.get("nombre"), new_v)
        if d:
            diffs.append(d); set_updates["cliente.nombre"] = new_v

    if "cliente_documento_tipo" in raw and raw["cliente_documento_tipo"] is not None:
        tipo = str(raw["cliente_documento_tipo"]).upper().strip()
        if tipo not in TIPO_DOC_VALIDOS:
            raise HTTPException(
                status_code=422,
                detail=f"cliente_documento_tipo inválido. Use: {sorted(TIPO_DOC_VALIDOS)}",
            )
        d = _diff_field("cliente.tipo_documento", cli.get("tipo_documento"), tipo)
        if d:
            diffs.append(d); set_updates["cliente.tipo_documento"] = tipo

    if "cliente_documento_numero" in raw and raw["cliente_documento_numero"] is not None:
        new_cc = str(raw["cliente_documento_numero"]).strip()
        if not new_cc:
            raise HTTPException(status_code=422, detail="cliente_documento_numero no puede ser vacío")
        if new_cc != cli.get("cc"):
            dup = await db.plan_separe_separaciones.find_one({
                "cliente.cc": new_cc,
                "estado": {"$in": ["activa", "completada"]},
                "separacion_id": {"$ne": separacion_id},
            })
            if dup:
                raise HTTPException(
                    status_code=422,
                    detail=f"Cédula {new_cc} ya tiene separación activa: {dup.get('separacion_id')}",
                )
        d = _diff_field("cliente.cc", cli.get("cc"), new_cc)
        if d:
            diffs.append(d); set_updates["cliente.cc"] = new_cc

    if "cliente_telefono" in raw and raw["cliente_telefono"] is not None:
        new_v = raw["cliente_telefono"]
        d = _diff_field("cliente.telefono", cli.get("telefono"), new_v)
        if d:
            diffs.append(d); set_updates["cliente.telefono"] = new_v

    if "moto_modelo" in raw and raw["moto_modelo"] is not None:
        new_v = raw["moto_modelo"]
        d = _diff_field("moto.modelo", mot.get("modelo"), new_v)
        if d:
            diffs.append(d); set_updates["moto.modelo"] = new_v

    if "cuota_inicial_esperada" in raw and raw["cuota_inicial_esperada"] is not None:
        new_v = float(raw["cuota_inicial_esperada"])
        if new_v <= 0:
            raise HTTPException(
                status_code=422,
                detail="cuota_inicial_esperada debe ser > 0",
            )
        d = _diff_field(
            "moto.cuota_inicial_requerida",
            mot.get("cuota_inicial_requerida"),
            new_v,
        )
        if d:
            diffs.append(d); set_updates["moto.cuota_inicial_requerida"] = new_v

    if "notas" in raw and raw["notas"] is not None:
        new_v = raw["notas"]
        d = _diff_field("notas", doc.get("notas"), new_v)
        if d:
            diffs.append(d); set_updates["notas"] = new_v

    motivo_raw = raw.get("motivo")

    if not diffs:
        return {
            "separacion_id": separacion_id,
            "modificado": False,
            "mensaje": "No hay cambios que aplicar",
        }

    # Audit entry ────────────────────────────────────────────────
    now_iso = datetime.now(timezone.utc).isoformat()
    audit_entry = {
        "timestamp": now_iso,
        "user_email": current_user.get("email", "unknown"),
        "campos_modificados": diffs,
        "motivo": motivo_raw,
        "source": "router.plan_separe.PATCH",
    }
    set_updates["updated_at"] = now_iso

    await db.plan_separe_separaciones.update_one(
        {"separacion_id": separacion_id},
        {"$set": set_updates, "$push": {"audit": audit_entry}},
    )

    # Publish event ──────────────────────────────────────────────
    await publish_event(
        db=db,
        event_type="plan_separe.editada",
        source="router.plan_separe",
        datos={
            "separacion_id": separacion_id,
            "campos_modificados": diffs,
            "user_email": current_user.get("email", "unknown"),
            "motivo": motivo_raw,
        },
        alegra_id=None,
        accion_ejecutada=f"Separación {separacion_id} editada ({len(diffs)} cambio(s))",
    )

    fresh = await db.plan_separe_separaciones.find_one({"separacion_id": separacion_id})
    _clean(fresh)
    _compute_fields(fresh)
    return {
        "separacion_id": separacion_id,
        "modificado": True,
        "cambios": diffs,
        "separacion": fresh,
    }
