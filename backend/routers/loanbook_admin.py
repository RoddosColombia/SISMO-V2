"""
routers/loanbook_admin.py — Endpoints administrativos del loanbook.

Estos endpoints aplican el motor unificado (services/loanbook/engine.py) sobre
los datos en MongoDB para auditoría y reparación masiva.

Endpoints:
    GET  /api/loanbook/admin/audit-all       → reporta divergencias por LB
    POST /api/loanbook/admin/full-repair     → aplica engine.recalcular() y persiste

Diseño:
    - Solo router; toda la lógica financiera vive en engine.py
    - dry_run=true por default en full-repair para preview seguro
    - Reporte detallado: qué campo cambió por LB
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_db
from core.datetime_utils import now_iso_bogota, today_bogota
from services.loanbook.engine import recalcular, auditar

logger = logging.getLogger("routers.loanbook_admin")

router = APIRouter(prefix="/api/loanbook-admin", tags=["loanbook-admin"])


# ─────────────────────────── audit-all ──────────────────────────────────────

@router.get("/audit-all")
async def audit_all(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Audita TODOS los loanbooks y devuelve divergencias vs versión canónica.

    No modifica nada. Útil para visualizar el semáforo del módulo.

    Returns:
        {
          "fecha_corte":    "2026-04-30",
          "total":          43,
          "verdes":         N,
          "amarillas":      N,
          "rojas":          N,
          "puede_enviar_email_martes": bool (rojas == 0),
          "loanbooks": [
            {
              "loanbook_id": "...",
              "cliente":     "...",
              "severidad":   "verde" | "amarilla" | "roja",
              "violaciones": [{"campo", "antes", "despues"}, ...]
            },
            ...
          ]
        }
    """
    total = 0
    verdes = 0
    amarillas = 0
    rojas = 0
    reportes = []

    async for lb in db.loanbook.find({}):
        total += 1
        report = auditar(lb)
        if report["severidad"] == "verde":
            verdes += 1
        elif report["severidad"] == "amarilla":
            amarillas += 1
        else:
            rojas += 1
        reportes.append(report)

    # Ordenar por severidad: rojas primero, luego amarillas
    orden = {"roja": 0, "amarilla": 1, "verde": 2}
    reportes.sort(key=lambda r: (orden[r["severidad"]], r.get("loanbook_id", "")))

    return {
        "fecha_corte":   today_bogota().isoformat(),
        "fecha_analisis": now_iso_bogota(),
        "total":         total,
        "verdes":        verdes,
        "amarillas":     amarillas,
        "rojas":         rojas,
        "puede_enviar_email_martes": rojas == 0,
        "loanbooks":     reportes,
    }


# ─────────────────────────── full-repair ────────────────────────────────────

@router.post("/full-repair")
async def full_repair(
    dry_run: Annotated[
        bool,
        Query(description="True (default) = solo preview. False = aplica cambios."),
    ] = True,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Aplica engine.recalcular() a TODOS los loanbooks y persiste cambios.

    Repara automáticamente:
      - Cronogramas con cuotas fuera de miércoles canónico
      - Saldos desfasados (sc, si, saldo_pendiente)
      - DPD y sub_bucket
      - Estado derivado
      - Modelo poblado con plan_codigo
      - num_cuotas vs catálogo
      - mora_acumulada

    Idempotente: aplicarlo dos veces no produce cambios la segunda vez.

    Args:
        dry_run: Por defecto True — solo reporta qué cambiaría. Pasar dry_run=false
                 para persistir.

    Returns:
        {
          "dry_run":        bool,
          "total":          43,
          "modificados":    N,
          "sin_cambios":    N,
          "errores":        [{"loanbook_id", "error"}, ...],
          "reparaciones":   [
            {"loanbook_id", "cliente", "cambios": [{"campo", "antes", "despues"}, ...]},
            ...
          ]
        }
    """
    total = 0
    modificados = 0
    sin_cambios = 0
    errores = []
    reparaciones = []

    async for lb in db.loanbook.find({}):
        total += 1
        loanbook_id = lb.get("loanbook_id") or str(lb.get("_id"))
        cliente = (lb.get("cliente") or {}).get("nombre") or lb.get("cliente_nombre") or "?"

        try:
            canonico = recalcular(lb)
        except Exception as exc:
            logger.exception("full-repair error en %s: %s", loanbook_id, exc)
            errores.append({"loanbook_id": loanbook_id, "error": str(exc)})
            continue

        # Detectar cambios reales (no contar fecha_ultima_recalculacion)
        cambios = _detectar_cambios(lb, canonico)
        if not cambios:
            sin_cambios += 1
            continue

        modificados += 1
        reparaciones.append({
            "loanbook_id": loanbook_id,
            "cliente":     cliente,
            "cambios":     cambios,
        })

        # Persistir solo si no es dry_run
        if not dry_run:
            # Preservar _id de MongoDB si existe
            if "_id" in lb:
                canonico["_id"] = lb["_id"]
            await db.loanbook.replace_one({"_id": lb["_id"]}, canonico)

    return {
        "dry_run":          dry_run,
        "fecha_analisis":   now_iso_bogota(),
        "total":            total,
        "modificados":      modificados,
        "sin_cambios":      sin_cambios,
        "errores":          errores,
        "reparaciones":     reparaciones,
    }


# ─────────────────────────── helpers ────────────────────────────────────────

# Campos cuyo cambio NO se reporta (volátil o esperado)
CAMPOS_IGNORAR = {"fecha_ultima_recalculacion", "fecha_analisis", "_id"}


def _detectar_cambios(antes: dict, despues: dict) -> list[dict]:
    """Devuelve lista de campos que cambiaron entre antes y después."""
    cambios = []
    keys = (set(antes.keys()) | set(despues.keys())) - CAMPOS_IGNORAR
    for k in sorted(keys):
        v_antes = antes.get(k)
        v_despues = despues.get(k)
        if v_antes == v_despues:
            continue
        # Para cuotas: solo reportar si las fechas cambiaron
        if k == "cuotas":
            fechas_antes = [c.get("fecha") for c in (v_antes or [])]
            fechas_despues = [c.get("fecha") for c in (v_despues or [])]
            if fechas_antes == fechas_despues:
                continue
            cambios.append({
                "campo":   "cuotas_fechas",
                "antes":   fechas_antes[:3] + (["..."] if len(fechas_antes) > 3 else []),
                "despues": fechas_despues[:3] + (["..."] if len(fechas_despues) > 3 else []),
            })
            continue
        cambios.append({
            "campo":   k,
            "antes":   v_antes,
            "despues": v_despues,
        })
    return cambios
