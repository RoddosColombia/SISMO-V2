"""
AlegraItemsService — Read-only access to Alegra items (motos, repuestos).

ROG-4: Alegra is the source of truth for inventory. This service ONLY reads.
MongoDB is used ONLY for operational state (apartados, kit definitions).
"""
from services.alegra.client import AlegraClient


# Item category IDs from Alegra discovery (2026-04-14)
ITEM_CATEGORY_MOTOS_NUEVAS = "1"
ITEM_CATEGORY_MOTOS_USADAS = "2"
ITEM_CATEGORY_GPS = "3"
ITEM_CATEGORY_SEGURO = "4"

MOTO_CATEGORIES = {ITEM_CATEGORY_MOTOS_NUEVAS, ITEM_CATEGORY_MOTOS_USADAS}


class AlegraItemsService:
    """Read items from Alegra. Never writes."""

    def __init__(self, client: AlegraClient):
        self.client = client

    async def list_all_items(self) -> list[dict]:
        """Fetch all items from Alegra with pagination."""
        all_items = []
        start = 0
        while True:
            page = await self.client.get("items", params={"limit": 30, "start": start})
            if not page or not isinstance(page, list):
                break
            all_items.extend([i for i in page if isinstance(i, dict)])
            if len(page) < 30:
                break
            start += 30
        return all_items

    async def list_motos(self) -> list[dict]:
        """Return only moto items (nuevas + usadas) with stock info."""
        items = await self.list_all_items()
        motos = []
        for item in items:
            if item.get("type") != "product":
                continue
            cat = item.get("itemCategory") or {}
            cat_id = str(cat.get("id", ""))
            if cat_id not in MOTO_CATEGORIES:
                continue
            motos.append(_format_moto(item))
        return motos

    async def list_repuestos(self) -> list[dict]:
        """Return non-moto product items (repuestos).
        Currently Alegra has no repuestos — returns empty until they're added."""
        items = await self.list_all_items()
        repuestos = []
        for item in items:
            if item.get("type") != "product":
                continue
            cat = item.get("itemCategory") or {}
            cat_id = str(cat.get("id", ""))
            if cat_id in MOTO_CATEGORIES:
                continue
            repuestos.append(_format_repuesto(item))
        return repuestos

    async def get_item(self, item_id: str) -> dict:
        """Fetch a single item from Alegra by ID."""
        return await self.client.get(f"items/{item_id}")

    async def get_item_stock(self, item_id: str) -> int:
        """Get available quantity for an item."""
        item = await self.get_item(item_id)
        inv = item.get("inventory") or {}
        return int(inv.get("availableQuantity", 0))


def _format_moto(item: dict) -> dict:
    """Normalize Alegra item to moto response format."""
    inv = item.get("inventory") or {}
    cat = item.get("itemCategory") or {}
    prices = item.get("price") or []
    price = prices[0].get("price", 0) if prices else 0

    return {
        "id_alegra": str(item.get("id", "")),
        "nombre": item.get("name", ""),
        "descripcion": item.get("description") or "",
        "referencia": item.get("reference") or "",
        "categoria": cat.get("name", ""),
        "stock": int(inv.get("availableQuantity", 0)),
        "precio": price,
        "costo_unitario": inv.get("unitCost", 0),
        "estado": "Disponible",  # Will be overridden by apartado check
    }


def _format_repuesto(item: dict) -> dict:
    """Normalize Alegra item to repuesto response format."""
    inv = item.get("inventory") or {}
    cat = item.get("itemCategory") or {}
    prices = item.get("price") or []
    price = prices[0].get("price", 0) if prices else 0

    return {
        "id_alegra": str(item.get("id", "")),
        "nombre": item.get("name", ""),
        "codigo": item.get("reference") or "",
        "stock_actual": int(inv.get("availableQuantity", 0)),
        "precio": price,
        "categoria": cat.get("name", ""),
        "alerta_stock_bajo": int(inv.get("availableQuantity", 0)) <= 3,
    }
