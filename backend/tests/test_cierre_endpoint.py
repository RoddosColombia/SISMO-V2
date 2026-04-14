"""
Tests for GET /api/cierre/{periodo} endpoint.

Verifies:
- Endpoint returns 200 with correct structure
- listo_para_cierre = false when HIGH findings exist
- distribucion_tipo includes at least AC and NO
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.audit.classify import Severity


# ───────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────

def _make_journal(jid, date, observations, entries, total=None):
    if total is None:
        total = sum(e.get("debit", 0) for e in entries)
    return {
        "id": jid,
        "date": date,
        "observations": observations,
        "total": total,
        "entries": entries,
    }


def _entry(eid, debit=0, credit=0, name=""):
    return {"id": str(eid), "debit": debit, "credit": credit, "name": name}


CLEAN_JOURNALS = [
    # AC - gasto normal balanced
    _make_journal("1", "2026-02-05", "[AC] Pago servicio internet",
                  [_entry("5487", debit=150000), _entry("5314", credit=150000)]),
    # NO - nomina
    _make_journal("2", "2026-02-28", "[NO] Nomina Alexa febrero 2026",
                  [_entry("5462", debit=4500000), _entry("5314", credit=4500000)]),
    # AC - arriendo with retenciones
    _make_journal("3", "2026-02-02", "[AC] Arriendo oficina febrero",
                  [_entry("5480", debit=3614953),
                   _entry("5386", credit=126523),
                   _entry("5392", credit=14966),
                   _entry("5376", credit=3473464)]),
]

HIGH_FINDING_JOURNALS = [
    # Unbalanced journal (R1-BALANCE -> HIGH)
    _make_journal("10", "2026-03-05", "[AC] Gasto desbalanceado",
                  [_entry("5494", debit=1000000), _entry("5314", credit=900000)]),
    # Nomina
    _make_journal("11", "2026-03-28", "[NO] Nomina marzo",
                  [_entry("5462", debit=2000000), _entry("5314", credit=2000000)]),
    # Arriendo
    _make_journal("12", "2026-03-02", "[AC] Arriendo oficina marzo",
                  [_entry("5480", debit=1000000), _entry("5314", credit=1000000)]),
]


def _mock_alegra_get(journals):
    """Create a mock AlegraClient.get that returns journals."""
    async def fake_get(path, params=None):
        if "journals" in path:
            return journals
        return []
    return fake_get


# ───────────────────────────────────────────────
# Test: correct structure
# ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cierre_returns_correct_structure():
    """Endpoint returns 200 with all required fields."""
    from routers.cierre import cierre_mensual

    mock_db = MagicMock()

    with patch("routers.cierre.AlegraClient") as MockAlegra:
        instance = MockAlegra.return_value
        instance.get = AsyncMock(side_effect=_mock_alegra_get(CLEAN_JOURNALS))

        result = await cierre_mensual("2026-02", db=mock_db)

    assert result["success"] is True
    assert result["periodo"] == "2026-02"
    assert "total_journals" in result
    assert "distribucion_tipo" in result
    assert "hallazgos" in result
    assert "HIGH" in result["hallazgos"]
    assert "MEDIUM" in result["hallazgos"]
    assert "LOW" in result["hallazgos"]
    assert "detalle_hallazgos" in result
    assert "total_debitos" in result
    assert "total_creditos" in result
    assert "diferencia" in result
    assert "nomina_causada" in result
    assert "arriendo_causado" in result
    assert "retenciones_completas" in result
    assert "listo_para_cierre" in result


# ───────────────────────────────────────────────
# Test: listo_para_cierre = false with HIGH findings
# ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cierre_not_ready_with_high_findings():
    """listo_para_cierre must be false when HIGH findings exist."""
    from routers.cierre import cierre_mensual

    mock_db = MagicMock()

    with patch("routers.cierre.AlegraClient") as MockAlegra:
        instance = MockAlegra.return_value
        instance.get = AsyncMock(side_effect=_mock_alegra_get(HIGH_FINDING_JOURNALS))

        result = await cierre_mensual("2026-03", db=mock_db)

    assert result["success"] is True
    assert result["hallazgos"]["HIGH"] > 0
    assert result["listo_para_cierre"] is False


# ───────────────────────────────────────────────
# Test: distribucion includes AC and NO
# ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cierre_distribucion_includes_ac_and_no():
    """distribucion_tipo must include at least AC and NO when both exist."""
    from routers.cierre import cierre_mensual

    mock_db = MagicMock()

    with patch("routers.cierre.AlegraClient") as MockAlegra:
        instance = MockAlegra.return_value
        instance.get = AsyncMock(side_effect=_mock_alegra_get(CLEAN_JOURNALS))

        result = await cierre_mensual("2026-02", db=mock_db)

    dist = result["distribucion_tipo"]
    assert "AC" in dist, f"AC not in distribucion: {dist}"
    assert "NO" in dist, f"NO not in distribucion: {dist}"


# ───────────────────────────────────────────────
# Test: listo_para_cierre = true when clean
# ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cierre_ready_when_clean():
    """listo_para_cierre = true when 0 HIGH, balanced, nomina+arriendo present."""
    from routers.cierre import cierre_mensual

    mock_db = MagicMock()

    with patch("routers.cierre.AlegraClient") as MockAlegra:
        instance = MockAlegra.return_value
        instance.get = AsyncMock(side_effect=_mock_alegra_get(CLEAN_JOURNALS))

        result = await cierre_mensual("2026-02", db=mock_db)

    assert result["listo_para_cierre"] is True
    assert result["hallazgos"]["HIGH"] == 0
    assert result["nomina_causada"] is True
    assert result["arriendo_causado"] is True
    assert abs(result["diferencia"]) < 0.01


# ───────────────────────────────────────────────
# Test: invalid periodo format
# ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cierre_invalid_periodo():
    """Invalid periodo returns error."""
    from routers.cierre import cierre_mensual

    mock_db = MagicMock()
    result = await cierre_mensual("2026", db=mock_db)
    assert result["success"] is False

    result2 = await cierre_mensual("2026-13", db=mock_db)
    assert result2["success"] is False


# ───────────────────────────────────────────────
# Test: not ready without nomina
# ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cierre_not_ready_without_nomina():
    """listo_para_cierre = false when no nomina journals exist."""
    from routers.cierre import cierre_mensual

    # Only AC journals, no nomina
    journals_no_nomina = [
        _make_journal("1", "2026-02-05", "[AC] Pago arriendo oficina",
                      [_entry("5480", debit=1000000),
                       _entry("5386", credit=35000),
                       _entry("5392", credit=4140),
                       _entry("5314", credit=960860)]),
    ]

    mock_db = MagicMock()
    with patch("routers.cierre.AlegraClient") as MockAlegra:
        instance = MockAlegra.return_value
        instance.get = AsyncMock(side_effect=_mock_alegra_get(journals_no_nomina))

        result = await cierre_mensual("2026-02", db=mock_db)

    assert result["nomina_causada"] is False
    assert result["listo_para_cierre"] is False
