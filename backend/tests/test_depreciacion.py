"""
Depreciation handler tests — handle_registrar_depreciacion.

Tests:
1. test_depreciacion_equipo_computo: verify uses accounts 5503/5360
2. test_depreciacion_anti_dup: mock GET /journals returning existing depreciation, verify skip
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_alegra():
    client = AsyncMock()
    client.request_with_verify = AsyncMock(return_value={"id": 900, "_alegra_id": "900"})
    client.get = AsyncMock(return_value=[])  # no existing journals by default
    return client


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.roddos_events = MagicMock()
    db.roddos_events.insert_one = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Test 1: equipo_computo uses accounts 5503 (gasto) / 5360 (contra)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_depreciacion_equipo_computo(mock_alegra, mock_db):
    from agents.contador.handlers.egresos import handle_registrar_depreciacion

    tool_input = {
        "activo": "Computadores oficina",
        "monto": 150000,
        "periodo": "marzo 2026",
        "tipo_activo": "equipo_computo",
        "fecha": "2026-03-31",
    }

    with patch("agents.contador.handlers.egresos.validate_write_permission"):
        with patch("agents.contador.handlers.egresos.publish_event", new_callable=AsyncMock):
            result = await handle_registrar_depreciacion(
                tool_input, mock_alegra, mock_db, mock_db, "u1"
            )

    assert result["success"] is True
    assert result["alegra_id"] == "900"

    # Verify request_with_verify was called (via _post_journal)
    mock_alegra.request_with_verify.assert_called_once()

    # _post_journal calls: alegra.request_with_verify("journals", "POST", payload=payload)
    args, kwargs = mock_alegra.request_with_verify.call_args
    payload = kwargs.get("payload")
    assert payload is not None, "payload must be passed to request_with_verify"

    entries = payload["entries"]

    # Must use 5503 for gasto (debit) and 5360 for contra-activo (credit)
    gasto_entry = [e for e in entries if e.get("debit", 0) > 0][0]
    contra_entry = [e for e in entries if e.get("credit", 0) > 0][0]

    assert gasto_entry["id"] == "5503", f"Expected gasto account 5503, got {gasto_entry['id']}"
    assert contra_entry["id"] == "5360", f"Expected contra account 5360, got {contra_entry['id']}"
    assert gasto_entry["debit"] == 150000
    assert contra_entry["credit"] == 150000

    # Observations must contain the asset name and period
    assert "Computadores oficina" in payload["observations"]
    assert "marzo 2026" in payload["observations"]


# ---------------------------------------------------------------------------
# Test 2: anti-dup — existing journal with same observation skips creation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_depreciacion_anti_dup(mock_alegra, mock_db):
    from agents.contador.handlers.egresos import handle_registrar_depreciacion

    # Mock GET /journals returning an existing depreciation with matching observations
    # Must use the exact accented string the handler generates: "Depreciación"
    mock_alegra.get = AsyncMock(return_value=[
        {"id": 800, "observations": "Depreciación Computadores oficina marzo 2026"},
    ])

    tool_input = {
        "activo": "Computadores oficina",
        "monto": 150000,
        "periodo": "marzo 2026",
        "tipo_activo": "equipo_computo",
        "fecha": "2026-03-31",
    }

    with patch("agents.contador.handlers.egresos.validate_write_permission"):
        with patch("agents.contador.handlers.egresos.publish_event", new_callable=AsyncMock):
            result = await handle_registrar_depreciacion(
                tool_input, mock_alegra, mock_db, mock_db, "u1"
            )

    assert result["success"] is False
    assert "duplicada" in result["error"].lower() or "ya existe" in result["error"].lower()

    # Must NOT have called request_with_verify (no journal created)
    mock_alegra.request_with_verify.assert_not_called()
