# Phase 7 Sprint 1: DataKeeper - Research

**Researched:** 2026-04-14
**Domain:** Event-driven architecture / MongoDB event processor / Python asyncio
**Confidence:** HIGH

## Summary

DataKeeper is a deterministic event processor that polls `roddos_events` for new events and routes them to registered handlers. The critical constraint is that MongoDB Atlas M0 (free tier) does NOT support change streams, so we must implement a polling-based approach using a tailable cursor or timestamp-based polling.

The processor runs as an `asyncio.create_task` inside the existing FastAPI process on Render (single web service, starter plan -- no separate worker). This is the standard pattern for lightweight background processing in single-service deployments. Motor 3.7.1 is the current async driver (deprecated May 2025, EOL May 2026); migration to PyMongo Async API is a future concern, not Sprint 1 scope.

**Primary recommendation:** Build `core/event_processor.py` as an asyncio background task launched during FastAPI lifespan, using timestamp-based polling with a `_datakeeper_cursor` collection to track the last processed event position.

## Standard Stack

### Core (already installed -- no new dependencies)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| motor | 3.7.1 | Async MongoDB driver | Already in use across entire backend [VERIFIED: pip show motor] |
| fastapi | 0.115.0 | Web framework + lifespan hooks | Already in use [VERIFIED: requirements.txt] |
| asyncio | stdlib | Background task, concurrency | Python stdlib, no install needed |

### Supporting (no new packages needed)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| logging | stdlib | Structured logging for processor | Every handler execution |
| datetime | stdlib | Timestamp comparisons for polling | Cursor tracking |
| uuid | stdlib | Event ID generation | Already used in events.py |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Polling | Change Streams | Change Streams not available on Atlas M0 [VERIFIED: MongoDB docs] |
| asyncio.create_task | Separate worker process | Render starter plan = 1 service; separate worker needs 2nd service ($) |
| Motor | PyMongo Async API | Motor deprecated but EOL May 2026; migration adds risk for no Sprint 1 benefit [VERIFIED: Motor docs] |
| Custom DLQ | Celery/RQ | Massive overkill; no Redis available; MongoDB-native DLQ is simpler |

**Installation:**
```bash
# No new packages needed -- all dependencies already in requirements.txt
```

## Architecture Patterns

### Recommended Project Structure
```
backend/
  core/
    event_processor.py     # EventProcessor class + polling loop
    event_handlers.py      # Handler registry + all handler functions
    events.py              # (existing) publish_event()
    database.py            # (existing) init_db/get_db + lifespan → start processor
  tests/
    test_event_processor.py
    test_event_handlers.py
```

### Pattern 1: Timestamp-Based Polling with Cursor Bookmark

**What:** Poll `roddos_events` for events newer than the last processed timestamp, stored in a `_datakeeper_cursor` document in MongoDB.

**When to use:** MongoDB Atlas M0 (no change streams available).

**Example:**
```python
# Source: Custom pattern for Atlas M0 constraint
import asyncio
import logging
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger("datakeeper")

POLL_INTERVAL_SECONDS = 5
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 300  # 5 min

class EventProcessor:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self._handlers: dict[str, list[dict]] = {}  # event_type -> [{"fn": handler, "critical": bool}]
        self._running = False

    def register(self, event_type: str, handler, critical: bool = False):
        """Register a handler for an event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append({"fn": handler, "critical": critical})

    async def _get_cursor_position(self) -> str:
        """Get last processed event timestamp from bookmark."""
        doc = await self.db._datakeeper_cursor.find_one({"_id": "position"})
        if doc:
            return doc["last_timestamp"]
        return datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat()

    async def _set_cursor_position(self, timestamp: str):
        """Update bookmark to latest processed timestamp."""
        await self.db._datakeeper_cursor.update_one(
            {"_id": "position"},
            {"$set": {"last_timestamp": timestamp, "updated_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )

    async def _process_event(self, event: dict) -> bool:
        """Route event to registered handlers. Returns True if all critical handlers succeeded."""
        event_type = event["event_type"]
        handlers = self._handlers.get(event_type, [])
        if not handlers:
            return True  # No handlers = nothing to do

        critical_handlers = [h for h in handlers if h["critical"]]
        parallel_handlers = [h for h in handlers if not h["critical"]]

        # Run critical handlers sequentially -- must all succeed
        for h in critical_handlers:
            try:
                await h["fn"](event, self.db)
            except Exception as e:
                logger.error(f"Critical handler failed for {event_type}: {e}")
                return False

        # Run parallel handlers concurrently -- failures don't block
        if parallel_handlers:
            tasks = [h["fn"](event, self.db) for h in parallel_handlers]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, r in enumerate(results):
                if isinstance(r, Exception):
                    logger.warning(f"Parallel handler failed for {event_type}: {r}")

        return True

    async def run(self):
        """Main polling loop."""
        self._running = True
        logger.info(f"DataKeeper started. Handlers: {list(self._handlers.keys())}")
        while self._running:
            try:
                last_ts = await self._get_cursor_position()
                cursor = self.db.roddos_events.find(
                    {"timestamp": {"$gt": last_ts}}
                ).sort("timestamp", 1).limit(50)

                async for event in cursor:
                    success = await self._process_event(event)
                    if success:
                        await self._set_cursor_position(event["timestamp"])
                    else:
                        await self._send_to_dlq(event)

            except Exception as e:
                logger.error(f"DataKeeper poll error: {e}")

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def stop(self):
        self._running = False
```

