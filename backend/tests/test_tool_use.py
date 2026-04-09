"""
Tests for Contador tool definitions (FOUND-04, D-04, D-05).

Rules verified:
- CONTADOR_TOOLS has >= 9 primary tools
- Each tool has required Anthropic format fields
- CFO/RADAR/Loanbook return empty tool lists (D-05)
- No /journal-entries in any tool description
"""
import pytest
from agents.contador.tools import CONTADOR_TOOLS, get_tools_for_agent


def test_contador_has_minimum_tools():
    """Must have at least 9 primary tools (D-04 requirement)."""
    assert len(CONTADOR_TOOLS) >= 9


def test_each_tool_has_required_fields():
    required = {'name', 'description', 'input_schema'}
    for tool in CONTADOR_TOOLS:
        assert required.issubset(tool.keys()), f"Tool missing fields: {tool.get('name')}"


def test_registrar_gasto_tool_exists():
    names = [t['name'] for t in CONTADOR_TOOLS]
    assert 'registrar_gasto' in names or 'crear_causacion' in names


def test_crear_causacion_tool_exists():
    """criar_causacion is the primary journal entry tool."""
    names = [t['name'] for t in CONTADOR_TOOLS]
    assert 'crear_causacion' in names


def test_get_tools_for_contador():
    tools = get_tools_for_agent('contador')
    assert len(tools) >= 9


def test_get_tools_for_cfo_returns_empty():
    """CFO has no tools in Phase 1 (D-05)."""
    tools = get_tools_for_agent('cfo')
    assert tools == []


def test_get_tools_for_radar_returns_empty():
    tools = get_tools_for_agent('radar')
    assert tools == []


def test_get_tools_for_loanbook_returns_empty():
    tools = get_tools_for_agent('loanbook')
    assert tools == []


def test_no_journal_entries_in_descriptions():
    for tool in CONTADOR_TOOLS:
        desc = tool.get('description', '')
        assert 'journal-entries' not in desc, \
            f"Tool {tool['name']} references /journal-entries — use /journals"


def test_input_schemas_are_valid():
    for tool in CONTADOR_TOOLS:
        schema = tool.get('input_schema', {})
        assert schema.get('type') == 'object', f"Tool {tool.get('name')} schema type must be 'object'"
        assert 'properties' in schema, f"Tool {tool.get('name')} schema must have 'properties'"


def test_registrar_nomina_tool_exists():
    names = [t['name'] for t in CONTADOR_TOOLS]
    assert 'registrar_nomina' in names


def test_crear_factura_venta_tool_exists():
    names = [t['name'] for t in CONTADOR_TOOLS]
    assert 'crear_factura_venta' in names


def test_unknown_agent_returns_empty():
    """Agents not in AGENT_TOOLS dict return empty list."""
    tools = get_tools_for_agent('unknown_agent')
    assert tools == []
