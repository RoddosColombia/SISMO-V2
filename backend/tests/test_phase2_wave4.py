"""
Wave 4 tests — 4 ingresos + CXC handlers.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_alegra():
    client = AsyncMock()
    client.request_with_verify = AsyncMock(return_value={"id": 999, "_alegra_id": "999"})
    client.get = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.roddos_events = MagicMock()
    db.roddos_events.insert_one = AsyncMock()
    db.loanbook = MagicMock()
    db.loanbook.find_one = AsyncMock(return_value={"loanbook_id": "LB-001", "factura_alegra_id": "500"})
    db.plan_ingresos_roddos = MagicMock()
    db.plan_ingresos_roddos.find_one = AsyncMock(return_value={"tipo": "ingresos_financieros", "alegra_id": 4100})
    db.plan_cuentas_roddos = MagicMock()
    db.plan_cuentas_roddos.find_one = AsyncMock(return_value={"tipo": "cxc_socios", "alegra_id": 1305})
    return db


# --- Test 1: Dual-operation calls payments then journals ---

@pytest.mark.asyncio
async def test_ingreso_cuota_dual_operation(mock_alegra, mock_db):
    from agents.contador.handlers.ingresos import handle_registrar_ingreso_cuota
    mock_alegra.request_with_verify = AsyncMock(
        side_effect=[
            {"id": 100, "_alegra_id": "100"},  # payment
            {"id": 200, "_alegra_id": "200"},  # journal
        ]
    )
    tool_input = {"loanbook_id": "LB-001", "monto": 175000, "banco": "Bancolombia", "numero_cuota": 5}
    with patch("agents.contador.handlers.ingresos.validate_write_permission"):
        with patch("agents.contador.handlers.ingresos.publish_event", new_callable=AsyncMock):
            result = await handle_registrar_ingreso_cuota(tool_input, mock_alegra, mock_db, mock_db, "user1")
            assert result["success"] is True
            assert result["payment_id"] == "100"
            assert result["journal_id"] == "200"
            assert mock_alegra.request_with_verify.call_count == 2


# --- Test 2: Payment failure prevents journal ---

@pytest.mark.asyncio
async def test_ingreso_cuota_payment_fails_no_journal(mock_alegra, mock_db):
    from agents.contador.handlers.ingresos import handle_registrar_ingreso_cuota
    mock_alegra.request_with_verify = AsyncMock(side_effect=Exception("Alegra 500"))
    tool_input = {"loanbook_id": "LB-001", "monto": 175000, "banco": "BBVA", "numero_cuota": 3}
    with patch("agents.contador.handlers.ingresos.validate_write_permission"):
        result = await handle_registrar_ingreso_cuota(tool_input, mock_alegra, mock_db, mock_db, "user1")
        assert result["success"] is False
        assert "Error" in result["error"]


# --- Test 3: Success returns both IDs ---

@pytest.mark.asyncio
async def test_ingreso_cuota_returns_both_ids(mock_alegra, mock_db):
    from agents.contador.handlers.ingresos import handle_registrar_ingreso_cuota
    mock_alegra.request_with_verify = AsyncMock(
        side_effect=[{"id": 10, "_alegra_id": "10"}, {"id": 20, "_alegra_id": "20"}]
    )
    tool_input = {"loanbook_id": "LB-001", "monto": 160000, "banco": "Davivienda", "numero_cuota": 1}
    with patch("agents.contador.handlers.ingresos.validate_write_permission"):
        with patch("agents.contador.handlers.ingresos.publish_event", new_callable=AsyncMock):
            result = await handle_registrar_ingreso_cuota(tool_input, mock_alegra, mock_db, mock_db, "user1")
            assert "payment_id" in result
            assert "journal_id" in result


# --- Test 4: Event published after both succeed ---

@pytest.mark.asyncio
async def test_ingreso_cuota_publishes_event(mock_alegra, mock_db):
    from agents.contador.handlers.ingresos import handle_registrar_ingreso_cuota
    mock_alegra.request_with_verify = AsyncMock(
        side_effect=[{"id": 1, "_alegra_id": "1"}, {"id": 2, "_alegra_id": "2"}]
    )
    tool_input = {"loanbook_id": "LB-001", "monto": 175000, "banco": "Bancolombia", "numero_cuota": 7}
    with patch("agents.contador.handlers.ingresos.validate_write_permission"):
        with patch("agents.contador.handlers.ingresos.publish_event", new_callable=AsyncMock) as mock_pub:
            result = await handle_registrar_ingreso_cuota(tool_input, mock_alegra, mock_db, mock_db, "user1")
            assert result["success"] is True
            mock_pub.assert_called_once()
            call_kwargs = mock_pub.call_args.kwargs
            assert call_kwargs["event_type"] == "pago.cuota.registrado"


# --- Test 5: Ingreso no operacional reads from plan_ingresos_roddos ---

@pytest.mark.asyncio
async def test_ingreso_no_op_reads_account(mock_alegra, mock_db):
    from agents.contador.handlers.ingresos import handle_registrar_ingreso_no_operacional
    tool_input = {"tipo": "intereses_bancarios", "monto": 50000, "banco": "Bancolombia", "descripcion": "Intereses"}
    with patch("agents.contador.handlers.ingresos.validate_write_permission"):
        with patch("agents.contador.handlers.ingresos.publish_event", new_callable=AsyncMock):
            result = await handle_registrar_ingreso_no_operacional(tool_input, mock_alegra, mock_db, mock_db, "user1")
            assert result["success"] is True
            mock_db.plan_ingresos_roddos.find_one.assert_called()


# --- Test 6: Ingreso no op fails if account not found ---

@pytest.mark.asyncio
async def test_ingreso_no_op_account_not_found(mock_alegra, mock_db):
    from agents.contador.handlers.ingresos import handle_registrar_ingreso_no_operacional
    mock_db.plan_ingresos_roddos.find_one = AsyncMock(return_value=None)
    tool_input = {"tipo": "tipo_desconocido", "monto": 10000, "banco": "BBVA", "descripcion": "Test"}
    with patch("agents.contador.handlers.ingresos.validate_write_permission"):
        result = await handle_registrar_ingreso_no_operacional(tool_input, mock_alegra, mock_db, mock_db, "user1")
        assert result["success"] is False
        assert "no encontrada" in result["error"]


# --- Test 7: CXC socio debits CXC account ---

@pytest.mark.asyncio
async def test_cxc_socio_debits_cxc(mock_alegra, mock_db):
    from agents.contador.handlers.ingresos import handle_registrar_cxc_socio
    tool_input = {"socio_cedula": "80075452", "monto": 500000, "banco": "Bancolombia", "descripcion": "Retiro personal"}
    with patch("agents.contador.handlers.ingresos.validate_write_permission"):
        with patch("agents.contador.handlers.ingresos.publish_event", new_callable=AsyncMock) as mock_pub:
            result = await handle_registrar_cxc_socio(tool_input, mock_alegra, mock_db, mock_db, "user1")
            assert result["success"] is True
            # Verify the payload uses CXC account (1305), not gasto (5493)
            call_args = mock_alegra.request_with_verify.call_args
            payload = call_args.kwargs.get("payload", {})
            debit_ids = [e["account"]["id"] for e in payload.get("entries", []) if e.get("debit", 0) > 0]
            assert 1305 in debit_ids, f"CXC account 1305 not in debit entries: {debit_ids}"
            assert 5493 not in debit_ids, "Gasto fallback 5493 should NOT be in CXC debit"


# --- Test 8: Unknown CC rejected ---

@pytest.mark.asyncio
async def test_cxc_socio_unknown_cc_rejected(mock_alegra, mock_db):
    from agents.contador.handlers.ingresos import handle_registrar_cxc_socio
    tool_input = {"socio_cedula": "99999999", "monto": 100000, "banco": "BBVA", "descripcion": "Test"}
    with patch("agents.contador.handlers.ingresos.validate_write_permission"):
        result = await handle_registrar_cxc_socio(tool_input, mock_alegra, mock_db, mock_db, "user1")
        assert result["success"] is False
        assert "no corresponde" in result["error"]


# --- Test 9: consultar_cxc_socios is read-only ---

@pytest.mark.asyncio
async def test_consultar_cxc_no_write(mock_alegra, mock_db):
    from agents.contador.handlers.ingresos import handle_consultar_cxc_socios
    mock_alegra.get = AsyncMock(return_value=[])
    result = await handle_consultar_cxc_socios({}, mock_alegra, mock_db, mock_db, "user1")
    assert result["success"] is True
    assert "socios" in result


# --- Test 10: Static — no MongoDB writes ---

def test_ingresos_no_mongodb_writes():
    import pathlib
    path = pathlib.Path("backend/agents/contador/handlers/ingresos.py")
    if path.exists():
        content = path.read_text(encoding="utf-8")
        for op in ["insert_one", "insert_many", "update_one", "replace_one"]:
            assert op not in content, f"ingresos.py contains {op} — violation of ROG-4"
