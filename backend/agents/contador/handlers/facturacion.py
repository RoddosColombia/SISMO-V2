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
import logging
from core.datetime_utils import now_bogota, today_bogota, now_iso_bogota

logger = logging.getLogger("handlers.facturacion")
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

# ── Catálogo de precios canónicos RODDOS (27-abril-2026) ──────────────────
# Alegra recibe precio SIN IVA. Regla: base = precio_cliente / 1.19
# NUNCA adivinar ni cambiar estos valores. Fuente: Andrés Sanjuan CEO.
PRECIOS_MOTO_BASE_ALEGRA = {
    "raider": 6_554_621.85,   # Raider 125: cliente $7.800.000
    "sport":  4_831_932.77,   # Sport 100:  cliente $5.750.000
}
SOAT_PRECIO      = 363_300   # exento IVA — va tal cual a Alegra
MATRICULA_PRECIO = 296_700   # exento IVA — va tal cual a Alegra
GPS_BASE_ALEGRA  = 69_580    # sin IVA — Alegra agrega 19% → total cliente $82.800


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
            precio_moto = moto.get("precio") if moto else None
        if not precio_moto:
            # Fallback catálogo canónico — NUNCA adivinar precios
            modelo_lower = modelo.lower()
            if "raider" in modelo_lower or "125" in modelo_lower:
                precio_moto = 7_800_000
            else:
                precio_moto = 5_750_000
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
        # gps_val viene como precio SIN IVA ($69.580) — Alegra agrega el 19%
        items.append({
            "id": ALEGRA_ITEM_GPS,
            "price": float(gps_val),
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


async def handle_consultar_cuentas_inventario(
    tool_input: dict,
    **kwargs,
) -> dict:
    """
    Retorna las cuentas contables canónicas de RODDOS para ítems en Alegra.
    Verificadas el 27-abril-2026 directamente en Alegra.
    Read-only — no llama a Alegra ni a MongoDB.
    """
    tipo = tool_input.get("tipo_item", "motos")

    if tipo == "motos":
        return {
            "tipo": "motos",
            "category_id": 1,
            "cuentas": {
                "account":          {"id": "41350501", "nombre": "Ingresos ventas motos"},
                "inventoryAccount": {"id": "14350101", "nombre": "Inventario motos (activo)"},
                "costsAccount":     {"id": "61350501", "nombre": "Costo de ventas motos"},
            },
            "payload_alegra": {
                "account":          {"id": "41350501"},
                "inventoryAccount": {"id": "14350101"},
                "costsAccount":     {"id": "61350501"},
            },
            "nota": "Incluir en POST /items junto con category:{id:1}. Sin estas cuentas Alegra rechaza con code 1008.",
        }
    else:  # repuestos
        return {
            "tipo": "repuestos",
            "category_id": 5,
            "cuentas": {
                "account":          {"id": "41350601", "nombre": "Ingresos ventas repuestos"},
                "inventoryAccount": {"id": "14350102", "nombre": "Inventario repuestos (activo)"},
                "costsAccount":     {"id": "61350601", "nombre": "Costo de ventas repuestos"},
            },
            "payload_alegra": {
                "account":          {"id": "41350601"},
                "inventoryAccount": {"id": "14350102"},
                "costsAccount":     {"id": "61350601"},
            },
            "nota": "Incluir en POST /items junto con category:{id:5}. Sin estas cuentas Alegra rechaza con code 1008.",
        }


# Precio base Alegra por modelo (sin IVA — Alegra agrega 19% automáticamente)
# Fuente: catálogo canónico RODDOS 27-abril-2026
_PRECIO_BASE_ALEGRA = {
    "TVS Raider 125": 6_554_622,
    "TVS Sport 100":  4_831_933,
}


async def handle_registrar_compra_motos(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Registra un lote de motos en Alegra.

    1. Crea un ítem individual por VIN (idempotente — omite si ya existe).
    2. Registra factura de compra (bill) al proveedor.
    3. Publica evento compra.motos.registrada para que el Datakeeper actualice MongoDB.
    ROG-4: solo escribe en Alegra + publica evento. MongoDB lo actualiza el Datakeeper.
    """
    # validate_write_permission NO va aquí — items/bills tienen Firecrawl como fallback.
    # Si validate lanzara PermissionError antes del try/except, el fallback sería inalcanzable.
    # Los permisos POST /items y POST /bills están declarados en permissions.py.

    motos         = tool_input["motos"]
    proveedor_nit = tool_input["proveedor_nit"]
    proveedor_nom = tool_input.get("proveedor_nombre", "Auteco Mobility S.A.S.")
    num_factura   = tool_input["numero_factura"]
    fecha         = tool_input["fecha"]

    creados:  list[dict] = []
    omitidos: list[dict] = []
    errores:  list[dict] = []

    # ── 1. Crear ítem individual por VIN ─────────────────────────────────
    for moto in motos:
        vin    = (moto.get("vin") or "").strip().upper()
        motor  = (moto.get("motor") or "").strip()
        modelo = moto.get("modelo", "TVS Raider 125")
        color  = moto.get("color", "")
        costo  = moto.get("precio_costo") or _PRECIO_BASE_ALEGRA.get(modelo, 6_554_622)

        if not vin or not motor:
            errores.append({"vin": vin, "error": "VIN y motor son obligatorios"})
            continue

        # Idempotente: verificar si ya existe por reference=VIN
        try:
            existentes = await alegra.get("items", params={"reference": vin, "limit": 1})
            if isinstance(existentes, list) and existentes:
                omitidos.append({
                    "vin":       vin,
                    "alegra_id": str(existentes[0].get("id", "")),
                    "razon":     "ya existía",
                })
                continue
        except Exception:
            pass  # Si el GET falla, intentar crear igual

        nombre_item = (
            f"{modelo} {color} - VIN: {vin} / Motor: {motor}".strip()
            if color
            else f"{modelo} - VIN: {vin} / Motor: {motor}"
        )
        precio_base = _PRECIO_BASE_ALEGRA.get(modelo, 6_554_622)

        payload: dict = {
            "name":        nombre_item,
            "reference":   vin,
            "description": f"{modelo} {color}".strip(),
            "price":       [{"idPriceList": 1, "price": precio_base}],
            "category":          {"id": 1},
            # Cuentas contables OBLIGATORIAS — sin ellas Alegra rechaza con code 1008
            "account":          {"id": "41350501"},  # Ingresos ventas motos
            "inventoryAccount": {"id": "14350101"},  # Inventario motos (activo)
            "costsAccount":     {"id": "61350501"},  # Costo de ventas motos
            "inventory": {
                "unit":            "unidad",
                "unitCost":        costo,
                "negativeSale":    False,
                "isInventoriable": True,
                "initialQuantity": 1,
                "minQuantity":     0,
            },
            "tax": [{"id": str(ALEGRA_IVA_TAX_ID)}],
        }

        try:
            result    = await alegra.request_with_verify("items", "POST", payload=payload)
            alegra_id = str(result.get("id") or result.get("_alegra_id") or "")
            creados.append({
                "vin":       vin,
                "motor":     motor,
                "modelo":    modelo,
                "color":     color,
                "alegra_id": alegra_id,
                "nombre":    nombre_item,
            })
        except Exception as ex:
            # Fallback Firecrawl si API REST falla (Alegra bloquea agentes IA en POST /items)
            logger.warning(f"API REST falló para VIN {vin}: {ex}. Intentando via Firecrawl...")
            try:
                from services.firecrawl.alegra_browser import get_alegra_browser
                browser = get_alegra_browser()
                fc_result = await browser.crear_item_moto(
                    nombre=nombre_item,
                    vin=vin,
                    precio_base=precio_base,
                    precio_costo=float(costo),
                )
                if fc_result.get("success"):
                    creados.append({
                        "vin":       vin,
                        "motor":     motor,
                        "modelo":    modelo,
                        "color":     color,
                        "alegra_id": "firecrawl",
                        "nombre":    nombre_item,
                        "via":       "firecrawl",
                    })
                else:
                    errores.append({"vin": vin, "error": f"API: {ex} | Firecrawl: {fc_result.get('error')}"})
            except Exception as fc_ex:
                errores.append({"vin": vin, "error": f"API: {ex} | Firecrawl exc: {fc_ex}"})

    # ── 2. Registrar bill (factura de compra) al proveedor ───────────────
    bill_id: str | None = None
    if creados:
        bill_items: list[dict] = []
        for m in creados:
            moto_src = next((x for x in motos if x.get("vin", "").upper() == m["vin"]), {})
            precio_costo = moto_src.get("precio_costo") or _PRECIO_BASE_ALEGRA.get(m["modelo"], 6_554_622)
            bill_items.append({
                "id":       int(m["alegra_id"]) if m["alegra_id"].isdigit() else m["alegra_id"],
                "quantity": 1,
                "price":    precio_costo,
            })

        bill_payload: dict = {
            "date":         fecha,
            "dueDate":      fecha,
            "provider":     {"identification": proveedor_nit},
            "observations": f"Compra lote motos — Factura proveedor {num_factura}",
            "items":        bill_items,
        }
        try:
            bill_result = await alegra.request_with_verify("bills", "POST", payload=bill_payload)
            bill_id     = str(bill_result.get("id") or bill_result.get("_alegra_id") or "")
        except Exception as ex:
            # Fallback Firecrawl si API REST falla en POST /bills
            logger.warning(f"Bill API REST falló: {ex}. Intentando via Firecrawl...")
            try:
                from services.firecrawl.alegra_browser import get_alegra_browser
                from datetime import timedelta
                browser = get_alegra_browser()
                items_para_bill = [
                    {
                        "nombre":   m["nombre"],
                        "cantidad": 1,
                        "precio":   _PRECIO_BASE_ALEGRA.get(m["modelo"], 6_554_622),
                    }
                    for m in creados
                ]
                fc_bill = await browser.registrar_bill(
                    proveedor_nit=proveedor_nit,
                    numero_factura=num_factura,
                    fecha=fecha,
                    fecha_vencimiento=(
                        datetime.datetime.strptime(fecha, "%Y-%m-%d") + timedelta(days=90)
                    ).strftime("%Y-%m-%d"),
                    items_para_bill=items_para_bill,
                    observations=f"Compra motos factura {num_factura}",
                )
                if fc_bill.get("success"):
                    bill_id = f"firecrawl:{fc_bill.get('firecrawl_output', '')[:50]}"
                else:
                    bill_id = f"ERROR: {ex} | Firecrawl: {fc_bill.get('error')}"
            except Exception as fc_ex:
                bill_id = f"ERROR: {ex} | Firecrawl exc: {fc_ex}"

    # ── 3. Publicar evento para que el Datakeeper actualice MongoDB ───────
    await publish_event(
        db=db,
        event_type="compra.motos.registrada",
        source="agente_contador",
        datos={
            "motos_creadas":  creados,
            "motos_omitidas": omitidos,
            "motos_error":    errores,
            "proveedor_nit":  proveedor_nit,
            "numero_factura": num_factura,
            "fecha":          fecha,
            "bill_alegra_id": bill_id,
        },
        alegra_id=bill_id,
        accion_ejecutada=f"Lote {len(creados)} motos registradas — bill {bill_id}",
    )

    bill_ok = bill_id and "ERROR" not in str(bill_id)
    return {
        "success":          len(errores) == 0,
        "creadas":          len(creados),
        "omitidas":         len(omitidos),
        "errores":          len(errores),
        "bill_alegra_id":   bill_id,
        "detalle_creadas":  creados,
        "detalle_omitidas": omitidos,
        "detalle_errores":  errores,
        "mensaje": (
            f"{len(creados)} motos registradas en Alegra. "
            + (f"{len(omitidos)} ya existían (omitidas). " if omitidos else "")
            + (f"Bill {bill_id} creado. " if bill_ok else "")
            + (f"{len(errores)} errores." if errores else "Listas para facturar.")
        ),
    }


async def handle_crear_item_inventario(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Crea un ítem (moto o repuesto) en Alegra via POST /items.

    Si ya existe (mismo reference), retorna el existente sin duplicar.
    Categorías: 1=Motos nuevas, 2=Motos usadas, 5=Repuestos.
    ROG-4 compliant: solo escribe en Alegra.
    """
    # validate_write_permission NO va aquí — Firecrawl fallback debe ser alcanzable.
    # El permiso POST /items está declarado en permissions.py.

    nombre = tool_input["nombre"]
    reference = tool_input["reference"]
    category_id = tool_input["category_id"]
    precio_venta = tool_input["precio_venta"]
    precio_costo = tool_input.get("precio_costo", 0)
    descripcion = tool_input.get("descripcion", "")
    unidad = tool_input.get("unidad", "unidad")
    iva_pct = tool_input.get("iva_pct", 0)
    inventariable = tool_input.get("inventariable", True)

    # 1. Verificar si ya existe por reference — evita duplicados
    try:
        existentes = await alegra.get("items", params={"reference": reference, "limit": 1})
        if isinstance(existentes, list) and existentes:
            item = existentes[0]
            return {
                "success": True,
                "ya_existia": True,
                "alegra_id": str(item.get("id", "")),
                "nombre": item.get("name", nombre),
                "reference": reference,
                "mensaje": f"Ítem '{nombre}' ya existe en Alegra con ID {item.get('id')}. Sin cambios.",
            }
    except Exception:
        pass  # Si el GET falla, intentar crear igual

    # 2. Construir payload Alegra
    # motos llegan con qty inicial = 1; repuestos arrancan en 0
    initial_qty = 1 if category_id in (1, 2) else 0

    # Cuentas contables canónicas RODDOS (verificadas 27-abril-2026)
    # OBLIGATORIAS — sin ellas Alegra rechaza con code 1008
    if category_id in (1, 2):  # Motos nuevas / usadas
        account_id          = "41350501"  # Ingresos ventas motos
        inventory_account_id = "14350101"  # Inventario motos (activo)
        costs_account_id    = "61350501"  # Costo de ventas motos
    else:  # Repuestos (category_id = 5)
        account_id          = "41350601"  # Ingresos ventas repuestos
        inventory_account_id = "14350102"  # Inventario repuestos (activo)
        costs_account_id    = "61350601"  # Costo de ventas repuestos

    payload: dict = {
        "name": nombre,
        "reference": reference,
        "description": descripcion,
        "price": [{"idPriceList": 1, "price": precio_venta}],
        "category":          {"id": category_id},
        "account":           {"id": account_id},
        "inventoryAccount":  {"id": inventory_account_id},
        "costsAccount":      {"id": costs_account_id},
        "inventory": {
            "unit": unidad,
            "unitCost": precio_costo,
            "negativeSale": False,
            "isInventoriable": inventariable,
            "initialQuantity": initial_qty,
            "minQuantity": 0,
        },
        # IVA 19% tax ID en Alegra = 3; si iva_pct != 19 → sin impuesto
        "tax": [{"id": "3"}] if iva_pct == 19 else [],
    }

    # 3. Crear en Alegra con verificación — Firecrawl como fallback si API bloquea
    try:
        result = await alegra.request_with_verify("items", "POST", payload=payload)
        alegra_id = str(result.get("id") or result.get("_alegra_id") or "")
        via = "api"
    except Exception as ex:
        logger.warning(f"API REST falló para ítem '{nombre}': {ex}. Intentando via Firecrawl...")
        try:
            from services.firecrawl.alegra_browser import get_alegra_browser
            browser = get_alegra_browser()
            # Motos (category 1/2) → crear_item_moto; repuestos → crear_item_repuesto
            if category_id in (1, 2):
                fc_result = await browser.crear_item_moto(
                    nombre=nombre,
                    vin=reference,
                    precio_base=float(precio_venta),
                    precio_costo=float(precio_costo),
                )
            else:
                fc_result = await browser.crear_item_repuesto(
                    nombre=nombre,
                    referencia=reference,
                    precio=float(precio_venta),
                    costo=float(precio_costo),
                )
            if not fc_result.get("success"):
                return {
                    "success": False,
                    "error": f"API: {ex} | Firecrawl: {fc_result.get('error')}",
                }
            alegra_id = "firecrawl"
            via = "firecrawl"
        except Exception as fc_ex:
            return {"success": False, "error": f"API: {ex} | Firecrawl exc: {fc_ex}"}

    return {
        "success": True,
        "ya_existia": False,
        "alegra_id": alegra_id,
        "nombre": nombre,
        "reference": reference,
        "category_id": category_id,
        "precio_venta": precio_venta,
        "via": via,
        "mensaje": (
            f"Ítem '{nombre}' creado en Alegra (ID {alegra_id}, via {via}). "
            f"Reference: {reference}. "
            f"{'Listo para facturar.' if category_id in (1, 2) else 'Disponible en inventario Alegra.'}"
        ),
    }
