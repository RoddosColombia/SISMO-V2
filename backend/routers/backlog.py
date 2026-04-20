"""Backlog REST endpoints."""
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from core.database import get_db
from core.auth import get_current_user

router = APIRouter(prefix="/api/backlog", tags=["backlog"])


# ═══════════════════════════════════════════════════════════════════════════
# BUILD 1 — causar-por-regla constants
# ═══════════════════════════════════════════════════════════════════════════

# Bank account IDs (category IDs for journal entries)
CUENTAS_BANCO: dict[str, str] = {
    "nequi":       "5314",
    "bancolombia": "5315",
    "bbva":        "5318",
    "davivienda":  "5322",
    "global66":    "5536",
}

REGLAS_CONFIG: dict[str, dict] = {
    "gmf_4x1000": {
        "filtro_extra": {"descripcion": {"$regex": "GRAVAMEN", "$options": "i"}},
        "tipo_accion": "gasto",
        "cuenta_debito": "5509",
        "concepto_template": "GMF 4x1000 - {fecha}",
    },
    "cxc_andres": {
        "filtro_extra": {
            "descripcion": {"$regex": "ANDRES", "$options": "i"},
            "$or": [
                {"descripcion": {"$regex": "BRE-B",   "$options": "i"}},
                {"descripcion": {"$regex": "SANJUAN", "$options": "i"}},
            ],
        },
        "tipo_accion": "cxc_socio",
        "cuenta_cxc": "5329",
        "tercero_cedula": "80075452",
        "concepto_template": "CXC Andres Sanjuan - {desc_corta}",
    },
    "cxc_ivan": {
        "filtro_extra": {"descripcion": {"$regex": "IVAN.*ECHEVERRI", "$options": "i"}},
        "tipo_accion": "cxc_socio",
        "cuenta_cxc": "5329",
        "tercero_cedula": "80086601",
        "concepto_template": "CXC Ivan Echeverri - {desc_corta}",
    },
    "transporte_app": {
        "filtro_extra": {"descripcion": {"$regex": "UBER|TAXI|DIDI", "$options": "i"}},
        "tipo_accion": "gasto",
        "cuenta_debito": "5491",
        "concepto_template": "Transporte - {desc_corta}",
    },
    "flag_lizbeth": {
        "filtro_extra": {"descripcion": {"$regex": r"LIZBETH|\bLIZ\b", "$options": "i"}},
        "tipo_accion": "flag_only",
        "nuevo_estado": "manual_pendiente",
        "motivo": "Movimiento de Lizbeth — clasificacion manual por Andres",
    },
}


def _banco_id(banco: str) -> str:
    """Normalize banco name and return its Alegra category ID."""
    return CUENTAS_BANCO.get(banco.lower(), "5315")  # fallback Bancolombia 2540


def _format_concepto(template: str, mov: dict) -> str:
    fecha = mov.get("fecha", "")
    desc = mov.get("descripcion", "")
    desc_corta = desc[:40] if desc else ""
    return template.format(fecha=fecha, desc_corta=desc_corta)


async def _lookup_alegra_contact(alegra_client, cedula: str) -> str | None:
    """GET /contacts?identification={cedula} → Alegra contact id or None."""
    try:
        data = await alegra_client.get("contacts", params={"identification": cedula, "limit": 1})
        if isinstance(data, list) and data:
            return str(data[0].get("id", ""))
        if isinstance(data, dict) and data.get("data"):
            return str(data["data"][0].get("id", ""))
    except Exception:
        pass
    return None


async def _causar_movimiento(mov: dict, config: dict, alegra_client, db) -> dict:
    """
    Process one backlog movement under the given rule config.
    Returns {"ok": bool, "alegra_journal_id": str|None, "error": str|None}.
    """
    from core.events import publish_event

    monto = abs(float(mov.get("monto", 0)))
    fecha = mov.get("fecha", "")
    banco = mov.get("banco", "bancolombia")
    tipo  = mov.get("tipo", "debito")      # "debito" | "credito"
    tipo_accion = config["tipo_accion"]

    banco_cuenta = _banco_id(banco)
    now = datetime.now(timezone.utc)

    # ── flag_only: skip Alegra, just update estado ────────────────────────
    if tipo_accion == "flag_only":
        await db.backlog_movimientos.update_one(
            {"_id": mov["_id"]},
            {"$set": {
                "estado":          config["nuevo_estado"],
                "razon_pendiente": config["motivo"],
                "updated_at":      now,
            }},
        )
        return {"ok": True, "alegra_journal_id": None, "error": None}

    # concepto only needed for Alegra writes (not flag_only)
    concepto = _format_concepto(config["concepto_template"], mov)

    # ── Build journal entries ─────────────────────────────────────────────
    if tipo_accion == "gasto":
        # Money OUT: DB=cuenta_gasto, CR=banco
        cuenta_gasto = config["cuenta_debito"]
        entries = [
            {"id": cuenta_gasto,  "debit": monto, "credit": 0},
            {"id": banco_cuenta,  "debit": 0,     "credit": monto},
        ]
        third_party_id = None

    elif tipo_accion == "cxc_socio":
        cuenta_cxc = config["cuenta_cxc"]
        # Look up the socio's Alegra contact
        third_party_id = await _lookup_alegra_contact(alegra_client, config["tercero_cedula"])

        if tipo == "credito":
            # Money IN from socio: DB=banco, CR=CXC
            cxc_entry = {"id": cuenta_cxc, "debit": 0, "credit": monto}
            banco_entry = {"id": banco_cuenta, "debit": monto, "credit": 0}
        else:
            # Money OUT to socio: DB=CXC, CR=banco
            cxc_entry = {"id": cuenta_cxc, "debit": monto, "credit": 0}
            banco_entry = {"id": banco_cuenta, "debit": 0, "credit": monto}

        if third_party_id:
            cxc_entry["thirdParty"] = {"id": third_party_id}

        entries = [cxc_entry, banco_entry]
    else:
        return {"ok": False, "alegra_journal_id": None, "error": f"tipo_accion desconocido: {tipo_accion}"}

    payload = {
        "date":         fecha,
        "observations": concepto,
        "entries":      entries,
    }

    try:
        result = await alegra_client.request_with_verify("journals", "POST", payload=payload)
        journal_id = result["_alegra_id"]

        await db.backlog_movimientos.update_one(
            {"_id": mov["_id"]},
            {"$set": {
                "estado":             "causado",
                "alegra_journal_id":  journal_id,
                "fecha_causacion":    now,
                "updated_at":         now,
            }},
        )
        await publish_event(
            db=db,
            event_type="gasto.causado",
            source="causar_por_regla",
            datos={
                "alegra_id":   journal_id,
                "regla":       config.get("tipo_accion"),
                "backlog_id":  str(mov["_id"]),
                "monto":       monto,
            },
            alegra_id=journal_id,
            accion_ejecutada=f"causar_por_regla — Journal #{journal_id}: {concepto}",
        )
        return {"ok": True, "alegra_journal_id": journal_id, "error": None}

    except Exception as exc:
        await db.backlog_movimientos.update_one(
            {"_id": mov["_id"]},
            {"$set": {"razon_pendiente": str(exc)[:300], "updated_at": now},
             "$inc": {"intentos": 1}},
        )
        return {"ok": False, "alegra_journal_id": None, "error": str(exc)[:300]}


