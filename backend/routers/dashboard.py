"""
GET /api/dashboard/stats — Métricas ejecutivas del mes actual.

Cards:
  1. dinero_facturado_mes   — Suma de facturas Alegra (status≠draft) del mes corriente
  2. motos_facturadas_mes   — Cantidad de facturas de venta del mes corriente
  3. cuotas_recibidas_mes   — Suma de cuotas pagadas en el mes corriente (MongoDB loanbook)

Todas las cifras son del mes calendario actual en hora Colombia (UTC-5).
Si Alegra falla, los campos de Alegra retornan null sin tirar 500.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_db
from core.auth import get_current_user
from services.alegra.client import AlegraClient

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# Colombia = UTC-5
COLOMBIA_OFFSET = timedelta(hours=-5)


def _mes_actual_rango() -> tuple[str, str]:
    """Retorna (start_date, end_date) del mes actual en hora Colombia (yyyy-MM-dd)."""
    ahora_col = datetime.now(timezone.utc) + COLOMBIA_OFFSET
    start = ahora_col.replace(day=1)
    # Último día del mes: ir al primer día del mes siguiente y restar 1
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        end = start.replace(month=start.month + 1, day=1) - timedelta(days=1)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _mes_actual_prefix() -> str:
    """Retorna prefijo 'YYYY-MM' del mes actual en hora Colombia."""
    ahora_col = datetime.now(timezone.utc) + COLOMBIA_OFFSET
    return ahora_col.strftime("%Y-%m")


@router.get("/stats")
async def dashboard_stats(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    start_date, end_date = _mes_actual_rango()
    mes_prefix = _mes_actual_prefix()

    # ── Card 3: cuotas recibidas este mes (MongoDB) ──────────────────────
    cuotas_mes = 0.0
    cuotas_count = 0
    try:
        pipeline = [
            {"$match": {"estado": {"$nin": ["cancelado"]}}},
            {"$unwind": "$cuotas"},
            {
                "$match": {
                    "cuotas.estado": "pagada",
                    "cuotas.fecha_pago": {"$regex": f"^{mes_prefix}"},
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total": {"$sum": "$cuotas.monto"},
                    "count": {"$sum": 1},
                }
            },
        ]
        async for doc in db.loanbook.aggregate(pipeline):
            cuotas_mes = doc.get("total", 0.0)
            cuotas_count = doc.get("count", 0)
    except Exception:
        pass  # MongoDB error — degrade gracefully

    # ── Cards 1 + 2: facturas Alegra del mes ────────────────────────────
    dinero_facturado = None
    motos_facturadas = None
    try:
        alegra = AlegraClient(db=db)
        # Alegra paginates at 30 by default; usamos limit=100 para no perdernos facturas
        invoices = await alegra.get(
            "invoices",
            params={
                "start-date": start_date,
                "end-date": end_date,
                "type": "sale",
                "limit": 100,
                "start": 0,
            },
        )
        if isinstance(invoices, list):
            # Solo facturas que no sean borrador
            activas = [inv for inv in invoices if inv.get("status") != "draft"]
            dinero_facturado = sum(
                float(inv.get("total", 0) or 0) for inv in activas
            )
            motos_facturadas = len(activas)
    except Exception:
        pass  # Alegra offline — campos quedan en null, no es crítico

    return {
        "mes": mes_prefix,
        "rango": {"desde": start_date, "hasta": end_date},
        # Alegra — null si el servicio no responde
        "dinero_facturado_mes": dinero_facturado,
        "motos_facturadas_mes": motos_facturadas,
        # MongoDB — siempre disponible
        "cuotas_recibidas_mes": cuotas_mes,
        "cuotas_pagadas_count": cuotas_count,
    }
