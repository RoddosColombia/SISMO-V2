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


# ─────────────────────── MOTOR CANÓNICO ENDPOINTS (DAY1) ────────────────────

@router.get("/motor/audit-all")
async def motor_audit_all(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Audita los 43 LBs aplicando el motor canónico (services.loanbook.motor).

    No modifica nada. Devuelve semáforo verde/amarilla/roja por LB.

    El motor aplica reglas v1.1 (Opción B):
      - 9 estados: pendiente_entrega, al_dia, mora_leve, mora_media, mora_grave,
        default, castigado, reestructurado, saldado.
      - Sub-buckets v1.1: Current/Grace/Warning/Alert/Critical/Severe/Pre-default/Default.
      - Mora $2.000 COP/día sin cap.
      - Solo recalcula derivados; NO toca cronograma.
    """
    from services.loanbook.motor import auditar
    from core.datetime_utils import today_bogota

    hoy = today_bogota()
    total = 0
    verdes = 0
    amarillas = 0
    rojas = 0
    reportes = []

    async for lb in db.loanbook.find({}):
        total += 1
        try:
            r = auditar(lb, hoy=hoy)
        except Exception as exc:
            r = {
                "loanbook_id": lb.get("loanbook_id"),
                "cliente":     (lb.get("cliente") or {}).get("nombre"),
                "ok":          False,
                "severidad":   "roja",
                "violaciones": [{"campo": "exception", "antes": "", "despues": str(exc), "tipo": "estructural"}],
            }
        if r["severidad"] == "verde":
            verdes += 1
        elif r["severidad"] == "amarilla":
            amarillas += 1
        else:
            rojas += 1
        reportes.append(r)

    orden = {"roja": 0, "amarilla": 1, "verde": 2}
    reportes.sort(key=lambda r: (orden.get(r["severidad"], 3), r.get("loanbook_id") or ""))

    return {
        "fecha_corte":               hoy.isoformat(),
        "fecha_analisis":            now_iso_bogota(),
        "motor":                     "services.loanbook.motor v1 (DAY1)",
        "total":                     total,
        "verdes":                    verdes,
        "amarillas":                 amarillas,
        "rojas":                     rojas,
        "puede_migrar_sin_riesgo":   rojas == 0,
        "loanbooks":                 reportes,
    }


@router.post("/motor/migrar")
async def motor_migrar(
    dry_run: Annotated[
        bool,
        Query(description="True (default) = solo preview. False = aplica derivar_estado y persiste."),
    ] = True,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Aplica services.loanbook.motor.derivar_estado a todos los LBs y persiste.

    SOLO recalcula derivados (saldo, dpd, sub_bucket, estado, mora, total_pagado,
    cuotas_pagadas, cuotas_vencidas). NO toca cronograma, NO toca términos pactados,
    NO toca metadata cliente. Cumple invariante: idempotente.

    Args:
        dry_run: True por defecto. False persiste cambios en MongoDB.

    Returns:
        Reporte detallado: cuántos LBs cambiaron, qué campo cambió en cada uno,
        cartera_total antes vs después.
    """
    from services.loanbook.motor import derivar_estado
    from core.datetime_utils import today_bogota

    hoy = today_bogota()
    total = 0
    modificados = 0
    sin_cambios = 0
    errores = []
    cambios_detalle = []
    cartera_antes = 0
    cartera_despues = 0

    async for lb in db.loanbook.find({}):
        total += 1
        loanbook_id = lb.get("loanbook_id") or str(lb.get("_id"))
        cliente = (lb.get("cliente") or {}).get("nombre") or lb.get("cliente_nombre") or "?"

        # Saldo antes (usa el persistido)
        saldo_antes = int(lb.get("saldo_pendiente") or 0)
        cartera_antes += saldo_antes

        try:
            canonico = derivar_estado(lb, hoy=hoy)
        except Exception as exc:
            errores.append({"loanbook_id": loanbook_id, "error": str(exc)})
            continue

        # Saldo después (canónico)
        saldo_despues = int(canonico.get("saldo_pendiente") or 0)
        cartera_despues += saldo_despues

        # Detectar cambios reales (campos derivados solamente)
        cambios = {}
        for k in ["saldo_pendiente", "total_pagado", "dpd", "estado", "sub_bucket",
                  "mora_acumulada_cop", "cuotas_pagadas", "cuotas_vencidas"]:
            v_antes = lb.get(k)
            v_despues = canonico.get(k)
            if v_antes != v_despues:
                cambios[k] = {"antes": v_antes, "despues": v_despues}

        if not cambios:
            sin_cambios += 1
            continue

        modificados += 1
        cambios_detalle.append({
            "loanbook_id": loanbook_id,
            "cliente":     cliente,
            "cambios":     cambios,
        })

        if not dry_run:
            # Persistir solo los campos derivados, no tocar cronograma ni términos
            patch = {k: canonico[k] for k in [
                "saldo_pendiente", "total_pagado", "dpd", "estado", "sub_bucket",
                "mora_acumulada_cop", "cuotas_pagadas", "cuotas_vencidas",
                "fecha_ultima_recalculacion",
            ] if k in canonico}
            await db.loanbook.update_one(
                {"_id": lb["_id"]},
                {"$set": patch},
            )

    return {
        "dry_run":                  dry_run,
        "fecha_analisis":           now_iso_bogota(),
        "motor":                    "services.loanbook.motor v1 (DAY1)",
        "total_loanbooks":          total,
        "modificados":              modificados,
        "sin_cambios":              sin_cambios,
        "errores":                  errores,
        "cartera_total_antes":      cartera_antes,
        "cartera_total_despues":    cartera_despues,
        "delta_cartera":            cartera_despues - cartera_antes,
        "cambios":                  cambios_detalle,
    }



# ─────────────────────── APLICAR PATCHES JSON (DAY2 — sin multipart) ─────────

@router.post("/aplicar-patches")
async def aplicar_patches(
    body: dict,
    dry_run: bool = Query(True, description="True (default) preview. False persiste."),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Aplica patches canónicos a los LBs desde un JSON body.

    Alternativa al endpoint multipart restaurar-desde-excel: recibe los patches
    pre-generados como JSON body, sin dependencia de python-multipart.

    Body esperado:
        {
          "total_loanbooks": 43,
          "patches": [
            {
              "loanbook_id": "LB-2026-0001",
              "saldo_capital": 6720600,
              "saldo_intereses": 1554800,
              "saldo_pendiente": 8275400,
              "valor_total": 9354800,
              "total_pagado": 1079400,
              "cuotas_pagadas": 6,
              "dpd": 1,
              "estado": "mora_leve",
              "sub_bucket": "Grace",
              ...
            },
            ...
          ]
        }

    Por cada patch hace $set sobre el doc del LB sin tocar:
      - cuotas[] (cronograma con fechas reales)
      - cliente, moto, metadata_producto
      - fechas pactadas (entrega, primer_pago)
      - factura_alegra_id

    Idempotente: aplicarlo dos veces no produce cambios la segunda vez.
    """
    patches = body.get("patches") or []
    if not patches:
        return {"error": "body debe incluir 'patches' (lista de dicts)"}

    total = len(patches)
    actualizados = 0
    no_encontrados = []
    sin_cambios = 0
    errores = []
    cambios_detalle = []

    for patch in patches:
        loanbook_id = patch.get("loanbook_id")
        if not loanbook_id:
            errores.append({"patch": patch, "error": "sin loanbook_id"})
            continue

        doc_actual = await db.loanbook.find_one({"loanbook_id": loanbook_id})
        if doc_actual is None:
            no_encontrados.append(loanbook_id)
            continue

        # Detectar cambios reales
        cambios_lb = {}
        for k, v in patch.items():
            if k == "loanbook_id":
                continue
            v_actual = doc_actual.get(k)
            if v_actual != v:
                cambios_lb[k] = {"antes": v_actual, "despues": v}

        if not cambios_lb:
            sin_cambios += 1
            continue

        actualizados += 1
        cambios_detalle.append({
            "loanbook_id": loanbook_id,
            "cliente":     (doc_actual.get("cliente") or {}).get("nombre")
                            or doc_actual.get("cliente_nombre") or "?",
            "n_cambios":   len(cambios_lb),
        })

        if not dry_run:
            patch_set = {k: v for k, v in patch.items() if k != "loanbook_id"}
            patch_set["restaurado_desde_excel_at"] = now_iso_bogota()
            await db.loanbook.update_one(
                {"loanbook_id": loanbook_id},
                {"$set": patch_set},
            )

    return {
        "dry_run":          dry_run,
        "fecha_analisis":   now_iso_bogota(),
        "total_patches":    total,
        "actualizados":     actualizados,
        "sin_cambios":      sin_cambios,
        "no_encontrados":   no_encontrados,
        "errores":          errores,
        "cambios":          cambios_detalle,
    }
