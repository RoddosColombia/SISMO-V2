"""
cierres.py — Módulo Cierres Contables (V2)

Endpoints:
  GET /api/cierres                  → lista de períodos Q detectados
  GET /api/cierres/{periodo_id}     → detalle completo de un período
  GET /api/cierre-q1/reporte        → alias → redirige a /api/cierres/2026-Q1

Detecta períodos leyendo fechas de backlog_movimientos.
Siempre incluye el trimestre actual aunque tenga 0 movimientos.

Estado:
  cerrado     = pct >= 95% AND errores == 0 AND manual_pendiente == 0
  en_progreso = tiene movimientos con cualquier estado
  abierto     = 0 movimientos en el backlog para ese trimestre
"""
import calendar
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import RedirectResponse
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_db
from core.auth import get_current_user

router = APIRouter(tags=["cierres"])

# ── Constantes proceso Q1 ─────────────────────────────────────────────────────
# Estas rondas son conocimiento del proceso — no se almacenan en MongoDB.
Q1_RONDAS = [
    {
        "ronda": "pre_sprint",
        "label": "Pre-sprint",
        "causados": None,  # se calcula como causados_total - sum(rondas conocidas)
    },
    {
        "ronda": "r1_reglas",
        "label": "Ronda 1 — Reglas mecánicas",
        "causados": 143,
        "detalle": {
            "gmf_4x1000":    69,
            "cxc_andres":    60,
            "cxc_ivan":      13,
            "transporte_app": 1,
        },
    },
    {
        "ronda": "r2_automatch",
        "label": "Ronda 2 — Auto-contrapartida",
        "causados": 0,
        "nota": "Contrapartidas no presentes en backlog — match omitido",
    },
    {
        "ronda": "r3_cartera",
        "label": "Ronda 3 — Matcheo cartera",
        "causados": 41,
        "nota": "Matcheo fuzzy cartera V2 + legacy",
    },
]

MES_CORTO = {
    1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr",
    5: "May", 6: "Jun", 7: "Jul", 8: "Ago",
    9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic",
}
MES_LARGO = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _quarter_of(fecha_str: str) -> str | None:
    """'2026-01-15' → '2026-Q1'"""
    try:
        year = fecha_str[:4]
        month = int(fecha_str[5:7])
        q = (month - 1) // 3 + 1
        return f"{year}-Q{q}"
    except (ValueError, IndexError):
        return None


def _current_quarter() -> str:
    now = datetime.now(timezone.utc)
    q = (now.month - 1) // 3 + 1
    return f"{now.year}-Q{q}"


def _quarter_meta(periodo_id: str) -> dict:
    """'2026-Q1' → dict con label, rango, fechas, meses del trimestre"""
    try:
        year_str, qstr = periodo_id.split("-Q")
        year = int(year_str)
        q = int(qstr)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"periodo_id inválido: {periodo_id}. Usar formato YYYY-Qn")

    month_start = (q - 1) * 3 + 1
    month_end = q * 3
    last_day = calendar.monthrange(year, month_end)[1]

    return {
        "label":        f"Q{q} {year}",
        "rango":        f"{MES_CORTO[month_start]} – {MES_CORTO[month_end]} {year}",
        "fecha_inicio": f"{year}-{month_start:02d}-01",
        "fecha_fin":    f"{year}-{month_end:02d}-{last_day:02d}",
        "meses":        [f"{year}-{m:02d}" for m in range(month_start, month_end + 1)],
        "year":         year,
        "q":            q,
        "month_start":  month_start,
        "month_end":    month_end,
    }


def _estado(pct_causado: float, errores: int, manual_pendiente: int, total: int) -> str:
    if total == 0:
        return "abierto"
    if pct_causado >= 95.0 and errores == 0 and manual_pendiente == 0:
        return "cerrado"
    return "en_progreso"


