"""
it_sismo.py — Módulo IT SISMO (Observabilidad + Deuda Técnica)

GET  /api/it/status           → salud de todos los servicios
GET  /api/it/deuda            → lista deuda técnica (array plano)
POST /api/it/deuda            → crear ítem
PATCH /api/it/deuda/{codigo}  → actualizar ítem
DELETE /api/it/deuda/{codigo} → eliminar ítem

ROG-4: MongoDB solo como infraestructura operativa.
       NUNCA se crea journals ni datos contables desde aquí.

Contrato de respuesta (alineado con ITSismoPage.tsx):
  - /status → ServiceStatus tiene {ok: bool, latencia_ms, detalle}
  - /status → campos top-level: render, mongodb, alegra, mercately,
               backlog {pendiente, causado, error, total},
               jobs_activos: int, datakeeper_vivo: bool
  - /deuda  → array plano de DeudaItem (sin wrapper success/data)
  - DeudaItem: prioridad 1-5 (int), categoria enum, impacto, esfuerzo_dias
"""
import os
import time
import uuid
from datetime import datetime, timezone, date
from core.datetime_utils import now_bogota, today_bogota, now_iso_bogota

import httpx
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field
from typing import Optional

from core.database import get_db, get_processor
from core.auth import get_current_user

router = APIRouter(tags=["it"])

# ── Deuda técnica — ítems iniciales ──────────────────────────────────────────

_HOY = datetime.now(timezone.utc)
_HOY_STR = _HOY.strftime("%Y-%m-%dT%H:%M:%SZ")

DT_INICIALES = [
    {
        "codigo":       "DT-5",
        "titulo":       "APScheduler frágil",
        "descripcion":  "Los jobs de cobranza mueren en cold start de Render. "
                        "Necesita n8n o un scheduler externo para garantizar ejecución.",
        "categoria":    "infra",
        "prioridad":    2,
        "estado":       "pendiente",
        "impacto":      "Jobs de cobranza no corren en frío — ingresos sin procesar",
        "esfuerzo_dias": 3,
        "fase_origen":  "Phase 4",
        "creado_en":    _HOY,
        "resuelto_en":  None,
    },
    {
        "codigo":       "DT-6",
        "titulo":       "Observabilidad del sistema",
        "descripcion":  "Panel IT SISMO con métricas de servicios, backlog y CB Alegra.",
        "categoria":    "observabilidad",
        "prioridad":    2,
        "estado":       "en_progreso",
        "impacto":      "Sin visibilidad en tiempo real del estado operativo",
        "esfuerzo_dias": 2,
        "fase_origen":  "BUILD C",
        "creado_en":    _HOY,
        "resuelto_en":  None,
    },
    {
        "codigo":       "DT-7",
        "titulo":       "MongoDB M0 sin backups automáticos",
        "descripcion":  "El cluster M0 (free) de MongoDB Atlas no tiene backup automático. "
                        "Exportaciones manuales no son suficientes para producción.",
        "categoria":    "infra",
        "prioridad":    2,
        "estado":       "pendiente",
        "impacto":      "Pérdida total de datos ante fallo de Atlas sin posibilidad de recovery",
        "esfuerzo_dias": 1,
        "fase_origen":  "Phase 1",
        "creado_en":    _HOY,
        "resuelto_en":  None,
    },
    {
        "codigo":       "DT-8",
        "titulo":       "Phase 8 gaps B1/B4/B5",
        "descripcion":  "Bloques B1, B4 y B5 de Phase 8 (RADAR, inventario real, reportes) "
                        "sin implementar. Afecta visibilidad de cartera.",
        "categoria":    "deuda_codigo",
        "prioridad":    3,
        "estado":       "pendiente",
        "impacto":      "Sin RADAR ni reportes de cartera — decisiones de cobranza a ciegas",
        "esfuerzo_dias": 10,
        "fase_origen":  "Phase 8",
        "creado_en":    _HOY,
        "resuelto_en":  None,
    },
    {
        "codigo":       "DT-9",
        "titulo":       "DIAN en simulación",
        "descripcion":  "Validación de facturas contra DIAN en modo mock. "
                        "Necesita credenciales reales del portal DIAN de Roddos.",
        "categoria":    "proceso",
        "prioridad":    4,
        "estado":       "pendiente",
        "impacto":      "Facturas electrónicas no validadas ante DIAN — riesgo tributario",
        "esfuerzo_dias": 5,
        "fase_origen":  "Phase 2",
        "creado_en":    _HOY,
        "resuelto_en":  None,
    },
    {
        "codigo":       "DT-10",
        "titulo":       "Roles multiusuario",
        "descripcion":  "Sistema de permisos granulares (contador, admin, auditor). "
                        "Actualmente todos los usuarios autenticados tienen acceso total.",
        "categoria":    "seguridad",
        "prioridad":    3,
        "estado":       "pendiente",
        "impacto":      "Cualquier usuario puede ejecutar operaciones contables destructivas",
        "esfuerzo_dias": 4,
        "fase_origen":  "Phase 1",
        "creado_en":    _HOY,
        "resuelto_en":  None,
    },
    {
        "codigo":       "DT-11",
        "titulo":       "Circuit Breaker Alegra",
        "descripcion":  "CB implementado en services/alegra/client.py. "
                        "Estado persiste en MongoDB system_health. CLOSED/OPEN/HALF_OPEN.",
        "categoria":    "infra",
        "prioridad":    1,
        "estado":       "resuelto",
        "impacto":      "Sin CB: fallos en cascada de Alegra bloquean toda la conciliación",
        "esfuerzo_dias": 1,
        "fase_origen":  "TAREA-3",
        "creado_en":    _HOY,
        "resuelto_en":  _HOY,
    },
]