### Pattern 2: Idempotent Handler via event_id Check

**What:** Each handler checks if it already processed an event by storing processed event_ids in a set per handler.

**When to use:** Every handler must be idempotent -- processing the same event twice produces the same result.

**Example:**
```python
# Source: Standard idempotency pattern [CITED: mongodb.com/community/forums]
async def handle_factura_venta_inventario(event: dict, db: AsyncIOMotorDatabase):
    """Mark moto as Vendida when factura.venta.creada fires."""
    event_id = event["event_id"]

    # Idempotency check: has this event been processed by this handler?
    already = await db._datakeeper_processed.find_one({
        "event_id": event_id,
        "handler": "factura_venta_inventario",
    })
    if already:
        return  # Already processed -- skip

    # Business logic
    vin = event["datos"].get("vin")
    if vin:
        await db.inventario_motos.update_one(
            {"vin": vin},
            {"$set": {"estado": "vendida", "fecha_venta": event["timestamp"]}}
        )

    # Mark as processed
    await db._datakeeper_processed.insert_one({
        "event_id": event_id,
        "handler": "factura_venta_inventario",
        "processed_at": datetime.now(timezone.utc).isoformat(),
    })
```

### Pattern 3: DLQ with Retry Counter

**What:** Failed events get a retry counter. After MAX_RETRIES, move to `dead_letter` collection.

**Example:**
```python
async def _send_to_dlq(self, event: dict, error: str = ""):
    """Retry or dead-letter a failed event."""
    event_id = event["event_id"]
    retry_doc = await self.db._datakeeper_retries.find_one({"event_id": event_id})
    attempts = (retry_doc["attempts"] if retry_doc else 0) + 1

    if attempts >= MAX_RETRIES:
        # Move to dead letter
        await self.db.dead_letter.insert_one({
            "event_id": event_id,
            "event_type": event["event_type"],
            "event": event,
            "attempts": attempts,
            "last_error": error,
            "dead_at": datetime.now(timezone.utc).isoformat(),
        })
        await self.db._datakeeper_retries.delete_one({"event_id": event_id})
        logger.error(f"Event {event_id} moved to dead_letter after {attempts} attempts")
    else:
        # Schedule retry
        retry_at = datetime.now(timezone.utc).isoformat()  # Will be picked up on next poll cycle
        await self.db._datakeeper_retries.update_one(
            {"event_id": event_id},
            {"$set": {"attempts": attempts, "retry_at": retry_at, "last_error": error},
             "$setOnInsert": {"event": event}},
            upsert=True,
        )
```

### Pattern 4: FastAPI Lifespan Integration

**What:** Start the EventProcessor as an asyncio background task during FastAPI startup, cancel on shutdown.

