"""Tests for anular_factura and crear_nota_credito handlers."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_alegra():
    m = MagicMock()
    m.request_with_verify = AsyncMock(return_value={"_alegra_id": "NC-100", "id": "NC-100"})
    m.get = AsyncMock(return_value=[])
    return m


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.mark.asyncio
async def test_anular_factura_calls_void(mock_alegra, mock_db):
    """anular_factura POSTs to /invoices/{id}/void in Alegra."""
    from agents.contador.handlers.facturacion import handle_anular_factura
    tool_input = {"invoice_id": "555", "motivo": "Error en datos"}
    with patch("agents.contador.handlers.facturacion.validate_write_permission"):
        with patch("agents.contador.handlers.facturacion.publish_event", new_callable=AsyncMock) as mock_pub:
            result = await handle_anular_factura(tool_input, mock_alegra, mock_db, mock_db, "user1")
            assert result["success"] is True
            assert "555" in result["message"]
            # Verify it called void endpoint
            call_args = mock_alegra.request_with_verify.call_args
            assert "invoices/555/void" in call_args[0][0]
            # Verify event published
            mock_pub.assert_called_once()
            event_kwargs = mock_pub.call_args.kwargs
            assert event_kwargs["event_type"] == "factura.venta.anulada"


@pytest.mark.asyncio
async def test_crear_nota_credito_calls_post(mock_alegra, mock_db):
    """crear_nota_credito POSTs to /credit-notes in Alegra."""
    from agents.contador.handlers.facturacion import handle_crear_nota_credito
    tool_input = {
        "invoice_id": "200",
        "motivo": "Devolucion parcial",
        "items": [{"name": "Ajuste", "price": 50000, "quantity": 1}],
    }
    with patch("agents.contador.handlers.facturacion.validate_write_permission"):
        with patch("agents.contador.handlers.facturacion.publish_event", new_callable=AsyncMock) as mock_pub:
            result = await handle_crear_nota_credito(tool_input, mock_alegra, mock_db, mock_db, "user1")
            assert result["success"] is True
            assert result["alegra_id"] == "NC-100"
            # Verify POST /credit-notes
            call_args = mock_alegra.request_with_verify.call_args
            assert call_args[0][0] == "credit-notes"
            assert call_args[0][1] == "POST"
            payload = call_args.kwargs.get("payload", {})
            assert payload["invoiceId"] == "200"
            # Verify event
            mock_pub.assert_called_once()
            assert mock_pub.call_args.kwargs["event_type"] == "nota_credito.creada"


@pytest.mark.asyncio
async def test_tools_dispatcher_alignment():
    """All write tools in tools.py should have a handler in the dispatcher."""
    from agents.contador.tools import CONTADOR_TOOLS
    from agents.contador.handlers.dispatcher import ToolDispatcher, READ_ONLY_TOOLS, CONCILIATION_TOOLS

    tool_names = {t["name"] for t in CONTADOR_TOOLS}
    d = ToolDispatcher.__new__(ToolDispatcher)
    d._handlers = {}
    d.alegra = None
    d.db = None
    d.event_bus = None
    d._build_handlers()
    handler_names = set(d._handlers.keys())

    # Every handler key must be a valid tool name
    orphans = handler_names - tool_names
    assert not orphans, f"Dispatcher keys not in tools.py: {orphans}"

    # Write tools (not read-only, not conciliation) should all have handlers
    write_tools = tool_names - READ_ONLY_TOOLS - CONCILIATION_TOOLS
    write_with_handler = write_tools & handler_names
    # At least 15 write tools should be wired
    assert len(write_with_handler) >= 15, f"Only {len(write_with_handler)} write tools wired"
