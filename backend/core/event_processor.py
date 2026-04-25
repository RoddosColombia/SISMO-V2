"""
DataKeeper — Deterministic event processor for roddos_events.

NOT an AI agent. Polls roddos_events for new events and routes them
to registered handlers. Runs as asyncio.create_task inside FastAPI lifespan.

Architecture:
- Timestamp-based polling (Atlas M0 does not support change streams)
- Critical handlers: sequential, must succeed before cursor advances
- Parallel handlers: concurrent via asyncio.gather, failures logged but don't block
- Idempotent: _datakeeper_processed tracks (event_id, handler) pairs
- DLQ: 3 retries, then dead_letter collection

ROG-4: DataKeeper writes ONLY to MongoDB operational/internal collections.
       NEVER to Alegra. Accounting goes through Contador via event bus.
"""
import asyncio
import logging
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger("datakeeper")

POLL_INTERVAL_SECONDS = 5
MAX_RETRIES = 3
BATCH_SIZE = 50


class EventProcessor:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self._handlers: dict[str, list[dict]] = {}
        self._running = False
        self._events_processed = 0
        self._last_event_timestamp: str | None = None

    # --- Registration ---

    def register(self, event_type: str, handler_fn, critical: bool = False):
        """Register a handler for an event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        name = getattr(handler_fn, "__name__", str(handler_fn))
        self._handlers[event_type].append({
            "fn": handler_fn,
            "critical": critical,
            "name": name,
        })

    # --- Properties (for status endpoint) ---

    @property
    def events_processed(self) -> int:
        return self._events_processed

    @property
    def last_event_timestamp(self) -> str | None:
        return self._last_event_timestamp

    @property
    def handler_types(self) -> list[str]:
        return list(self._handlers.keys())

    # --- Cursor management ---

    async def _get_cursor_position(self) -> str:
        """Get last processed event timestamp from bookmark."""
        doc = await self.db["datakeeper_cursor"].find_one({"_id": "position"})
        if doc:
            return doc["last_timestamp"]
        return "2024-01-01T00:00:00+00:00"

    async def _set_cursor_position(self, timestamp: str):
        """Update bookmark to latest processed timestamp."""
        await self.db["datakeeper_cursor"].update_one(
            {"_id": "position"},
            {"$set": {
                "last_timestamp": timestamp,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )

    # --- Idempotency ---

    async def _is_processed(self, event_id: str, handler_name: str) -> bool:
        """Check if this event was already processed by this handler."""
        doc = await self.db["datakeeper_processed"].find_one({
            "event_id": event_id,
            "handler": handler_name,
        })
        return doc is not None

    async def _mark_processed(self, event_id: str, handler_name: str):
        """Record that this handler processed this event."""
        await self.db["datakeeper_processed"].insert_one({
            "event_id": event_id,
            "handler": handler_name,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        })

    # --- Event processing ---

    async def _process_event(self, event: dict) -> bool:
        """
        Route event to registered handlers.
        Returns True if all critical handlers succeeded (or were already processed).
        """
        event_type = event.get("event_type", "")
        event_id = event.get("event_id", "")
        handlers = self._handlers.get(event_type, [])

        if not handlers:
            return True  # No handlers registered = nothing to do

        critical_handlers = [h for h in handlers if h["critical"]]
        parallel_handlers = [h for h in handlers if not h["critical"]]

        # Run critical handlers sequentially — must all succeed
        for h in critical_handlers:
            handler_name = h["name"]

            # Idempotency check
            if await self._is_processed(event_id, handler_name):
                continue  # Already done

            try:
                await h["fn"](event, self.db)
                await self._mark_processed(event_id, handler_name)
            except Exception as e:
                logger.error(
                    f"Critical handler '{handler_name}' failed for "
                    f"{event_type}/{event_id}: {e}"
                )
                return False  # Stop processing, don't advance cursor

        # Run parallel handlers concurrently — failures don't block
        if parallel_handlers:
            async def _run_parallel(h):
                handler_name = h["name"]
                if await self._is_processed(event_id, handler_name):
                    return
                try:
                    await h["fn"](event, self.db)
                    await self._mark_processed(event_id, handler_name)
                except Exception as e:
                    logger.warning(
                        f"Parallel handler '{handler_name}' failed for "
                        f"{event_type}/{event_id}: {e}"
                    )

            await asyncio.gather(
                *[_run_parallel(h) for h in parallel_handlers],
                return_exceptions=True,
            )

        self._events_processed += 1
        self._last_event_timestamp = event.get("timestamp")
        return True

    # --- DLQ ---

    async def _send_to_dlq(self, event: dict, error: str = ""):
        """Retry or dead-letter a failed event."""
        event_id = event.get("event_id", "")
        retry_doc = await self.db["datakeeper_retries"].find_one(
            {"event_id": event_id}
        )
        attempts = (retry_doc["attempts"] if retry_doc else 0) + 1

        if attempts >= MAX_RETRIES:
            # Move to dead letter
            await self.db.dead_letter.insert_one({
                "event_id": event_id,
                "event_type": event.get("event_type", ""),
                "event": event,
                "attempts": attempts,
                "last_error": error,
                "dead_at": datetime.now(timezone.utc).isoformat(),
            })
            await self.db["datakeeper_retries"].delete_one(
                {"event_id": event_id}
            )
            logger.error(
                f"Event {event_id} moved to dead_letter after {attempts} attempts"
            )
        else:
            # Schedule retry
            await self.db["datakeeper_retries"].update_one(
                {"event_id": event_id},
                {
                    "$set": {
                        "attempts": attempts,
                        "retry_at": datetime.now(timezone.utc).isoformat(),
                        "last_error": error,
                    },
                    "$setOnInsert": {"event": event},
                },
                upsert=True,
            )
            logger.warning(
                f"Event {event_id} queued for retry (attempt {attempts}/{MAX_RETRIES})"
            )

    # --- Main loop ---

    async def run(self):
        """Main polling loop — runs until stop() is called."""
        self._running = True
        logger.info(
            f"DataKeeper started. Handlers registered: {list(self._handlers.keys())}"
        )

        while self._running:
            try:
                await self._poll_cycle()
            except Exception as e:
                logger.error(f"DataKeeper poll cycle error: {e}")

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _poll_cycle(self):
        """Single poll cycle: new events + retries."""
        last_ts = await self._get_cursor_position()

        # 1. New events
        cursor = self.db.roddos_events.find(
            {"timestamp": {"$gt": last_ts}}
        ).sort("timestamp", 1).limit(BATCH_SIZE)

        async for event in cursor:
            success = await self._process_event(event)
            if success:
                await self._set_cursor_position(event["timestamp"])
            else:
                await self._send_to_dlq(event, "critical_handler_failed")

        # 2. Retryable events
        now = datetime.now(timezone.utc).isoformat()
        retries = await self.db["datakeeper_retries"].find(
            {"retry_at": {"$lte": now}}
        ).to_list(length=10)

        for retry in retries:
            evt = retry.get("event", {})
            success = await self._process_event(evt)
            if success:
                await self.db["datakeeper_retries"].delete_one(
                    {"_id": retry["_id"]}
                )
            else:
                await self._send_to_dlq(evt, "retry_failed")

    async def stop(self):
        """Graceful shutdown."""
        self._running = False
        logger.info("DataKeeper stopped.")


# --- Index creation ---

async def ensure_datakeeper_indexes(db: AsyncIOMotorDatabase):
    """Create indexes needed by DataKeeper. Call once at startup."""
    await db.roddos_events.create_index("timestamp")
    await db["datakeeper_processed"].create_index(
        [("event_id", 1), ("handler", 1)],
        unique=True,
    )
    await db["datakeeper_retries"].create_index("retry_at")
    await db.dead_letter.create_index("dead_at")
