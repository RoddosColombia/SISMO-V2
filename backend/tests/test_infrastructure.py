"""
test_infrastructure.py — Verifies FOUND-04 (Tool Use) and FOUND-06 (request_with_verify).

Also serves as the consolidated smoke test for Phase 1 infrastructure.
"""
import pytest
import inspect
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from agents.contador.tools import CONTADOR_TOOLS, get_tools_for_agent


# -- FOUND-04: Tool Use native ---------------------------------------------------

class TestToolUseNative:
    def test_contador_has_minimum_tools(self):
        """FOUND-04: All Contador tools registered (minimum 9 from D-04 requirement)."""
        assert len(CONTADOR_TOOLS) >= 9, (
            f"Expected >= 9 Contador tools, got {len(CONTADOR_TOOLS)}. "
            "Check agents/contador/tools.py against V1 tool_definitions.py"
        )

    def test_each_tool_anthropic_format(self):
        """Each tool must have the 3 fields Anthropic API requires."""
        for tool in CONTADOR_TOOLS:
            assert 'name' in tool, f"Tool missing 'name': {tool}"
            assert 'description' in tool, f"Tool {tool.get('name')} missing 'description'"
            assert 'input_schema' in tool, f"Tool {tool.get('name')} missing 'input_schema'"
            assert tool['input_schema']['type'] == 'object'

    def test_no_journal_entries_in_tool_definitions(self):
        """NEVER /journal-entries as active endpoint — only allowed in NUNCA warnings."""
        for tool in CONTADOR_TOOLS:
            desc = tool.get('description', '')
            if 'journal-entries' in desc:
                assert 'NUNCA' in desc, (
                    f"Tool '{tool['name']}' references /journal-entries without NUNCA warning"
                )

    def test_cfo_and_radar_have_no_tools(self):
        """D-05: CFO, RADAR get no tools. Loanbook has 11 tools (Phase 7)."""
        assert get_tools_for_agent('cfo') == []
        assert get_tools_for_agent('radar') == []
        assert len(get_tools_for_agent('loanbook')) == 11

    def test_registrar_gasto_or_crear_causacion_tool_exists(self):
        names = {t['name'] for t in CONTADOR_TOOLS}
        assert 'registrar_gasto' in names or 'crear_causacion' in names, (
            "Primary expense tool missing from CONTADOR_TOOLS"
        )

    def test_tool_use_feature_flag_gated_in_chat(self):
        """TOOL_USE_ENABLED env var must be checked in chat.py before passing tools to Claude."""
        import agents.chat as chat_module
        source = inspect.getsource(chat_module)
        assert "TOOL_USE_ENABLED" in source, (
            "chat.py must check TOOL_USE_ENABLED env var before passing tools to Claude"
        )


# -- FOUND-06: request_with_verify() ---------------------------------------------

class TestRequestWithVerify:
    @pytest.mark.asyncio
    async def test_calls_post_then_get(self):
        """FOUND-06: Must POST first, then GET to verify. Both calls required."""
        from services.alegra.client import AlegraClient

        mock_db = MagicMock()
        client = AlegraClient(db=mock_db)

        post_response = MagicMock(spec=httpx.Response)
        post_response.status_code = 201
        post_response.raise_for_status = MagicMock()
        post_response.json = MagicMock(return_value={"id": "J-001"})

        get_response = MagicMock(spec=httpx.Response)
        get_response.status_code = 200
        get_response.raise_for_status = MagicMock()
        get_response.json = MagicMock(return_value={"id": "J-001", "status": "active"})

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=post_response)
        mock_http.get = AsyncMock(return_value=get_response)

        with patch("services.alegra.client.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await client.request_with_verify("journals", "POST", {"date": "2026-04-01"})

        # CRITICAL: Both calls must have happened
        mock_http.post.assert_called_once()
        mock_http.get.assert_called_once()
        assert result["id"] == "J-001"

    @pytest.mark.asyncio
    async def test_spanish_error_not_http_code(self):
        """FOUND-06: Errors shown in Spanish, never raw HTTP codes (ROG-1 corollary)."""
        from services.alegra.client import AlegraClient, AlegraError

        mock_db = MagicMock()
        client = AlegraClient(db=mock_db)

        for status_code in [400, 401, 403, 422, 429]:
            error_response = MagicMock(spec=httpx.Response)
            error_response.status_code = status_code
            error_response.raise_for_status = MagicMock(
                side_effect=httpx.HTTPStatusError(
                    str(status_code), request=MagicMock(), response=error_response
                )
            )
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=error_response)

            with patch("services.alegra.client.httpx.AsyncClient") as MockClient:
                MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

                with pytest.raises(AlegraError) as exc:
                    await client.request_with_verify("journals", "POST", {})

                error_msg = str(exc.value)
                assert str(status_code) not in error_msg, (
                    f"Error for HTTP {status_code} must be in Spanish, "
                    f"not show the status code. Got: {error_msg}"
                )

    def test_never_uses_journal_entries_in_source(self):
        """Canonical rule from Registro Canonico: /journal-entries returns 403."""
        import services.alegra.client as module
        source = inspect.getsource(module)
        assert "journal-entries" not in source, (
            "AlegraClient source contains 'journal-entries' -- "
            "this returns HTTP 403. Use /journals instead."
        )

    def test_never_uses_accounts_endpoint_in_source(self):
        """Canonical rule: /accounts returns 403. Use /categories."""
        import services.alegra.client as module
        source = inspect.getsource(module)
        assert '"/accounts"' not in source and "'/accounts'" not in source, (
            "AlegraClient references /accounts -- use /categories instead (403 on /accounts)"
        )
