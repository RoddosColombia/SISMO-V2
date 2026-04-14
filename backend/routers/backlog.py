"""Backlog REST endpoints."""
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from core.database import get_db

router = APIRouter(prefix="/api/backlog", tags=["backlog"])


@router.get("")
async def list_backlog(
    banco: str | None = None,
    estado: str = "pendiente",
    limit: int = 500,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """List pending backlog movements."""
    filtro = {"estado": estado}
    if banco:
        filtro["banco"] = banco

    cursor = db.backlog_movimientos.find(filtro).sort("fecha_ingreso_backlog", 1).limit(limit)
    items = await cursor.to_list(length=limit)
    for item in items:
        item["_id"] = str(item["_id"])
    return {"success": True, "data": items, "count": len(items)}


@router.get("/count")
async def backlog_count(
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Count pending backlog movements (for badge)."""
    count = await db.backlog_movimientos.count_documents({"estado": "pendiente"})
    return {"success": True, "count": count}


# --- Batch causar endpoints (must be BEFORE /{backlog_id}/causar) ---


class BatchCausarRequest(BaseModel):
    confianza_minima: float = 0.70


class TransferCausarRequest(BaseModel):
    cuenta_origen: str
    cuenta_destino: str


@router.post("/causar-batch")
async def causar_batch(
    request: BatchCausarRequest,
    background_tasks: BackgroundTasks,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Batch-cause all movements with confidence >= threshold. Runs in background."""
    # Count eligible movements
    filtro = {
        "estado": "pendiente",
        "confianza_v1": {"$gte": request.confianza_minima},
    }
    total = await db.backlog_movimientos.count_documents(filtro)

    job_id = str(uuid.uuid4())[:8]

    # Create job tracker
    await db.conciliacion_jobs.insert_one({
        "job_id": job_id,
        "tipo": "causar_batch",
        "total": total,
        "procesados": 0,
        "exitosos": 0,
        "errores": 0,
        "detalle_errores": [],
        "estado": "procesando" if total > 0 else "completado",
    })

    if total > 0:
        background_tasks.add_task(_run_batch_causar, job_id, request.confianza_minima, db)

    return {"success": True, "job_id": job_id, "total_elegibles": total}


async def _run_batch_causar(job_id: str, confianza_minima: float, db):
    """Background task: cause each eligible movement via Alegra."""
    from services.alegra.client import AlegraClient
    from agents.contador.handlers.conciliacion import _classify_movement, BANCO_CATEGORY_IDS
    from services.retenciones import calcular_retenciones
    from core.events import publish_event

    alegra = AlegraClient(db=db)

    filtro = {
        "estado": "pendiente",
        "confianza_v1": {"$gte": confianza_minima},
    }
    cursor = db.backlog_movimientos.find(filtro)

    procesados = 0
    exitosos = 0
    errores = 0
    detalle_errores = []

    async for mov in cursor:
        procesados += 1
        mov_id = mov["_id"]

        try:
            # Re-verify not already caused (anti-dup)
            current = await db.backlog_movimientos.find_one({"_id": mov_id, "estado": "pendiente"})
            if not current:
                continue

            # Classify movement
            classification = _classify_movement(mov["descripcion"], mov["monto"])
            cuenta_id = str(classification["cuenta_id"])
            tipo = classification["tipo"]

            # Get bank ID
            banco = mov.get("banco", "Bancolombia")
            banco_id = BANCO_CATEGORY_IDS.get(banco, "5314")

            # Calculate retenciones
            ret = calcular_retenciones(tipo, mov["monto"])

            # Build entries
            entries = [
                {"id": cuenta_id, "debit": mov["monto"], "credit": 0},
                {"id": banco_id, "debit": 0, "credit": ret["neto_a_pagar"]},
            ]
            if ret["retefuente_monto"] > 0:
                entries.append({"id": ret["retefuente_alegra_id"], "debit": 0, "credit": ret["retefuente_monto"]})
            if ret["reteica_monto"] > 0:
                entries.append({"id": ret["reteica_alegra_id"], "debit": 0, "credit": ret["reteica_monto"]})

            # POST to Alegra
            payload = {
                "date": mov.get("fecha", ""),
                "observations": f"[AC] Batch: {mov.get('descripcion', '')[:80]}",
                "entries": entries,
            }
            result = await alegra.request_with_verify("journals", "POST", payload=payload)

            # Mark as causado
            await db.backlog_movimientos.update_one(
                {"_id": mov_id},
                {"$set": {"estado": "causado", "alegra_id": result["_alegra_id"]}},
            )

            await publish_event(
                db=db,
                event_type="gasto.causado",
                source="batch_causar",
                datos={"alegra_id": result["_alegra_id"], "origen": "batch", "backlog_id": str(mov_id)},
                alegra_id=result["_alegra_id"],
                accion_ejecutada=f"Batch causar — Journal #{result['_alegra_id']}",
            )

            exitosos += 1

        except Exception as e:
            errores += 1
            detalle_errores.append({"movimiento_id": str(mov_id), "error": str(e)[:200]})
            await db.backlog_movimientos.update_one(
                {"_id": mov_id},
                {"$set": {"estado": "error", "razon_pendiente": str(e)[:200]}, "$inc": {"intentos": 1}},
            )

        # Update job progress every iteration
        await db.conciliacion_jobs.update_one(
            {"job_id": job_id},
            {"$set": {"procesados": procesados, "exitosos": exitosos, "errores": errores, "detalle_errores": detalle_errores}},
        )

    # Mark job complete
    await db.conciliacion_jobs.update_one(
        {"job_id": job_id},
        {"$set": {"estado": "completado", "procesados": procesados, "exitosos": exitosos, "errores": errores, "detalle_errores": detalle_errores}},
    )


@router.get("/job/{job_id}")
async def get_job_status(
    job_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Get batch job status."""
    job = await db.conciliacion_jobs.find_one({"job_id": job_id})
    if not job:
        return {"success": False, "error": "Job no encontrado"}
    job.pop("_id", None)
    return {"success": True, **job}


# --- Transfer between accounts (must be BEFORE /{backlog_id}/causar) ---


@router.post("/{backlog_id}/causar-transferencia")
async def causar_transferencia(
    backlog_id: str,
    request: TransferCausarRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Cause a backlog movement as inter-account transfer — DEBIT destino / CREDIT origen."""
    from bson import ObjectId
    from services.alegra.client import AlegraClient
    from core.events import publish_event

    mov = await db.backlog_movimientos.find_one({"_id": ObjectId(backlog_id)})
    if not mov:
        return {"success": False, "error": "Movimiento no encontrado"}

    alegra = AlegraClient(db=db)
    payload = {
        "date": mov.get("fecha", ""),
        "observations": f"[TR] Transferencia entre cuentas: {request.cuenta_origen} -> {request.cuenta_destino} — {mov.get('descripcion', '')[:80]}",
        "entries": [
            {"id": request.cuenta_destino, "debit": mov["monto"], "credit": 0},
            {"id": request.cuenta_origen, "debit": 0, "credit": mov["monto"]},
        ],
    }

    try:
        result = await alegra.request_with_verify("journals", "POST", payload=payload)
        await db.backlog_movimientos.update_one(
            {"_id": ObjectId(backlog_id)},
            {"$set": {"estado": "causado", "alegra_id": result["_alegra_id"]}},
        )
        await publish_event(
            db=db,
            event_type="transferencia.causada",
            source="backlog_manual",
            datos={"alegra_id": result["_alegra_id"], "origen": request.cuenta_origen, "destino": request.cuenta_destino},
            alegra_id=result["_alegra_id"],
            accion_ejecutada=f"Transferencia #{result['_alegra_id']}: {request.cuenta_origen} -> {request.cuenta_destino}",
        )
        return {"success": True, "alegra_id": result["_alegra_id"], "message": f"Transferencia #{result['_alegra_id']} registrada en Alegra."}
    except Exception as e:
        return {"success": False, "error": f"Error: {str(e)}"}


# --- Single-movement causar (must be AFTER /causar-batch and /job/{job_id}) ---


@router.post("/{backlog_id}/causar")
async def causar_desde_backlog(
    backlog_id: str,
    cuenta_id: str = "5494",
    retefuente: float = 0,
    reteica: float = 0,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Cause a backlog movement — POST /journals with verification."""
    from agents.contador.handlers.conciliacion import handle_causar_desde_backlog
    from services.alegra.client import AlegraClient

    alegra = AlegraClient(db=db)
    result = await handle_causar_desde_backlog(
        tool_input={
            "backlog_id": backlog_id,
            "cuenta_id": cuenta_id,
            "retenciones": {"retefuente": retefuente, "reteica": reteica},
        },
        alegra=alegra,
        db=db,
        event_bus=db,
        user_id="api",
    )
    return result
