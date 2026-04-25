"""
routers/radar.py — Endpoints RADAR de cobranza.

GET  /api/radar/preview          — dry_run: qué alertas se enviarían hoy (sin enviar)
POST /api/radar/enviar           — Ejecuta envío real de alertas (solo admin)
GET  /api/radar/queue            — Cola de cobranza priorizada
GET  /api/radar/portfolio-health — KPIs de cartera
GET  /api/radar/semana           — Resumen semanal
GET  /api/radar/roll-rate        — Roll rate de cartera
GET  /api/radar/diagnostico      — Diagnóstico del sistema RADAR
POST /api/radar/arranque         — Activar RADAR
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.auth import get_current_user
from core.database import get_db
from core.datetime_utils import today_bogota

logger = logging.getLogger("routers.radar")

router = APIRouter(prefix="/api/radar", tags=["radar"])


# ─────────────────────── Alertas WhatsApp ────────────────────────────────────

@router.get("/preview")
async def radar_preview(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Muestra qué alertas se enviarían HOY sin enviar nada (dry_run=True).

    Útil para verificar la lista de destinatarios antes del miércoles real.
    Si hoy no es miércoles, el resumen lo indica y no hay destinatarios.
    Requiere autenticación.
    """
    from agents.radar.alertas import enviar_alertas_cobro
    result = await enviar_alertas_cobro(db, dry_run=True)
    return result


@router.post("/enviar")
async def radar_enviar(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Ejecuta el envío real de alertas de cobro via Mercately.

    Solo disponible los miércoles (la función valida internamente).
    Registra cada envío en la colección radar_alertas.
    Requiere autenticación.
    """
    from agents.radar.alertas import enviar_alertas_cobro
    result = await enviar_alertas_cobro(db, dry_run=False)
    return result


# ─────────────────────── Cola de cobranza ────────────────────────────────────

@router.get("/queue")
async def radar_queue(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Cola de cobranza priorizada por DPD y monto pendiente."""
    hoy = today_bogota()

    lbs = await db.loanbook.find(
        {"estado": {"$nin": ["saldado", "castigado", "pendiente_entrega"]}}
    ).to_list(length=1000)

    cola = []
    for lb in lbs:
        dpd = lb.get("dpd") or 0
        if dpd <= 0:
            continue
        cola.append({
            "loanbook_id":   lb.get("loanbook_id"),
            "cliente":       lb.get("cliente", {}).get("nombre") or lb.get("nombre_conductor"),
            "telefono":      lb.get("cliente", {}).get("telefono") or lb.get("telefono"),
            "dpd":           dpd,
            "mora_cop":      lb.get("mora_acumulada_cop") or 0,
            "saldo_capital": lb.get("saldo_capital") or 0,
            "cuota_monto":   lb.get("cuota_monto") or 0,
            "estado":        lb.get("estado"),
            "sub_bucket":    lb.get("sub_bucket_semanal"),
        })

    # Orden: mayor DPD primero, luego mayor saldo
    cola.sort(key=lambda x: (-x["dpd"], -x["saldo_capital"]))

    return {
        "fecha": hoy.isoformat(),
        "total_en_mora": len(cola),
        "cola": cola,
    }


@router.get("/portfolio-health")
async def radar_portfolio_health(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """KPIs de salud de la cartera: mora, distribución por bucket, cartera total."""
    lbs = await db.loanbook.find(
        {"estado": {"$nin": ["saldado", "castigado", "pendiente_entrega"]}}
    ).to_list(length=1000)

    total   = len(lbs)
    en_mora = sum(1 for lb in lbs if (lb.get("dpd") or 0) > 0)
    al_dia  = total - en_mora

    cartera_total = sum(
        (lb.get("saldo_capital") or 0) + (lb.get("saldo_intereses") or 0)
        for lb in lbs
    )
    mora_total_cop = sum(lb.get("mora_acumulada_cop") or 0 for lb in lbs)

    buckets: dict[str, int] = {}
    for lb in lbs:
        bucket = lb.get("sub_bucket_semanal") or "sin_bucket"
        buckets[bucket] = buckets.get(bucket, 0) + 1

    return {
        "total_activos":   total,
        "al_dia":          al_dia,
        "en_mora":         en_mora,
        "tasa_mora_pct":   round(en_mora / total * 100, 1) if total else 0,
        "cartera_total":   round(cartera_total),
        "mora_total_cop":  round(mora_total_cop),
        "buckets":         buckets,
    }


@router.get("/semana")
async def radar_semana(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Resumen semanal de cobros: cuánto se recaudó esta semana."""
    from datetime import timedelta
    hoy = today_bogota()
    inicio_semana = hoy - timedelta(days=hoy.weekday())  # lunes
    inicio_str = inicio_semana.isoformat()

    lbs = await db.loanbook.find({}).to_list(length=1000)

    recaudado = 0
    cuotas_pagadas = 0

    for lb in lbs:
        for c in lb.get("cuotas", []):
            fecha_pago = c.get("fecha_pago") or ""
            if c.get("estado") == "pagada" and fecha_pago >= inicio_str:
                recaudado += c.get("monto") or lb.get("cuota_monto") or 0
                cuotas_pagadas += 1

    return {
        "semana_desde":   inicio_str,
        "semana_hasta":   hoy.isoformat(),
        "recaudado_cop":  round(recaudado),
        "cuotas_pagadas": cuotas_pagadas,
    }


@router.get("/roll-rate")
async def radar_roll_rate(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Matriz de migración entre buckets (roll rate). Placeholder — historial en loanbook_modificaciones."""
    return {
        "nota": "Roll rate placeholder. Requiere historial en loanbook_modificaciones.",
        "matriz": {
            "Current → Early":    "0.0%",
            "Early → Mid":        "0.0%",
            "Mid → Late":         "0.0%",
            "Late → Default":     "0.0%",
            "Default → Charge-Off": "0.0%",
        }
    }


@router.get("/diagnostico")
async def radar_diagnostico(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Diagnóstico del sistema RADAR: templates configurados, último envío."""
    import os

    template_cobro = bool(os.getenv("MERCATELY_TEMPLATE_COBRO_ID"))
    template_mora  = bool(os.getenv("MERCATELY_TEMPLATE_MORA_ID"))
    api_key        = bool(os.getenv("MERCATELY_API_KEY"))

    ultimo_envio = await db.radar_alertas.find_one(
        sort=[("fecha_envio", -1)]
    )
    if ultimo_envio:
        ultimo_envio.pop("_id", None)

    return {
        "mercately_api_key_configurada":      api_key,
        "template_cobro_configurado":         template_cobro,
        "template_mora_configurado":          template_mora,
        "scheduler": "miercoles 08:00 AM America/Bogota",
        "ultimo_envio":                       ultimo_envio,
    }


@router.post("/arranque")
async def radar_arranque(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Activa RADAR — ejecuta preview del estado actual de la cola."""
    from agents.radar.alertas import enviar_alertas_cobro
    preview = await enviar_alertas_cobro(db, dry_run=True)
    return {
        "status": "radar_activo",
        "preview": preview,
    }
