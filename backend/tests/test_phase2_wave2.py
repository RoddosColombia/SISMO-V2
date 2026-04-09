"""
Wave 2 — consultas.py handler tests (9 tests).

Rules verified:
- consultar_plan_cuentas calls alegra.get("categories") — NEVER "accounts"
- consultar_journals passes date_from/date_to as GET params when provided
- consultar_journals defaults to limit=50 when no params
- consultar_balance passes date_from/date_to to GET /balance
- consultar_estado_resultados calls GET /income-statement and returns data
- consultar_movimiento_cuenta passes account_id as GET param to GET /journals
- All 8 handlers return {success, data, count} on success
- All 8 handlers return {success: False, error} when alegra raises
- STATIC: consultas.py has ZERO MongoDB write calls
"""
import pytest
import ast
import os
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def make_alegra_mock(return_value=None):
    """Create an AlegraClient mock with async get() method."""
    mock = MagicMock()
    mock.get = AsyncMock(return_value=return_value if return_value is not None else [])
    return mock


def make_deps():
    """Return (db_mock, event_bus_mock, user_id)."""
    return MagicMock(), MagicMock(), "user-test-001"


# ---------------------------------------------------------------------------
# Test 1: consultar_plan_cuentas calls GET /categories — NEVER /accounts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consultar_plan_cuentas_uses_categories():
    from agents.contador.handlers.consultas import handle_consultar_plan_cuentas

    alegra = make_alegra_mock(return_value=[{"id": 1, "name": "Caja"}, {"id": 2, "name": "Bancos"}])
    db, event_bus, user_id = make_deps()

    result = await handle_consultar_plan_cuentas({}, alegra, db, event_bus, user_id)

    # Must call GET categories — NOT accounts
    alegra.get.assert_called_once()
    call_args = alegra.get.call_args
    endpoint = call_args[0][0] if call_args[0] else call_args[1].get("endpoint", "")
    assert endpoint == "categories", f"Expected 'categories', got '{endpoint}'. NEVER use /accounts."
    assert result["success"] is True
    assert result["count"] == 2


# ---------------------------------------------------------------------------
# Test 2: consultar_journals passes date_from/date_to when provided
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consultar_journals_passes_date_filters():
    from agents.contador.handlers.consultas import handle_consultar_journals

    alegra = make_alegra_mock(return_value=[{"id": 100}, {"id": 101}])
    db, event_bus, user_id = make_deps()

    tool_input = {"date_from": "2026-01-01", "date_to": "2026-01-31"}
    result = await handle_consultar_journals(tool_input, alegra, db, event_bus, user_id)

    alegra.get.assert_called_once()
    call_kwargs = alegra.get.call_args[1] if alegra.get.call_args[1] else {}
    call_args_pos = alegra.get.call_args[0]

    # params may be keyword or positional
    params = call_kwargs.get("params") or (call_args_pos[1] if len(call_args_pos) > 1 else {})
    assert params is not None, "Expected params dict to be passed"

    # date_from must appear in params under some key
    params_str = str(params)
    assert "2026-01-01" in params_str, "date_from not passed to Alegra params"
    assert "2026-01-31" in params_str, "date_to not passed to Alegra params"

    assert result["success"] is True
    assert result["count"] == 2


# ---------------------------------------------------------------------------
# Test 3: consultar_journals defaults to limit=50 when no params
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consultar_journals_default_limit():
    from agents.contador.handlers.consultas import handle_consultar_journals

    alegra = make_alegra_mock(return_value=[])
    db, event_bus, user_id = make_deps()

    await handle_consultar_journals({}, alegra, db, event_bus, user_id)

    alegra.get.assert_called_once()
    call_kwargs = alegra.get.call_args[1] if alegra.get.call_args[1] else {}
    call_args_pos = alegra.get.call_args[0]

    params = call_kwargs.get("params") or (call_args_pos[1] if len(call_args_pos) > 1 else {})
    assert params is not None, "Expected params dict"
    assert params.get("limit") == 50, f"Expected default limit=50, got {params.get('limit')}"


# ---------------------------------------------------------------------------
# Test 4: consultar_balance passes date_from/date_to to GET /balance
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consultar_balance_passes_dates():
    from agents.contador.handlers.consultas import handle_consultar_balance

    alegra = make_alegra_mock(return_value={"assets": 1000, "liabilities": 500})
    db, event_bus, user_id = make_deps()

    tool_input = {"date_from": "2026-01-01", "date_to": "2026-03-31"}
    result = await handle_consultar_balance(tool_input, alegra, db, event_bus, user_id)

    alegra.get.assert_called_once()
    call_args_pos = alegra.get.call_args[0]
    endpoint = call_args_pos[0]
    assert endpoint == "balance", f"Expected 'balance', got '{endpoint}'"

    call_kwargs = alegra.get.call_args[1] if alegra.get.call_args[1] else {}
    params = call_kwargs.get("params") or (call_args_pos[1] if len(call_args_pos) > 1 else {})
    params_str = str(params)
    assert "2026-01-01" in params_str, "date_from not in balance params"
    assert "2026-03-31" in params_str, "date_to not in balance params"

    assert result["success"] is True


