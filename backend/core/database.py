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
_alegra_sync_task: asyncio.Task | None = None
_dpd_scheduler_task: asyncio.Task | None = None
_informes_scheduler_task: asyncio.Task | None = None
_radar_scheduler_task: asyncio.Task | None = None


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
    global _processor, _processor_task, _alegra_sync_task, _informes_scheduler_task, _radar_scheduler_task

    await init_db()
    db = await get_db()

    # ── Catálogos maestros Loanbook ────────────────────────────────────
    try:
        from services.loanbook.catalogo_service import warm_catalogo
        await warm_catalogo(db)
        logger.info("catalogo_service: warm_catalogo completado")
    except Exception as e:
        logger.error(f"catalogo_service: warm_catalogo falló: {e}")

    # ── DataKeeper event processor ─────────────────────────────────────
    try:
        from core.event_processor import EventProcessor, ensure_datakeeper_indexes
        from core.event_handlers import register_all_handlers

        # Importar todos los módulos de handlers para activar sus @on_event
        # IMPORTANTE: deben importarse ANTES de register_all_handlers
        import core.loanbook_handlers      # noqa: F401
        import core.contabilidad_handlers  # noqa: F401
        import core.crm_handlers           # noqa: F401

        await ensure_datakeeper_indexes(db)

        _processor = EventProcessor(db)
        register_all_handlers(_processor)
        _processor_task = asyncio.create_task(_processor.run())
        logger.info("DataKeeper started in lifespan")
    except Exception as e:
        logger.error(f"DataKeeper failed to start: {e}")

    # ── Alegra stats sync loop ─────────────────────────────────────────
    try:
        from core.alegra_sync import run_sync_loop
        _alegra_sync_task = asyncio.create_task(run_sync_loop(db))
        logger.info("Alegra stats sync loop started")
    except Exception as e:
        logger.error(f"Alegra sync loop failed to start: {e}")

    # ── DPD scheduler — 06:00 AM America/Bogotá diario ────────────────
    try:
        from services.loanbook.dpd_scheduler import run_dpd_scheduler
        _dpd_scheduler_task = asyncio.create_task(run_dpd_scheduler(db))
        logger.info("DPD scheduler started (runs at 06:00 AM Bogota)")
    except Exception as e:
        logger.error(f"DPD scheduler failed to start: {e}")

    # ── Informes scheduler — jueves 09:00 AM America/Bogotá ───────────
    try:
        from services.loanbook.informes_service import run_informes_scheduler
        _informes_scheduler_task = asyncio.create_task(run_informes_scheduler(db))
        logger.info("Informes scheduler started (runs Thursdays 09:00 AM Bogota)")
    except Exception as e:
        logger.error(f"Informes scheduler failed to start: {e}")

    # ── RADAR scheduler — miércoles 08:00 AM America/Bogotá ───────────
    try:
        from agents.radar.alertas import run_radar_scheduler
        _radar_scheduler_task = asyncio.create_task(run_radar_scheduler(db))
        logger.info("RADAR scheduler started (runs Wednesdays 08:00 AM Bogota)")
    except Exception as e:
        logger.error(f"RADAR scheduler failed to start: {e}")

    yield

    # ── Shutdown ───────────────────────────────────────────────────────
    if _processor:
        await _processor.stop()

    for task in (_processor_task, _alegra_sync_task, _dpd_scheduler_task, _informes_scheduler_task, _radar_scheduler_task):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    await close_db()
