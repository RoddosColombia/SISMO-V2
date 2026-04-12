"""Tests for provisionar_prestaciones handler."""
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
async def test_provision_calculates_correctly(mock_alegra, mock_db):
    """Verify amounts for Alexa ($4.5M): prima=374850, cesantias=374850, int_cesantias=45000, vacaciones=187650."""
    from agents.contador.handlers.nomina import handle_provisionar_prestaciones

    tool_input = {
        "mes": "2026-04",
        "empleados": [{"nombre": "Alexa", "salario": 4_500_000}],
    }
    with patch("agents.contador.handlers.nomina.validate_write_permission"):
        with patch("agents.contador.handlers.nomina.publish_event", new_callable=AsyncMock):
            result = await handle_provisionar_prestaciones(tool_input, mock_alegra, mock_db, mock_db, "u1")

    assert result["success"] is True
    assert result["resultados"][0]["status"] == "creado"

    # Verify the journal payload sent to Alegra
    call_args = mock_alegra.request_with_verify.call_args
    payload = call_args[1]["payload"] if "payload" in call_args[1] else call_args[0][2]
    entries = payload["entries"]

    # 8 entries: 4 debit (gasto) + 4 credit (provision)
    assert len(entries) == 8

    # Extract debit amounts by account ID
    debits = {e["id"]: e["debit"] for e in entries if e["debit"] > 0}
    credits = {e["id"]: e["credit"] for e in entries if e["credit"] > 0}

    # Gasto prima: 4_500_000 * 0.0833 = 374_850.0
    assert debits["5468"] == 374_850.0
    # Gasto cesantias: 4_500_000 * 0.0833 = 374_850.0
    assert debits["5466"] == 374_850.0
    # Gasto int_cesantias: 4_500_000 * 0.01 = 45_000.0
    assert debits["5467"] == 45_000.0
    # Gasto vacaciones: 4_500_000 * 0.0417 = 187_650.0
    assert debits["5469"] == 187_650.0

    # Provision credits mirror the debits
    assert credits["5418"] == 374_850.0   # provision prima
    assert credits["5416"] == 374_850.0   # provision cesantias
    assert credits["5417"] == 45_000.0    # provision int_cesantias
    assert credits["5415"] == 187_650.0   # provision vacaciones


@pytest.mark.asyncio
async def test_provision_anti_dup(mock_alegra, mock_db):
    """Mock GET /journals returning existing provision, verify it skips."""
    from agents.contador.handlers.nomina import handle_provisionar_prestaciones

    # Simulate existing journal with matching observations
    mock_alegra.get = AsyncMock(return_value=[
        {"observations": "Prestaciones Alexa 2026-04", "id": 500}
    ])

    tool_input = {
        "mes": "2026-04",
        "empleados": [{"nombre": "Alexa", "salario": 4_500_000}],
    }
    with patch("agents.contador.handlers.nomina.validate_write_permission"):
        with patch("agents.contador.handlers.nomina.publish_event", new_callable=AsyncMock):
            result = await handle_provisionar_prestaciones(tool_input, mock_alegra, mock_db, mock_db, "u1")

    assert result["success"] is True
    assert result["resultados"][0]["status"] == "duplicado"
    assert "ya provisionadas" in result["resultados"][0]["error"]
    # No journal should have been created
    mock_alegra.request_with_verify.assert_not_called()


@pytest.mark.asyncio
async def test_provision_default_employees(mock_alegra, mock_db):
    """Call without empleados param, verify uses Alexa+Liz defaults."""
    from agents.contador.handlers.nomina import handle_provisionar_prestaciones

    tool_input = {"mes": "2026-04"}  # No empleados provided

    with patch("agents.contador.handlers.nomina.validate_write_permission"):
        with patch("agents.contador.handlers.nomina.publish_event", new_callable=AsyncMock):
            result = await handle_provisionar_prestaciones(tool_input, mock_alegra, mock_db, mock_db, "u1")

    assert result["success"] is True
    assert len(result["resultados"]) == 2
    assert result["resultados"][0]["nombre"] == "Alexa"
    assert result["resultados"][1]["nombre"] == "Liz"
    # Two journals created (one per employee)
    assert mock_alegra.request_with_verify.call_count == 2
