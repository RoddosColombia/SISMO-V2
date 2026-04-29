"""
services/cobranza/cartera_revisor.py — Análisis de cartera para revisión jueves.

Lee todos los loanbooks activos, asigna sub-bucket Phase 7, calcula métricas
agregadas y genera la cola priorizada para gestión RADAR.

Usado por:
- Scheduler jueves 8AM: ejecuta análisis y dispara templates
- Endpoint /api/loanbook/cartera-revisor (admin frontend)
- Reporte HTML semanal email a Andres/Ivan/Fabian
"""
from __future__ import annotations
import logging
from datetime import date, datetime, timezone
from typing import TypedDict

from motor.motor_asyncio import AsyncIOMotorDatabase

from core.datetime_utils import today_bogota
from services.cobranza.sub_buckets import (
    asignar_sub_bucket, prioridad_score,
    ACCION_POR_BUCKET, COLOR_POR_BUCKET, RECUPERABILIDAD_ESPERADA,
    BUCKETS_ORDEN, SubBucket,
)

logger = logging.getLogger("cobranza.revisor")


class LoanbookCobranza(TypedDict):
    loanbook_id: str
    cliente_nombre: str
    cliente_cedula: str
    cliente_telefono: str
    saldo_pendiente: float
    dpd: int
    sub_bucket: SubBucket
    accion: str
    color: str
    score_prioridad: float
    cuotas_pagadas: int
    cuotas_total: int
    proxima_cuota_fecha: str | None
    proxima_cuota_monto: float
    plan_codigo: str
    modalidad: str
    modelo: str


async def analizar_cartera(
    db: AsyncIOMotorDatabase, fecha_corte: date | None = None,
) -> dict:
    """Analiza toda la cartera activa y devuelve dashboard + cola.

    Returns:
        {
          "fecha_corte": "2026-04-30",
          "total_creditos": 43,
          "cartera_total":  372845281,
          "saldo_en_mora":  X,
          "n_en_mora":      Y,
          "distribucion": {
            "Current":  {"count": N, "saldo": X, "pct": 0.X},
            "Grace":    {...},
            ...
          },
          "cola_priorizada": [LoanbookCobranza, ...]  # ordenada DESC
          "top_5_urgentes":  [LoanbookCobranza, ...]  # los primeros 5
          "expectativa_recuperabilidad_cop": float,
          "fecha_analisis": ISO timestamp
        }
    """
    fecha_corte = fecha_corte or today_bogota()

    # Init buckets
    distribucion: dict[SubBucket, dict] = {
        b: {"count": 0, "saldo": 0.0, "loanbooks": []}
        for b in BUCKETS_ORDEN
    }
    cola: list[LoanbookCobranza] = []
    cartera_total = 0.0
    saldo_en_mora = 0.0
    n_en_mora = 0
    recuperabilidad_total = 0.0

    estados_excluir = {
        "saldado", "Pagado", "castigado", "ChargeOff",
        "pendiente_entrega", "Pendiente Entrega",
    }

    async for lb in db.loanbook.find({}):
        estado = lb.get("estado", "")
        if estado in estados_excluir:
            continue

        # DPD canonico (preferir el ya calculado en doc, fallback a 0)
        dpd = int(lb.get("dpd", 0) or 0)
        bucket = asignar_sub_bucket(dpd)
        saldo = float(lb.get("saldo_pendiente", 0) or 0)
        if saldo < 0:
            saldo = 0.0

        cartera_total += saldo
        if dpd > 0:
            n_en_mora += 1
            saldo_en_mora += saldo

        recuperabilidad_total += saldo * RECUPERABILIDAD_ESPERADA[bucket]

        # Acumular distribucion
        distribucion[bucket]["count"] += 1
        distribucion[bucket]["saldo"] += saldo

        # Construir item de cola
        cliente_block = lb.get("cliente") or {}
        nombre = cliente_block.get("nombre") or lb.get("cliente_nombre", "?")
        cedula = cliente_block.get("cedula") or lb.get("cliente_cedula", "")
        telefono = cliente_block.get("telefono") or lb.get("cliente_telefono", "")

        # Proxima cuota pendiente
        proxima_fecha = None
        proxima_monto = lb.get("cuota_periodica") or lb.get("cuota_monto", 0)
        for c in (lb.get("cuotas") or []):
            if c.get("estado") in ("pendiente", "vencida"):
                proxima_fecha = c.get("fecha")
                proxima_monto = c.get("monto") or proxima_monto
                break

        item: LoanbookCobranza = {
            "loanbook_id":         lb.get("loanbook_id", ""),
            "cliente_nombre":      nombre,
            "cliente_cedula":      cedula,
            "cliente_telefono":    telefono,
            "saldo_pendiente":     saldo,
            "dpd":                 dpd,
            "sub_bucket":          bucket,
            "accion":              ACCION_POR_BUCKET[bucket],
            "color":               COLOR_POR_BUCKET[bucket],
            "score_prioridad":     prioridad_score(dpd, saldo),
            "cuotas_pagadas":      int(lb.get("cuotas_pagadas", 0) or 0),
            "cuotas_total":        int(lb.get("cuotas_total", 0) or lb.get("total_cuotas", 0) or 0),
            "proxima_cuota_fecha": proxima_fecha,
            "proxima_cuota_monto": float(proxima_monto or 0),
            "plan_codigo":         lb.get("plan_codigo", ""),
            "modalidad":           lb.get("modalidad", "") or lb.get("modalidad_pago", ""),
            "modelo":              lb.get("modelo", "") or (lb.get("moto") or {}).get("modelo", ""),
        }
        cola.append(item)

    # Cola: solo en mora, ordenada por score desc
    cola_mora = sorted(
        [c for c in cola if c["dpd"] > 0],
        key=lambda x: -x["score_prioridad"],
    )

    # Calcular pct por bucket
    total_creditos = sum(d["count"] for d in distribucion.values())
    for b, d in distribucion.items():
        d["pct"] = (d["count"] / total_creditos) if total_creditos else 0
        d.pop("loanbooks", None)  # No exponer en respuesta

    return {
        "fecha_corte":                       fecha_corte.isoformat(),
        "total_creditos":                    total_creditos,
        "cartera_total":                     round(cartera_total),
        "saldo_en_mora":                     round(saldo_en_mora),
        "n_en_mora":                         n_en_mora,
        "pct_cartera_en_mora":               (saldo_en_mora / cartera_total) if cartera_total else 0,
        "distribucion":                      distribucion,
        "cola_priorizada":                   cola_mora,
        "top_5_urgentes":                    cola_mora[:5],
        "expectativa_recuperabilidad_cop":   round(recuperabilidad_total),
        "perdida_esperada_cop":              round(cartera_total - recuperabilidad_total),
        "fecha_analisis":                    datetime.now(timezone.utc).isoformat(),
    }
