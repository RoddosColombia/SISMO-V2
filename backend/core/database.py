import os
import asyncio
import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from contextlib import asynccontextmanager
from fastapi import FastAPI

logger = logging.getLogger("datakeeper")

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None
_processor = None  # EventProcessor instance
_processor_task: asyncio.Task | None = None


async def init_db() -> None:
    global _client, _db
    _client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    _db = _client[os.environ["DB_NAME"]]


async def close_db() -> None:
    global _client
    if _client:
        _client.close()


async def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db


def get_processor():
    """Return the EventProcessor instance (for status endpoint)."""
    return _processor


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _processor, _processor_task

    await init_db()

    # Start DataKeeper event processor
    try:
        from core.event_processor import EventProcessor, ensure_datakeeper_indexes
        from core.event_handlers import register_all_handlers

        db = await get_db()
        await ensure_datakeeper_indexes(db)

        _processor = EventProcessor(db)
        register_all_handlers(_processor)
        _processor_task = asyncio.create_task(_processor.run())
        logger.info("DataKeeper started in lifespan")
    except Exception as e:
        logger.error(f"DataKeeper failed to start: {e}")

    yield

    # Shutdown DataKeeper
    if _processor:
        await _processor.stop()
    if _processor_task:
        _processor_task.cancel()
        try:
            await _processor_task
        except asyncio.CancelledError:
            pass

    await close_db()
