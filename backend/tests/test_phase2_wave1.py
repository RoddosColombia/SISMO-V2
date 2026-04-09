"""
Phase 2 Wave 1 Tests — ToolDispatcher + chat.py integration.

Tests 1-6: ToolDispatcher behavior
Tests 7-10: chat.py read/write routing
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# TESTS 1-6: ToolDispatcher
# ---------------------------------------------------------------------------

class TestToolDispatcher:
    """Tests 1-6 — ToolDispatcher dispatch() behavior."""

    def _make_dispatcher(self):
        """Create a ToolDispatcher with mocked dependencies."""
        from agents.contador.handlers import ToolDispatcher
        alegra = MagicMock()
        db = MagicMock()
        event_bus = MagicMock()
        return ToolDispatcher(alegra=alegra, db=db, event_bus=event_bus)

    @pytest.mark.asyncio
    async def test_1_unknown_tool_returns_error_dict(self):
        """Test 1: Dispatching an unknown tool_name returns error dict without raising."""
        dispatcher = self._make_dispatcher()
        result = await dispatcher.dispatch("unknown_tool", {}, "u1")
        assert result == {"success": False, "error": "Handler no encontrado: unknown_tool"}

    @pytest.mark.asyncio
    async def test_2_permission_error_caught_and_returned(self):
        """Test 2: When handler raises PermissionError, dispatch returns error dict."""
        from agents.contador.handlers import ToolDispatcher

        async def bad_handler(**kwargs):
            raise PermissionError("sin permiso")

        dispatcher = self._make_dispatcher()
        dispatcher._handlers["test_tool"] = bad_handler

        result = await dispatcher.dispatch("test_tool", {}, "u1")
        assert result == {"success": False, "error": "Sin permiso: sin permiso"}

    @pytest.mark.asyncio
    async def test_3_generic_exception_caught_and_returned(self):
        """Test 3: When handler raises generic Exception, dispatch returns error dict."""

        async def bad_handler(**kwargs):
            raise Exception("db error")

        dispatcher = self._make_dispatcher()
        dispatcher._handlers["tool_name"] = bad_handler

        result = await dispatcher.dispatch("tool_name", {}, "u1")
        assert result == {"success": False, "error": "Error ejecutando tool_name: db error"}

    def test_4_handlers_contains_all_28_tool_keys(self):
        """Test 4: _handlers contains exactly the expected tool keys."""
        dispatcher = self._make_dispatcher()
        expected_keys = {
            # Egresos
            "crear_causacion",
            "registrar_gasto",
            "registrar_gasto_recurrente",
            "anular_causacion",
            "causar_movimiento_bancario",
            "registrar_ajuste_contable",
            "registrar_depreciacion",
            # Ingresos + CXC
            "registrar_pago_cuota",
            "registrar_ingreso_no_operacional",
            "registrar_cxc_socio",
            "consultar_cxc_socios",
            # Facturacion
            "crear_factura_venta_moto",
            "consultar_facturas",
            "anular_factura",
            "crear_nota_credito",
            # Consultas
            "consultar_plan_cuentas",
            "consultar_journals",
            "consultar_balance",
            "consultar_estado_resultados",
            "consultar_pagos",
            "consultar_contactos",
            "consultar_items",
            "consultar_movimiento_cuenta",
            # Cartera + Nomina + Catalogo
            "consultar_cartera",
            "registrar_nomina_mensual",
            "consultar_obligaciones_tributarias",
            "calcular_retenciones",
            "consultar_catalogo_roddos",
        }
        assert set(dispatcher._handlers.keys()) == expected_keys

    def test_5_is_read_only_tool(self):
        """Test 5: is_read_only_tool correctly classifies tools."""
        from agents.contador.handlers import is_read_only_tool
        assert is_read_only_tool("consultar_journals") is True
        assert is_read_only_tool("crear_causacion") is False
        assert is_read_only_tool("consultar_plan_cuentas") is True
        assert is_read_only_tool("registrar_gasto") is False

    @pytest.mark.asyncio
    async def test_6_conciliation_tool_returns_phase3_stub(self):
        """Test 6: Conciliation tools return Phase 3 stub."""
        from agents.contador.handlers import is_conciliation_tool
        assert is_conciliation_tool("cargar_extracto_bancario") is True

        dispatcher = self._make_dispatcher()
        result = await dispatcher.dispatch("cargar_extracto_bancario", {}, "u1")
        assert result["success"] is True
        assert "Phase 3" in result["message"]


# ---------------------------------------------------------------------------
# TESTS 7-10: chat.py read/write routing
# ---------------------------------------------------------------------------

class TestChatRouting:
    """Tests 7-10 — chat.py dispatcher integration."""

    @pytest.mark.asyncio
    async def test_7_read_tool_executes_immediately(self):
        """Test 7: Read-only tool executes immediately via dispatcher, no ExecutionCard."""
        from agents.chat import process_chat
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch.return_value = {
            "success": True,
            "result": [{"id": 1, "name": "Test category"}]
        }

        # Fake tool_use block
        fake_block = MagicMock()
        fake_block.type = "tool_use"
        fake_block.name = "consultar_plan_cuentas"
        fake_block.input = {"tipo": "gastos"}

        fake_final_message = MagicMock()
        fake_final_message.content = [fake_block]

        fake_stream = AsyncMock()
        fake_stream.__aenter__ = AsyncMock(return_value=fake_stream)
        fake_stream.__aexit__ = AsyncMock(return_value=None)
        fake_stream.__aiter__ = MagicMock(return_value=iter([]))
        fake_stream.get_final_message = AsyncMock(return_value=fake_final_message)

        mock_db = AsyncMock()
        mock_db.agent_sessions = AsyncMock()

        with patch("agents.chat.anthropic.AsyncAnthropic") as mock_anthropic:
            mock_anthropic.return_value.messages.stream.return_value = fake_stream

            events = []
            async for event in process_chat(
                message="muestra el plan de cuentas",
                db=mock_db,
                agent_type="contador",
                session_id="test-session-7",
                dispatcher=mock_dispatcher,
            ):
                events.append(event)

        # Verify dispatcher was called
        mock_dispatcher.dispatch.assert_called_once_with(
            "consultar_plan_cuentas", {"tipo": "gastos"}, "test-session-7"
        )

        # Verify tool_result SSE was yielded (not tool_proposal)
        tool_result_events = [e for e in events if '"tool_result"' in e]
        tool_proposal_events = [e for e in events if '"tool_proposal"' in e]
        assert len(tool_result_events) >= 1
        assert len(tool_proposal_events) == 0

    @pytest.mark.asyncio
    async def test_8_write_tool_yields_execution_card(self):
        """Test 8: Write tool yields ExecutionCard with requires_confirmation=True."""
        from agents.chat import process_chat

        mock_dispatcher = AsyncMock()

        fake_block = MagicMock()
        fake_block.type = "tool_use"
        fake_block.name = "registrar_gasto"
        fake_block.input = {"descripcion": "arriendo", "monto": 3000000, "banco": "Bancolombia"}

        fake_final_message = MagicMock()
        fake_final_message.content = [fake_block]

        fake_stream = AsyncMock()
        fake_stream.__aenter__ = AsyncMock(return_value=fake_stream)
        fake_stream.__aexit__ = AsyncMock(return_value=None)
        fake_stream.__aiter__ = MagicMock(return_value=iter([]))
        fake_stream.get_final_message = AsyncMock(return_value=fake_final_message)

        mock_db = AsyncMock()
        mock_db.agent_sessions = AsyncMock()
        mock_db.agent_sessions.update_one = AsyncMock()

        with patch("agents.chat.anthropic.AsyncAnthropic") as mock_anthropic:
            mock_anthropic.return_value.messages.stream.return_value = fake_stream

            events = []
            async for event in process_chat(
                message="registra el arriendo",
                db=mock_db,
                agent_type="contador",
                session_id="test-session-8",
                dispatcher=mock_dispatcher,
            ):
                events.append(event)

        # Dispatcher should NOT be called for write tools (they need confirmation first)
        mock_dispatcher.dispatch.assert_not_called()

        # Verify ExecutionCard SSE was yielded
        proposal_events = [e for e in events if '"tool_proposal"' in e]
        assert len(proposal_events) == 1
        proposal_data = json.loads(proposal_events[0].replace("data: ", "").strip())
        assert proposal_data["requires_confirmation"] is True
        assert proposal_data["tool_name"] == "registrar_gasto"

    @pytest.mark.asyncio
    async def test_9_approve_plan_dispatches_pending_action(self):
        """Test 9: execute_approved_action dispatches pending action from session."""
        from agents.chat import execute_approved_action

        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch.return_value = {
            "success": True,
            "alegra_id": "J-1234",
        }

        mock_db = AsyncMock()
        mock_db.agent_sessions = AsyncMock()
        mock_db.agent_sessions.find_one = AsyncMock(return_value={
            "session_id": "test-session-9",
            "pending_action": {
                "tool_name": "registrar_gasto",
                "tool_input": {"descripcion": "arriendo", "monto": 3000000},
                "correlation_id": "corr-123",
            },
            "agent_type": "contador",
        })
        mock_db.agent_sessions.update_one = AsyncMock()

        result = await execute_approved_action(
            session_id="test-session-9",
            db=mock_db,
            dispatcher=mock_dispatcher,
        )

        mock_dispatcher.dispatch.assert_called_once_with(
            tool_name="registrar_gasto",
            tool_input={"descripcion": "arriendo", "monto": 3000000},
            user_id="test-session-9",
        )
        assert result["success"] is True
        assert result["alegra_id"] == "J-1234"

    @pytest.mark.asyncio
    async def test_10_dispatcher_error_yields_sse_error(self):
        """Test 10: If dispatcher returns success=False, SSE error event is yielded."""
        from agents.chat import process_chat

        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch.return_value = {
            "success": False,
            "error": "Handler no encontrado: consultar_plan_cuentas",
        }

        fake_block = MagicMock()
        fake_block.type = "tool_use"
        fake_block.name = "consultar_plan_cuentas"
        fake_block.input = {}

        fake_final_message = MagicMock()
        fake_final_message.content = [fake_block]

        fake_stream = AsyncMock()
        fake_stream.__aenter__ = AsyncMock(return_value=fake_stream)
        fake_stream.__aexit__ = AsyncMock(return_value=None)
        fake_stream.__aiter__ = MagicMock(return_value=iter([]))
        fake_stream.get_final_message = AsyncMock(return_value=fake_final_message)

        mock_db = AsyncMock()
        mock_db.agent_sessions = AsyncMock()

        with patch("agents.chat.anthropic.AsyncAnthropic") as mock_anthropic:
            mock_anthropic.return_value.messages.stream.return_value = fake_stream

            events = []
            async for event in process_chat(
                message="consultar plan",
                db=mock_db,
                agent_type="contador",
                session_id="test-session-10",
                dispatcher=mock_dispatcher,
            ):
                events.append(event)

        # Verify tool_result with success=False is in events (dispatcher error surfaced)
        tool_result_events = [e for e in events if '"tool_result"' in e]
        assert len(tool_result_events) >= 1
        result_data = json.loads(tool_result_events[0].replace("data: ", "").strip())
        assert result_data["result"]["success"] is False
