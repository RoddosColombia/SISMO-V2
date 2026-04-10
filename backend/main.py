import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.database import lifespan
from routers.chat import router as chat_router
from routers.conciliacion import router as conciliacion_router
from routers.backlog import router as backlog_router

app = FastAPI(title="SISMO V2", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(conciliacion_router)
app.include_router(backlog_router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
