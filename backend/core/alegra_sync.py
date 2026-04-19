"""
Alegra Stats Sync — DataKeeper background service.

Responsabilidad: sincronizar métricas de facturas del mes actual desde Alegra
hacia la colección `alegra_stats_cache` en MongoDB.

Cuándo se ejecuta:
  1. Periódicamente cada SYNC_INTERVAL_MINUTES minutos (loop en lifespan)
  2. On-demand cuando llega el evento factura.venta.creada

Colección: alegra_stats_cache
  {
    "tipo": "invoices_mes",
    "mes": "2026-04",
    "dinero_facturado": 12_000_000,
    "motos_facturadas": 3,
    "updated_at": "2026-04-19T...",
    "source": "alegra_api" | "error_previo"
  }
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

import httpx
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger("datakeeper.alegra_sync")

SYNC_INTERVAL_MINUTES = 60  # Resync desde Alegra cada hora
COLOMBIA_OFFSET = timedelta(hours=-5)
ALEGRA_BASE_URL = "https://api.alegra.com/api/v1"


def _mes_rango() -> tuple[str, str, str]:
    """Retorna (mes_prefix, start_date, end_date) en hora Colombia."""
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
    Llama Alegra GET /invoices del mes actual y cachea el resultado.
    Retorna el doc guardado. Si Alegra falla, retorna el cache anterior
    o un dict con zeros si no hay nada previo.
    """
    mes_prefix, start_date, end_date = _mes_rango()
    CACHE_KEY = {"tipo": "invoices_mes", "mes": mes_prefix}

    token = os.environ.get("ALEGRA_TOKEN", "")
    if not token:
        logger.warning("ALEGRA_TOKEN no configurado — saltando sync de Alegra")
        return {}

    try:
        auth = httpx.BasicAuth(username=token, password="")
        params = {
            "start-date": start_date,
            "end-date": end_date,
            "type": "sale",
            "limit": 100,
            "start": 0,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{ALEGRA_BASE_URL}/invoices",
                params=params,
                auth=auth,
            )
            resp.raise_for_status()
            invoices = resp.json()

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
            f"Alegra sync OK — mes {mes_prefix}: "
            f"{count} facturas / ${dinero:,.0f}"
        )
        return doc

    except Exception as exc:
        logger.error(f"Alegra sync error: {exc}")
        # Retorna lo que haya en cache (puede ser de hace una hora)
        prev = await db.alegra_stats_cache.find_one(CACHE_KEY)
        if prev:
            prev.pop("_id", None)
        return prev or {}


async def run_sync_loop(db: AsyncIOMotorDatabase) -> None:
    """
    Loop infinito que sincroniza Alegra cada SYNC_INTERVAL_MINUTES.
    Se lanza como asyncio.Task en lifespan.
    """
    # Sync inicial al arrancar
    await asyncio.sleep(5)  # espera que el servidor esté listo
    await sync_alegra_invoice_stats(db)

    while True:
        await asyncio.sleep(SYNC_INTERVAL_MINUTES * 60)
        await sync_alegra_invoice_stats(db)
