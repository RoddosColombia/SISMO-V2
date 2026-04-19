"""Conciliacion bancaria REST endpoints."""
import os
import tempfile
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.auth import get_current_user
from core.database import get_db

router = APIRouter(prefix="/api/conciliacion", tags=["conciliacion"])


async def _run_conciliacion(
    tmp_path: str,
    banco: str | None,
    pdf_password: str | None,
    job_id: str,
    db: AsyncIOMotorDatabase,
    user_id: str,
) -> None:
    """Background task: parse + classify + cause/backlog. Deletes temp file when done."""
    try:
        from agents.contador.handlers.conciliacion import handle_conciliar_extracto_bancario
        from services.alegra.client import AlegraClient

        alegra = AlegraClient(db=db)
        await handle_conciliar_extracto_bancario(
            tool_input={
                "archivo_path": tmp_path,
                "banco": banco,
                "pdf_password": pdf_password,
                "job_id_override": job_id,
            },
            alegra=alegra,
            db=db,
            event_bus=db,
            user_id=user_id,
        )
    except Exception as exc:
        await db.conciliacion_jobs.update_one(
            {"job_id": job_id},
            {"$set": {"estado": "error", "error": str(exc)}},
            upsert=True,
        )
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@router.post("/cargar-extracto")
async def cargar_extracto(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    banco: str | None = Form(default=None),
    pdf_password: str | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Sube extracto bancario y lanza conciliación en background.

    Retorna job_id inmediatamente — usa GET /estado/{job_id} para seguir el progreso.

    Args:
        file: Extracto bancario (.xlsx, .xls, .pdf)
        banco: Banco opcional — se detecta automáticamente si no se envía
        pdf_password: Contraseña del PDF (Nequi usa la cédula del titular)
    """
    # Validate file type quickly before spawning background task
    suffix = os.path.splitext(file.filename or "")[1].lower() or ".xlsx"
    if suffix not in (".xlsx", ".xls", ".pdf"):
        return {"success": False, "error": f"Formato no soportado: {suffix}. Solo .xlsx, .xls, .pdf."}

    # Save to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    # Create job record immediately so frontend can poll
    job_id = str(uuid.uuid4())[:8]
    await db.conciliacion_jobs.insert_one({
        "job_id": job_id,
        "banco": banco or "auto",
        "archivo": file.filename,
        "estado": "pendiente",
        "progress": 0,
        "user_id": current_user.get("username", "api"),
    })

    # Run processing in background — response returns immediately
    background_tasks.add_task(
        _run_conciliacion,
        tmp_path=tmp_path,
        banco=banco,
        pdf_password=pdf_password,
        job_id=job_id,
        db=db,
        user_id=current_user.get("username", "api"),
    )

    return {
        "success": True,
        "job_id": job_id,
        "message": f"Extracto recibido. Procesando en background — consulta el estado con job_id: {job_id}",
    }


@router.get("/estado/{job_id}")
async def estado_conciliacion(
    job_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Poll job progress."""
    job = await db.conciliacion_jobs.find_one({"job_id": job_id})
    if not job:
        return {"success": False, "error": f"Job {job_id} no encontrado"}
    job.pop("_id", None)
    return {"success": True, "data": job}