async def _run_regla_background(job_id: str, regla: str, config: dict, db) -> None:
    """Background task: process all movements for a rule and update job tracker."""
    from services.alegra.client import AlegraClient

    alegra = AlegraClient(db=db)
    filtro = {"estado": "pendiente", **config["filtro_extra"]}
    movimientos = await db.backlog_movimientos.find(filtro).to_list(length=5000)

    exitos = 0
    fallos = 0
    fallos_detalle: list[dict] = []

    for mov in movimientos:
        res = await _causar_movimiento(mov, config, alegra, db)
        if res["ok"]:
            exitos += 1
        else:
            fallos += 1
            fallos_detalle.append({"id": str(mov["_id"]), "error": res["error"]})

        await db.conciliacion_jobs.update_one(
            {"job_id": job_id},
            {"$set": {
                "procesados": exitos + fallos,
                "exitosos":   exitos,
                "errores":    fallos,
                "detalle_errores": fallos_detalle,
            }},
        )

    await db.conciliacion_jobs.update_one(
        {"job_id": job_id},
        {"$set": {"estado": "completado"}},
    )


# ═══════════════════════════════════════════════════════════════════════════
# BUILD 1 — Endpoint
# ═══════════════════════════════════════════════════════════════════════════

class CausarPorReglaRequest(BaseModel):
    regla: str


@router.post("/causar-por-regla")
async def causar_por_regla(
    request: CausarPorReglaRequest,
    background_tasks: BackgroundTasks,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    POST /api/backlog/causar-por-regla
    Applies one of 5 mechanical rules to all pending backlog movements.
    If > 50 matching movements, runs in background and returns job_id.
    """
    regla = request.regla
    if regla not in REGLAS_CONFIG:
        raise HTTPException(status_code=400, detail=f"Regla desconocida: '{regla}'. Opciones: {list(REGLAS_CONFIG)}")

    config = REGLAS_CONFIG[regla]
    filtro = {"estado": "pendiente", **config["filtro_extra"]}
    total = await db.backlog_movimientos.count_documents(filtro)

    if total == 0:
        return {
            "success": True,
            "regla_aplicada": regla,
            "movimientos_procesados": 0,
            "exitos": 0,
            "fallos": 0,
            "fallos_detalle": [],
        }

    # ── Background for large batches (>50) ───────────────────────────────
    if total > 50:
        job_id = str(uuid.uuid4())[:8]
        await db.conciliacion_jobs.insert_one({
            "job_id":          job_id,
            "tipo":            f"causar_por_regla:{regla}",
            "total":           total,
            "procesados":      0,
            "exitosos":        0,
            "errores":         0,
            "detalle_errores": [],
            "estado":          "procesando",
            "creado_en":       datetime.now(timezone.utc),
        })
        background_tasks.add_task(_run_regla_background, job_id, regla, config, db)
        return {
            "success":         True,
            "regla_aplicada":  regla,
            "job_id":          job_id,
            "total_elegibles": total,
            "message":         f"Procesando {total} movimientos en background. Consulte GET /api/backlog/job/{job_id}",
        }

    # ── Inline for small batches (<=50) ──────────────────────────────────
    from services.alegra.client import AlegraClient
    alegra = AlegraClient(db=db)

    movimientos = await db.backlog_movimientos.find(filtro).to_list(length=200)
    exitos = 0
    fallos = 0
    fallos_detalle: list[dict] = []

    for mov in movimientos:
        res = await _causar_movimiento(mov, config, alegra, db)
        if res["ok"]:
            exitos += 1
        else:
            fallos += 1
            fallos_detalle.append({
                "id":    str(mov["_id"]),
                "desc":  mov.get("descripcion", "")[:60],
                "error": res["error"],
            })

    return {
        "success":              True,
        "regla_aplicada":       regla,
        "movimientos_procesados": exitos + fallos,
        "exitos":               exitos,
        "fallos":               fallos,
        "fallos_detalle":       fallos_detalle,
    }


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
