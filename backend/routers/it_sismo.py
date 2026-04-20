"""
it_sismo.py — Módulo IT SISMO (Observabilidad + Deuda Técnica)

GET  /api/it/status           → salud de todos los servicios
GET  /api/it/deuda            → lista deuda técnica
POST /api/it/deuda            → crear ítem
PATCH /api/it/deuda/{codigo}  → actualizar ítem
DELETE /api/it/deuda/{codigo} → eliminar ítem

ROG-4: MongoDB solo como infraestructura operativa.
       NUNCA se crea journals ni datos contables desde aquí.
"""
import os
import time
from datetime import datetime, timezone, date

import httpx
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from core.database import get_db, get_processor
from core.auth import get_current_user

router = APIRouter(tags=["it"])

# ── Deuda técnica — ítems iniciales ──────────────────────────────────────────

_HOY = datetime.now(timezone.utc)

DT_INICIALES = [
    {
        "codigo":        "DT-5",
        "titulo":        "APScheduler frágil",
        "descripcion":   "Los jobs de cobranza mueren en cold start de Render. "
                         "Necesita n8n o un scheduler externo para garantizar ejecución.",
        "prioridad":     "importante",
        "estado":        "pendiente",
        "responsable":   "andres",
        "build_asignado": None,
        "creado_en":     _HOY,
        "resuelto_en":   None,
    },
    {
        "codigo":        "DT-6",
        "titulo":        "Observabilidad del sistema",
        "descripcion":   "Panel IT SISMO con métricas de servicios, backlog y CB Alegra.",
        "prioridad":     "importante",
        "estado":        "en_progreso",
        "responsable":   "claude_code",
        "build_asignado": "BUILD C",
        "creado_en":     _HOY,
        "resuelto_en":   None,
    },
    {
        "codigo":        "DT-7",
        "titulo":        "MongoDB M0 sin backups automáticos",
        "descripcion":   "El cluster M0 (free) de MongoDB Atlas no tiene backup automático. "
                         "Exportaciones manuales no son suficientes para producción.",
        "prioridad":     "importante",
        "estado":        "pendiente",
        "responsable":   "andres",
        "build_asignado": None,
        "creado_en":     _HOY,
        "resuelto_en":   None,
    },
    {
        "codigo":        "DT-8",
        "titulo":        "Phase 8 gaps B1/B4/B5",
        "descripcion":   "Bloques B1, B4 y B5 de Phase 8 (RADAR, inventario real, reportes) "
                         "sin implementar. Afecta visibilidad de cartera.",
        "prioridad":     "importante",
        "estado":        "pendiente",
        "responsable":   "claude_code",
        "build_asignado": None,
        "creado_en":     _HOY,
        "resuelto_en":   None,
    },
    {
        "codigo":        "DT-9",
        "titulo":        "DIAN en simulación",
        "descripcion":   "Validación de facturas contra DIAN en modo mock. "
                         "Necesita credenciales reales del portal DIAN de Roddos.",
        "prioridad":     "deseada",
        "estado":        "pendiente",
        "responsable":   "andres",
        "build_asignado": None,
        "creado_en":     _HOY,
        "resuelto_en":   None,
    },
    {
        "codigo":        "DT-10",
        "titulo":        "Roles multiusuario",
        "descripcion":   "Sistema de permisos granulares (contador, admin, auditor). "
                         "Actualmente todos los usuarios autenticados tienen acceso total.",
        "prioridad":     "deseada",
        "estado":        "pendiente",
        "responsable":   "claude_code",
        "build_asignado": None,
        "creado_en":     _HOY,
        "resuelto_en":   None,
    },
    {
        "codigo":        "DT-11",
        "titulo":        "Circuit Breaker Alegra",
        "descripcion":   "CB implementado en services/alegra/client.py. "
                         "Estado persiste en MongoDB system_health. CLOSED/OPEN/HALF_OPEN.",
        "prioridad":     "critica",
        "estado":        "resuelto",
        "responsable":   "claude_code",
        "build_asignado": "BUILD c43ba24",
        "creado_en":     _HOY,
        "resuelto_en":   _HOY,
    },
]


async def _seed_deuda_si_vacia(db: AsyncIOMotorDatabase) -> None:
    """Inserta los ítems iniciales si la colección está vacía. Idempotente."""
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
            if r.status_code == 200:
                if latencia_ms < 2000:
                    estado = "ok"
                elif latencia_ms < 5000:
                    estado = "degradado"
                else:
                    estado = "caido"
                detalle = f"HTTP {r.status_code} en {latencia_ms}ms"
            else:
                estado = "degradado"
                detalle = f"HTTP {r.status_code} inesperado"
    except Exception as exc:
        latencia_ms = int((time.monotonic() - start) * 1000)
        estado = "caido"
        detalle = f"Sin respuesta: {str(exc)[:80]}"
    return {"estado": estado, "latencia_ms": latencia_ms, "detalle": detalle}


