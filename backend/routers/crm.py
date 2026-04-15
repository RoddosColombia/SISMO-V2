"""
CRM endpoints — Client management for RODDOS motorcycle credits.

GET  /api/crm/clientes          — List clients (filterable by estado, score)
GET  /api/crm/clientes/{cedula} — Client detail with loanbooks
POST /api/crm/clientes          — Create new client
PUT  /api/crm/clientes/{cedula} — Update client data
GET  /api/crm/stats             — Summary stats
"""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_db
from core.crm_model import crear_cliente_doc, validar_telefono, ESTADOS_CRM

router = APIRouter(prefix="/api/crm", tags=["crm"])


# ═══════════════════════════════════════════
# Internal functions (testable without HTTP)
# ═══════════════════════════════════════════


async def _crear_cliente(db: AsyncIOMotorDatabase, data: dict) -> dict:
    """Create a new CRM client. Raises ValueError if duplicate."""
    cedula = data["cedula"]

    existing = await db.crm_clientes.find_one({"cedula": cedula})
    if existing:
        raise ValueError(f"Cliente con cédula {cedula} ya existe.")

    doc = crear_cliente_doc(
        cedula=cedula,
        nombre=data.get("nombre", ""),
        telefono=data.get("telefono", ""),
        email=data.get("email", ""),
        direccion=data.get("direccion", ""),
    )
    await db.crm_clientes.insert_one(doc)

    # Return without _id
    doc.pop("_id", None)
    return doc


async def _get_cliente(db: AsyncIOMotorDatabase, cedula: str) -> dict | None:
    """Get client by cédula. Returns None if not found."""
    doc = await db.crm_clientes.find_one({"cedula": cedula})
    if doc:
        doc.pop("_id", None)
    return doc


async def _actualizar_cliente(
    db: AsyncIOMotorDatabase, cedula: str, updates: dict
) -> bool:
    """Update client fields. Returns True if found."""
    existing = await db.crm_clientes.find_one({"cedula": cedula})
    if not existing:
        return False

    updates["updated_at"] = date.today().isoformat()
    await db.crm_clientes.update_one(
        {"cedula": cedula},
        {"$set": updates},
    )
    return True


async def _listar_clientes(
    db: AsyncIOMotorDatabase,
    estado: str | None = None,
    score: str | None = None,
) -> list[dict]:
    """List clients with optional filters."""
    filtro: dict = {}
    if estado:
        filtro["estado"] = estado
    if score:
        filtro["score"] = score

    cursor = db.crm_clientes.find(filtro).sort("nombre", 1)
    items = await cursor.to_list(length=500)
    for item in items:
        item.pop("_id", None)
    return items


async def _get_stats(db: AsyncIOMotorDatabase) -> dict:
    """Get CRM summary statistics."""
    total = await db.crm_clientes.count_documents({})
    por_estado = {}
    for estado in ESTADOS_CRM:
        count = await db.crm_clientes.count_documents({"estado": estado})
        por_estado[estado] = count

    return {
        "total": total,
        "por_estado": por_estado,
    }


# ═══════════════════════════════════════════
# HTTP Endpoints
# ═══════════════════════════════════════════


@router.get("/clientes")
async def listar_clientes(
    estado: str | None = None,
    score: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """List all clients with optional filters."""
    items = await _listar_clientes(db, estado=estado, score=score)
    return {"count": len(items), "clientes": items}


@router.get("/clientes/{cedula}")
async def get_cliente(
    cedula: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Get client detail by cédula."""
    doc = await _get_cliente(db, cedula)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Cliente {cedula} no encontrado")
    return doc


@router.post("/clientes", status_code=201)
async def crear_cliente(
    data: dict,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Create a new client."""
    if not data.get("cedula") or not data.get("nombre"):
        raise HTTPException(status_code=400, detail="cedula y nombre son obligatorios")
    try:
        doc = await _crear_cliente(db, data)
        return doc
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.put("/clientes/{cedula}")
async def actualizar_cliente(
    cedula: str,
    data: dict,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Update client data."""
    # Prevent changing cedula
    data.pop("cedula", None)
    data.pop("_id", None)

    updated = await _actualizar_cliente(db, cedula, data)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Cliente {cedula} no encontrado")
    return {"ok": True, "cedula": cedula}


@router.get("/stats")
async def crm_stats(db: AsyncIOMotorDatabase = Depends(get_db)):
    """CRM summary statistics."""
    return await _get_stats(db)
