"""
CRM DataKeeper handler — syncs clients from loanbook events.

When a loanbook is created (loanbook.creado), this handler:
- Creates the client in crm_clientes if they don't exist
- Adds the loanbook_id to the client's loanbooks array
"""
import logging
from datetime import date
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.event_handlers import on_event
from core.crm_model import crear_cliente_doc

logger = logging.getLogger("datakeeper.crm")


@on_event("loanbook.creado", critical=True)
async def handle_loanbook_creado(event: dict, db: AsyncIOMotorDatabase):
    """
    Sync CRM client when a loanbook is created.
    Upsert: create if not exists, add loanbook_id if exists.
    """
    datos = event["datos"]
    loanbook_id = datos["loanbook_id"]
    cliente_data = datos["cliente"]
    cedula = cliente_data["cedula"]

    # Check if client exists
    existing = await db.crm_clientes.find_one({"cedula": cedula})

    if existing:
        # Add loanbook to existing client
        await db.crm_clientes.update_one(
            {"cedula": cedula},
            {
                "$addToSet": {"loanbooks": loanbook_id},
                "$set": {"updated_at": date.today().isoformat()},
            },
        )
        logger.info(f"CRM: Added loanbook {loanbook_id} to client {cedula}")
    else:
        # Create new client
        doc = crear_cliente_doc(
            cedula=cedula,
            nombre=cliente_data.get("nombre", ""),
            telefono=cliente_data.get("telefono", ""),
            email=cliente_data.get("email", ""),
            direccion=cliente_data.get("direccion", ""),
        )
        doc["loanbooks"] = [loanbook_id]
        await db.crm_clientes.insert_one(doc)
        logger.info(f"CRM: Created client {cedula} with loanbook {loanbook_id}")