async def _check_mongodb(db: AsyncIOMotorDatabase) -> dict:
    start = time.monotonic()
    try:
        await db.command({"ping": 1})
        latencia_ms = int((time.monotonic() - start) * 1000)
        colecciones = len(await db.list_collection_names())
        if latencia_ms < 200:
            estado = "ok"
        elif latencia_ms < 1000:
            estado = "degradado"
        else:
            estado = "caido"
        detalle = f"Ping OK en {latencia_ms}ms · {colecciones} colecciones"
    except Exception as exc:
        latencia_ms = int((time.monotonic() - start) * 1000)
        estado, colecciones = "caido", 0
        detalle = f"Ping fallido: {str(exc)[:80]}"
    return {
        "estado":       estado,
        "latencia_ms":  latencia_ms,
        "colecciones":  colecciones,
        "detalle":      detalle,
    }


async def _check_alegra(db: AsyncIOMotorDatabase) -> dict:
    from services.alegra.client import get_circuit_breaker_estado, AlegraClient

    cb_estado = await get_circuit_breaker_estado(db)

    # Si el CB está abierto, no hacemos request a Alegra
    if cb_estado == "OPEN":
        return {
            "estado":           "degradado",
            "latencia_ms":      0,
            "circuit_breaker":  cb_estado,
            "ultimo_journal_id": None,
            "detalle":          "Circuit Breaker OPEN — requests bloqueados automáticamente",
        }

    # Medir latencia con GET /categories (lectura, no escritura — ROG-1 OK)
    alegra = AlegraClient(db=db)
    start = time.monotonic()
    try:
        data = await alegra.get("categories", params={"limit": 1})
        latencia_ms = int((time.monotonic() - start) * 1000)
        if latencia_ms < 1000:
            estado = "ok"
        elif latencia_ms < 3000:
            estado = "degradado"
        else:
            estado = "caido"
        detalle = f"GET /categories OK en {latencia_ms}ms"
    except Exception as exc:
        latencia_ms = int((time.monotonic() - start) * 1000)
        estado = "degradado"
        detalle = f"GET /categories falló: {str(exc)[:80]}"

    # Último journal registrado en backlog
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
        "estado":            estado,
        "latencia_ms":       latencia_ms,
        "circuit_breaker":   cb_estado,
        "ultimo_journal_id": ultimo_journal,
        "detalle":           detalle,
    }


