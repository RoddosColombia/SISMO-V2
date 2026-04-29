"""
routers/tributario.py — Endpoints motor tributario.

Wave 1 (cimientos): solo calendario y consulta de obligaciones próximas.
Wave 2-5: liquidaciones, recomendaciones CFO, dashboard, alertas.
"""
from __future__ import annotations
import logging
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_db
from core.datetime_utils import today_bogota
from services.tributario.calendario_dian import (
    obligaciones_proximas,
    todas_obligaciones_2026,
)
from services.tributario.conceptos_retencion import (
    CONCEPTOS_RETEFUENTE,
    UVT_2026,
    REICA_BOGOTA_TARIFA_COMERCIAL,
    RETEIVA_TARIFA,
    IVA_GENERAL,
)

logger = logging.getLogger("routers.tributario")

router = APIRouter(prefix="/api/tributario", tags=["tributario"])


@router.get("/obligaciones-proximas")
async def get_obligaciones_proximas(
    dias: Annotated[int, Query(ge=1, le=365)] = 30,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Devuelve obligaciones cuyo vencimiento está dentro de los próximos N días."""
    proximas = obligaciones_proximas(dias_adelante=dias)
    # Enriquecer con estado real desde MongoDB si ya hay registros
    obligaciones_db = {
        o["obligacion_id"]: o
        async for o in db.obligaciones_tributarias.find({})
    }

    enriched = []
    for o in proximas:
        oid = f"{o['tipo']}-{o['periodo'].lower()}"
        db_doc = obligaciones_db.get(oid)
        enriched.append({
            **o,
            "obligacion_id": oid,
            "estado": (db_doc or {}).get("estado", "pendiente"),
            "impuesto_a_pagar": (db_doc or {}).get("impuesto_a_pagar"),
            "calculado_at": (db_doc or {}).get("calculado_at"),
            "fecha_pago": (db_doc or {}).get("fecha_pago"),
        })

    return {
        "fecha_corte": today_bogota().isoformat(),
        "rango_dias": dias,
        "total": len(enriched),
        "obligaciones": enriched,
    }


@router.get("/calendario-2026")
async def get_calendario_2026():
    """Devuelve el calendario completo 2026."""
    return {
        "anio": 2026,
        "obligaciones": todas_obligaciones_2026(),
    }


@router.get("/conceptos-retencion")
async def get_conceptos_retencion():
    """Devuelve catálogo de conceptos de retención + tarifas vigentes."""
    return {
        "uvt_2026": UVT_2026,
        "iva_general": IVA_GENERAL,
        "reteiva_tarifa": RETEIVA_TARIFA,
        "reica_bogota_tarifa": REICA_BOGOTA_TARIFA_COMERCIAL,
        "retefuente_conceptos": CONCEPTOS_RETEFUENTE,
    }


@router.get("/dashboard")
async def get_dashboard(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Dashboard tributario consolidado para CFO/UI.

    Wave 1: solo lee tributario_estado_actual (singleton). Si no existe
    todavía (DataKeeper aún no corrió), devuelve esqueleto vacío.
    """
    estado = await db.tributario_estado_actual.find_one({"_id": "actual"})
    proximas = obligaciones_proximas(dias_adelante=60)

    return {
        "fecha_corte": today_bogota().isoformat(),
        "estado_actual": estado or {
            "_id": "actual",
            "iva_periodo_actual": {"generado": 0, "descontable": 0, "neto": 0},
            "retefuente_periodo_actual": {"acumulado": 0},
            "reica_periodo_actual": {"acumulado": 0},
            "tasa_efectiva_pct": 0,
        },
        "proximas_60d": proximas,
        "proximas_60d_count": len(proximas),
    }


@router.get("/recomendaciones")
async def get_recomendaciones(
    estado: Annotated[str, Query()] = "abierta",
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Recomendaciones del CFO. Wave 4 las generará. Por ahora solo lee."""
    recomendaciones = await db.tributario_recomendaciones.find(
        {"estado": estado}
    ).sort("creado_at", -1).to_list(length=100)
    # Convertir ObjectId a string
    for r in recomendaciones:
        r["_id"] = str(r["_id"])
    return {
        "estado_filtro": estado,
        "total": len(recomendaciones),
        "recomendaciones": recomendaciones,
    }