**Example:**
```python
# In core/database.py — modify existing lifespan
from core.event_processor import EventProcessor, register_all_handlers

_processor_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _processor_task
    await init_db()
    db = await get_db()

    # Start DataKeeper
    processor = EventProcessor(db)
    register_all_handlers(processor)
    _processor_task = asyncio.create_task(processor.run())

    yield

    # Shutdown
    processor.stop()
    if _processor_task:
        _processor_task.cancel()
    await close_db()
```

### Anti-Patterns to Avoid
- **Storing processed state ONLY in memory:** Server restart = reprocess all events. MUST persist cursor position in MongoDB. [ASSUMED]
- **Using change streams on Atlas M0:** Will throw OperationNotSupportedOnView or similar error. [VERIFIED: MongoDB Atlas docs]
- **Running DataKeeper as a separate process:** Render starter plan = 1 service. Adding a worker means paying for a 2nd service. [VERIFIED: render.yaml]
- **Polling without a limit:** `find().sort().limit(50)` prevents processing 10,000 events in one cycle. Always batch. [ASSUMED]
- **Writing to Alegra from DataKeeper:** Violates ROG-4. DataKeeper writes ONLY to MongoDB operational collections. Accounting goes through Contador via event bus. [VERIFIED: CLAUDE.md]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Event ID generation | Custom sequential IDs | `uuid.uuid4()` | Already standardized in events.py |
| Async concurrency | Thread pools | `asyncio.gather()` + `asyncio.create_task()` | Motor is natively async, threads add complexity |
| Retry scheduling | cron / APScheduler | Simple retry counter in MongoDB | Fewer moving parts, no new dependencies |
| JSON serialization | Custom encoders | Pydantic models for handler input validation | Already in the stack, handles datetime etc. |

**Key insight:** The entire DataKeeper is ~200 lines of code. The complexity is in the handler logic, not the infrastructure. Don't over-engineer the processor.

## Common Pitfalls

### Pitfall 1: Timestamp Ordering Gaps
**What goes wrong:** Two events published within the same millisecond get the same ISO timestamp, causing one to be skipped by `$gt` cursor.
**Why it happens:** `datetime.now(timezone.utc).isoformat()` has microsecond precision but events from concurrent requests can collide.
**How to avoid:** Use `$gte` with the last timestamp AND exclude already-processed event_ids. Or use MongoDB's `_id` (ObjectId) which is naturally ordered.
**Warning signs:** Events appear in `roddos_events` but handlers never fire for them.

### Pitfall 2: Cursor Position Races
**What goes wrong:** Event N+1 succeeds, event N fails, cursor moves to N+1 position. Event N is skipped forever.
**Why it happens:** Processing events out of order or moving cursor before all events in batch are processed.
**How to avoid:** Process events strictly in timestamp order. Only advance cursor to the last SUCCESSFULLY processed event. Failed events go to DLQ, don't block cursor.
**Warning signs:** Gap between cursor position and earliest unprocessed event.

### Pitfall 3: Handler Writes Violating Permissions
**What goes wrong:** A DataKeeper handler writes to a collection not in `loanbook` WRITE_PERMISSIONS.
**Why it happens:** DataKeeper is NOT an agent -- it's infrastructure. But it writes on behalf of loanbook agent.
**How to avoid:** All DataKeeper MongoDB writes should use `validate_write_permission("loanbook", collection_name)` before writing. For inventory updates, permissions already allow loanbook to write `inventario_motos`.
**Warning signs:** PermissionError at runtime.

### Pitfall 4: Blocking the FastAPI Event Loop
**What goes wrong:** A handler does CPU-intensive work or blocking I/O, freezing all HTTP requests.
**Why it happens:** DataKeeper runs on the same asyncio event loop as FastAPI.
**How to avoid:** All handler operations must be async (Motor queries are async). Never use `time.sleep()` -- always `asyncio.sleep()`. Keep handlers under 1 second each.
**Warning signs:** HTTP 503 or increased latency on API endpoints during event processing.

### Pitfall 5: Motor Deprecation Drift
**What goes wrong:** Motor 3.7.1 stops receiving security patches after May 2026.
**Why it happens:** MongoDB deprecated Motor in favor of PyMongo Async API.
**How to avoid:** Sprint 1 uses Motor (safe until May 2026). Plan migration to `pymongo.AsyncMongoClient` in a future phase. API is nearly identical -- mostly import changes. [VERIFIED: MongoDB migration guide]
**Warning signs:** Date approaching May 2026 without migration plan.

