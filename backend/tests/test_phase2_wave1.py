"""
Phase 2 Wave 1 Tests — ToolDispatcher + chat.py integration.

Tests 1-6: ToolDispatcher behavior
Tests 7-10: chat.py read/write routing
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Stream mock helper — used by Tests 7, 8, 10
# ---------------------------------------------------------------------------

def _make_stream_mock(final_message):
    """
    Build a mock for 'async with client.messages.stream(**kwargs) as stream:'.

    Structure needed:
      client.messages.stream(**kwargs) -> context manager (cm)
      async with cm as stream:
        async for event in stream: ...  (yields nothing)
        await stream.get_final_message() -> final_message
    """
    # The inner stream object (what 'as stream' binds to)
    class AsyncIterEmpty:
        def __aiter__(self):
            return self
        async def __anext__(self):
            raise StopAsyncIteration

    stream_inner = MagicMock()
    stream_inner.__aiter__ = lambda self: AsyncIterEmpty()
    stream_inner.get_final_message = AsyncMock(return_value=final_message)

    # The context manager returned by client.messages.stream(...)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=stream_inner)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


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

    def test_4_handlers_match_tools_py_names(self):
        """Test 4: dispatcher keys match tools.py tool names."""
        from agents.contador.tools import CONTADOR_TOOLS
        dispatcher = self._make_dispatcher()
        tool_names = {t['name'] for t in CONTADOR_TOOLS}
        handler_keys = set(dispatcher._handlers.keys())
        # All handler keys must be valid tool names (no orphan keys)
        orphans = handler_keys - tool_names
        assert not orphans, f"Dispatcher keys not in tools.py: {orphans}"
        # At least 25 tools should be wired (some may not have handlers yet)
        assert len(handler_keys) >= 25, f"Only {len(handler_keys)} handlers wired, expected >= 25"

    def test_5_is_read_only_tool(self):
        """Test 5: is_read_only_tool correctly classifies tools."""
        from agents.contador.handlers import is_read_only_tool
        assert is_read_only_tool("consultar_journals") is True
        assert is_read_only_tool("crear_causacion") is False
        assert is_read_only_tool("consultar_plan_cuentas") is True
        assert is_read_only_tool("registrar_gasto") is False

    def test_6_conciliation_tools_registered(self):
        """Test 6: Conciliation tools are registered in dispatcher (Phase 3 implemented)."""
        from agents.contador.handlers import is_conciliation_tool
        assert is_conciliation_tool("conciliar_extracto_bancario") is True
        assert is_conciliation_tool("clasificar_movimiento") is True

        dispatcher = self._make_dispatcher()
        assert "conciliar_extracto_bancario" in dispatcher._handlers


# ---------------------------------------------------------------------------
# TESTS 7-10: chat.py read/write routing
# ---------------------------------------------------------------------------

class TestChatRouting:
    """Tests 7-10 — chat.py dispatcher integration."""

    @pytest.mark.asyncio
    async def test_7_read_tool_executes_immediately(self):
        """Test 7: Read-only tool executes immediately via dispatcher, no ExecutionCard."""
        from agents.chat import process_chat

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

        mock_db = AsyncMock()
        mock_db.agent_sessions = AsyncMock()

        stream_cm = _make_stream_mock(fake_final_message)

        with patch("agents.chat.anthropic.AsyncAnthropic") as mock_anthropic:
            mock_anthropic.return_value.messages.stream.return_value = stream_cm

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

        mock_db = AsyncMock()
        mock_db.agent_sessions = AsyncMock()
        mock_db.agent_sessions.update_one = AsyncMock()

        stream_cm = _make_stream_mock(fake_final_message)

        with patch("agents.chat.anthropic.AsyncAnthropic") as mock_anthropic:
            mock_anthropic.return_value.messages.stream.return_value = stream_cm

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
        """Test 10: If dispatcher returns success=False, SSE tool_result is yielded."""
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

        mock_db = AsyncMock()
        mock_db.agent_sessions = AsyncMock()

        stream_cm = _make_stream_mock(fake_final_message)

        with patch("agents.chat.anthropic.AsyncAnthropic") as mock_anthropic:
            mock_anthropic.return_value.messages.stream.return_value = stream_cm

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