def _fmt_doc(doc: dict) -> dict:
    """Serializa un doc de deuda para el API: convierte datetime → ISO string."""
    doc["_id"] = str(doc["_id"])
    for campo in ("creado_en", "resuelto_en", "ultimo_update"):
        v = doc.get(campo)
        if isinstance(v, datetime):
            doc[campo] = v.strftime("%Y-%m-%dT%H:%M:%SZ")
        elif v is None:
            doc[campo] = None
    return doc


async def _seed_deuda_si_vacia(db: AsyncIOMotorDatabase) -> None:
    """
    Inserta los ítems iniciales si la colección está vacía.
    También migra docs con esquema viejo (prioridad como string "critica/importante/deseada")
    al esquema nuevo (prioridad numérica 1-5 + campos categoria/impacto/esfuerzo_dias).
    Idempotente.
    """
    # Detectar esquema viejo: prioridad guardada como string
    viejo = await db["deuda_tecnica"].find_one({"prioridad": {"$type": "string"}})
    if viejo is not None:
        # Drop y re-seed con el esquema nuevo
        await db["deuda_tecnica"].drop()

    count = await db["deuda_tecnica"].count_documents({})
    if count == 0:
        await db["deuda_tecnica"].insert_many(DT_INICIALES)


# ── Service check helpers ─────────────────────────────────────────────────────

async def _check_render() -> dict:
    port = os.environ.get("PORT", "8000")
    url = f"http://localhost:{port}/health"
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url)
            latencia_ms = int((time.monotonic() - start) * 1000)
            ok = r.status_code == 200
            version = None
            try:
                body = r.json()
                version = body.get("version")
            except Exception:
                pass
            detalle = f"HTTP {r.status_code} en {latencia_ms}ms"
    except Exception as exc:
        latencia_ms = int((time.monotonic() - start) * 1000)
        ok = False
        version = None
        detalle = f"Sin respuesta: {str(exc)[:80]}"
    return {"ok": ok, "latencia_ms": latencia_ms, "detalle": detalle, "version": version}


async def _check_mongodb(db: AsyncIOMotorDatabase) -> dict:
    start = time.monotonic()
    try:
        await db.command({"ping": 1})
        latencia_ms = int((time.monotonic() - start) * 1000)
        colecciones = len(await db.list_collection_names())
        ok = True
        detalle = f"Ping OK en {latencia_ms}ms · {colecciones} colecciones"
    except Exception as exc:
        latencia_ms = int((time.monotonic() - start) * 1000)
        ok = False
        detalle = f"Ping fallido: {str(exc)[:80]}"
    return {"ok": ok, "latencia_ms": latencia_ms, "detalle": detalle}