## Code Examples

### Handler Registration with Decorator Pattern
```python
# Source: Standard Python registry pattern [ASSUMED]
from typing import Callable, Awaitable
from motor.motor_asyncio import AsyncIOMotorDatabase

HandlerFn = Callable[[dict, AsyncIOMotorDatabase], Awaitable[None]]

_registry: dict[str, list[dict]] = {}

def on_event(event_type: str, critical: bool = False):
    """Decorator to register an event handler."""
    def decorator(fn: HandlerFn):
        if event_type not in _registry:
            _registry[event_type] = []
        _registry[event_type].append({"fn": fn, "critical": critical})
        return fn
    return decorator

def get_registry() -> dict[str, list[dict]]:
    return _registry

# Usage:
@on_event("factura.venta.creada", critical=True)
async def handle_factura_inventario(event: dict, db: AsyncIOMotorDatabase):
    vin = event["datos"].get("vin")
    if vin:
        await db.inventario_motos.update_one(
            {"vin": vin},
            {"$set": {"estado": "vendida"}}
        )
```

### Polling Loop with Retry Integration
```python
# Source: Composite of patterns above [ASSUMED]
async def poll_cycle(self):
    """Single poll cycle: fetch new events + retryable events."""
    last_ts = await self._get_cursor_position()

    # 1. New events
    new_events = await self.db.roddos_events.find(
        {"timestamp": {"$gt": last_ts}}
    ).sort("timestamp", 1).limit(50).to_list(length=50)

    # 2. Retryable events (past retry_at time)
    now = datetime.now(timezone.utc).isoformat()
    retries = await self.db._datakeeper_retries.find(
        {"retry_at": {"$lte": now}}
    ).to_list(length=10)

    # Process new events in order
    for event in new_events:
        success = await self._process_event(event)
        if success:
            await self._set_cursor_position(event["timestamp"])
        else:
            await self._send_to_dlq(event, "handler_failed")

    # Process retries
    for retry in retries:
        success = await self._process_event(retry["event"])
        if success:
            await self.db._datakeeper_retries.delete_one({"_id": retry["_id"]})
        else:
            await self._send_to_dlq(retry["event"], "retry_failed")
```

