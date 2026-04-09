"""
Wave 6 — 2 cartera handlers + 1 catalogo handler.

REGLAS:
- Cartera reads from MongoDB loanbook (operational data, allowed)
- Pago cuota: POST /payments + POST /journals (dual operation, same as Wave 4)
- Catalogo: returns embedded catalog from tools.py description (no API call)
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


async def handle_registrar_pago_cuota(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """POST /payments contra factura del loanbook + update cuota estado. (INGR-01)"""
    validate_write_permission("contador", "POST /payments", "alegra")

    loanbook_id = tool_input["loanbook_id"]
    monto = tool_input["monto"]
    banco = tool_input["banco"]
    numero_cuota = tool_input.get("numero_cuota", "?")
    fecha = tool_input.get("fecha") or datetime.date.today().isoformat()
    banco_id = BANCO_IDS.get(banco, 111005)

    loanbook = await db.loanbook.find_one({"loanbook_id": loanbook_id})
    if not loanbook:
        return {"success": False, "error": f"Loanbook {loanbook_id} no encontrado"}
    invoice_id = loanbook.get("factura_alegra_id")
    if not invoice_id:
        return {"success": False, "error": f"Loanbook {loanbook_id} sin factura Alegra vinculada"}

    payment_payload = {
        "date": fecha,
        "bankAccount": {"id": banco_id},
        "invoiceId": invoice_id,
        "amount": monto,
        "observations": f"Pago cuota {numero_cuota} — {loanbook_id}",
    }
    result = await alegra.request_with_verify("payments", "POST", payload=payment_payload)

    # Update cuota in loanbook (operational, allowed)
    await db.loanbook.update_one(
        {"loanbook_id": loanbook_id, f"cuotas.{numero_cuota}.estado": {"$ne": "pagada"}},
        {"$set": {f"cuotas.{numero_cuota}.estado": "pagada", f"cuotas.{numero_cuota}.fecha_pago": fecha}},
    )

    await publish_event(
        db=db,
        event_type="pago.cuota.registrado",
        source="agente_contador",
        datos={"loanbook_id": loanbook_id, "cuota": numero_cuota, "monto": monto, "payment_id": result["_alegra_id"]},
        alegra_id=result["_alegra_id"],
        accion_ejecutada=f"Pago cuota {numero_cuota} {loanbook_id} — ${monto:,.0f}",
    )

    return {
        "success": True,
        "alegra_id": result["_alegra_id"],
        "message": f"Pago cuota {numero_cuota} registrado. Payment #{result['_alegra_id']}. Loanbook: {loanbook_id}",
    }


async def handle_consultar_cartera(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Read-only: loanbook portfolio from MongoDB (operational data)."""
    try:
        filtro = {}
        estado = tool_input.get("filtro_estado")
        if estado:
            filtro["estado"] = estado

        cursor = db.loanbook.find(filtro).sort("fecha_creacion", -1).limit(50)
        loanbooks = await cursor.to_list(length=50)

        for lb in loanbooks:
            lb.pop("_id", None)

        return {"success": True, "data": loanbooks, "count": len(loanbooks)}
    except Exception as e:
        return {"success": False, "error": f"Error consultando cartera: {str(e)}"}


async def handle_consultar_catalogo_roddos(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Returns embedded RODDOS catalog. No API call — catalog is in tools.py description."""
    return {
        "success": True,
        "data": {
            "gastos": {
                5462: "Sueldos 510506", 5470: "Honorarios", 5471: "Seguridad Social",
                5472: "Dotaciones", 5480: "Arrendamientos 512010", 5484: "Servicios Públicos",
                5487: "Teléfono/Internet 513535", 5490: "Mantenimiento", 5491: "Transporte",
                5493: "Gastos Generales (FALLBACK)", 5497: "Útiles Papelería 519530",
                5500: "Publicidad", 5501: "Eventos", 5505: "ICA",
                5508: "Comisiones Bancarias 530515", 5510: "Seguros", 5533: "Intereses 615020",
            },
            "retenciones": {236505: "ReteFuente practicada", 236560: "ReteICA practicada"},
            "bancos": {111005: "Bancolombia", 111010: "BBVA", 111015: "Davivienda", 111020: "Banco de Bogotá", 11100507: "Global66"},
            "tasas_2026": {
                "arriendo": "3.5%", "servicios": "4%", "honorarios_pn": "10%",
                "honorarios_pj": "11%", "compras": "2.5% (base >$1.344.573)", "reteica": "0.414%",
            },
            "autoretenedores": ["860024781 (Auteco)"],
            "socios": {"80075452": "Andrés Sanjuan", "80086601": "Iván Echeverri"},
            "nota": "NUNCA usar ID 5495. IVA cuatrimestral (ene-abr/may-ago/sep-dic).",
        },
        "message": "Catálogo de cuentas RODDOS cargado.",
    }
