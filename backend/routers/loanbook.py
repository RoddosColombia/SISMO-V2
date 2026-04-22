"""
Loanbook endpoints — credit portfolio management.

GET  /api/loanbook                              — List all loanbooks with summary stats
GET  /api/loanbook/{identifier}                 — Detail with full cuotas timeline
GET  /api/loanbook/stats                        — Portfolio summary
POST /api/loanbook/{id}/registrar-pago          — Manual: register a cuota payment
POST /api/loanbook/{id}/registrar-pago-inicial  — Manual: register cuota inicial paid
POST /api/loanbook/{id}/registrar-entrega       — Manual: activate a credit on delivery
"""
import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from core.database import get_db
from core.loanbook_model import (
    MORA_TASA_DIARIA,
    aplicar_waterfall,
    calcular_cronograma,
    calcular_dpd,
    calcular_mora,
    estado_from_dpd,
)

logger = logging.getLogger("routers.loanbook")

router = APIRouter(prefix="/api/loanbook", tags=["loanbook"])


def _clean_doc(doc: dict) -> dict:
    """Remove MongoDB _id for JSON serialization."""
    if doc:
        doc.pop("_id", None)
    return doc


@router.get("/stats")
async def loanbook_stats(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Portfolio summary stats."""
    today = date.today()

    all_lbs = await db.loanbook.find().to_list(length=1000)
    total = len(all_lbs)
    activos = 0
    saldados = 0
    pendiente_entrega = 0
    cartera_total = 0
    recaudo_semanal = 0
    en_mora = 0

    for lb in all_lbs:
        estado = lb.get("estado", "")
        if estado in ("saldado", "castigado"):
            saldados += 1
            continue
        if estado == "pendiente_entrega":
            pendiente_entrega += 1
        # Cartera viva: todo lo que no esté saldado/castigado, incluyendo
        # pendiente_entrega (son créditos reales esperando activación).
        activos += 1
        cartera_total += lb.get("saldo_capital", 0) or lb.get("saldo_pendiente", 0)

        # Recaudo semanal: cuota_monto for semanal, cuota/2 for quincenal, cuota/4 for mensual
        # Solo considera créditos activados (pendiente_entrega aún no genera recaudo).
        if estado != "pendiente_entrega":
            modalidad = lb.get("modalidad", "semanal")
            cuota = lb.get("cuota_monto", 0) or 0
            if modalidad == "semanal":
                recaudo_semanal += cuota
            elif modalidad == "quincenal":
                recaudo_semanal += cuota / 2
            elif modalidad == "mensual":
                recaudo_semanal += cuota / 4

            cuotas = lb.get("cuotas", [])
            dpd = calcular_dpd(cuotas, today)
            if dpd > 0:
                en_mora += 1

    return {
        "total": total,
        "activos": activos,
        "saldados": saldados,
        "pendiente_entrega": pendiente_entrega,
        "cartera_total": round(cartera_total),
        "recaudo_semanal": round(recaudo_semanal),
        "en_mora": en_mora,
    }


@router.get("")
async def listar_loanbooks(
    estado: str | None = None,
    modelo: str | None = None,
    plan: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """List all loanbooks with computed fields."""
    today = date.today()
    filtro: dict = {}
    if estado:
        filtro["estado"] = estado
    if modelo:
        filtro["modelo"] = modelo
    if plan:
        filtro["plan_codigo"] = plan

    cursor = db.loanbook.find(filtro).sort("fecha_creacion", -1)
    items = await cursor.to_list(length=500)

    result = []
    for lb in items:
        _clean_doc(lb)
        cuotas = lb.get("cuotas", [])
        pagadas = sum(1 for c in cuotas if c.get("estado") == "pagada")
        total_cuotas = len(cuotas)
        dpd = calcular_dpd(cuotas, today)

        # Find next pending cuota
        proxima = None
        for c in cuotas:
            if c.get("estado") != "pagada" and c.get("fecha"):
                proxima = {"fecha": c["fecha"], "monto": c["monto"]}
                break

        lb["cuotas_pagadas"] = pagadas
        lb["cuotas_total"] = total_cuotas
        lb["dpd"] = dpd
        lb["proxima_cuota"] = proxima
        # Strip full cuotas array from list view
        lb.pop("cuotas", None)
        result.append(lb)

    # Sort by DPD descending (morosos first)
    result.sort(key=lambda x: x.get("dpd", 0), reverse=True)

    return {"count": len(result), "loanbooks": result}


@router.get("/{identifier}")
async def get_loanbook(
    identifier: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Get full loanbook detail with cuotas timeline.

    Accepts either:
      - VIN (17-char vehicle id), for tipo_producto='moto'
      - loanbook_id (e.g. 'LB-2026-0026'), for any tipo_producto including
        comparendo/licencia which have no VIN.
    """
    today = date.today()

    # Try loanbook_id first (disambiguates when id looks like LB-XXXX)
    lb = None
    if identifier.upper().startswith("LB-"):
        lb = await db.loanbook.find_one({"loanbook_id": identifier})
    if lb is None:
        # Fall back to VIN lookup
        lb = await db.loanbook.find_one({"vin": identifier})
    if lb is None:
        # Last resort: try loanbook_id without prefix match (legacy ids)
        lb = await db.loanbook.find_one({"loanbook_id": identifier})
    if not lb:
        raise HTTPException(
            status_code=404,
            detail=f"Loanbook no encontrado para identifier '{identifier}'",
        )

    _clean_doc(lb)
    cuotas = lb.get("cuotas", [])
    pagadas = sum(1 for c in cuotas if c.get("estado") == "pagada")
    dpd = calcular_dpd(cuotas, today)

    # Classify cuotas for timeline
    for c in cuotas:
        if c.get("estado") == "pagada":
            c["timeline_status"] = "pagada"
        elif c.get("fecha"):
            fecha = date.fromisoformat(c["fecha"])
            if fecha < today:
                c["timeline_status"] = "vencida"
            elif fecha == today or (fecha > today and c == next(
                (x for x in cuotas if x.get("estado") != "pagada" and x.get("fecha")), None
            )):
                c["timeline_status"] = "proxima"
            else:
                c["timeline_status"] = "pendiente"
        else:
            c["timeline_status"] = "pendiente"

    proxima = None
    for c in cuotas:
        if c.get("estado") != "pagada" and c.get("fecha"):
            proxima = {"fecha": c["fecha"], "monto": c["monto"]}
            break

    lb["cuotas_pagadas"] = pagadas
    lb["cuotas_total"] = len(cuotas)
    lb["dpd"] = dpd
    lb["proxima_cuota"] = proxima

    return lb


# ═══════════════════════════════════════════
# Manual operations (BLOQUE 2)
# ═══════════════════════════════════════════

METODOS_PAGO = {"efectivo", "bancolombia", "bbva", "davivienda", "nequi", "transferencia", "otro"}
MODALIDADES = {"semanal", "quincenal", "mensual"}


class PatchLoanbookBody(BaseModel):
    """Campos opcionales para edición manual del crédito.

    Solo se aplican los campos enviados (PATCH semántico).
    No recalcula cronograma ni saldo — para eso usar registrar-entrega.
    """
    plan_codigo: str | None = None
    modalidad: str | None = None
    cuota_valor: float | None = None
    cuota_inicial_pagada: bool | None = None
    total_cuotas: int | None = None
    fecha_factura: str | None = None
    fecha_entrega: str | None = None
    primera_cuota: str | None = None
    vin: str | None = None
    modelo: str | None = None
    cliente_telefono: str | None = None
    cliente_telefono_alternativo: str | None = None
    tipo_producto: str | None = None


class RegistrarPagoBody(BaseModel):
    cuota_numero: int | None = None
    monto_pago: float
    metodo_pago: str = "efectivo"
    fecha_pago: str | None = None
    referencia: str | None = None


class RegistrarPagoInicialBody(BaseModel):
    monto_pago: float
    metodo_pago: str = "efectivo"
    fecha_pago: str | None = None
    referencia: str | None = None


class RegistrarEntregaBody(BaseModel):
    fecha_entrega: str | None = None
    fecha_primera_cuota: str | None = None
    dia_cobro_especial: str | None = None


@router.patch("/{identifier}")
async def patch_loanbook(
    identifier: str,
    body: PatchLoanbookBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Edición manual de campos del crédito.

    Solo actualiza los campos enviados (PATCH semántico).
    NO recalcula cronograma ni saldo — solo sobreescribe metadatos del crédito.
    Para regenerar cuotas, usar registrar-entrega después.
    """
    lb = await _find_lb_by_identifier(db, identifier)

    update: dict = {}

    if body.plan_codigo is not None:
        update["plan_codigo"] = body.plan_codigo
        update["plan.codigo"] = body.plan_codigo
    if body.modalidad is not None:
        if body.modalidad not in MODALIDADES:
            raise HTTPException(status_code=400, detail=f"modalidad debe ser: {sorted(MODALIDADES)}")
        update["modalidad"] = body.modalidad
        update["plan.modalidad"] = body.modalidad
    if body.cuota_valor is not None:
        update["cuota_monto"] = body.cuota_valor
        update["plan.cuota_valor"] = body.cuota_valor
    if body.cuota_inicial_pagada is not None:
        update["cuota_inicial_pagada"] = body.cuota_inicial_pagada
    if body.total_cuotas is not None:
        update["num_cuotas"] = body.total_cuotas
        update["plan.total_cuotas"] = body.total_cuotas
    if body.fecha_factura is not None:
        update["fechas.factura"] = body.fecha_factura
    if body.fecha_entrega is not None:
        update["fecha_entrega"] = body.fecha_entrega
        update["fechas.entrega"] = body.fecha_entrega
    if body.primera_cuota is not None:
        update["fecha_primer_pago"] = body.primera_cuota
        update["fechas.primera_cuota"] = body.primera_cuota
    if body.vin is not None:
        update["vin"] = body.vin
        update["moto.vin"] = body.vin
    if body.modelo is not None:
        update["modelo"] = body.modelo
        update["moto.modelo"] = body.modelo
    if body.cliente_telefono is not None:
        update["cliente.telefono"] = body.cliente_telefono
    if body.cliente_telefono_alternativo is not None:
        update["cliente.telefono_alternativo"] = body.cliente_telefono_alternativo
    if body.tipo_producto is not None:
        update["tipo_producto"] = body.tipo_producto

    if not update:
        raise HTTPException(status_code=400, detail="No se enviaron campos para actualizar")

    update["updated_at"] = datetime.now(timezone.utc).isoformat()

    await db.loanbook.update_one(
        {"loanbook_id": lb["loanbook_id"]},
        {"$set": update},
    )

    campos = list(body.model_fields_set)
    await _publish_event(
        db,
        "loanbook.editado",
        "routers.loanbook.manual",
        {
            "loanbook_id": lb["loanbook_id"],
            "campos_editados": campos,
            "valores": body.model_dump(exclude_none=True),
        },
        accion=f"Edición manual {lb['loanbook_id']}: {', '.join(campos)}",
    )

    logger.info(f"Loanbook editado: {lb['loanbook_id']} campos={campos}")

    return {
        "success": True,
        "loanbook_id": lb["loanbook_id"],
        "campos_actualizados": campos,
    }


async def _find_lb_by_identifier(db: AsyncIOMotorDatabase, identifier: str) -> dict:
    """Lookup helper: accept VIN or loanbook_id."""
    lb = None
    if identifier.upper().startswith("LB-"):
        lb = await db.loanbook.find_one({"loanbook_id": identifier})
    if lb is None:
        lb = await db.loanbook.find_one({"vin": identifier})
    if lb is None:
        lb = await db.loanbook.find_one({"loanbook_id": identifier})
    if not lb:
        raise HTTPException(
            status_code=404,
            detail=f"Loanbook no encontrado para identifier '{identifier}'",
        )
    return lb


async def _publish_event(db: AsyncIOMotorDatabase, event_type: str, source: str, datos: dict, alegra_id: str | None = None, accion: str = "") -> None:
    """Append-only event bus write. Per ROG-4 this is allowed from routers."""
    await db.roddos_events.insert_one({
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "source": source,
        "correlation_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "datos": datos,
        "alegra_id": alegra_id,
        "accion_ejecutada": accion,
    })


@router.post("/{identifier}/registrar-pago")
async def registrar_pago_manual(
    identifier: str,
    body: RegistrarPagoBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Registra un pago manual de cuota. Aplica waterfall.

    Flujo:
      1. MongoDB update inmediato (no bloquea si Alegra falla)
      2. publish_event("pago.cuota.registrado") al bus
      3. Alegra journal como best-effort (via DataKeeper listener)
    """
    metodo = body.metodo_pago.lower() if body.metodo_pago else "efectivo"
    if metodo not in METODOS_PAGO:
        raise HTTPException(status_code=400, detail=f"metodo_pago inválido. Use: {sorted(METODOS_PAGO)}")

    lb = await _find_lb_by_identifier(db, identifier)
    today = date.today()
    fecha_pago_str = body.fecha_pago or today.isoformat()
    try:
        fecha_pago = date.fromisoformat(fecha_pago_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="fecha_pago inválida (use yyyy-MM-dd)")

    cuotas = lb.get("cuotas", [])
    if not cuotas:
        raise HTTPException(status_code=400, detail="Loanbook sin cuotas — ejecuta registrar-entrega primero")

    anzi_pct = lb.get("anzi_pct", 0.02) or 0.0

    # Calcular mora pendiente
    mora_pendiente = 0
    for c in cuotas:
        if c.get("estado") == "pagada" or not c.get("fecha"):
            continue
        fc = date.fromisoformat(c["fecha"])
        mora = calcular_mora(fc, fecha_pago, MORA_TASA_DIARIA)
        c["mora_acumulada"] = mora
        mora_pendiente += mora

    # Vencidas
    vencidas_total = sum(
        c["monto"] for c in cuotas
        if c.get("estado") != "pagada" and c.get("fecha")
        and date.fromisoformat(c["fecha"]) < fecha_pago
    )

    # Corriente
    corriente_monto = 0
    for c in cuotas:
        if c.get("estado") == "pagada":
            continue
        if c.get("fecha") and date.fromisoformat(c["fecha"]) >= fecha_pago:
            corriente_monto = c["monto"]
            break
        if not c.get("fecha"):
            corriente_monto = c["monto"]
            break

    saldo_capital = lb.get("saldo_capital", 0) or lb.get("saldo_pendiente", 0) or 0

    alloc = aplicar_waterfall(
        monto_pago=body.monto_pago,
        anzi_pct=anzi_pct,
        mora_pendiente=mora_pendiente,
        cuotas_vencidas_total=vencidas_total,
        cuota_corriente=corriente_monto,
        saldo_capital=saldo_capital,
    )

    # Marcar cuotas pagadas según allocation
    rem_venc = alloc["vencidas"]
    rem_corr = alloc["corriente"]
    for c in cuotas:
        if c.get("estado") == "pagada":
            continue
        if c.get("fecha"):
            fc = date.fromisoformat(c["fecha"])
            if fc < fecha_pago and rem_venc >= c["monto"]:
                c["estado"] = "pagada"
                c["fecha_pago"] = fecha_pago_str
                c["mora_acumulada"] = 0
                c["metodo_pago"] = metodo
                c["referencia"] = body.referencia
                rem_venc -= c["monto"]
                continue
            if fc >= fecha_pago and rem_corr >= c["monto"]:
                c["estado"] = "pagada"
                c["fecha_pago"] = fecha_pago_str
                c["mora_acumulada"] = 0
                c["metodo_pago"] = metodo
                c["referencia"] = body.referencia
                rem_corr -= c["monto"]
                break
        else:
            if rem_corr >= c["monto"]:
                c["estado"] = "pagada"
                c["fecha_pago"] = fecha_pago_str
                c["metodo_pago"] = metodo
                c["referencia"] = body.referencia
                rem_corr -= c["monto"]
                break

    new_saldo = max(saldo_capital - alloc["corriente"] - alloc["vencidas"] - alloc["capital"], 0)
    total_pagado = (lb.get("total_pagado", 0) or 0) + body.monto_pago
    total_mora = (lb.get("total_mora_pagada", 0) or 0) + alloc["mora"]
    total_anzi = (lb.get("total_anzi_pagado", 0) or 0) + alloc["anzi"]
    cuotas_pagadas = sum(1 for c in cuotas if c.get("estado") == "pagada")

    dpd = calcular_dpd(cuotas, fecha_pago)
    nuevo_estado = "saldado" if new_saldo == 0 and cuotas_pagadas == len(cuotas) else estado_from_dpd(dpd)

    await db.loanbook.update_one(
        {"loanbook_id": lb["loanbook_id"]},
        {"$set": {
            "cuotas": cuotas,
            "saldo_capital": new_saldo,
            "saldo_pendiente": new_saldo,
            "total_pagado": total_pagado,
            "total_mora_pagada": total_mora,
            "total_anzi_pagado": total_anzi,
            "cuotas_pagadas": cuotas_pagadas,
            "estado": nuevo_estado,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )

    await _publish_event(
        db,
        "pago.cuota.registrado",
        "routers.loanbook.manual",
        {
            "loanbook_id": lb["loanbook_id"],
            "vin": lb.get("vin"),
            "monto_pago": body.monto_pago,
            "fecha_pago": fecha_pago_str,
            "metodo_pago": metodo,
            "referencia": body.referencia,
            "desglose": alloc,
            "cuota_numero": body.cuota_numero,
        },
        accion=f"Pago manual ${body.monto_pago:,.0f} VIN {lb.get('vin') or lb['loanbook_id']}",
    )

    logger.info(f"Pago manual registrado: {lb['loanbook_id']} ${body.monto_pago:,.0f} método={metodo}")

    return {
        "success": True,
        "loanbook_id": lb["loanbook_id"],
        "nuevo_saldo": new_saldo,
        "nuevo_estado": nuevo_estado,
        "cuotas_pagadas": cuotas_pagadas,
        "desglose": alloc,
    }


@router.post("/{identifier}/registrar-pago-inicial")
async def registrar_pago_inicial(
    identifier: str,
    body: RegistrarPagoInicialBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Registra la cuota inicial (solo válido en pendiente_entrega)."""
    lb = await _find_lb_by_identifier(db, identifier)
    if lb.get("estado") != "pendiente_entrega":
        raise HTTPException(
            status_code=400,
            detail=f"Solo aplica a créditos pendiente_entrega (estado actual: {lb.get('estado')})",
        )

    metodo = body.metodo_pago.lower() if body.metodo_pago else "efectivo"
    if metodo not in METODOS_PAGO:
        raise HTTPException(status_code=400, detail=f"metodo_pago inválido. Use: {sorted(METODOS_PAGO)}")

    fecha_pago_str = body.fecha_pago or date.today().isoformat()

    await db.loanbook.update_one(
        {"loanbook_id": lb["loanbook_id"]},
        {"$set": {
            "cuota_inicial_pagada": True,
            "cuota_inicial_monto": body.monto_pago,
            "cuota_inicial_metodo": metodo,
            "cuota_inicial_fecha": fecha_pago_str,
            "cuota_inicial_referencia": body.referencia,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )

    await _publish_event(
        db,
        "pago.inicial.registrado",
        "routers.loanbook.manual",
        {
            "loanbook_id": lb["loanbook_id"],
            "vin": lb.get("vin"),
            "monto_pago": body.monto_pago,
            "metodo_pago": metodo,
            "fecha_pago": fecha_pago_str,
        },
        accion=f"Cuota inicial ${body.monto_pago:,.0f} registrada manual",
    )

    return {
        "success": True,
        "loanbook_id": lb["loanbook_id"],
        "cuota_inicial_pagada": True,
    }


def _next_wednesday_from(d: date) -> date:
    """First Wednesday >= d."""
    offset = (2 - d.weekday()) % 7
    return d + timedelta(days=offset)


@router.post("/{identifier}/registrar-entrega")
async def registrar_entrega(
    identifier: str,
    body: RegistrarEntregaBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Activa el crédito: pendiente_entrega → activo + genera cronograma."""
    lb = await _find_lb_by_identifier(db, identifier)
    if lb.get("estado") not in ("pendiente_entrega", "activo"):
        raise HTTPException(
            status_code=400,
            detail=f"No aplicable en estado '{lb.get('estado')}'",
        )

    today = date.today()
    fecha_entrega_str = body.fecha_entrega or today.isoformat()
    try:
        fecha_entrega = date.fromisoformat(fecha_entrega_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="fecha_entrega inválida (yyyy-MM-dd)")

    # Auto-calcular primera cuota si no se envió
    if body.fecha_primera_cuota:
        try:
            fpc = date.fromisoformat(body.fecha_primera_cuota)
        except ValueError:
            raise HTTPException(status_code=400, detail="fecha_primera_cuota inválida (yyyy-MM-dd)")
    else:
        fpc = _next_wednesday_from(fecha_entrega + timedelta(days=7))

    modalidad = lb.get("modalidad", "semanal")
    num_cuotas = lb.get("num_cuotas", 0) or lb.get("cuotas_total", 0)
    cuota_monto = lb.get("cuota_monto", 0) or 0

    if num_cuotas <= 0:
        raise HTTPException(status_code=400, detail="Loanbook sin num_cuotas configurado")

    # Generar cronograma respetando dia_cobro_especial
    fechas = calcular_cronograma(
        fecha_entrega=fecha_entrega,
        modalidad=modalidad,
        num_cuotas=num_cuotas,
        fecha_primer_pago=fpc,
        dia_cobro_especial=body.dia_cobro_especial,
    )

    cuotas = [
        {
            "numero": i + 1,
            "monto": cuota_monto,
            "estado": "pendiente",
            "fecha": f.isoformat(),
            "fecha_pago": None,
            "mora_acumulada": 0,
        }
        for i, f in enumerate(fechas)
    ]

    update_fields = {
        "estado": "activo",
        "fecha_entrega": fecha_entrega_str,
        "fecha_primer_pago": fpc.isoformat(),
        "fechas.entrega": fecha_entrega_str,
        "fechas.primera_cuota": fpc.isoformat(),
        "cuotas": cuotas,
        "cuotas_pagadas": 0,
        "cuotas_total": len(cuotas),
        "saldo_capital": num_cuotas * cuota_monto,
        "saldo_pendiente": num_cuotas * cuota_monto,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if body.dia_cobro_especial:
        update_fields["dia_cobro_especial"] = body.dia_cobro_especial

    await db.loanbook.update_one({"loanbook_id": lb["loanbook_id"]}, {"$set": update_fields})

    await _publish_event(
        db,
        "moto.entregada",
        "routers.loanbook.manual",
        {
            "loanbook_id": lb["loanbook_id"],
            "vin": lb.get("vin"),
            "fecha_entrega": fecha_entrega_str,
            "fecha_primera_cuota": fpc.isoformat(),
            "dia_cobro_especial": body.dia_cobro_especial,
        },
        accion=f"Entrega manual {lb['loanbook_id']} — primer cobro {fpc.isoformat()}",
    )

    return {
        "success": True,
        "loanbook_id": lb["loanbook_id"],
        "estado": "activo",
        "fecha_entrega": fecha_entrega_str,
        "fecha_primera_cuota": fpc.isoformat(),
        "num_cuotas": len(cuotas),
    }