# ---------------------------------------------------------------------------
# Test 5: consultar_estado_resultados calls GET /income-statement and returns data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consultar_estado_resultados_income_statement():
    from agents.contador.handlers.consultas import handle_consultar_estado_resultados

    alegra = make_alegra_mock(return_value={"revenues": 5000, "expenses": 3000, "net": 2000})
    db, event_bus, user_id = make_deps()

    result = await handle_consultar_estado_resultados({}, alegra, db, event_bus, user_id)

    alegra.get.assert_called_once()
    call_args_pos = alegra.get.call_args[0]
    endpoint = call_args_pos[0]
    assert endpoint == "income-statement", f"Expected 'income-statement', got '{endpoint}'"

    assert result["success"] is True
    assert result["data"]["net"] == 2000


# ---------------------------------------------------------------------------
# Test 6: consultar_movimiento_cuenta passes account_id to GET /journals
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consultar_movimiento_cuenta_passes_account_id():
    from agents.contador.handlers.consultas import handle_consultar_movimiento_cuenta

    alegra = make_alegra_mock(return_value=[{"id": 1, "account": 5493}])
    db, event_bus, user_id = make_deps()

    tool_input = {"account_id": 5493}
    result = await handle_consultar_movimiento_cuenta(tool_input, alegra, db, event_bus, user_id)

    alegra.get.assert_called_once()
    call_kwargs = alegra.get.call_args[1] if alegra.get.call_args[1] else {}
    call_args_pos = alegra.get.call_args[0]
    params = call_kwargs.get("params") or (call_args_pos[1] if len(call_args_pos) > 1 else {})
    params_str = str(params)

    assert "5493" in params_str or 5493 in (params or {}).values(), \
        f"account_id not found in params: {params}"
    assert result["success"] is True
    assert result["count"] == 1


# ---------------------------------------------------------------------------
# Test 7: All 8 handlers return {success: True, data, count} on success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_8_handlers_return_success_shape():
    from agents.contador.handlers.consultas import (
        handle_consultar_plan_cuentas,
        handle_consultar_journals,
        handle_consultar_balance,
        handle_consultar_estado_resultados,
        handle_consultar_pagos,
        handle_consultar_contactos,
        handle_consultar_items,
        handle_consultar_movimiento_cuenta,
    )

    handlers_and_inputs = [
        (handle_consultar_plan_cuentas, {}, [{"id": 1}]),
        (handle_consultar_journals, {}, [{"id": 1}]),
        (handle_consultar_balance, {}, {"assets": 100}),
        (handle_consultar_estado_resultados, {}, {"net": 50}),
        (handle_consultar_pagos, {}, [{"id": 1}]),
        (handle_consultar_contactos, {}, [{"id": 1}]),
        (handle_consultar_items, {}, [{"id": 1}]),
        (handle_consultar_movimiento_cuenta, {"account_id": 5493}, [{"id": 1}]),
    ]

    db, event_bus, user_id = make_deps()

    for handler, tool_input, mock_return in handlers_and_inputs:
        alegra = make_alegra_mock(return_value=mock_return)
        result = await handler(tool_input, alegra, db, event_bus, user_id)
        assert result.get("success") is True, \
            f"{handler.__name__} did not return success=True: {result}"
        assert "data" in result, f"{handler.__name__} missing 'data' key"
        assert "count" in result, f"{handler.__name__} missing 'count' key"


# ---------------------------------------------------------------------------
# Test 8: All 8 handlers return {success: False, error} when AlegraClient raises
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_8_handlers_return_error_shape_on_exception():
    from agents.contador.handlers.consultas import (
        handle_consultar_plan_cuentas,
        handle_consultar_journals,
        handle_consultar_balance,
        handle_consultar_estado_resultados,
        handle_consultar_pagos,
        handle_consultar_contactos,
        handle_consultar_items,
        handle_consultar_movimiento_cuenta,
    )

    handlers_and_inputs = [
        (handle_consultar_plan_cuentas, {}),
        (handle_consultar_journals, {}),
        (handle_consultar_balance, {}),
        (handle_consultar_estado_resultados, {}),
        (handle_consultar_pagos, {}),
        (handle_consultar_contactos, {}),
        (handle_consultar_items, {}),
        (handle_consultar_movimiento_cuenta, {"account_id": 5493}),
    ]

    db, event_bus, user_id = make_deps()

    for handler, tool_input in handlers_and_inputs:
        alegra = MagicMock()
        alegra.get = AsyncMock(side_effect=Exception("Alegra unavailable"))
        result = await handler(tool_input, alegra, db, event_bus, user_id)
        assert result.get("success") is False, \
            f"{handler.__name__} did not return success=False on error: {result}"
        assert "error" in result, f"{handler.__name__} missing 'error' key on exception"


# ---------------------------------------------------------------------------
# Test 9: STATIC — consultas.py has ZERO MongoDB write calls
# ---------------------------------------------------------------------------

def test_no_mongodb_writes_in_consultas():
    """Static analysis: consultas.py must have 0 insert_one/update_one/insert_many/replace_one calls."""
    consultas_path = os.path.join(
        os.path.dirname(__file__),
        "..", "agents", "contador", "handlers", "consultas.py"
    )
    consultas_path = os.path.normpath(consultas_path)

    assert os.path.exists(consultas_path), f"consultas.py not found at {consultas_path}"

    with open(consultas_path, "r", encoding="utf-8") as f:
        source = f.read()

    forbidden = ["insert_one", "insert_many", "update_one", "replace_one"]
    violations = [kw for kw in forbidden if kw in source]
    assert not violations, (
        f"consultas.py contains forbidden MongoDB write calls: {violations}. "
        "Wave 2 handlers are read-only — NUNCA escribir en MongoDB."
    )
