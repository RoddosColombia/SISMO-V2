"""Backlog REST endpoints."""
from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from core.database import get_db

router = APIRouter(prefix="/api/backlog", tags=["backlog"])


@router.get("")
async def list_backlog(
    banco: str | None = None,
    estado: str = "pendiente",
    limit: int = 500,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """List pending backlog movements."""
    filtro = {"estado": estado}
    if banco:
        filtro["banco"] = banco

    cursor = db.backlog_movimientos.find(filtro).sort("fecha_ingreso_backlog", 1).limit(limit)
    items = await cursor.to_list(length=limit)
    for item in items:
        item["_id"] = str(item["_id"])
    return {"success": True, "data": items, "count": len(items)}


@router.get("/count")
async def backlog_count(
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Count pending backlog movements (for badge)."""
    count = await db.backlog_movimientos.count_documents({"estado": "pendiente"})
    return {"success": True, "count": count}


@router.post("/{backlog_id}/causar")
async def causar_desde_backlog(
    backlog_id: str,
    cuenta_id: int = 5493,
    retefuente: float = 0,
    reteica: float = 0,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Cause a backlog movement — POST /journals with verification."""
    from agents.contador.handlers.conciliacion import handle_causar_desde_backlog
    from services.alegra.client import AlegraClient

    alegra = AlegraClient(db=db)
    result = await handle_causar_desde_backlog(
        tool_input={
            "backlog_id": backlog_id,
            "cuenta_id": cuenta_id,
            "retenciones": {"retefuente": retefuente, "reteica": reteica},
        },
        alegra=alegra,
        db=db,
        event_bus=db,
        user_id="api",
    )
    return result
