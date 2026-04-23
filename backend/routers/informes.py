"""
routers/informes.py — CRUD del informe semanal de créditos sin pago.

Endpoints:
  GET  /api/informes/semana-actual          — Informe de la semana actual (crea si no existe)
  GET  /api/informes/semana/{semana_id}     — Informe específico ej: 2026-W17
  GET  /api/informes/historial              — Últimas 12 semanas
  POST /api/informes/generar                — Genera / regenera informe de la semana actual
  PATCH /api/informes/semana/{semana_id}/credito/{loanbook_id}  — Actualiza gestión de un crédito
  PATCH /api/informes/semana/{semana_id}/notas                  — Actualiza notas generales
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.auth import get_current_user
from core.database import get_db

logger = logging.getLogger("routers.informes")

router = APIRouter(prefix="/api/informes", tags=["informes"])

_ESTADOS_GESTION_VALIDOS = {"pendiente", "contactado", "acuerdo", "pagó"}


def _clean(doc: dict) -> dict:
    """Elimina _id para serialización JSON."""
    if doc:
        doc = dict(doc)
        doc.pop("_id", None)
    return doc or {}


# ─────────────────────── GET semana actual ────────────────────────────────────

@router.get("/semana-actual")
async def get_semana_actual(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Retorna el informe de la semana actual. Lo crea si no existe."""
    from services.loanbook.informes_service import generar_informe_semanal, _semana_id
    from datetime import date

    semana_id = _semana_id(date.today())
    informe = await db.informes_semanales.find_one({"semana_id": semana_id})
    if not informe:
        await generar_informe_semanal(db, generado_por="auto")
        informe = await db.informes_semanales.find_one({"semana_id": semana_id})
    if not informe:
        raise HTTPException(status_code=404, detail=f"No se pudo generar informe para {semana_id}")
    return _clean(informe)


# ─────────────────────── GET semana específica ───────────────────────────────

@router.get("/semana/{semana_id}")
async def get_semana(
    semana_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Retorna informe de una semana específica (ej: 2026-W17)."""
    informe = await db.informes_semanales.find_one({"semana_id": semana_id})
    if not informe:
        raise HTTPException(status_code=404, detail=f"Informe {semana_id} no encontrado")
    return _clean(informe)


# ─────────────────────── GET historial ───────────────────────────────────────

@router.get("/historial")
async def get_historial(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Últimas 12 semanas de informes (resumen sin sin_pago detallado)."""
    docs = await db.informes_semanales.find(
        {},
        {"semana_id": 1, "fecha_corte": 1, "fecha_generacion": 1,
         "total_sin_pago": 1, "valor_en_riesgo": 1, "generado_por": 1},
    ).sort("fecha_generacion", -1).limit(12).to_list(12)
    return [_clean(d) for d in docs]


# ─────────────────────── POST generar ────────────────────────────────────────

@router.post("/generar")
async def generar_informe(
    forzar: bool = False,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Genera manualmente el informe de la semana actual.
    Si forzar=True, sobreescribe el existente.
    """
    from services.loanbook.informes_service import generar_informe_semanal
    return await generar_informe_semanal(db, generado_por="manual", forzar=forzar)


# ─────────────────────── PATCH crédito individual ────────────────────────────

@router.patch("/semana/{semana_id}/credito/{loanbook_id}")
async def patch_credito_gestion(
    semana_id: str,
    loanbook_id: str,
    body: dict = Body(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Actualiza estado_gestion y/o notas de un crédito en el informe."""
    estado_gestion = body.get("estado_gestion")
    notas = body.get("notas")

    if estado_gestion and estado_gestion not in _ESTADOS_GESTION_VALIDOS:
        raise HTTPException(
            status_code=422,
            detail=f"estado_gestion inválido. Válidos: {sorted(_ESTADOS_GESTION_VALIDOS)}",
        )

    informe = await db.informes_semanales.find_one({"semana_id": semana_id})
    if not informe:
        raise HTTPException(status_code=404, detail=f"Informe {semana_id} no encontrado")

    sin_pago = informe.get("sin_pago") or []
    idx = next(
        (i for i, c in enumerate(sin_pago) if c.get("loanbook_id") == loanbook_id),
        None,
    )
    if idx is None:
        raise HTTPException(
            status_code=404,
            detail=f"Crédito {loanbook_id} no encontrado en informe {semana_id}",
        )

    user_id = current_user.get("id") or current_user.get("sub") or "admin"
    update: dict = {"updated_at": datetime.utcnow()}
    if estado_gestion is not None:
        update[f"sin_pago.{idx}.estado_gestion"] = estado_gestion
    if notas is not None:
        update[f"sin_pago.{idx}.notas"] = notas
    update[f"sin_pago.{idx}.actualizado_por"] = user_id
    update[f"sin_pago.{idx}.actualizado_at"] = datetime.utcnow()

    await db.informes_semanales.update_one(
        {"semana_id": semana_id},
        {"$set": update},
    )
    return {"ok": True, "semana_id": semana_id, "loanbook_id": loanbook_id}


# ─────────────────────── PATCH notas generales ───────────────────────────────

@router.patch("/semana/{semana_id}/notas")
async def patch_notas_generales(
    semana_id: str,
    body: dict = Body(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Actualiza las notas generales del informe de la semana."""
    notas = body.get("notas_generales")
    if notas is None:
        raise HTTPException(status_code=400, detail="Se requiere 'notas_generales' en el body")

    result = await db.informes_semanales.update_one(
        {"semana_id": semana_id},
        {"$set": {"notas_generales": notas, "updated_at": datetime.utcnow()}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail=f"Informe {semana_id} no encontrado")
    return {"ok": True, "semana_id": semana_id}
