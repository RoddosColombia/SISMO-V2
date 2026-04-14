"""
DataKeeper monitoring endpoints.
GET /api/datakeeper/status — processor health
GET /api/datakeeper/dlq — dead letter items
"""
from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_db, get_processor

router = APIRouter(prefix="/api/datakeeper", tags=["datakeeper"])


@router.get("/status")
async def datakeeper_status(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Return DataKeeper processor health."""
    processor = get_processor()

    if processor is None:
        return {
            "running": False,
            "events_processed": 0,
            "last_event_timestamp": None,
            "dlq_count": 0,
            "retry_count": 0,
            "handlers_registered": [],
        }

    dlq_count = await db.dead_letter.count_documents({})
    retry_count = await db._datakeeper_retries.count_documents({})

    return {
        "running": processor._running,
        "events_processed": processor.events_processed,
        "last_event_timestamp": processor.last_event_timestamp,
        "dlq_count": dlq_count,
        "retry_count": retry_count,
        "handlers_registered": processor.handler_types,
    }


@router.get("/dlq")
async def datakeeper_dlq(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Return dead letter items for debugging."""
    items = await db.dead_letter.find().sort(
        "dead_at", -1
    ).limit(50).to_list(length=50)

    # Remove MongoDB _id for JSON serialization
    for item in items:
        item.pop("_id", None)
        evt = item.get("event", {})
        if evt:
            evt.pop("_id", None)

    return {"count": len(items), "items": items}
