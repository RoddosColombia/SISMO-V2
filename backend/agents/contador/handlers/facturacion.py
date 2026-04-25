"""
Wave 5 — 4 facturacion handlers.

REGLAS:
- VIN y motor OBLIGATORIOS en factura de venta moto — sin ellos NO facturar
- Formato item: "[Modelo] [Color] - VIN: [chasis] / Motor: [motor]"
- Moto debe estar en estado "disponible" — bloqueo total si no
- Contador SOLO escribe en Alegra + publica eventos (ROG-4 reforzada)
- DataKeeper/Loanbook listeners manejan cascadas MongoDB via eventos
- CERO escrituras directas a inventario_motos o loanbook desde Contador
"""
import datetime
from core.datetime_utils import now_bogota, today_bogota, now_iso_bogota
from typing import Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from services.alegra.client import AlegraClient
from core.permissions import validate_write_permission
from core.events import publish_event

# Alegra category IDs for journal entries
BANCO_CATEGORY_IDS = {
    "Bancolombia": "5314", "Bancolombia 2029": "5314", "Bancolombia 2540": "5315",
    "BBVA": "5318", "BBVA 0210": "5318", "BBVA 0212": "5319",
    "Davivienda": "5322",
    "Banco de Bogotá": "5321", "Banco de Bogota": "5321", "Bogota": "5321",
    "Global66": "5536",
}


# Plan → (num_cuotas_base, cuota_default_COP) — referencia para tests/UI.
# Los valores reales vienen del tool_input; estos son fallbacks.
PLAN_CUOTAS_BASE = {"P15S": 15, "P26S": 26, "P39S": 39, "P52S": 52, "P78S": 78}
MODALIDAD_DIAS = {"semanal": 7, "quincenal": 14, "mensual": 28}

# Alegra item IDs reales para rubros adicionales (vía config de items, verificado 2026-04-17)
ALEGRA_ITEM_SOAT = 30       # category=5452 Soat (exento IVA)
ALEGRA_ITEM_MATRICULA = 29  # category=5453 Matricula (exento)
ALEGRA_ITEM_GPS = 28        # category=5448 Instalacion GPS (IVA 19%)
ALEGRA_IVA_TAX_ID = 4       # IVA 19%


async def _resolve_alegra_contact(alegra: AlegraClient, cedula: str, nombre: str,
                                  telefono: str, direccion: str) -> str | int | None:
    """Return Alegra contact id for a cedula; create if missing.
    Returns None on failure (caller falls back to inline client dict)."""
    try:
        contacts = await alegra.get("contacts", params={"identification": cedula, "limit": 5})
        if isinstance(contacts, list):
            for c in contacts:
                if isinstance(c, dict) and str(c.get("identification", "")) == str(cedula):
                    return c.get("id")
        # Not found — create
        first, *rest = (nombre or "").strip().split(" ", 1)
        payload = {
            "nameObject": {"firstName": first or nombre, "lastName": rest[0] if rest else ""},
            "name": nombre,
            "identification": cedula,
            "identificationObject": {"type": "CC", "number": cedula},
            "kindOfPerson": "PERSON_ENTITY",
            "regime": "SIMPLIFIED_REGIME",
            "type": ["client"],
        }
        if telefono:
            payload["phonePrimary"] = telefono
        if direccion:
            payload["address"] = {"address": direccion, "department": "Bogota D.C.", "city": "Bogota, D.C."}
        created = await alegra.request_with_verify("contacts", "POST", payload=payload)
        return created.get("id") or created.get("_alegra_id")
    except Exception:
        return None


