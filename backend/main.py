import os
import logging
import sys

# ── Logging global (P0 fix 2026-04-27) ───────────────────────────────────────
# Sin esto, los logger.error/info de firecrawl/handlers/dispatcher quedan
# silenciados — la causa principal de "falla sin lograr ver el por qué".
# Diagnóstico: .planning/DIAGNOSTICO_CONTADOR_FIRECRAWL.md (F-2).
_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True,  # override uvicorn's default config so our handlers/firecrawl logs show up
)
# Silenciar httpx/httpcore (demasiado verbose en INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from core.database import lifespan, get_db
from core.sliding_session import SlidingSessionMiddleware
from routers.auth import router as auth_router
from routers.chat import router as chat_router
from routers.conciliacion import router as conciliacion_router
from routers.backlog import router as backlog_router
from routers.alegra import router as alegra_router
from routers.cierre import router as cierre_router
from routers.inventario import router as inventario_router
from routers.datakeeper import router as datakeeper_router
from routers.crm import router as crm_router
from routers.loanbook import router as loanbook_router
from routers.plan_separe import router as plan_separe_router
from routers.dashboard import router as dashboard_router
from routers.cartera_legacy import router as cartera_legacy_router
from routers.cierres import router as cierres_router
from routers.it_sismo import router as it_sismo_router
from routers.informes import router as informes_router
from routers.radar import router as radar_router
from routers.integraciones import router as integraciones_router
from routers.webhooks import router as webhooks_router  # Sprint S1.5

app = FastAPI(title="SISMO V2", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-New-Token"],
)
app.add_middleware(SlidingSessionMiddleware)

# API routers — MUST be before the SPA mount
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(conciliacion_router)
app.include_router(backlog_router)
app.include_router(alegra_router)
app.include_router(cierre_router)
app.include_router(inventario_router)
app.include_router(datakeeper_router)
app.include_router(crm_router)
app.include_router(loanbook_router)
app.include_router(plan_separe_router)
app.include_router(dashboard_router)
app.include_router(cartera_legacy_router)
app.include_router(cierres_router)
app.include_router(it_sismo_router, prefix="/api/it", tags=["it"])
app.include_router(informes_router)
app.include_router(radar_router)
app.include_router(integraciones_router)
app.include_router(webhooks_router)  # Sprint S1.5 — Alegra/Mercately webhooks


@app.get("/health")
async def health(db: AsyncIOMotorDatabase = Depends(get_db)):
    from services.alegra.client import get_circuit_breaker_estado
    from core.datetime_utils import now_iso_bogota
    cb_estado = await get_circuit_breaker_estado(db)
    return {
        "status": "ok",
        "version": "0.1.0",
        "alegra_circuit_breaker": cb_estado,
        "server_time_bogota": now_iso_bogota(),
    }


# SPA static files — serves React build in production
# Mount AFTER all API routes so /api/* has priority over catch-all
class SPAStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except (StarletteHTTPException,) as ex:
            if ex.status_code == 404:
                return await super().get_response("index.html", scope)
            raise ex


frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(frontend_dist):
    app.mount("/", SPAStaticFiles(directory=frontend_dist, html=True), name="spa")
