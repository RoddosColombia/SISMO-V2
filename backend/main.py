import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from core.database import lifespan
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
from routers.cierre_q1 import router as cierre_q1_router

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
app.include_router(cierre_q1_router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


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
