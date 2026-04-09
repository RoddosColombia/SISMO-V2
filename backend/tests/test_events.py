import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock
from core.events import publish_event


@pytest.mark.asyncio
async def test_publish_event_inserts_to_roddos_events():
    db = MagicMock()
    db.roddos_events = MagicMock()
    db.roddos_events.insert_one = AsyncMock(return_value=MagicMock(inserted_id="ok"))

    result = await publish_event(
        db=db,
        event_type="gasto.causado",
        source="agente_contador",
        datos={"cuenta": "5480", "monto": 3614953},
        alegra_id="J-12345",
        accion_ejecutada="Journal arrendamiento $3.614.953 causado",
        correlation_id=str(uuid.uuid4()),
    )

    db.roddos_events.insert_one.assert_called_once()
    doc = db.roddos_events.insert_one.call_args[0][0]
    assert doc["event_type"] == "gasto.causado"
    assert doc["source"] == "agente_contador"
    assert doc["alegra_id"] == "J-12345"
    assert "event_id" in doc
    assert "timestamp" in doc
    assert result["event_id"] == doc["event_id"]


@pytest.mark.asyncio
async def test_publish_event_is_append_only():
    """Events must be inserted, never updated."""
    db = MagicMock()
    db.roddos_events = MagicMock()
    db.roddos_events.insert_one = AsyncMock(return_value=MagicMock(inserted_id="ok"))

    await publish_event(db=db, event_type="test.event", source="test",
                        datos={}, alegra_id=None, accion_ejecutada="test")

    # Must use insert_one — NEVER update_one or replace_one
    assert db.roddos_events.insert_one.called
    assert not hasattr(db.roddos_events, 'update_one') or not db.roddos_events.update_one.called