def _proximos_pasos(
    estado: str,
    manual_pendiente: int,
    errores: int,
    sin_categoria: int,
    meta: dict,
) -> list[str]:
    pasos: list[str] = []
    if manual_pendiente > 0:
        pasos.append(
            f"{manual_pendiente} movimientos requieren clasificación manual "
            f"(Lizbeth — decisión de Andrés)"
        )
    if errores > 0:
        pasos.append(
            f"{errores} movimientos con error de cuenta contable "
            f"— revisar en backlog filtro 'Con error'"
        )
    if sin_categoria > 0:
        pasos.append(
            f"{sin_categoria} movimientos sin categoría "
            f"— revisar reglas de clasificación"
        )
    if estado == "abierto":
        pasos.append(f"Extractos {meta['rango']} pendientes de subir")
    return pasos


async def _detect_periods(col_blg) -> list[str]:
    """Detecta trimestres con datos en backlog_movimientos + trimestre actual."""
    pipeline = [
        {"$group": {"_id": {"$substr": ["$fecha", 0, 7]}}},
        {"$sort": {"_id": 1}},
    ]
    docs = await col_blg.aggregate(pipeline).to_list(length=200)
    quarters: set[str] = set()
    for d in docs:
        mes_str = d.get("_id") or ""
        if len(mes_str) >= 7:
            q = _quarter_of(mes_str + "-01")
            if q:
                quarters.add(q)
    quarters.add(_current_quarter())
    return sorted(quarters)


