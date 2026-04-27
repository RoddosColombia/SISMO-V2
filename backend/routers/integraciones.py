"""
routers/integraciones.py — Endpoints read-only para integraciones externas.

Autenticación: X-API-Key header con key en colección api_keys (scope=read_only).
NO requiere JWT — diseñado para consumo server-to-server (ARGOS, etc.).

Endpoints:
  GET /api/integraciones/health               — health check público (sin API key)
  GET /api/integraciones/repuestos            — catálogo de repuestos (EL MÁS CRÍTICO)
  GET /api/integraciones/motos/inventario     — lista motos sin PII de clientes
  GET /api/integraciones/cartera/resumen      — KPIs de cartera activa
"""

import logging

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.auth import get_api_key
from core.database import get_db
from core.datetime_utils import today_bogota, now_iso_bogota

logger = logging.getLogger("routers.integraciones")

router = APIRouter(prefix="/api/integraciones", tags=["integraciones"])


# ─────────────────────── Health (público, sin API key) ───────────────────────

@router.get("/health")
async def integraciones_health():
    """Health check público — no requiere API key.

    Permite a sistemas externos verificar que la API está viva antes de hacer
    llamadas autenticadas.
    """
    return {
        "status": "ok",
        "fuente": "sismo_v2",
        "timestamp": now_iso_bogota(),
    }


# ─────────────────────── Repuestos (EL MÁS CRÍTICO) ─────────────────────────

@router.get("/repuestos")
async def integraciones_repuestos(
    api_key: dict = Depends(get_api_key),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Catálogo completo de repuestos con stock y precios.

    Devuelve: sku, nombre, categoria, marca_compatible, precio_venta,
              precio_costo, stock, estado, proveedor, ultima_actualizacion.
    Sin PII. Requiere X-API-Key con scope=read_only.

    ARGOS usa este endpoint para detectar qué repuestos necesita reponer
    y comparar precios contra el mercado.
    """
    docs = await db.inventario_repuestos.find({}).to_list(length=5000)

    repuestos = []
    disponibles = 0
    for d in docs:
        estado = d.get("estado") or "desconocido"
        if estado == "disponible":
            disponibles += 1
        repuestos.append({
            "sku":                 d.get("sku") or "",
            "nombre":              d.get("nombre") or "",
            "categoria":           d.get("categoria") or "",
            "marca_compatible":    d.get("marca_compatible") or "",
            "precio_venta":        d.get("precio_venta") or 0,
            "precio_costo":        d.get("precio_costo") or 0,
            "stock":               d.get("stock") or 0,
            "estado":              estado,
            "proveedor":           d.get("proveedor") or "",
            "ultima_actualizacion": d.get("ultima_actualizacion") or "",
        })

    return {
        "total":       len(repuestos),
        "disponibles": disponibles,
        "repuestos":   repuestos,
        "fuente":      "sismo_v2",
        "timestamp":   now_iso_bogota(),
    }


# ─────────────────────── Motos — inventario ──────────────────────────────────

@router.get("/motos/inventario")
async def integraciones_motos_inventario(
    api_key: dict = Depends(get_api_key),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Lista motos en inventario con estado.

    Devuelve: vin, modelo, estado, color, placa — sin PII de clientes.
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
        "total":      len(resultado),
        "inventario": resultado,
        "fuente":     "sismo_v2",
        "fecha":      today_bogota().isoformat(),
    }


# ─────────────────────── Cartera ─────────────────────────────────────────────

@router.get("/cartera/resumen")
async def integraciones_cartera_resumen(
    api_key: dict = Depends(get_api_key),
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
