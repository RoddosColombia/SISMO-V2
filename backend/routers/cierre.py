"""Cierre mensual endpoint — validates a period is ready for accounting close."""
from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_db
from services.alegra.client import AlegraClient
from services.audit.classify import (
    audit_all_journals,
    _infer_type,
    _extract_entries,
    Severity,
)

router = APIRouter(prefix="/api/cierre", tags=["cierre"])

NOMINA_KEYWORDS = ["nomina", "sueldo", "salario"]
ARRIENDO_KEYWORDS = ["arriendo", "arrendamiento", "alquiler"]
RETEFUENTE_IDS = {"5381", "5382", "5383", "5384", "5386", "5388"}
RETEICA_IDS = {"5392", "5393"}


@router.get("/{periodo}")
async def cierre_mensual(
    periodo: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Validate a monthly period for accounting close.

    Args:
        periodo: "YYYY-MM" format (e.g. "2026-02")

    Returns:
        Summary with readiness assessment.
    """
    # Validate periodo format
    if len(periodo) != 7 or periodo[4] != "-":
        return {"success": False, "error": "Formato invalido. Usar YYYY-MM (ej: 2026-02)"}

    year_str, month_str = periodo.split("-")
    try:
        year = int(year_str)
        month = int(month_str)
        if month < 1 or month > 12:
            raise ValueError
    except ValueError:
        return {"success": False, "error": "Periodo invalido"}

    # Calculate date range
    date_from = f"{periodo}-01"
    if month == 12:
        date_to = f"{year + 1}-01-01"
    else:
        date_to = f"{year}-{month + 1:02d}-01"
    # Last day of month
    from datetime import date, timedelta
    last_day = date.fromisoformat(date_to) - timedelta(days=1)
    date_to_str = last_day.isoformat()

    # Fetch journals from Alegra for period
    alegra = AlegraClient(db=db)
    all_journals = []
    start = 0
    limit = 30

    while True:
        try:
            result = await alegra.get("journals", params={
                "start": start,
                "limit": limit,
                "order_direction": "ASC",
            })
        except Exception:
            break

        if isinstance(result, list):
            page = result
        elif isinstance(result, dict) and "data" in result:
            page = result["data"]
        else:
            break

        if not page:
            break

        # Filter by date range
        for j in page:
            jdate = j.get("date", "")
            if date_from <= jdate <= date_to_str:
                all_journals.append(j)

        start += limit
        if len(page) < limit:
            break

    # If we got nothing from paginated fetch, try direct filter
    if not all_journals:
        try:
            result = await alegra.get("journals", params={
                "start": 0,
                "limit": 500,
            })
            if isinstance(result, list):
                all_journals = [j for j in result if date_from <= j.get("date", "") <= date_to_str]
            elif isinstance(result, dict) and "data" in result:
                all_journals = [j for j in result["data"] if date_from <= j.get("date", "") <= date_to_str]
        except Exception:
            pass

    total = len(all_journals)
    if total == 0:
        return {
            "success": True,
            "periodo": periodo,
            "total_journals": 0,
            "distribucion_tipo": {},
            "hallazgos": {"HIGH": 0, "MEDIUM": 0, "LOW": 0},
            "detalle_hallazgos": [],
            "total_debitos": 0,
            "total_creditos": 0,
            "diferencia": 0,
            "nomina_causada": False,
            "arriendo_causado": False,
            "retenciones_completas": True,
            "listo_para_cierre": False,
        }

    # Run audit engine
    classifications = audit_all_journals(all_journals)

    # Type distribution
    dist = {}
    for c in classifications:
        dist[c.inferred_type] = dist.get(c.inferred_type, 0) + 1

    # Findings
    high = sum(1 for c in classifications if c.max_severity == Severity.HIGH)
    medium = sum(1 for c in classifications if c.max_severity == Severity.MEDIUM)
    low = sum(1 for c in classifications if c.max_severity == Severity.LOW)

    detalle = []
    for c in classifications:
        for f in c.findings:
            detalle.append({
                "journal_id": c.journal_id,
                "date": c.date,
                "total": c.total,
                "rule": f.rule,
                "severity": f.severity.value,
                "description": f.description,
            })

    # Totals
    total_debitos = 0.0
    total_creditos = 0.0
    for j in all_journals:
        for e in j.get("entries", []):
            total_debitos += float(e.get("debit", 0) or 0)
            total_creditos += float(e.get("credit", 0) or 0)
    total_debitos = round(total_debitos, 2)
    total_creditos = round(total_creditos, 2)
    diferencia = round(total_debitos - total_creditos, 2)

    # Nomina check
    nomina_causada = any(
        any(kw in (j.get("observations") or "").lower() for kw in NOMINA_KEYWORDS)
        for j in all_journals
    )

    # Arriendo check
    arriendo_causado = any(
        any(kw in (j.get("observations") or "").lower() for kw in ARRIENDO_KEYWORDS)
        for j in all_journals
    )

    # Retenciones check: any arriendo/honorarios journal without retefuente
    retenciones_completas = True
    for c in classifications:
        for f in c.findings:
            if f.rule in ("R3-RETEFUENTE", "R4-RETEICA") and f.severity == Severity.HIGH:
                retenciones_completas = False
                break

    listo = (
        high == 0
        and abs(diferencia) < 0.01
        and nomina_causada
        and arriendo_causado
        and retenciones_completas
    )

    return {
        "success": True,
        "periodo": periodo,
        "total_journals": total,
        "distribucion_tipo": dist,
        "hallazgos": {"HIGH": high, "MEDIUM": medium, "LOW": low},
        "detalle_hallazgos": detalle,
        "total_debitos": total_debitos,
        "total_creditos": total_creditos,
        "diferencia": diferencia,
        "nomina_causada": nomina_causada,
        "arriendo_causado": arriendo_causado,
        "retenciones_completas": retenciones_completas,
        "listo_para_cierre": listo,
    }