async def _check_mercately() -> dict:
    base_url = os.environ.get("MERCATELY_BASE_URL") or os.environ.get("MERCATELY_API_URL")
    api_key  = os.environ.get("MERCATELY_API_KEY")

    if not base_url or not api_key:
        return {
            "estado":  "degradado",
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
            if r.status_code in (200, 201):
                estado  = "ok"
                detalle = f"HTTP {r.status_code} en {latencia_ms}ms"
            else:
                estado  = "degradado"
                detalle = f"HTTP {r.status_code} inesperado"
    except Exception as exc:
        estado  = "caido"
        detalle = f"Sin respuesta: {str(exc)[:80]}"
    return {"estado": estado, "detalle": detalle}


async def _get_backlog_stats(db: AsyncIOMotorDatabase) -> dict:
    pipeline = [{"$group": {"_id": "$estado", "count": {"$sum": 1}}}]
    docs = await db["backlog_movimientos"].aggregate(pipeline).to_list(length=50)
    conteos = {d["_id"]: d["count"] for d in docs if d["_id"]}
    total     = sum(conteos.values())
    causados  = conteos.get("causado", 0)
    pendiente = conteos.get("pendiente", 0)
    errores   = conteos.get("error", 0)
    manual    = conteos.get("manual_pendiente", 0)
    pct       = round(causados / total * 100, 1) if total else 0.0
    return {
        "pendientes":       pendiente,
        "causados":         causados,
        "errores":          errores,
        "manual_pendiente": manual,
        "pct_completado":   pct,
    }


async def _get_jobs_stats(db: AsyncIOMotorDatabase) -> dict:
    hoy_inicio = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
    activos   = await db["conciliacion_jobs"].count_documents({"estado": "procesando"})
    comp_hoy  = await db["conciliacion_jobs"].count_documents(
        {"estado": "completado", "creado_en": {"$gte": hoy_inicio}}
    )
    # Jobs que terminaron hoy con errores > 0
    fail_hoy  = await db["conciliacion_jobs"].count_documents(
        {"estado": "completado", "errores": {"$gt": 0}, "creado_en": {"$gte": hoy_inicio}}
    )
    return {
        "activos":         activos,
        "completados_hoy": comp_hoy,
        "fallidos_hoy":    fail_hoy,
    }


# ── Pydantic models ───────────────────────────────────────────────────────────

class DeudaCreate(BaseModel):
    codigo:        str
    titulo:        str
    descripcion:   str = ""
    prioridad:     str = "importante"   # critica | importante | deseada
    responsable:   str = "claude_code"  # claude_code | andres | liz
    build_asignado: str | None = None


class DeudaPatch(BaseModel):
    titulo:        str | None = None
    descripcion:   str | None = None
    prioridad:     str | None = None
    estado:        str | None = None    # pendiente | en_progreso | resuelto
    responsable:   str | None = None
    build_asignado: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status")
async def it_status(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Salud en tiempo real de todos los servicios de SISMO V2."""
    now = datetime.now(timezone.utc)

    # Ejecutar checks (Mercately puede tardar, hacerlo concurrente)
    import asyncio
    render_task    = asyncio.create_task(_check_render())
    mongodb_task   = asyncio.create_task(_check_mongodb(db))
    alegra_task    = asyncio.create_task(_check_alegra(db))
    mercately_task = asyncio.create_task(_check_mercately())

    render_r, mongodb_r, alegra_r, mercately_r = await asyncio.gather(
        render_task, mongodb_task, alegra_task, mercately_task
    )

    backlog_r  = await _get_backlog_stats(db)
    jobs_r     = await _get_jobs_stats(db)

    processor  = get_processor()
    dk_running = processor is not None and not getattr(processor, "_stopped", True)

    eventos_hoy = 0
    try:
        hoy_inicio = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
        eventos_hoy = await db["roddos_events"].count_documents(
            {"timestamp": {"$gte": hoy_inicio.isoformat()}}
        )
    except Exception:
        pass

    return {
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "servicios": {
            "render":    render_r,
            "mongodb":   mongodb_r,
            "alegra":    alegra_r,
            "mercately": mercately_r,
        },
        "backlog":    backlog_r,
        "jobs":       jobs_r,
        "datakeeper": {
            "estado":                  "running" if dk_running else "stopped",
            "eventos_procesados_hoy":  eventos_hoy,
        },
    }


@router.get("/deuda")
async def listar_deuda(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Lista todos los ítems de deuda técnica, ordenados por prioridad."""
    await _seed_deuda_si_vacia(db)

    orden_prioridad = {"critica": 0, "importante": 1, "deseada": 2}
    docs = await db["deuda_tecnica"].find({}).to_list(length=200)

    for d in docs:
        d["_id"] = str(d["_id"])
        for campo in ("creado_en", "resuelto_en"):
            v = d.get(campo)
            if isinstance(v, datetime):
                d[campo] = v.strftime("%Y-%m-%dT%H:%M:%SZ")

    docs.sort(key=lambda d: (
        orden_prioridad.get(d.get("prioridad", "deseada"), 9),
        d.get("codigo", ""),
    ))

    return {"success": True, "data": docs, "total": len(docs)}


@router.post("/deuda", status_code=201)
async def crear_deuda(
    body: DeudaCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Crea un nuevo ítem de deuda técnica."""
    existe = await db["deuda_tecnica"].find_one({"codigo": body.codigo})
    if existe:
        raise HTTPException(status_code=409, detail=f"Código {body.codigo} ya existe")

    now = datetime.now(timezone.utc)
    doc = {
        "codigo":        body.codigo,
        "titulo":        body.titulo,
        "descripcion":   body.descripcion,
        "prioridad":     body.prioridad,
        "estado":        "pendiente",
        "responsable":   body.responsable,
        "build_asignado": body.build_asignado,
        "creado_en":     now,
        "resuelto_en":   None,
    }
    await db["deuda_tecnica"].insert_one(doc)
    doc["_id"] = str(doc["_id"])
    doc["creado_en"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"success": True, "data": doc}


@router.patch("/deuda/{codigo}")
async def actualizar_deuda(
    codigo: str,
    body: DeudaPatch,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Actualiza estado, prioridad, descripción u otros campos de un ítem."""
    now = datetime.now(timezone.utc)
    update: dict = {"$set": {"ultimo_update": now}}

    campos = body.model_dump(exclude_none=True)
    if not campos:
        raise HTTPException(status_code=400, detail="No hay campos para actualizar")

    for k, v in campos.items():
        update["$set"][k] = v

    if campos.get("estado") == "resuelto":
        update["$set"]["resuelto_en"] = now

    result = await db["deuda_tecnica"].update_one({"codigo": codigo}, update)
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail=f"Ítem {codigo} no encontrado")

    doc = await db["deuda_tecnica"].find_one({"codigo": codigo})
    doc["_id"] = str(doc["_id"])
    for campo in ("creado_en", "resuelto_en", "ultimo_update"):
        v = doc.get(campo)
        if isinstance(v, datetime):
            doc[campo] = v.strftime("%Y-%m-%dT%H:%M:%SZ")

    return {"success": True, "data": doc}


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
    return {"success": True, "deleted": codigo}
