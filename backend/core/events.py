"""
EventPublisher — Append-only event bus via roddos_events collection.
Every successful Alegra write MUST call publish_event() immediately after.
Events are immutable — insert_one only, never update or delete.
"""
import uuid
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase


async def publish_event(
    db: AsyncIOMotorDatabase,
    event_type: str,
    source: str,
    datos: dict,
    alegra_id: str | None,
    accion_ejecutada: str,
    correlation_id: str | None = None,
) -> dict:
    """
    Publish an immutable event to roddos_events.

    Args:
        db: Motor database instance
        event_type: e.g. 'gasto.causado', 'factura.venta.creada'
        source: e.g. 'agente_contador', 'cfo'
        datos: Payload specific to the event
        alegra_id: Alegra record ID returned by request_with_verify() (or None)
        accion_ejecutada: Human-readable summary of what happened
        correlation_id: Original request UUID for tracing

    Returns:
        The event document that was inserted (without MongoDB _id).
    """
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "source": source,
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "datos": datos,
        "alegra_id": alegra_id,
        "accion_ejecutada": accion_ejecutada,
    }

    await db.roddos_events.insert_one(event)
    # Return a copy without _id (which Motor adds in-place)
    return {k: v for k, v in event.items() if k != "_id"}
