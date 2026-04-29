"""
routers/tributario.py — Endpoints motor tributario.

Wave 1: calendario + consulta obligaciones próximas.
Wave 2: liquidaciones IVA + ReteFuente + ReICA leyendo Alegra.
Wave 3-5: DataKeeper, CFO, UI.
"""
from __future__ import annotations
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_db
from core.datetime_utils import today_bogota
from core.events import publish_event
from services.alegra.client import AlegraClient
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
from services.tributario.liquidador_iva import liquidar_iva_cuatrimestre
from services.tributario.liquidador_retefuente import liquidar_retefuente_mes
from services.tributario.liquidador_reica import liquidar_reica_bogota_bimestre

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


# ───────────────────────────────────────────────────────────────────────────
# WAVE 2 — Endpoints de liquidación. Disparan cálculo + persisten +
# publican obligacion.tributaria.calculada para que DataKeeper consolide.
# ───────────────────────────────────────────────────────────────────────────


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _persistir_obligacion_calculada(
    db: AsyncIOMotorDatabase,
    obligacion_id: str,
    tipo: str,
    nombre: str,
    periodo: str,
    impuesto_a_pagar: float,
    detalle: dict,
    fecha_vencimiento: str,
):
    """Persiste cálculo en obligaciones_tributarias y publica evento."""
    doc = {
        "obligacion_id": obligacion_id,
        "tipo": tipo,
        "nombre": nombre,
        "periodo": periodo,
        "fecha_vencimiento": fecha_vencimiento,
        "impuesto_a_pagar": impuesto_a_pagar,
        "detalle_calculo": detalle,
        "estado": "calculada",
        "calculado_at": _iso_now(),
        "calculado_por": "contador_tool",
        "actualizado_at": _iso_now(),
    }
    await db.obligaciones_tributarias.update_one(
        {"obligacion_id": obligacion_id},
        {"$set": doc},
        upsert=True,
    )
    await publish_event(
        db=db,
        event_type="obligacion.tributaria.calculada",
        source="contador.tributario",
        datos={
            "obligacion_id": obligacion_id,
            "tipo": tipo,
            "periodo": periodo,
            "impuesto_a_pagar": impuesto_a_pagar,
            "fecha_vencimiento": fecha_vencimiento,
        },
        alegra_id=None,
        accion_ejecutada=f"Liquidación {nombre}: ${impuesto_a_pagar:,.0f}",
    )
    return doc


def _ventana_iva_cuatrimestre(periodo: str) -> tuple[date, date, str]:
    """Convierte '2026-C1' → (2026-01-01, 2026-04-30, '2026-05-13')."""
    from services.tributario.calendario_dian import obligaciones_iva_2026
    for o in obligaciones_iva_2026():
        if o["periodo"] == periodo:
            return (
                date.fromisoformat(o["periodo_inicio"]),
                date.fromisoformat(o["periodo_fin"]),
                o["fecha_vencimiento"],
            )
    raise HTTPException(404, f"Periodo IVA {periodo} no encontrado")