async def _check_alegra(db: AsyncIOMotorDatabase) -> dict:
    from services.alegra.client import get_circuit_breaker_estado, AlegraClient

    cb_estado = await get_circuit_breaker_estado(db)

    if cb_estado == "OPEN":
        return {
            "ok":               False,
            "latencia_ms":      0,
            "circuit_breaker":  cb_estado,
            "ultimo_journal_id": None,
            "detalle":          "Circuit Breaker OPEN — requests bloqueados automáticamente",
        }

    alegra = AlegraClient(db=db)
    start = time.monotonic()
    try:
        await alegra.get("categories", params={"limit": 1})
        latencia_ms = int((time.monotonic() - start) * 1000)
        ok = True
        detalle = f"GET /categories OK en {latencia_ms}ms"
    except Exception as exc:
        latencia_ms = int((time.monotonic() - start) * 1000)
        ok = False
        detalle = f"GET /categories falló: {str(exc)[:80]}"

    ultimo_journal: str | None = None
    try:
        last = await db["backlog_movimientos"].find_one(
            {"alegra_journal_id": {"$exists": True, "$ne": None}},
            sort=[("fecha_causacion", -1)],
        )
        if last:
            ultimo_journal = last.get("alegra_journal_id")
    except Exception:
        pass

    return {
        "ok":               ok,
        "latencia_ms":      latencia_ms,
        "circuit_breaker":  cb_estado,
        "ultimo_journal_id": ultimo_journal,
        "detalle":          detalle,
    }


async def _check_mercately() -> dict:
    base_url = os.environ.get("MERCATELY_BASE_URL") or os.environ.get("MERCATELY_API_URL")
    api_key  = os.environ.get("MERCATELY_API_KEY")

    if not base_url or not api_key:
        return {
            "ok":     False,
            "detalle": "Variables MERCATELY_BASE_URL / MERCATELY_API_KEY no configuradas",
        }

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{base_url.rstrip('/')}/api/v1/retailer/retailers/",
                headers={"Authorization": f"Token {api_key}"},
            )
            latencia_ms = int((time.monotonic() - start) * 1000)
            ok = r.status_code in (200, 201)
            detalle = f"HTTP {r.status_code} en {latencia_ms}ms"
    except Exception as exc:
        latencia_ms = 0
        ok = False
        detalle = f"Sin respuesta: {str(exc)[:80]}"
    return {"ok": ok, "latencia_ms": latencia_ms, "detalle": detalle}


# ── Pydantic models ───────────────────────────────────────────────────────────

class DeudaCreate(BaseModel):
    titulo:        str
    descripcion:   str = ""
    categoria:     str = "deuda_codigo"   # infra | observabilidad | seguridad | deuda_codigo | proceso
    prioridad:     int = Field(default=3, ge=1, le=5)
    impacto:       str = ""
    esfuerzo_dias: int = Field(default=1, ge=1)
    fase_origen:   Optional[str] = None


class DeudaPatch(BaseModel):
    titulo:        Optional[str] = None
    descripcion:   Optional[str] = None
    categoria:     Optional[str] = None
    prioridad:     Optional[int] = Field(default=None, ge=1, le=5)
    estado:        Optional[str] = None   # pendiente | en_progreso | resuelto | descartado
    impacto:       Optional[str] = None
    esfuerzo_dias: Optional[int] = None
    fase_origen:   Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status")
