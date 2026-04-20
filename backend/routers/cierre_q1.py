"""
cierre_q1.py — BUILD 5 (V2)

GET /api/cierre-q1/reporte
Reporte consolidado de cierre Q1 2026 (ene-mar).

Fuentes:
  - backlog_movimientos  → estado actual de movimientos
  - cierre_q1_reporte   → recaudo matcheado (legacy + V2)
  - loanbook_legacy      → saldo total cartera legacy

No escribe nada — solo lee y agrega.
"""
from datetime import datetime
from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_db
from core.auth import get_current_user

router = APIRouter(prefix="/api/cierre-q1", tags=["cierre-q1"])


@router.get("/reporte")
async def reporte_cierre_q1(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Reporte consolidado cierre Q1 2026.

    Retorna:
      - resumen de backlog (total, causados, pendientes, flags)
      - desglose de causados por ronda
      - cifras de recaudo (legacy + V2 + total)
      - saldo cartera legacy
      - pendientes estimados vs cartera
    """

    # ── 1. Backlog — conteos por estado ──────────────────────────────────────
    col_blg = db["backlog_movimientos"]

    pipeline_estados = [
        {"$group": {"_id": "$estado", "count": {"$sum": 1}}}
    ]
    estado_docs = await col_blg.aggregate(pipeline_estados).to_list(length=50)
    conteos: dict[str, int] = {d["_id"]: d["count"] for d in estado_docs if d["_id"]}

    total_blg      = sum(conteos.values())
    causados       = conteos.get("causado", 0)
    pendiente      = conteos.get("pendiente", 0)
    manual_pend    = conteos.get("manual_pendiente", 0)
    sin_match      = conteos.get("sin_match", 0)
    error_count    = conteos.get("error", 0)

    # ── 2. Rondas — aproximación por conocimiento del proceso ────────────────
    # BUILD 1: causar-por-regla → 143 movs (gmf=69, cxc_andres=60, cxc_ivan=13, transporte=1)
    # BUILD 2: auto-match-contrapartida → 0 matches (contrapartidas no estaban en backlog)
    # BUILD 3: matchear-cartera → 41 matches
    # Los registros previos al sprint (pre-BUILD 1) completan el resto de causados.
    ronda_1 = {
        "total": 143,
        "detalle": {
            "gmf_4x1000":   69,
            "cxc_andres":   60,
            "cxc_ivan":     13,
            "transporte_app": 1,
        }
    }
    ronda_2 = {"total": 0, "nota": "Contrapartidas no presentes en backlog — match omitido"}
    ronda_3 = {"total": 41, "nota": "Matcheo fuzzy cartera — V2 + legacy"}

    pre_sprint = max(0, causados - ronda_1["total"] - ronda_3["total"])

    # ── 3. cierre_q1_reporte — recaudo matcheado ────────────────────────────
    col_reporte = db["cierre_q1_reporte"]
    reporte_doc = await col_reporte.find_one(sort=[("_id", -1)])

    recaudo_legacy = 0
    recaudo_v2     = 0
    matcheados     = 0
    analizados     = 0
    reporte_ts     = None

    if reporte_doc:
        recaudo_legacy = reporte_doc.get("recaudo_q1_legacy", 0) or 0
        recaudo_v2     = reporte_doc.get("recaudo_q1_v2", 0) or 0
        matcheados     = reporte_doc.get("total_matcheados", 0) or 0
        analizados     = reporte_doc.get("total_analizados", 0) or 0
        reporte_ts     = reporte_doc.get("generado_en") or reporte_doc.get("fecha_hora")

    recaudo_total = recaudo_legacy + recaudo_v2

    # ── 4. Loanbook legacy — saldo vigente ───────────────────────────────────
    col_legacy = db["loanbook_legacy"]
    pipeline_legacy = [
        {"$group": {
            "_id": None,
            "total_creditos": {"$sum": 1},
            "activos":        {"$sum": {"$cond": [{"$eq": ["$estado", "activo"]}, 1, 0]}},
            "saldados":       {"$sum": {"$cond": [{"$eq": ["$estado", "saldado"]}, 1, 0]}},
            "saldo_total":    {"$sum": "$saldo_actual"},
        }}
    ]
    legacy_agg = await col_legacy.aggregate(pipeline_legacy).to_list(length=1)
    legacy_stats = legacy_agg[0] if legacy_agg else {}

    saldo_legacy    = legacy_stats.get("saldo_total", 0) or 0
    activos_legacy  = legacy_stats.get("activos", 0) or 0
    saldados_legacy = legacy_stats.get("saldados", 0) or 0
    total_legacy    = legacy_stats.get("total_creditos", 0) or 0

    # ── 5. Pendientes estimados ───────────────────────────────────────────────
    # Los movimientos en estado "pendiente" aún no tienen contraparte contable.
    # Estimamos el monto promedio por movimiento cauado para dar un rango.
    movs_con_monto = await col_blg.aggregate([
        {"$match": {"estado": "causado", "monto": {"$gt": 0}}},
        {"$group": {"_id": None, "total": {"$sum": "$monto"}, "count": {"$sum": 1}}}
    ]).to_list(length=1)

    monto_promedio_mov = 0
    if movs_con_monto:
        doc = movs_con_monto[0]
        cnt = doc.get("count", 0)
        if cnt > 0:
            monto_promedio_mov = abs(doc.get("total", 0)) / cnt

    pendientes_estimado = round(monto_promedio_mov * pendiente)

    # ── 6. Respuesta ─────────────────────────────────────────────────────────
    return {
        "success": True,
        "generado_en": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "periodo": "Q1 2026 (ene – mar)",

        "backlog": {
            "total":            total_blg,
            "causados":         causados,
            "pendiente":        pendiente,
            "manual_pendiente": manual_pend,
            "sin_match":        sin_match,
            "error":            error_count,
            "pct_causado":      round(causados / total_blg * 100, 1) if total_blg else 0,
        },

        "rondas": {
            "pre_sprint": pre_sprint,
            "ronda_1":    ronda_1,
            "ronda_2":    ronda_2,
            "ronda_3":    ronda_3,
        },

        "recaudo": {
            "legacy":       recaudo_legacy,
            "v2":           recaudo_v2,
            "total":        recaudo_total,
            "matcheados":   matcheados,
            "analizados":   analizados,
            "reporte_ts":   str(reporte_ts) if reporte_ts else None,
        },

        "cartera_legacy": {
            "total_creditos": total_legacy,
            "activos":        activos_legacy,
            "saldados":       saldados_legacy,
            "saldo_vigente":  saldo_legacy,
            "cobertura_pct":  round(recaudo_legacy / saldo_legacy * 100, 1) if saldo_legacy else 0,
        },

        "pendientes_estimado": {
            "movimientos":      pendiente,
            "monto_estimado":   pendientes_estimado,
            "monto_promedio_mov": round(monto_promedio_mov),
            "nota": "Estimado basado en promedio de movimientos causados con monto > 0",
        },
    }
