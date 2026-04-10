"""Conciliacion bancaria REST endpoints."""
from fastapi import APIRouter, UploadFile, File, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from core.database import get_db

router = APIRouter(prefix="/api/conciliacion", tags=["conciliacion"])


@router.post("/cargar-extracto")
async def cargar_extracto(
    file: UploadFile = File(...),
    banco: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Upload bank extract (.xlsx or .pdf) for reconciliation."""
    import tempfile, os
    from services.bank_parsers import detect_bank
    from agents.contador.handlers.conciliacion import handle_conciliar_extracto_bancario
    from services.alegra.client import AlegraClient

    # Save to temp file
    suffix = os.path.splitext(file.filename or "")[1] or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        alegra = AlegraClient(db=db)
        result = await handle_conciliar_extracto_bancario(
            tool_input={"archivo_path": tmp_path, "banco": banco},
            alegra=alegra,
            db=db,
            event_bus=db,
            user_id="api",
        )
        return result
    finally:
        os.unlink(tmp_path)


@router.get("/estado/{job_id}")
async def estado_conciliacion(
    job_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Poll job progress."""
    job = await db.conciliacion_jobs.find_one({"job_id": job_id})
    if not job:
        return {"success": False, "error": f"Job {job_id} no encontrado"}
    job.pop("_id", None)
    return {"success": True, "data": job}