async def it_status(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Salud en tiempo real de todos los servicios de SISMO V2."""
    import asyncio
    now = datetime.now(timezone.utc)

    render_r, mongodb_r, alegra_r, mercately_r = await asyncio.gather(
        _check_render(),
        _check_mongodb(db),
        _check_alegra(db),
        _check_mercately(),
    )

    # Backlog stats
    pipeline = [{"$group": {"_id": "$estado", "count": {"$sum": 1}}}]
    docs = await db["backlog_movimientos"].aggregate(pipeline).to_list(length=50)
    conteos = {d["_id"]: d["count"] for d in docs if d["_id"]}
    pendiente = conteos.get("pendiente", 0)
    causado   = conteos.get("causado", 0)
    error     = conteos.get("error", 0)
    total_bl  = sum(conteos.values())

    # Jobs
    activos = await db["conciliacion_jobs"].count_documents({"estado": "procesando"})

    # DataKeeper
    processor  = get_processor()
    dk_running = processor is not None and not getattr(processor, "_stopped", True)

    return {
        "render":    render_r,
        "mongodb":   mongodb_r,
        "alegra":    alegra_r,
        "mercately": mercately_r,
        "backlog": {
            "pendiente": pendiente,
            "causado":   causado,
            "error":     error,
            "total":     total_bl,
        },
        "jobs_activos":    activos,
        "datakeeper_vivo": dk_running,
        "generado_en":     now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


@router.get("/deuda")
async def listar_deuda(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Lista todos los ítems de deuda técnica, ordenados por prioridad (1=más urgente)."""
    await _seed_deuda_si_vacia(db)
    docs = await db["deuda_tecnica"].find({}).to_list(length=200)
    docs.sort(key=lambda d: (d.get("prioridad", 9), d.get("codigo", "")))
    return [_fmt_doc(d) for d in docs]


@router.post("/deuda", status_code=201)
async def crear_deuda(
    body: DeudaCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Crea un nuevo ítem de deuda técnica. Genera el código automáticamente."""
    now = datetime.now(timezone.utc)
    # Auto-generate código: DT-<short uuid>
    short_id = uuid.uuid4().hex[:6].upper()
    codigo = f"DT-{short_id}"

    doc = {
        "codigo":       codigo,
        "titulo":       body.titulo,
        "descripcion":  body.descripcion,
        "categoria":    body.categoria,
        "prioridad":    body.prioridad,
        "estado":       "pendiente",
        "impacto":      body.impacto,
        "esfuerzo_dias": body.esfuerzo_dias,
        "fase_origen":  body.fase_origen,
        "creado_en":    now,
        "resuelto_en":  None,
    }
    await db["deuda_tecnica"].insert_one(doc)
    return _fmt_doc(doc)


@router.patch("/deuda/{codigo}")
async def actualizar_deuda(
    codigo: str,
    body: DeudaPatch,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Actualiza estado, prioridad, descripción u otros campos de un ítem."""
    now = datetime.now(timezone.utc)
    campos = body.model_dump(exclude_none=True)
    if not campos:
        raise HTTPException(status_code=400, detail="No hay campos para actualizar")

    update: dict = {"$set": {"ultimo_update": now, **campos}}
    if campos.get("estado") == "resuelto":
        update["$set"]["resuelto_en"] = now

    result = await db["deuda_tecnica"].update_one({"codigo": codigo}, update)
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail=f"Ítem {codigo} no encontrado")

    doc = await db["deuda_tecnica"].find_one({"codigo": codigo})
    return _fmt_doc(doc)


@router.delete("/deuda/{codigo}", status_code=200)
async def eliminar_deuda(
    codigo: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Elimina un ítem de deuda técnica por código."""
    result = await db["deuda_tecnica"].delete_one({"codigo": codigo})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"Ítem {codigo} no encontrado")
    return {"deleted": codigo}


# ── Mantenimiento ─────────────────────────────────────────────────────────────

class LimpiarCuotasBody(BaseModel):
    dry_run: bool = True


@router.post("/limpiar-cuotas-seed-corruptas")
async def limpiar_cuotas_seed_corruptas(
    body: LimpiarCuotasBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Revierte cuotas futuras mal marcadas como 'pagada' por el seed inicial.

    Idempotente: puede ejecutarse múltiples veces sin efecto secundario.
    Con dry_run=true (default) solo reporta — NO escribe en MongoDB.

    Criterio de corrupción: cuota.estado == 'pagada' AND cuota.fecha > hoy
    AND cuota.fecha_pago is None (el seed no registró fecha de pago real).

    Acción: cuota.estado = 'pendiente', cuota.mora_acumulada = 0.
    """
    hoy = today_bogota().isoformat()

    loanbooks = await db.loanbook.find(
        {"cuotas": {"$elemMatch": {"estado": "pagada", "fecha": {"$gt": hoy}}}}
    ).to_list(length=1000)

    afectados: list[dict] = []

    for lb in loanbooks:
        loanbook_id = lb.get("loanbook_id", str(lb.get("_id", "")))
        cuotas: list[dict] = lb.get("cuotas", [])
        cuotas_corruptas = []

        for c in cuotas:
            if (
                c.get("estado") == "pagada"
                and c.get("fecha", "") > hoy
                and not c.get("fecha_pago")   # nunca tuvo pago real
            ):
                cuotas_corruptas.append(c.get("numero"))
                c["estado"] = "pendiente"
                c["mora_acumulada"] = 0

        if cuotas_corruptas:
            afectados.append({
                "loanbook_id": loanbook_id,
                "cuotas_revertidas": cuotas_corruptas,
            })
            if not body.dry_run:
                await db.loanbook.update_one(
                    {"loanbook_id": loanbook_id},
                    {"$set": {
                        "cuotas": cuotas,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }},
                )

    return {
        "dry_run": body.dry_run,
        "loanbooks_afectados": len(afectados),
        "cuotas_revertidas_total": sum(len(r["cuotas_revertidas"]) for r in afectados),
        "detalle": afectados,
        "ejecutado": not body.dry_run,
        "mensaje": (
            f"DRY RUN — {len(afectados)} loanbooks tendrían {sum(len(r['cuotas_revertidas']) for r in afectados)} "
            f"cuotas revertidas. Envía dry_run=false para aplicar."
            if body.dry_run
            else f"Aplicado — {len(afectados)} loanbooks corregidos."
        ),
    }
