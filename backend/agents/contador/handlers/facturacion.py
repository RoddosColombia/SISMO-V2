"""
Wave 5 — 4 facturacion handlers.

REGLAS:
- VIN y motor OBLIGATORIOS en factura de venta moto — sin ellos NO facturar
- Formato item: "[Modelo] [Color] - VIN: [chasis] / Motor: [motor]"
- Moto debe estar en estado "disponible" — bloqueo total si no
- Factura exitosa: inventario → Vendida, loanbook creado, evento publicado
- Anulacion: inventario → Disponible, loanbook → cancelado, evento publicado
- NUNCA escribir datos contables en MongoDB (ROG-4)
- Escrituras MongoDB PERMITIDAS: inventario_motos (operativo), loanbook (operativo)
"""
import datetime
from typing import Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from services.alegra.client import AlegraClient
from core.permissions import validate_write_permission
from core.events import publish_event

BANCO_IDS = {
    "Bancolombia": 111005, "BBVA": 111010, "Davivienda": 111015,
    "Banco de Bogotá": 111020, "Banco de Bogota": 111020, "Global66": 11100507,
}


async def handle_crear_factura_venta_moto(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """POST /invoices con VIN+motor obligatorios. Cascade: inventario+loanbook+event. (FACT-01, FACT-02, FACT-03)"""
    validate_write_permission("contador", "POST /invoices", "alegra")

    cliente_nombre = tool_input.get("cliente_nombre", "")
    cliente_cedula = tool_input.get("cliente_cedula", "")
    moto_vin = (tool_input.get("moto_vin") or "").strip()
    plan = tool_input.get("plan", "P52S")
    cuota_inicial = tool_input.get("cuota_inicial", 0)
    fecha = tool_input.get("fecha") or datetime.date.today().isoformat()

    # VIN mandatory check
    if not moto_vin:
        return {"success": False, "error": "VIN (chasis) es OBLIGATORIO para facturar. No se puede crear factura sin VIN."}

    # Look up moto in inventory (MongoDB operational data — allowed)
    moto = await db.inventario_motos.find_one({"vin": moto_vin})
    if not moto:
        return {"success": False, "error": f"Moto con VIN {moto_vin} no encontrada en inventario."}

    motor = (moto.get("motor") or "").strip()
    if not motor:
        return {"success": False, "error": f"Moto VIN {moto_vin} no tiene número de motor registrado. OBLIGATORIO para facturar."}

    if moto.get("estado", "").lower() != "disponible":
        return {"success": False, "error": f"Moto VIN {moto_vin} no está disponible (estado: {moto.get('estado')}). Solo se facturan motos disponibles."}

    modelo = moto.get("modelo", "TVS")
    color = moto.get("color", "")

    # Build item description in mandatory format
    item_desc = f"{modelo} {color} - VIN: {moto_vin} / Motor: {motor}"

    invoice_payload = {
        "date": fecha,
        "client": {"name": cliente_nombre, "identification": cliente_cedula},
        "items": [{"name": item_desc, "price": cuota_inicial or moto.get("precio", 0), "quantity": 1}],
        "observations": f"Venta moto {modelo} plan {plan} — VIN: {moto_vin}",
    }

    result = await alegra.request_with_verify("invoices", "POST", payload=invoice_payload)
    factura_id = result["_alegra_id"]

    # Cascade 1: Update inventory — moto → Vendida (operational write, allowed)
    await db.inventario_motos.update_one(
        {"vin": moto_vin},
        {"$set": {"estado": "Vendida", "fecha_venta": fecha, "factura_alegra_id": factura_id}},
    )

    # Cascade 2: Create loanbook (operational write, allowed)
    await db.loanbook.insert_one({
        "loanbook_id": f"LB-{factura_id}",
        "factura_alegra_id": factura_id,
        "cliente_nombre": cliente_nombre,
        "cliente_cedula": cliente_cedula,
        "moto_vin": moto_vin,
        "plan": plan,
        "cuota_inicial": cuota_inicial,
        "estado": "pendiente_entrega",
        "fecha_creacion": fecha,
    })

    # Cascade 3: Event
    await publish_event(
        db=db,
        event_type="factura.venta.creada",
        source="agente_contador",
        datos={"factura_id": factura_id, "cliente": cliente_nombre, "vin": moto_vin, "plan": plan},
        alegra_id=factura_id,
        accion_ejecutada=f"Factura #{factura_id} — {item_desc}",
    )

    return {
        "success": True,
        "alegra_id": factura_id,
        "message": f"Factura #{factura_id} creada en Alegra. {item_desc}. Plan {plan}.",
    }


async def handle_consultar_facturas(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """GET /invoices — read-only, no confirmation needed."""
    try:
        params = {}
        if tool_input.get("fecha_desde"):
            params["date_from"] = tool_input["fecha_desde"]
        if tool_input.get("fecha_hasta"):
            params["date_to"] = tool_input["fecha_hasta"]
        data = await alegra.get("invoices", params=params or None)
        return {"success": True, "data": data, "count": len(data) if isinstance(data, list) else 1}
    except Exception as e:
        return {"success": False, "error": f"Error consultando facturas: {str(e)}"}


async def handle_anular_factura(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Void invoice and reverse cascades (inventory + loanbook)."""
    validate_write_permission("contador", "POST /invoices", "alegra")

    invoice_id = tool_input["invoice_id"]
    motivo = tool_input.get("motivo", "Anulación de factura")

    # Void in Alegra
    try:
        result = await alegra.request_with_verify(f"invoices/{invoice_id}/void", "POST", payload={"observations": motivo})
    except Exception as e:
        return {"success": False, "error": f"Error anulando factura en Alegra: {str(e)}"}

    # Reverse cascade 1: inventory → Disponible
    await db.inventario_motos.update_one(
        {"factura_alegra_id": str(invoice_id)},
        {"$set": {"estado": "Disponible", "fecha_venta": None, "factura_alegra_id": None}},
    )

    # Reverse cascade 2: loanbook → cancelado
    await db.loanbook.update_one(
        {"factura_alegra_id": str(invoice_id)},
        {"$set": {"estado": "cancelado"}},
    )

    await publish_event(
        db=db,
        event_type="factura.venta.anulada",
        source="agente_contador",
        datos={"invoice_id": invoice_id, "motivo": motivo},
        alegra_id=str(invoice_id),
        accion_ejecutada=f"Factura #{invoice_id} anulada — {motivo}",
    )

    return {"success": True, "message": f"Factura #{invoice_id} anulada. Inventario y loanbook revertidos."}


async def handle_crear_nota_credito(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """POST /credit-notes."""
    validate_write_permission("contador", "POST /credit-notes", "alegra")

    payload = {
        "date": tool_input.get("fecha") or datetime.date.today().isoformat(),
        "invoiceId": tool_input.get("invoice_id"),
        "observations": tool_input.get("motivo", "Nota crédito"),
        "items": tool_input.get("items", []),
    }
    result = await alegra.request_with_verify("credit-notes", "POST", payload=payload)

    await publish_event(
        db=db,
        event_type="nota_credito.creada",
        source="agente_contador",
        datos={"alegra_id": result["_alegra_id"], "invoice_id": tool_input.get("invoice_id")},
        alegra_id=result["_alegra_id"],
        accion_ejecutada=f"Nota crédito #{result['_alegra_id']} creada",
    )

    return {
        "success": True,
        "alegra_id": result["_alegra_id"],
        "message": f"Nota crédito #{result['_alegra_id']} creada en Alegra.",
    }