async def _build_period_data(
    db: AsyncIOMotorDatabase,
    periodo_id: str,
    include_detail: bool = False,
) -> dict:
    """
    Construye el dict de un período.
    include_detail=True añade desglose_por_mes, desglose_por_ronda,
    cartera_legacy y proximos_pasos.
    """
    meta = _quarter_meta(periodo_id)
    col_blg = db["backlog_movimientos"]

    fecha_ini = meta["fecha_inicio"]
    fecha_fin = meta["fecha_fin"]

    # ── Conteos por estado dentro del período ─────────────────────────────────
    pipeline_estados = [
        {"$match": {"fecha": {"$gte": fecha_ini, "$lte": fecha_fin}}},
        {"$group": {"_id": "$estado", "count": {"$sum": 1}}},
    ]
    estado_docs = await col_blg.aggregate(pipeline_estados).to_list(length=50)
    conteos: dict[str, int] = {
        d["_id"]: d["count"] for d in estado_docs if d.get("_id")
    }

    total         = sum(conteos.values())
    causados      = conteos.get("causado", 0)
    pendiente     = conteos.get("pendiente", 0)
    manual_pend   = conteos.get("manual_pendiente", 0)
    sin_match     = conteos.get("sin_match", 0)
    errores       = conteos.get("error", 0)
    pct_causado   = round(causados / total * 100, 1) if total else 0.0

    estado = _estado(pct_causado, errores, manual_pend, total)

    summary: dict = {
        "periodo_id":       periodo_id,
        "label":            meta["label"],
        "rango":            meta["rango"],
        "fecha_inicio":     meta["fecha_inicio"],
        "fecha_fin":        meta["fecha_fin"],
        "estado":           estado,
        "total_movimientos": total,
        "causados":         causados,
        "pendientes":       pendiente,
        "errores":          errores,
        "manual_pendiente": manual_pend,
        "pct_causado":      pct_causado,
        "bloqueantes": {
            "manual_pendiente": manual_pend,
            "errores_cuenta":   errores,
            "sin_categoria":    sin_match,
        },
        "capacidad_cierre": {
            "movimientos_por_semana":    0.0,
            "semanas_estimadas_cierre":  None,
            "tendencia":                 "sin_datos",
        },
    }

    if not include_detail:
        return summary

    # ── Desglose por mes ──────────────────────────────────────────────────────
    pipeline_meses = [
        {"$match": {"fecha": {"$gte": fecha_ini, "$lte": fecha_fin}}},
        {"$addFields": {"mes": {"$substr": ["$fecha", 0, 7]}}},
        {"$group": {
            "_id":      "$mes",
            "total":    {"$sum": 1},
            "causados": {"$sum": {"$cond": [{"$eq": ["$estado", "causado"]}, 1, 0]}},
        }},
        {"$sort": {"_id": 1}},
    ]
    mes_docs = await col_blg.aggregate(pipeline_meses).to_list(length=12)
    mes_map = {d["_id"]: d for d in mes_docs}

    desglose_por_mes = []
    for mes_str in meta["meses"]:
        d = mes_map.get(mes_str, {})
        mes_total   = d.get("total", 0)
        mes_causados = d.get("causados", 0)
        mes_pend     = mes_total - mes_causados
        mes_num      = int(mes_str[5:7])
        desglose_por_mes.append({
            "mes":        mes_str,
            "label":      MES_LARGO[mes_num],
            "total":      mes_total,
            "causados":   mes_causados,
            "pendientes": mes_pend,
            "pct_causado": round(mes_causados / mes_total * 100, 1) if mes_total else 0.0,
        })

    # ── Desglose por ronda (solo Q1 tiene datos históricos) ──────────────────
    if periodo_id == "2026-Q1":
        known_sum = sum(
            r["causados"] for r in Q1_RONDAS
            if r["ronda"] != "pre_sprint" and r["causados"] is not None
        )
        pre_sprint = max(0, causados - known_sum)
        desglose_por_ronda = []
        for r in Q1_RONDAS:
            entry = dict(r)
            if entry["ronda"] == "pre_sprint":
                entry["causados"] = pre_sprint
            desglose_por_ronda.append(entry)
    else:
        desglose_por_ronda = []

    # ── Cartera legacy (solo si hay datos de recaudo) ─────────────────────────
    cartera_legacy: dict | None = None
    if periodo_id == "2026-Q1":
        col_reporte = db["cierre_q1_reporte"]
        reporte_doc = await col_reporte.find_one(sort=[("_id", -1)])
        recaudo_legacy = 0
        if reporte_doc:
            recaudo_legacy = reporte_doc.get("recaudo_q1_legacy", 0) or 0

        col_ll = db["loanbook_legacy"]
        ll_agg = await col_ll.aggregate([
            {"$group": {
                "_id":        None,
                "activos":    {"$sum": {"$cond": [{"$eq": ["$estado", "activo"]}, 1, 0]}},
                "saldo_total": {"$sum": "$saldo_actual"},
            }}
        ]).to_list(length=1)
        ll = ll_agg[0] if ll_agg else {}
        cartera_legacy = {
            "creditos_activos": ll.get("activos", 0) or 0,
            "recaudo_periodo":  recaudo_legacy,
            "saldo_vigente":    ll.get("saldo_total", 0) or 0,
        }

    # ── Próximos pasos ────────────────────────────────────────────────────────
    proximos_pasos = _proximos_pasos(estado, manual_pend, errores, sin_match, meta)

    # ── Nota BUILD 4 (solo Q1) ────────────────────────────────────────────────
    nota_build4: str | None = None
    if periodo_id == "2026-Q1":
        nota_build4 = (
            "Asiento de apertura cartera legacy pendiente "
            "— decisión del contador sobre cuenta de contrapartida (ID 5538)"
        )

    detail: dict = {
        **summary,
        "desglose_por_mes":   desglose_por_mes,
        "desglose_por_ronda": desglose_por_ronda,
        "proximos_pasos":     proximos_pasos,
    }
    if cartera_legacy is not None:
        detail["cartera_legacy"] = cartera_legacy
    if nota_build4:
        detail["nota_build4"] = nota_build4

    return detail


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/api/cierres")
async def listar_cierres(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Lista todos los períodos Q relevantes para RODDOS con resumen de estado."""
    col_blg = db["backlog_movimientos"]
    periodo_ids = await _detect_periods(col_blg)

    periodos = []
    for pid in periodo_ids:
        data = await _build_period_data(db, pid, include_detail=False)
        periodos.append(data)

    return {
        "success": True,
        "generado_en": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "periodos": periodos,
    }


@router.get("/api/cierres/{periodo_id}")
async def detalle_cierre(
    periodo_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Detalle completo de un período: desglose por mes, rondas, cartera, bloqueantes."""
    # Validar formato
    if "-Q" not in periodo_id:
        raise HTTPException(status_code=400, detail="periodo_id debe tener formato YYYY-Qn (ej: 2026-Q1)")

    data = await _build_period_data(db, periodo_id, include_detail=True)
    return {"success": True, "generado_en": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **data}


@router.get("/api/cierre-q1/reporte")
async def alias_cierre_q1_reporte():
    """Alias de compatibilidad → redirige a /api/cierres/2026-Q1."""
    return RedirectResponse(url="/api/cierres/2026-Q1", status_code=307)
