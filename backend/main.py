import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.database import lifespan

app = FastAPI(title="SISMO V2", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
