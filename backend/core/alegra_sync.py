"""
Alegra Stats Sync — DataKeeper background service.

Usa AlegraClient (el único path autorizado para llamadas a Alegra en SISMO V2)
para obtener las métricas de facturas del mes actual y cachearlas en MongoDB.

Colección: alegra_stats_cache
  {
    "tipo": "invoices_mes",
    "mes": "2026-04",
    "dinero_facturado": 12_000_000,
    "motos_facturadas": 3,
    "updated_at": "2026-04-19T...",
    "source": "alegra_api"
  }
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger("datakeeper.alegra_sync")

SYNC_INTERVAL_MINUTES = 60
COLOMBIA_OFFSET = timedelta(hours=-5)


def _mes_rango() -> tuple[str, str, str]:
    """(mes_prefix, start_date, end_date) en hora Colombia."""
    now_col = datetime.now(timezone.utc) + COLOMBIA_OFFSET
    start = now_col.replace(day=1)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        end = start.replace(month=start.month + 1, day=1) - timedelta(days=1)
    return (
        now_col.strftime("%Y-%m"),
        start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
    )


async def sync_alegra_invoice_stats(db: AsyncIOMotorDatabase) -> dict:
    """
    Llama Alegra GET /invoices del mes actual y cachea en alegra_stats_cache.
    Usa AlegraClient (auth correcta: ALEGRA_EMAIL + ALEGRA_TOKEN).
    Si falla, retorna el cache anterior sin tirar excepción.
    """
    from services.alegra.client import AlegraClient

    mes_prefix, start_date, end_date = _mes_rango()
    CACHE_KEY = {"tipo": "invoices_mes", "mes": mes_prefix}

    try:
        alegra = AlegraClient(db=db)

        invoices = await alegra.get(
            "invoices",
            params={
                "date_range_start": start_date,
                "date_range_end": end_date,
                "limit": 30,
                "start": 0,
            },
        )

        if not isinstance(invoices, list):
            invoices = []

        activas = [inv for inv in invoices if inv.get("status") != "draft"]
        dinero = sum(float(inv.get("total", 0) or 0) for inv in activas)
        count = len(activas)

        doc = {
            **CACHE_KEY,
            "dinero_facturado": dinero,
            "motos_facturadas": count,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source": "alegra_api",
        }
        await db.alegra_stats_cache.update_one(
            CACHE_KEY,
            {"$set": doc},
            upsert=True,
        )
        logger.info(
            f"Alegra sync OK — {mes_prefix}: {count} facturas / ${dinero:,.0f}"
        )
        return doc

    except Exception as exc:
        logger.error(f"Alegra sync error: {exc}")
        prev = await db.alegra_stats_cache.find_one(CACHE_KEY)
        if prev:
            prev.pop("_id", None)
        return prev or {}


async def run_sync_loop(db: AsyncIOMotorDatabase) -> None:
    """Loop infinito que sincroniza Alegra cada SYNC_INTERVAL_MINUTES."""
    await asyncio.sleep(5)  # espera arranque del servidor
    await sync_alegra_invoice_stats(db)
    while True:
        await asyncio.sleep(SYNC_INTERVAL_MINUTES * 60)
        await sync_alegra_invoice_stats(db)
