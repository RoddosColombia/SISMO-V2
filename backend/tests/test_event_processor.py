"""
EventProcessor tests — core polling loop, DLQ, idempotency, cursor.

Tests:
1. test_registers_handlers_by_event_type
2. test_critical_handler_runs_sequentially
3. test_parallel_handler_failure_does_not_block
4. test_idempotent_processing_skips_duplicate
5. test_cursor_advances_on_success
6. test_cursor_does_not_advance_on_critical_failure
7. test_dlq_increments_retry_counter
8. test_dead_letter_after_3_failures
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


def _make_db():
    """Create a mock db with all DataKeeper collections."""
    db = MagicMock()

    # _datakeeper_cursor
    db._datakeeper_cursor = MagicMock()
    db._datakeeper_cursor.find_one = AsyncMock(return_value=None)
    db._datakeeper_cursor.update_one = AsyncMock()

    # _datakeeper_processed
    db._datakeeper_processed = MagicMock()
    db._datakeeper_processed.find_one = AsyncMock(return_value=None)
    db._datakeeper_processed.insert_one = AsyncMock()
    db._datakeeper_processed.create_index = AsyncMock()

    # _datakeeper_retries
    db._datakeeper_retries = MagicMock()
    db._datakeeper_retries.find_one = AsyncMock(return_value=None)
    db._datakeeper_retries.update_one = AsyncMock()
    db._datakeeper_retries.delete_one = AsyncMock()
    db._datakeeper_retries.find = MagicMock(return_value=MagicMock(to_list=AsyncMock(return_value=[])))
    db._datakeeper_retries.create_index = AsyncMock()

    # dead_letter
    db.dead_letter = MagicMock()
    db.dead_letter.insert_one = AsyncMock()
    db.dead_letter.count_documents = AsyncMock(return_value=0)
    db.dead_letter.create_index = AsyncMock()

    # roddos_events
    db.roddos_events = MagicMock()
    db.roddos_events.create_index = AsyncMock()

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
# Test 1: register handlers by event type
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_registers_handlers_by_event_type():
    from core.event_processor import EventProcessor

    db = _make_db()
    proc = EventProcessor(db)

    handler = AsyncMock()
    proc.register("gasto.causado", handler, critical=False)

    assert "gasto.causado" in proc._handlers
    assert len(proc._handlers["gasto.causado"]) == 1
    assert proc._handlers["gasto.causado"][0]["fn"] is handler
    assert proc._handlers["gasto.causado"][0]["critical"] is False


# ---------------------------------------------------------------------------
# Test 2: critical handlers run sequentially, second skipped on failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_critical_handler_runs_sequentially():
    from core.event_processor import EventProcessor

    db = _make_db()
    proc = EventProcessor(db)

    call_order = []

    async def handler_a(event, db):
        call_order.append("A")
        raise RuntimeError("A failed")

    async def handler_b(event, db):
        call_order.append("B")

    proc.register("test.event", handler_a, critical=True)
    proc.register("test.event", handler_b, critical=True)

    event = _make_event("test.event")
    result = await proc._process_event(event)

    assert result is False  # Critical failure
    assert call_order == ["A"]  # B never ran


# ---------------------------------------------------------------------------
# Test 3: parallel handler failure does not block
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_parallel_handler_failure_does_not_block():
    from core.event_processor import EventProcessor

    db = _make_db()
    proc = EventProcessor(db)

    critical_called = False

    async def critical_handler(event, db):
        nonlocal critical_called
        critical_called = True

    async def parallel_bad(event, db):
        raise RuntimeError("parallel failed")

    proc.register("test.event", critical_handler, critical=True)
    proc.register("test.event", parallel_bad, critical=False)

    event = _make_event("test.event")
    result = await proc._process_event(event)

    assert result is True  # Critical succeeded
    assert critical_called is True


# ---------------------------------------------------------------------------
# Test 4: idempotent processing skips duplicate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_idempotent_processing_skips_duplicate():
    from core.event_processor import EventProcessor

    db = _make_db()
    # Simulate already processed
    db._datakeeper_processed.find_one = AsyncMock(
        return_value={"event_id": "evt-001", "handler": "my_handler"}
    )
    proc = EventProcessor(db)

    handler = AsyncMock()
    handler.__name__ = "my_handler"
    proc.register("test.event", handler, critical=True)

    event = _make_event("test.event", event_id="evt-001")
    result = await proc._process_event(event)

    assert result is True  # Treated as success (already done)
    handler.assert_not_called()  # But handler never actually ran


# ---------------------------------------------------------------------------
# Test 5: cursor advances on success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cursor_advances_on_success():
    from core.event_processor import EventProcessor

    db = _make_db()
    proc = EventProcessor(db)

    handler = AsyncMock()
    handler.__name__ = "test_handler"
    proc.register("test.event", handler, critical=False)

    event = _make_event("test.event")
    result = await proc._process_event(event)
    assert result is True

    # Simulate what the poll loop does on success
    await proc._set_cursor_position(event["timestamp"])
    db._datakeeper_cursor.update_one.assert_called_once()

    # Verify the timestamp was stored
    call_args = db._datakeeper_cursor.update_one.call_args
    assert event["timestamp"] in str(call_args)


# ---------------------------------------------------------------------------
# Test 6: cursor does NOT advance on critical failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cursor_does_not_advance_on_critical_failure():
    from core.event_processor import EventProcessor

    db = _make_db()
    proc = EventProcessor(db)

    async def failing_handler(event, db):
        raise RuntimeError("boom")

    proc.register("test.event", failing_handler, critical=True)

    event = _make_event("test.event")
    result = await proc._process_event(event)
    assert result is False

    # _send_to_dlq should be called by the poll loop (not _process_event)
    # But cursor should NOT advance — verify update_one not called
    db._datakeeper_cursor.update_one.assert_not_called()


# ---------------------------------------------------------------------------
# Test 7: DLQ increments retry counter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dlq_increments_retry_counter():
    from core.event_processor import EventProcessor

    db = _make_db()
    # First failure — no existing retry doc
    db._datakeeper_retries.find_one = AsyncMock(return_value=None)

    proc = EventProcessor(db)
    event = _make_event("test.event")

    await proc._send_to_dlq(event, "handler_failed")

    # Should upsert retry doc with attempts=1
    db._datakeeper_retries.update_one.assert_called_once()
    call_args = db._datakeeper_retries.update_one.call_args
    update_doc = call_args[0][1]  # second positional arg is the update
    assert update_doc["$set"]["attempts"] == 1

    # Should NOT have moved to dead_letter yet
    db.dead_letter.insert_one.assert_not_called()


# ---------------------------------------------------------------------------
# Test 8: dead letter after 3 failures
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dead_letter_after_3_failures():
    from core.event_processor import EventProcessor

    db = _make_db()
    # Existing retry doc with 2 attempts (this will be the 3rd)
    db._datakeeper_retries.find_one = AsyncMock(
        return_value={"event_id": "evt-001", "attempts": 2, "event": _make_event()}
    )

    proc = EventProcessor(db)
    event = _make_event("test.event", event_id="evt-001")

    await proc._send_to_dlq(event, "third_failure")

    # Should insert into dead_letter
    db.dead_letter.insert_one.assert_called_once()
    dl_doc = db.dead_letter.insert_one.call_args[0][0]
    assert dl_doc["event_id"] == "evt-001"
    assert dl_doc["attempts"] == 3

    # Should delete from retries
    db._datakeeper_retries.delete_one.assert_called_once()