@router.post("/liquidar/iva")
async def liquidar_iva(
    periodo: str = Body(..., embed=True, examples=["2026-C1"]),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Dispara liquidación IVA del cuatrimestre. Lee Alegra, calcula, persiste, publica evento."""
    inicio, fin, venc = _ventana_iva_cuatrimestre(periodo)
    alegra = AlegraClient(db=db)
    liq = await liquidar_iva_cuatrimestre(alegra, inicio, fin, periodo)
    doc = await _persistir_obligacion_calculada(
        db,
        obligacion_id=f"iva_cuatrimestral-{periodo.lower()}",
        tipo="iva_cuatrimestral",
        nombre=f"IVA {periodo}",
        periodo=periodo,
        impuesto_a_pagar=liq["iva_neto_a_pagar"],
        detalle=liq,
        fecha_vencimiento=venc,
    )
    return {"ok": True, "liquidacion": liq, "doc_id": doc["obligacion_id"]}


def _ventana_retefuente(periodo: str) -> tuple[int, int, str]:
    """'2026-04' → (2026, 4, '2026-05-13')."""
    from services.tributario.calendario_dian import obligaciones_retefuente_2026
    for o in obligaciones_retefuente_2026():
        if o["periodo"] == periodo:
            anio, mes = periodo.split("-")
            return int(anio), int(mes), o["fecha_vencimiento"]
    raise HTTPException(404, f"Periodo ReteFuente {periodo} no encontrado")


@router.post("/liquidar/retefuente")
async def liquidar_retefuente(
    periodo: str = Body(..., embed=True, examples=["2026-04"]),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Dispara liquidación ReteFuente + ReteIVA del mes."""
    anio, mes, venc = _ventana_retefuente(periodo)
    alegra = AlegraClient(db=db)
    liq = await liquidar_retefuente_mes(alegra, anio, mes)
    liq["fecha_calculo"] = _iso_now()
    doc = await _persistir_obligacion_calculada(
        db,
        obligacion_id=f"retefuente_mensual-{periodo}",
        tipo="retefuente_mensual",
        nombre=f"ReteFuente + ReteIVA {periodo}",
        periodo=periodo,
        impuesto_a_pagar=liq["total_a_pagar"],
        detalle=liq,
        fecha_vencimiento=venc,
    )
    return {"ok": True, "liquidacion": liq, "doc_id": doc["obligacion_id"]}


def _ventana_reica(periodo: str) -> tuple[date, date, str]:
    from services.tributario.calendario_dian import obligaciones_reica_bogota_2026
    for o in obligaciones_reica_bogota_2026():
        if o["periodo"] == periodo:
            return (
                date.fromisoformat(o["periodo_inicio"]),
                date.fromisoformat(o["periodo_fin"]),
                o["fecha_vencimiento"],
            )
    raise HTTPException(404, f"Periodo ReICA {periodo} no encontrado")


@router.post("/liquidar/reica-bogota")
async def liquidar_reica_bogota(
    periodo: str = Body(..., embed=True, examples=["2026-B2"]),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Dispara liquidación ReICA Bogotá del bimestre."""
    inicio, fin, venc = _ventana_reica(periodo)
    alegra = AlegraClient(db=db)
    liq = await liquidar_reica_bogota_bimestre(alegra, inicio, fin, periodo)
    doc = await _persistir_obligacion_calculada(
        db,
        obligacion_id=f"reica_bogota_bimestral-{periodo.lower()}",
        tipo="reica_bogota_bimestral",
        nombre=f"ReICA Bogotá {periodo}",
        periodo=periodo,
        impuesto_a_pagar=liq["total_a_pagar"],
        detalle=liq,
        fecha_vencimiento=venc,
    )
    return {"ok": True, "liquidacion": liq, "doc_id": doc["obligacion_id"]}


@router.post("/liquidar/todo-vencimientos-30d")
async def liquidar_todo_proximos_30d(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Conveniencia: dispara liquidación de TODAS las obligaciones que vencen en 30 días."""
    proximas = obligaciones_proximas(dias_adelante=30)
    alegra = AlegraClient(db=db)
    resultados = []
    for o in proximas:
        try:
            if o["tipo"] == "iva_cuatrimestral":
                inicio = date.fromisoformat(o["periodo_inicio"])
                fin = date.fromisoformat(o["periodo_fin"])
                liq = await liquidar_iva_cuatrimestre(alegra, inicio, fin, o["periodo"])
                await _persistir_obligacion_calculada(
                    db, f"iva_cuatrimestral-{o['periodo'].lower()}", o["tipo"],
                    o["nombre"], o["periodo"], liq["iva_neto_a_pagar"], liq,
                    o["fecha_vencimiento"],
                )
                resultados.append({"periodo": o["periodo"], "tipo": o["tipo"], "monto": liq["iva_neto_a_pagar"]})
            elif o["tipo"] == "retefuente_mensual":
                anio, mes = o["periodo"].split("-")
                liq = await liquidar_retefuente_mes(alegra, int(anio), int(mes))
                liq["fecha_calculo"] = _iso_now()
                await _persistir_obligacion_calculada(
                    db, f"retefuente_mensual-{o['periodo']}", o["tipo"],
                    o["nombre"], o["periodo"], liq["total_a_pagar"], liq,
                    o["fecha_vencimiento"],
                )
                resultados.append({"periodo": o["periodo"], "tipo": o["tipo"], "monto": liq["total_a_pagar"]})
            elif o["tipo"] == "reica_bogota_bimestral":
                inicio = date.fromisoformat(o["periodo_inicio"])
                fin = date.fromisoformat(o["periodo_fin"])
                liq = await liquidar_reica_bogota_bimestre(alegra, inicio, fin, o["periodo"])
                await _persistir_obligacion_calculada(
                    db, f"reica_bogota_bimestral-{o['periodo'].lower()}", o["tipo"],
                    o["nombre"], o["periodo"], liq["total_a_pagar"], liq,
                    o["fecha_vencimiento"],
                )
                resultados.append({"periodo": o["periodo"], "tipo": o["tipo"], "monto": liq["total_a_pagar"]})
        except Exception as e:
            logger.exception(f"Error liquidando {o['nombre']}")
            resultados.append({"periodo": o["periodo"], "tipo": o["tipo"], "error": str(e)})
    total = sum(r.get("monto", 0) for r in resultados)
    return {
        "fecha_corte": today_bogota().isoformat(),
        "obligaciones_liquidadas": len(resultados),
        "total_a_pagar_30d_cop": round(total),
        "resultados": resultados,
    }
