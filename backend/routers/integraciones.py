"""
routers/integraciones.py — Endpoints read-only para integraciones externas.

Autenticación: X-API-Key header con key en colección api_keys (scope=read_only).
NO requiere JWT — diseñado para consumo server-to-server (ARGOS, etc.).

Endpoints:
  GET /api/integraciones/inventario        — Lista motos sin PII de clientes
  GET /api/integraciones/cartera/resumen   — KPIs de cartera activa
  GET /api/integraciones/loanbook/stats    — Alias público de /api/loanbook/stats
"""

import logging

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.auth import get_api_key_dep
from core.database import get_db
from core.datetime_utils import today_bogota

logger = logging.getLogger("routers.integraciones")

router = APIRouter(prefix="/api/integraciones", tags=["integraciones"])

# Dependency singleton — creado una sola vez al importar el módulo
_api_key_auth = get_api_key_dep()


# ─────────────────────── Inventario ──────────────────────────────────────────

@router.get("/inventario")
async def integraciones_inventario(
    api_key: dict = Depends(_api_key_auth),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Lista motos en inventario con estado.

    Devuelve: vin, modelo, estado, color — sin PII de clientes.
    Requiere X-API-Key con scope=read_only.
    """
    motos = await db.inventario_motos.find({}).to_list(length=2000)

    resultado = []
    for m in motos:
        resultado.append({
            "vin":    m.get("vin") or m.get("chasis") or "",
            "modelo": m.get("modelo") or "",
            "estado": m.get("estado") or "",
            "color":  m.get("color") or "",
            "placa":  m.get("placa") or "",
        })

    return {
        "total":     len(resultado),
        "inventario": resultado,
        "fuente":    "sismo_v2",
        "fecha":     today_bogota().isoformat(),
    }


# ─────────────────────── Cartera ─────────────────────────────────────────────

@router.get("/cartera/resumen")
async def integraciones_cartera_resumen(
    api_key: dict = Depends(_api_key_auth),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Resumen ejecutivo de la cartera activa.

    Devuelve: cartera_total_cop, creditos_activos, creditos_en_mora,
              recaudo_semanal_proyectado_cop.
    Sin datos de clientes ni PII.
    Requiere X-API-Key con scope=read_only.
    """
    estados_excluidos = ["saldado", "castigado", "Pagado", "pagado"]
    lbs = await db.loanbook.find(
        {"estado": {"$nin": estados_excluidos}}
    ).to_list(length=2000)

    cartera_total   = 0
    en_mora         = 0
    activos         = 0
    recaudo_semanal = 0

    for lb in lbs:
        estado = lb.get("estado", "")
        if estado == "pendiente_entrega":
            continue

        activos += 1
        cartera_total += (lb.get("saldo_capital") or 0) + (lb.get("saldo_intereses") or 0)

        if (lb.get("dpd") or 0) > 0:
            en_mora += 1

        modalidad = lb.get("modalidad", "semanal")
        cuota     = lb.get("cuota_monto") or 0
        if modalidad == "semanal":
            recaudo_semanal += cuota
        elif modalidad == "quincenal":
            recaudo_semanal += cuota / 2
        elif modalidad == "mensual":
            recaudo_semanal += cuota / 4

    return {
        "cartera_total_cop":              round(cartera_total),
        "creditos_activos":               activos,
        "creditos_en_mora":               en_mora,
        "tasa_mora_pct":                  round(en_mora / activos * 100, 1) if activos else 0,
        "recaudo_semanal_proyectado_cop": round(recaudo_semanal),
        "fuente": "sismo_v2",
        "fecha":  today_bogota().isoformat(),
    }


# ─────────────────────── Loanbook stats ──────────────────────────────────────

@router.get("/loanbook/stats")
async def integraciones_loanbook_stats(
    api_key: dict = Depends(_api_key_auth),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Alias público de GET /api/loanbook/stats.

    Devuelve KPIs del portafolio: total, activos, saldados, cartera, recaudo,
    en_mora. Sin datos de clientes ni PII.
    Requiere X-API-Key con scope=read_only.
    """
    hoy = today_bogota()

    all_lbs = await db.loanbook.find().to_list(length=1000)
    total           = len(all_lbs)
    activos         = 0
    saldados        = 0
    pendiente_entrega = 0
    cartera_total   = 0
    recaudo_semanal = 0
    en_mora         = 0

    from core.loanbook_model import calcular_dpd

    for lb in all_lbs:
        estado = lb.get("estado", "")
        if estado in ("saldado", "castigado"):
            saldados += 1
            continue
        if estado == "pendiente_entrega":
            pendiente_entrega += 1
        activos += 1
        if estado != "pendiente_entrega":
            cartera_total += (
                (lb.get("saldo_capital") or lb.get("saldo_pendiente") or 0)
                + (lb.get("saldo_intereses") or 0)
            )
            modalidad = lb.get("modalidad", "semanal")
            cuota     = lb.get("cuota_monto") or 0
            if modalidad == "semanal":
                recaudo_semanal += cuota
            elif modalidad == "quincenal":
                recaudo_semanal += cuota / 2
            elif modalidad == "mensual":
                recaudo_semanal += cuota / 4

            cuotas = lb.get("cuotas", [])
            if calcular_dpd(cuotas, hoy) > 0:
                en_mora += 1

    return {
        "total":             total,
        "activos":           activos,
        "saldados":          saldados,
        "pendiente_entrega": pendiente_entrega,
        "cartera_total":     round(cartera_total),
        "recaudo_semanal":   round(recaudo_semanal),
        "en_mora":           en_mora,
        "fuente":            "sismo_v2",
        "fecha":             hoy.isoformat(),
    }
