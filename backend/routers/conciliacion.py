"""Conciliacion bancaria REST endpoints."""
from fastapi import APIRouter, UploadFile, File, Depends, Form
from motor.motor_asyncio import AsyncIOMotorDatabase
from core.database import get_db
from core.auth import get_current_user

router = APIRouter(prefix="/api/conciliacion", tags=["conciliacion"])


@router.post("/cargar-extracto")
async def cargar_extracto(
    file: UploadFile = File(...),
    banco: str | None = Form(default=None),
    pdf_password: str | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Upload bank extract (.xlsx or .pdf) for reconciliation.

    Args:
        file: El extracto bancario (.xlsx, .xls, .pdf)
        banco: Banco opcional — se detecta automáticamente si no se envía
        pdf_password: Contraseña del PDF (requerido para Nequi — es la cédula del titular)
    """
    import tempfile
    import os
    from services.bank_parsers import detect_bank
    from agents.contador.handlers.conciliacion import handle_conciliar_extracto_bancario
    from services.alegra.client import AlegraClient

    suffix = os.path.splitext(file.filename or "")[1] or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        alegra = AlegraClient(db=db)
        result = await handle_conciliar_extracto_bancario(
            tool_input={
                "archivo_path": tmp_path,
                "banco": banco,
                "pdf_password": pdf_password,
            },
            alegra=alegra,
            db=db,
            event_bus=db,
            user_id=current_user.get("username", "api"),
        )
        return result
    except Exception as exc:
        return {"success": False, "error": str(exc), "job_id": None}
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


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
