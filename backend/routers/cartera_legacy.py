"""
cartera_legacy.py — BUILD 0.1 (V2)

Read-only endpoints for the legacy credit portfolio.

GET  /api/cartera-legacy/stats     — totals + distribution by aliado
GET  /api/cartera-legacy           — paginated list with filters
GET  /api/cartera-legacy/{codigo}  — detail + pagos_recibidos

Collection: loanbook_legacy
Key:        codigo_sismo  (LG-{cedula}-{numero_credito})
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from core.auth import get_current_user
from core.database import get_db

logger = logging.getLogger("routers.cartera_legacy")

router = APIRouter(prefix="/api/cartera-legacy", tags=["cartera-legacy"])


# ── Pydantic schema ────────────────────────────────────────────────────────────

class PagoRegistrado(BaseModel):
    fecha: Optional[str] = None
    monto: Optional[float] = None
    alegra_journal_id: Optional[str] = None
    backlog_movimiento_id: Optional[str] = None


class LoanbookLegacyDoc(BaseModel):
    codigo_sismo: str
    cedula: str
    numero_credito_original: str
    nombre_completo: str
    placa: Optional[str] = None
    aliado: str
    estado: str
    estado_legacy_excel: str
    saldo_actual: float
    saldo_inicial: float
    dias_mora_maxima: Optional[int] = None
    pct_on_time: Optional[float] = None
    score_total: Optional[float] = None
    decision_historica: Optional[str] = None
    analisis_texto: Optional[str] = None
    alegra_contact_id: Optional[str] = None
    pagos_recibidos: list[PagoRegistrado] = Field(default_factory=list)
    fecha_importacion: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


def _clean(doc: dict) -> dict:
    """Strip ObjectId and return JSON-safe dict."""
    doc.pop("_id", None)
    return doc


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_cartera_legacy_stats(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Portfolio totals and aliado distribution."""
    pipeline = [
        {
            "$group": {
                "_id": None,
                "total_creditos": {"$sum": 1},
                "saldo_total":    {"$sum": "$saldo_actual"},
                "activos":        {"$sum": {"$cond": [{"$eq": ["$estado", "activo"]}, 1, 0]}},
                "saldados":       {"$sum": {"$cond": [{"$eq": ["$estado", "saldado"]}, 1, 0]}},
                "castigados":     {"$sum": {"$cond": [{"$eq": ["$estado", "castigado"]}, 1, 0]}},
                "en_mora":        {"$sum": {"$cond": [{"$eq": ["$estado_legacy_excel", "En Mora"]}, 1, 0]}},
                "al_dia":         {"$sum": {"$cond": [{"$eq": ["$estado_legacy_excel", "Al Día"]}, 1, 0]}},
            }
        }
    ]

    totales: dict = {}
    async for doc in db.loanbook_legacy.aggregate(pipeline):
        doc.pop("_id", None)
        totales = doc

    aliado_pipeline = [
        {"$group": {
            "_id":   "$aliado",
            "count": {"$sum": 1},
            "saldo": {"$sum": "$saldo_actual"},
        }},
        {"$sort": {"saldo": -1}},
    ]
    por_aliado = []
    async for doc in db.loanbook_legacy.aggregate(aliado_pipeline):
        por_aliado.append({"aliado": doc["_id"], "count": doc["count"], "saldo": doc["saldo"]})

    return {"success": True, "data": {**totales, "por_aliado": por_aliado}}


@router.get("")
async def list_cartera_legacy(
    estado:  Optional[str]  = Query(None, description="activo|saldado|castigado"),
    aliado:  Optional[str]  = Query(None),
    en_mora: Optional[bool] = Query(None, description="true=En Mora, false=Al Día"),
    page:    int             = Query(1, ge=1),
    limit:   int             = Query(50, ge=1, le=200),
    db:      AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict       = Depends(get_current_user),
):
    """Paginated list of legacy credits with optional filters."""
    filtro: dict = {}
    if estado:
        filtro["estado"] = estado
    if aliado:
        filtro["aliado"] = aliado
    if en_mora is not None:
        filtro["estado_legacy_excel"] = "En Mora" if en_mora else "Al Día"

    skip  = (page - 1) * limit
    total = await db.loanbook_legacy.count_documents(filtro)

    cursor = (
        db.loanbook_legacy
        .find(filtro, {"pagos_recibidos": 0})
        .sort("saldo_actual", -1)
        .skip(skip)
        .limit(limit)
    )
    docs = await cursor.to_list(length=limit)
    for doc in docs:
        doc.pop("_id", None)

    return {
        "success": True,
        "data":    docs,
        "total":   total,
        "page":    page,
        "pages":   (total + limit - 1) // limit,
    }


@router.get("/{codigo}")
async def get_cartera_legacy_detalle(
    codigo: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Full detail for one legacy credit, including pagos_recibidos."""
    doc = await db.loanbook_legacy.find_one({"codigo_sismo": codigo})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Crédito {codigo} no encontrado")
    return {"success": True, "data": _clean(doc)}