async def handle_crear_factura_venta_moto(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Crea factura venta moto en Alegra. ROG-4 compliant: solo escribe Alegra +
    publica evento factura.venta.creada. Los listeners (loanbook, crm) hacen la
    cascada a MongoDB.

    Soporta:
      - Rubros adicionales SOAT / matrícula / GPS (items Alegra con cuenta propia)
      - modo_promocion=true → cuota_inicial=0 permitido
      - Fallback Alegra si la moto no está en inventario_motos (inventario canónico)
    """
    validate_write_permission("contador", "POST /invoices", "alegra")

    cliente_nombre = tool_input.get("cliente_nombre", "")
    cliente_cedula = tool_input.get("cliente_cedula", "")
    cliente_telefono = tool_input.get("cliente_telefono", "")
    cliente_direccion = tool_input.get("cliente_direccion", "")
    moto_vin = (tool_input.get("moto_vin") or "").strip()
    plan = tool_input.get("plan", "P52S")
    modo_pago = tool_input.get("modo_pago", "semanal")
    cuota_inicial = tool_input.get("cuota_inicial")
    cuota_valor = tool_input.get("cuota_valor")
    num_cuotas = tool_input.get("num_cuotas") or PLAN_CUOTAS_BASE.get(plan)
    modo_promocion = bool(tool_input.get("modo_promocion", False))
    precio_moto = tool_input.get("precio_moto")
    rubros = tool_input.get("rubros_adicionales") or {}
    fecha = tool_input.get("fecha") or today_bogota().isoformat()

    if not moto_vin:
        return {"success": False, "error": "VIN (chasis) es OBLIGATORIO para facturar. No se puede crear factura sin VIN."}

    # cuota_inicial: opcional (default 0). Si es 0 y no hay modo_promocion el
    # operador debe asumir la responsabilidad operativa — no bloqueamos aquí.
    if cuota_inicial is None:
        cuota_inicial = 0

    # Inventario: primero MongoDB (fuente operativa con color/motor), luego Alegra fallback
    moto = await db.inventario_motos.find_one({"vin": moto_vin})
    motor = ""
    modelo = ""
    color = ""
    moto_item_id = None

    if moto:
        motor = (moto.get("motor") or "").strip()
        modelo = moto.get("modelo", "TVS")
        color = moto.get("color", "")
        if not motor:
            return {"success": False, "error": f"Moto VIN {moto_vin} no tiene número de motor registrado. OBLIGATORIO para facturar."}
        if moto.get("estado", "").lower() != "disponible":
            return {"success": False, "error": f"Moto VIN {moto_vin} no está disponible (estado: {moto.get('estado')}). Solo se facturan motos disponibles."}
        moto_item_id = moto.get("alegra_item_id")
        if precio_moto is None:
            precio_moto = moto.get("precio", 0)
    else:
        # Fallback: inventario canónico es Alegra. Requerimos motor explícito en el input
        motor = (tool_input.get("moto_motor") or "").strip()
        modelo = tool_input.get("moto_modelo", "TVS Sport 100")
        color = tool_input.get("moto_color", "")
        if not motor:
            return {"success": False, "error": (
                f"Moto VIN {moto_vin} no está en inventario_motos (MongoDB) y no se pasó moto_motor en el input. "
                "Envía moto_motor + moto_modelo cuando el inventario canónico sea Alegra."
            )}

    # Build items — la moto siempre es la primera línea
    items: list[dict] = []
    item_desc = f"{modelo} {color} - VIN: {moto_vin} / Motor: {motor}".strip()
    moto_line: dict[str, Any] = {"name": item_desc, "quantity": 1, "tax": [{"id": ALEGRA_IVA_TAX_ID}]}
    if moto_item_id:
        moto_line["id"] = moto_item_id
    if precio_moto is not None:
        # POST /invoices acepta price con IVA ya descontado si type='price' o total. Pasamos base sin IVA:
        # Si el precio que llega es con IVA (precio_moto), base = precio / 1.19
        moto_line["price"] = round(float(precio_moto) / 1.19, 2)
    items.append(moto_line)

    # Rubros adicionales (si vienen) como líneas separadas con IDs Alegra reales
    soat_val = rubros.get("soat") if isinstance(rubros, dict) else None
    matricula_val = rubros.get("matricula") if isinstance(rubros, dict) else None
    gps_val = rubros.get("gps") if isinstance(rubros, dict) else None

    if soat_val and soat_val > 0:
        items.append({"id": ALEGRA_ITEM_SOAT, "price": float(soat_val), "quantity": 1})
    if matricula_val and matricula_val > 0:
        items.append({"id": ALEGRA_ITEM_MATRICULA, "price": float(matricula_val), "quantity": 1})
    if gps_val and gps_val > 0:
        # GPS viene con IVA incluido — base = valor / 1.19
        items.append({
            "id": ALEGRA_ITEM_GPS,
            "price": round(float(gps_val) / 1.19, 2),
            "quantity": 1,
            "tax": [{"id": ALEGRA_IVA_TAX_ID}],
        })

    # Resolve Alegra contact — permite POST /invoices con client.id (limpia numeración DIAN)
    contact_id = await _resolve_alegra_contact(
        alegra=alegra, cedula=cliente_cedula, nombre=cliente_nombre,
        telefono=cliente_telefono, direccion=cliente_direccion,
    )

    client_block: dict[str, Any] = {"name": cliente_nombre, "identification": cliente_cedula}
    if contact_id:
        client_block = {"id": contact_id}

    promo_note = " (PROMO sin cuota inicial)" if modo_promocion else ""
    anotation = (
        f"MOTO {modelo} {color}{promo_note}\n"
        f"VIN: {moto_vin}\nMOTOR: {motor}\n"
        f"Plan: {plan} {modo_pago}"
        + (f" — {num_cuotas} cuotas de ${cuota_valor:,.0f}" if cuota_valor else "")
    )
    observations = f"Venta moto {modelo} plan {plan} — VIN: {moto_vin}{promo_note}"

    invoice_payload = {
        "date": fecha,
        "client": client_block,
        "paymentForm": "CREDIT",
        "status": "open",
        "operationType": "STANDARD",
        "items": items,
        "anotation": anotation,
        "observations": observations,
    }

    result = await alegra.request_with_verify("invoices", "POST", payload=invoice_payload)
    factura_id = result.get("_alegra_id") or result.get("id")
    factura_number = (result.get("numberTemplate") or {}).get("fullNumber") if isinstance(result, dict) else None

    # Publish event — listeners handle loanbook + CRM cascades (ROG-4)
    valor_factura = (
        (precio_moto or 0)
        + (soat_val or 0)
        + (matricula_val or 0)
        + (gps_val or 0)
    )
    await publish_event(
        db=db,
        event_type="factura.venta.creada",
        source="agente_contador",
        datos={
            "factura_id": str(factura_id),
            "alegra_invoice_number": factura_number,
            "cliente_nombre": cliente_nombre,
            "cliente_cedula": cliente_cedula,
            "cliente_telefono": cliente_telefono,
            "cliente_direccion": cliente_direccion,
            "vin": moto_vin,
            "motor": motor,
            "modelo": modelo,
            "color": color,
            "plan": plan,
            "modalidad": modo_pago,
            "cuota_monto": cuota_valor,
            "num_cuotas": num_cuotas,
            "cuota_inicial": cuota_inicial,
            "modo_promocion": modo_promocion,
            "precio_moto": precio_moto,
            "rubros": {"soat": soat_val or 0, "matricula": matricula_val or 0, "gps": gps_val or 0},
            "valor_factura": valor_factura,
            "fecha": fecha,
        },
        alegra_id=str(factura_id) if factura_id else None,
        accion_ejecutada=f"Factura #{factura_id} — {item_desc}{promo_note}",
    )

    return {
        "success": True,
        "alegra_id": str(factura_id),
        "alegra_invoice_number": factura_number,
        "message": (
            f"Factura #{factura_number or factura_id} creada en Alegra. "
            f"{item_desc}. Plan {plan} {modo_pago}{promo_note}. "
            f"Total factura: ${valor_factura:,.0f}."
        ),
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

    # Publish event — DataKeeper/Loanbook listeners handle MongoDB reversals
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
        "date": tool_input.get("fecha") or today_bogota().isoformat(),
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
