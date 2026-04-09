"""
test_event_bus_integration.py — Verifies FOUND-05 (event bus).

Acceptance criteria from SISMO_V2_Fase0_Fase1.md C5:
  - Every successful Alegra write generates an event
  - Events are immutable (append-only)
  - Event schema has all required fields
"""
import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock
from core.events import publish_event
import inspect


class TestEventBusSchema:
    @pytest.mark.asyncio
    async def test_event_has_all_required_fields(self):
        """FOUND-05: Event schema must include all 8 fields."""
        db = MagicMock()
        db.roddos_events = MagicMock()
        captured_doc = {}

        async def capture_insert(doc):
            captured_doc.update(doc)
            return MagicMock(inserted_id="ok")

        db.roddos_events.insert_one = capture_insert

        await publish_event(
            db=db,
            event_type="gasto.causado",
            source="agente_contador",
            datos={"cuenta": "5480", "monto": 3614953},
            alegra_id="J-12345",
            accion_ejecutada="Journal arrendamiento $3.614.953 causado",
            correlation_id=str(uuid.uuid4()),
        )

        required_fields = [
            "event_id", "event_type", "source", "correlation_id",
            "timestamp", "datos", "alegra_id", "accion_ejecutada"
        ]
        for field in required_fields:
            assert field in captured_doc, f"Event missing required field: '{field}'"

    @pytest.mark.asyncio
    async def test_event_id_is_valid_uuid(self):
        db = MagicMock()
        db.roddos_events = MagicMock()
        captured = {}

        async def capture(doc):
            captured.update(doc)
            return MagicMock()

        db.roddos_events.insert_one = capture

        await publish_event(
            db=db, event_type="test", source="test",
            datos={}, alegra_id=None, accion_ejecutada="test"
        )

        # event_id must be a valid UUID4
        try:
            uid = uuid.UUID(captured["event_id"], version=4)
            assert str(uid) == captured["event_id"]
        except ValueError:
            pytest.fail(f"event_id is not a valid UUID4: {captured.get('event_id')}")

    @pytest.mark.asyncio
    async def test_timestamp_is_utc_iso_format(self):
        """Timestamps must be ISO 8601 UTC for Alegra date compatibility."""
        db = MagicMock()
        db.roddos_events = MagicMock()
        captured = {}

        async def capture(doc):
            captured.update(doc)
            return MagicMock()

        db.roddos_events.insert_one = capture

        await publish_event(
            db=db, event_type="test", source="test",
            datos={}, alegra_id=None, accion_ejecutada="test"
        )

        ts = captured.get("timestamp", "")
        assert "T" in ts, f"Timestamp not ISO 8601: {ts}"
        # UTC offset: either Z, +00:00, or UTC
        assert "Z" in ts or "+00:00" in ts or "UTC" in ts.upper(), (
            f"Timestamp must be UTC: {ts}"
        )

    def test_events_module_uses_only_insert_one(self):
        """Events are append-only — no update_one, replace_one, or delete."""
        import core.events as module
        source = inspect.getsource(module)

        forbidden = ["update_one", "replace_one", "delete_one", "delete_many", "update_many"]
        for op in forbidden:
            assert op not in source, (
                f"core/events.py contains '{op}' -- events must be append-only (insert_one only)"
            )

    @pytest.mark.asyncio
    async def test_event_type_stored_verbatim(self):
        db = MagicMock()
        db.roddos_events = MagicMock()
        captured = {}

        async def capture(doc):
            captured.update(doc)
            return MagicMock()

        db.roddos_events.insert_one = capture

        await publish_event(
            db=db, event_type="factura.venta.creada", source="agente_contador",
            datos={}, alegra_id="INV-001", accion_ejecutada="Factura TVS Raider creada"
        )

        assert captured["event_type"] == "factura.venta.creada"
        assert captured["alegra_id"] == "INV-001"
        assert captured["source"] == "agente_contador"


class TestEventBusImmutability:
    @pytest.mark.asyncio
    async def test_publish_event_returns_dict_without_mongo_id(self):
        """The _id field MongoDB adds in-place must not be returned."""
        db = MagicMock()
        db.roddos_events = MagicMock()
        db.roddos_events.insert_one = AsyncMock(return_value=MagicMock(inserted_id="ok"))

        result = await publish_event(
            db=db, event_type="gasto.causado", source="contador",
            datos={}, alegra_id="J-01", accion_ejecutada="test"
        )

        assert "_id" not in result, "Published event must not expose MongoDB's _id field"
        assert "event_id" in result
