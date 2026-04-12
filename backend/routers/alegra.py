"""Alegra REST endpoints — account lookups from GET /categories."""
from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from core.database import get_db
from core.auth import get_current_user
from services.alegra.client import AlegraClient

router = APIRouter(prefix="/api/alegra", tags=["alegra"])


@router.get("/cuentas")
async def list_cuentas(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return all usable Alegra accounts from GET /categories. ROG-4 compliant."""
    alegra = AlegraClient(db=db)

    try:
        categories = await alegra.get("categories")
    except Exception as e:
        return {"success": False, "error": f"Error consultando Alegra: {str(e)}", "data": []}

    # Flatten tree, keep only movement (usable) accounts
    accounts = []
    _flatten_categories(categories, accounts)

    # Sort alphabetically
    accounts.sort(key=lambda a: a["nombre"])

    return {"success": True, "data": accounts, "count": len(accounts)}


def _flatten_categories(nodes, result: list, depth: int = 0):
    """Recursively flatten category tree into flat list of usable accounts."""
    if isinstance(nodes, dict):
        nodes = [nodes]
    for node in nodes:
        if not isinstance(node, dict):
            continue
        use = node.get("use", "")
        cat_id = str(node.get("id", ""))
        name = node.get("name", "")
        code = node.get("code", "")

        if use == "movement" and cat_id and name:
            result.append({
                "id": cat_id,
                "nombre": name,
                "codigo": code,
            })

        children = node.get("children", [])
        if children:
            _flatten_categories(children, result, depth + 1)
