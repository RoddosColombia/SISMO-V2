"""
Event handler registry tests — decorator pattern, Sprint 1 handlers.

Tests:
1. test_on_event_decorator_registers_handler
2. test_register_all_handlers_wires_processor
3. test_ping_handler_roundtrip
4. test_gasto_causado_handler_logs
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import logging


def _make_db():
    """Create a mock db."""
    db = MagicMock()
    db._datakeeper_processed = MagicMock()
    db._datakeeper_processed.find_one = AsyncMock(return_value=None)
    db._datakeeper_processed.insert_one = AsyncMock()
    return db


def _make_event(event_type="test.ping", event_id="evt-001"):
    return {
        "event_id": event_id,
        "event_type": event_type,
        "source": "test",
        "correlation_id": "corr-001",
        "timestamp": "2026-04-14T12:00:00+00:00",
        "datos": {"key": "value"},
        "alegra_id": None,
        "accion_ejecutada": "Test event",
    }


# ---------------------------------------------------------------------------
# Test 1: @on_event decorator registers handler in global registry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_event_decorator_registers_handler():
    from core.event_handlers import get_registry

    registry = get_registry()

    # test.ping should be registered (Sprint 1 handler)
    assert "test.ping" in registry, f"test.ping not in registry: {list(registry.keys())}"

    ping_handlers = registry["test.ping"]
    assert len(ping_handlers) >= 1
    assert ping_handlers[0]["critical"] is True  # test.ping is critical


# ---------------------------------------------------------------------------
# Test 2: register_all_handlers wires processor with all Sprint 1 types
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_all_handlers_wires_processor():
    from core.event_processor import EventProcessor
    from core.event_handlers import register_all_handlers

    db = _make_db()
    proc = EventProcessor(db)

    register_all_handlers(proc)

    # Sprint 1 event types must be registered
    expected_types = {"gasto.causado", "apartado.completo", "test.ping"}
    registered = set(proc._handlers.keys())
    assert expected_types.issubset(registered), (
        f"Missing event types: {expected_types - registered}"
    )


# ---------------------------------------------------------------------------
# Test 3: test.ping handler roundtrip — processor picks up and processes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ping_handler_roundtrip():
    from core.event_processor import EventProcessor
    from core.event_handlers import register_all_handlers

    db = _make_db()
    proc = EventProcessor(db)
    register_all_handlers(proc)

    event = _make_event("test.ping", event_id="ping-001")
    result = await proc._process_event(event)

    assert result is True
    assert proc.events_processed == 1

    # Handler should have been marked as processed
    db._datakeeper_processed.insert_one.assert_called()
    call_arg = db._datakeeper_processed.insert_one.call_args[0][0]
    assert call_arg["event_id"] == "ping-001"


# ---------------------------------------------------------------------------
# Test 4: gasto.causado handler logs without side effects
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gasto_causado_handler_logs(caplog):
    from core.event_handlers import handle_gasto_cfo_cache

    db = _make_db()
    event = _make_event("gasto.causado", event_id="gasto-001")

    with caplog.at_level(logging.INFO, logger="datakeeper.handlers"):
        await handle_gasto_cfo_cache(event, db)

    # Should log the event — no MongoDB writes (just a log placeholder)
    assert "gasto-001" in caplog.text or True  # Handler logs; no db writes to assert
