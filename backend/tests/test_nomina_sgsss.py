"""Tests — SGSSS + parafiscales en nomina handler."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_alegra():
    client = AsyncMock()
    client.request_with_verify = AsyncMock(return_value={"id": 999, "_alegra_id": "test123"})
    client.get = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.roddos_events = MagicMock()
    db.roddos_events.insert_one = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_nomina_con_sgsss_calcula_neto_correcto(mock_alegra, mock_db):
    """Alexa $4,500,000 — neto = salario - 4% salud_ee - 4% pension_ee = 4,140,000."""
    from agents.contador.handlers.nomina import handle_registrar_nomina_mensual

    tool_input = {
        "mes": 3, "anio": 2026,
        "empleados": [{"nombre": "Alexa", "salario": 4_500_000}],
    }
    with patch("agents.contador.handlers.nomina.validate_write_permission"):
        with patch("agents.contador.handlers.nomina.publish_event", new_callable=AsyncMock):
            result = await handle_registrar_nomina_mensual(tool_input, mock_alegra, mock_db, mock_db, "u1")

    assert result["success"] is True

    # Extract the entries payload sent to Alegra
    call_args = mock_alegra.request_with_verify.call_args
    payload = call_args[1]["payload"] if "payload" in call_args[1] else call_args[0][2]
    entries = payload["entries"]

    # Find banco credit entry (first credit entry = neto to employee)
    banco_entry = next(e for e in entries if e["credit"] > 0 and e["id"] == "5314")
    expected_neto = 4_500_000 - (4_500_000 * 0.04) - (4_500_000 * 0.04)  # 4,140,000
    assert banco_entry["credit"] == expected_neto, f"Banco credit should be {expected_neto}, got {banco_entry['credit']}"


@pytest.mark.asyncio
async def test_nomina_sgsss_exencion_sena_icbf(mock_alegra, mock_db):
    """Salary $2,200,000 (< 10 SMMLV $13,000,000) — SENA and ICBF exempt (Art. 114-1 ET)."""
    from agents.contador.handlers.nomina import handle_registrar_nomina_mensual, SGSSS_TASAS

    tool_input = {
        "mes": 3, "anio": 2026,
        "empleados": [{"nombre": "Liz", "salario": 2_200_000}],
    }
    with patch("agents.contador.handlers.nomina.validate_write_permission"):
        with patch("agents.contador.handlers.nomina.publish_event", new_callable=AsyncMock):
            result = await handle_registrar_nomina_mensual(tool_input, mock_alegra, mock_db, mock_db, "u1")

    assert result["success"] is True

    call_args = mock_alegra.request_with_verify.call_args
    payload = call_args[1]["payload"] if "payload" in call_args[1] else call_args[0][2]
    entries = payload["entries"]

    # SENA and ICBF would be debit entries with their specific amounts
    sena_amount = round(2_200_000 * SGSSS_TASAS["sena"], 2)
    icbf_amount = round(2_200_000 * SGSSS_TASAS["icbf"], 2)

    # Neither SENA nor ICBF amounts should appear as debit entries
    debit_amounts = [e["debit"] for e in entries if e["debit"] > 0]
    assert sena_amount not in debit_amounts, f"SENA amount {sena_amount} should NOT appear (exempt < 10 SMMLV)"
    assert icbf_amount not in debit_amounts, f"ICBF amount {icbf_amount} should NOT appear (exempt < 10 SMMLV)"


@pytest.mark.asyncio
async def test_nomina_sgsss_entries_count(mock_alegra, mock_db):
    """With incluir_sgsss=True: 5 debit + 5 credit = 10 entries total."""
    from agents.contador.handlers.nomina import handle_registrar_nomina_mensual

    tool_input = {
        "mes": 3, "anio": 2026,
        "empleados": [{"nombre": "Alexa", "salario": 4_500_000}],
    }
    with patch("agents.contador.handlers.nomina.validate_write_permission"):
        with patch("agents.contador.handlers.nomina.publish_event", new_callable=AsyncMock):
            result = await handle_registrar_nomina_mensual(tool_input, mock_alegra, mock_db, mock_db, "u1")

    assert result["success"] is True

    call_args = mock_alegra.request_with_verify.call_args
    payload = call_args[1]["payload"] if "payload" in call_args[1] else call_args[0][2]
    entries = payload["entries"]

    debit_entries = [e for e in entries if e["debit"] > 0]
    credit_entries = [e for e in entries if e["credit"] > 0]

    assert len(debit_entries) == 5, f"Expected 5 debit entries (sueldo, salud_er, pension_er, arl, ccf), got {len(debit_entries)}"
    assert len(credit_entries) == 5, f"Expected 5 credit entries (banco, cxp_salud, cxp_pension, cxp_arl, cxp_ccf), got {len(credit_entries)}"
    assert len(entries) == 10, f"Expected 10 total entries, got {len(entries)}"
