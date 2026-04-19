"""
GET /api/dashboard/stats — Métricas ejecutivas del mes actual.

Cards:
  1. dinero_facturado_mes   — Facturas Alegra del mes (desde cache MongoDB)
  2. motos_facturadas_mes   — Cantidad de facturas de venta del mes
  3. cuotas_recibidas_mes   — Cuotas pagadas en el mes (aggregation MongoDB loanbook)

Arquitectura de datos:
  - Cards 1+2: DataKeeper sincroniza desde Alegra cada hora y al recibir
    factura.venta.creada → guarda en `alegra_stats_cache`.
    El endpoint lee del cache. Si el cache está vacío, intenta sync on-demand.
  - Card 3: aggregation directa sobre MongoDB (siempre disponible).

Todas las cifras en hora Colombia (UTC-5).
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_db
from core.auth import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

COLOMBIA_OFFSET = timedelta(hours=-5)


def _mes_prefix() -> str:
    return (datetime.now(timezone.utc) + COLOMBIA_OFFSET).strftime("%Y-%m")


def _mes_rango() -> tuple[str, str]:
    ahora_col = datetime.now(timezone.utc) + COLOMBIA_OFFSET
    start = ahora_col.replace(day=1)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        end = start.replace(month=start.month + 1, day=1) - timedelta(days=1)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


@router.get("/stats")
async def dashboard_stats(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    mes = _mes_prefix()
    start_date, end_date = _mes_rango()

    # ── Cards 1+2: Alegra — leer desde cache DataKeeper ─────────────────
    dinero_facturado: float | None = None
    motos_facturadas: int | None = None
    cache_updated_at: str | None = None

    try:
        cache = await db.alegra_stats_cache.find_one(
            {"tipo": "invoices_mes", "mes": mes}
        )
        if cache:
            dinero_facturado = cache.get("dinero_facturado")
            motos_facturadas = cache.get("motos_facturadas")
            cache_updated_at = cache.get("updated_at")
        else:
            # Cache vacío (primer arranque o cache expirado) — sync on-demand
            from core.alegra_sync import sync_alegra_invoice_stats
            result = await sync_alegra_invoice_stats(db)
            if result:
                dinero_facturado = result.get("dinero_facturado")
                motos_facturadas = result.get("motos_facturadas")
                cache_updated_at = result.get("updated_at")
    except Exception:
        pass  # Degrada sin 500

    # ── Card 3: cuotas recibidas — aggregation MongoDB ───────────────────
    cuotas_mes = 0.0
    cuotas_count = 0
    try:
        pipeline = [
            {"$match": {"estado": {"$nin": ["cancelado"]}}},
            {"$unwind": "$cuotas"},
            {
                "$match": {
                    "cuotas.estado": "pagada",
                    "cuotas.fecha_pago": {"$regex": f"^{mes}"},
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
        pass

    return {
        "mes": mes,
        "rango": {"desde": start_date, "hasta": end_date},
        "dinero_facturado_mes": dinero_facturado,
        "motos_facturadas_mes": motos_facturadas,
        "cuotas_recibidas_mes": cuotas_mes,
        "cuotas_pagadas_count": cuotas_count,
        "cache_updated_at": cache_updated_at,
    }


@router.post("/sync-alegra")
async def trigger_alegra_sync(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Fuerza sync inmediato desde Alegra. Borra el cache antes para garantizar dato fresco."""
    from core.alegra_sync import sync_alegra_invoice_stats
    mes = _mes_prefix()
    await db.alegra_stats_cache.delete_one({"tipo": "invoices_mes", "mes": mes})
    result = await sync_alegra_invoice_stats(db)
    return {"ok": True, "result": result}


@router.get("/debug-alegra")
async def debug_alegra(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Debug: prueba 3 variantes de parámetros contra Alegra para identificar cuál funciona."""
    from services.alegra.client import AlegraClient
    import os

    mes_prefix = _mes_prefix()
    start_date, end_date = _mes_rango()

    result: dict = {
        "mes": mes_prefix,
        "start_date": start_date,
        "end_date": end_date,
        "alegra_email_set": bool(os.environ.get("ALEGRA_EMAIL")),
        "alegra_token_set": bool(os.environ.get("ALEGRA_TOKEN")),
        "cache": None,
        "probe_no_date": None,
        "probe_start_date": None,
        "probe_date_range": None,
    }

    # Estado del cache
    cache = await db.alegra_stats_cache.find_one({"tipo": "invoices_mes", "mes": mes_prefix})
    if cache:
        cache.pop("_id", None)
    result["cache"] = cache

    alegra = AlegraClient(db=db)

    async def probe(params: dict) -> dict:
        try:
            resp = await alegra.get("invoices", params=params)
            if isinstance(resp, list):
                return {"ok": True, "count": len(resp), "sample": resp[:2]}
            return {"ok": True, "type": type(resp).__name__, "data": resp}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # Prueba 1: sin filtro — muestra campos reales del primer invoice
    result["probe_no_date"] = await probe({"limit": 3, "start": 0})

    # Campos del primer invoice (para saber cómo se llama el campo de fecha)
    try:
        raw = await alegra.get("invoices", params={"limit": 1, "start": 0})
        if isinstance(raw, list) and raw:
            first = raw[0]
            result["invoice_keys"] = list(first.keys())
            result["invoice_date_fields"] = {
                k: v for k, v in first.items()
                if "date" in k.lower() or "fecha" in k.lower() or k in ("date", "dueDate", "createdAt", "updatedAt")
            }
            result["invoice_sample_id"] = first.get("id")
            result["invoice_sample_total"] = first.get("total")
    except Exception as exc:
        result["invoice_keys_error"] = str(exc)

    return result