### Index Creation for Performance
```python
# Source: MongoDB best practices [ASSUMED]
async def ensure_datakeeper_indexes(db: AsyncIOMotorDatabase):
    """Create indexes needed by DataKeeper. Call once at startup."""
    # Events polling: sort by timestamp, filter by timestamp
    await db.roddos_events.create_index("timestamp")

    # Idempotency checks: compound index on event_id + handler
    await db._datakeeper_processed.create_index(
        [("event_id", 1), ("handler", 1)],
        unique=True,
    )

    # Retry scheduling
    await db._datakeeper_retries.create_index("retry_at")

    # Dead letter monitoring
    await db.dead_letter.create_index("dead_at")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Motor async driver | PyMongo Async API | May 2025 | Motor EOL May 2026; migration is import-level changes [VERIFIED: MongoDB docs] |
| Change Streams everywhere | Polling on M0, Change Streams on M2+ | Always | M0 limitation is permanent [VERIFIED: Atlas docs] |
| Celery + Redis for task queues | asyncio.create_task for lightweight processing | ~2022 | No Redis needed, simpler deployment |

**Deprecated/outdated:**
- Motor: Deprecated May 2025, EOL May 2026. Still safe for Sprint 1. [VERIFIED: Motor docs]
- `io_loop` parameter in Motor: Removed in Motor 3.x. [VERIFIED: Motor docs]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 5-second polling interval is adequate for RODDOS event volume (~50 events/day) | Architecture Patterns | If events need near-real-time processing, reduce to 1-2s |
| A2 | Batch size of 50 events per poll cycle is sufficient | Architecture Patterns | If bursts exceed 50, increase or remove limit |
| A3 | `_datakeeper_cursor`, `_datakeeper_processed`, `_datakeeper_retries` collection names with underscore prefix are acceptable for internal infrastructure | Architecture Patterns | Naming convention clash; could rename |
| A4 | DataKeeper handler writes should validate as "loanbook" agent in permissions.py | Pitfalls | May need a "datakeeper" entry in WRITE_PERMISSIONS instead |
| A5 | 3 retry attempts with 5-minute delay is appropriate for DLQ policy | Architecture Patterns | Business requirements may differ |

## Open Questions

1. **Permissions identity for DataKeeper**
   - What we know: DataKeeper writes to `inventario_motos` and `loanbook` collections. Current WRITE_PERMISSIONS has "loanbook" agent with access to both.
   - What's unclear: Should DataKeeper validate as "loanbook" agent, or should a new "datakeeper" agent be added to permissions.py?
   - Recommendation: Use "loanbook" identity since DataKeeper IS the loanbook agent's write mechanism. Adding a new agent entry requires modifying a protected file.

2. **Event replay / backfill strategy**
   - What we know: Cursor position determines where processing starts.
   - What's unclear: If DataKeeper deploys and 200 historical events exist, should it process all of them?
   - Recommendation: Start cursor at current time on first deploy. Provide a manual `/api/datakeeper/replay` endpoint for backfill.

3. **Monitoring and alerting for DLQ**
   - What we know: Dead letter events are stored in `dead_letter` collection.
   - What's unclear: How should ops be alerted? Email? Slack? Dashboard?
   - Recommendation: For Sprint 1, expose `/api/datakeeper/status` endpoint showing DLQ count + last processed timestamp. Alerting deferred.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Backend runtime | Yes | 3.14.3 | -- |
| Motor | Async MongoDB | Yes | 3.7.1 | -- |
| MongoDB Atlas M0 | Data storage | Yes (remote) | 8.0 | -- |
| Node.js | Frontend build | Yes | 24.14.0 | -- |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None -- all dependencies already installed.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | DataKeeper is internal, no user-facing auth |
| V3 Session Management | No | No sessions |
| V4 Access Control | Yes | validate_write_permission() before every MongoDB write |
| V5 Input Validation | Yes | Validate event schema before processing (event_type, datos fields) |
| V6 Cryptography | No | No crypto operations |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Event injection (malformed datos) | Tampering | Validate event schema in handler before acting on datos |
| Infinite retry loop (poison event) | Denial of Service | MAX_RETRIES=3, then DLQ -- never retry forever |
| Permission bypass via DataKeeper | Elevation of Privilege | validate_write_permission() on every handler write |

## Sources

### Primary (HIGH confidence)
- [MongoDB Atlas M0 Limitations](https://www.mongodb.com/docs/atlas/reference/free-shared-limitations/) -- confirmed no change streams on free tier
- [Motor 3.7.1 deprecation notice](https://www.mongodb.com/docs/drivers/motor/) -- deprecated May 2025, EOL May 2026
- [PyMongo Async Migration Guide](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/reference/migration/) -- migration path from Motor
- Project files: `core/events.py`, `core/permissions.py`, `core/database.py`, `routers/inventario.py`, `agents/contador/handlers/egresos.py` -- current event publishing patterns
- `render.yaml` -- single web service deployment, starter plan
- `requirements.txt` -- motor==3.7.0 pinned (3.7.1 installed)

### Secondary (MEDIUM confidence)
- [MongoDB Community Forum - Idempotent Consumer Pattern](https://www.mongodb.com/community/forums/t/how-to-implement-the-idempotent-consumer-pattern-with-mongodb/301827) -- idempotency via processed event tracking
- [MongoMQ2 DLQ pattern](https://github.com/morris/mongomq2) -- dead letter queue with maxRetries in MongoDB

### Tertiary (LOW confidence)
- Polling interval (5s) and batch size (50) -- reasonable defaults, not verified against RODDOS event volume

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all dependencies already installed, no new packages
- Architecture: HIGH -- polling is the only viable pattern on Atlas M0; lifespan integration is standard FastAPI
- Pitfalls: HIGH -- derived from actual codebase analysis (permissions system, event schema, render.yaml constraints)
- Handler patterns: MEDIUM -- idempotency and DLQ patterns are well-established but specific implementation details are assumed

**Research date:** 2026-04-14
**Valid until:** 2026-05-14 (30 days -- stable domain, no fast-moving dependencies)
