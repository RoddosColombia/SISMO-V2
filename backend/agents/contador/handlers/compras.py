"""
Wave 7 — Compras a proveedores (bills) + consulta inventario desde Alegra.

Tools:
  - registrar_compra_proveedor: POST /bills con items (auto-crea items inexistentes)
  - consultar_inventario_alegra: GET /items (stock real desde Alegra, no MongoDB)

ROG-4: Todo contable va a Alegra via request_with_verify().

Regla Auteco (NIT 860024781 o 901249413): AUTORETENEDOR — NUNCA aplicar ReteFuente.

Firecrawl fallback: si API REST falla en POST /items o POST /bills, usa Firecrawl /interact
para operar la UI de Alegra como un humano.
"""
import logging
from typing import Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from services.alegra.client import AlegraClient

logger = logging.getLogger("handlers.compras")

# NITs de proveedores autoretenedores (NUNCA ReteFuente)
AUTORETENEDORES_NIT = {"860024781", "901249413", "901-249-413-7", "901.249.413-7"}

# Fallback: Repuestos category id en Alegra (creada 2026-04-16)
REPUESTOS_CATEGORY_ID = "5"


def _normalize_nit(nit: str) -> str:
    """Strip dashes, dots, and spaces from NIT for comparison."""
    return (nit or "").replace("-", "").replace(".", "").replace(" ", "").strip()


def _is_autoretenedor(nit: str) -> bool:
    normalized = _normalize_nit(nit)
    return normalized in {_normalize_nit(n) for n in AUTORETENEDORES_NIT}


async def _find_or_create_item(alegra: AlegraClient, item: dict) -> str:
    """
    Buscar item por reference en Alegra. Si no existe, crearlo como inventariable.
    Returns: Alegra item id (string).
    """
    reference = item.get("referencia") or item.get("reference") or ""
    # Search by reference
    if reference:
        try:
            results = await alegra.get("items", params={"reference": reference, "limit": 30})
            if isinstance(results, list) and results:
                for r in results:
                    if isinstance(r, dict) and r.get("reference") == reference:
                        return str(r["id"])
        except Exception:
            pass  # Fall through to create

    # Create as inventariable product under Repuestos category
    nombre = item.get("nombre") or item.get("name") or "Repuesto sin nombre"
    precio_unit = float(item.get("precio_unit") or item.get("price") or 0)
    payload = {
        "name": nombre,
        "reference": reference,
        "type": "product",
        "itemCategory": {"id": REPUESTOS_CATEGORY_ID},
        "price": [{"price": precio_unit, "idPriceList": None}] if precio_unit else [],
        "inventory": {
            "unit": "unit",
            "unitCost": precio_unit,
            "initialQuantity": 0,
            "initialQuantityDate": item.get("fecha") or None,
        },
    }
    try:
        created = await alegra.request_with_verify(
            endpoint="items",
            method="POST",
            payload=payload,
        )
        return str(created.get("id") or created.get("_alegra_id"))
    except Exception as ex:
        # Fallback Firecrawl si API REST bloquea POST /items
        logger.warning(f"API REST falló creando ítem '{nombre}': {ex}. Intentando via Firecrawl...")
        try:
            from services.firecrawl.alegra_browser import get_alegra_browser
            browser = get_alegra_browser()
            fc_result = await browser.crear_item_repuesto(
                nombre=nombre,
                referencia=reference,
                precio=precio_unit,
                costo=precio_unit,
            )
            if fc_result.get("success"):
                return f"firecrawl:{reference}"
        except Exception as fc_ex:
            logger.error(f"Firecrawl también falló para ítem '{nombre}': {fc_ex}")
        raise  # re-raise original si Firecrawl también falla


async def handle_registrar_compra_proveedor(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """
    Registra factura de compra (bill) en Alegra.
    - Busca/crea items por referencia
    - Si proveedor es Auteco → AUTORETENEDOR (NUNCA ReteFuente)
    - Ejecuta via request_with_verify()
    """
    try:
        numero_factura = tool_input.get("numero_factura")
        proveedor_nombre = tool_input.get("proveedor_nombre")
        proveedor_nit = tool_input.get("proveedor_nit", "")
        items_input = tool_input.get("items") or []
        fecha = tool_input.get("fecha")

        if not numero_factura or not proveedor_nit or not items_input:
            return {
                "success": False,
                "error": "numero_factura, proveedor_nit e items son requeridos.",
            }

        autoretenedor = _is_autoretenedor(proveedor_nit)

        # Find/create items in Alegra
        bill_items = []
        for i, it in enumerate(items_input):
            cantidad = float(it.get("cantidad", 0))
            precio_unit = float(it.get("precio_unit", 0))
            iva_pct = float(it.get("iva_pct", 19))
            if cantidad <= 0 or precio_unit <= 0:
                return {
                    "success": False,
                    "error": f"item[{i}] requiere cantidad>0 y precio_unit>0.",
                }
            alegra_item_id = await _find_or_create_item(alegra, it)
            bill_items.append({
                "id": alegra_item_id,
                "quantity": cantidad,
                "price": precio_unit,
                "tax": [{"id": 4}] if iva_pct == 19 else [],  # IVA 19% = id 4
            })

        # Resolve Alegra contact id by NIT (create if missing)
        contact_id = await _resolve_contact_id(
            alegra=alegra,
            nit=proveedor_nit,
            nombre=proveedor_nombre,
            autoretenedor=autoretenedor,
        )

        observations = (
            f"[AC] Compra {'repuestos' if proveedor_nombre and 'auteco' in proveedor_nombre.lower() else 'mercancia'} "
            f"{proveedor_nombre or proveedor_nit} — Factura {numero_factura}"
        )

        payload = {
            "date": fecha,
            "dueDate": fecha,
            "provider": {"id": contact_id},
            "numberTemplate": {"number": numero_factura},
            "items": bill_items,
            "observations": observations,
        }

        if autoretenedor:
            payload["observations"] += " — PROVEEDOR AUTORETENEDOR (sin ReteFuente)"
            # Alegra's bill endpoint auto-applies retenciones based on contact config.
            # Contact must be flagged autoretenedor in Alegra for this to work.

        try:
            result = await alegra.request_with_verify(
                endpoint="bills",
                method="POST",
                payload=payload,
            )
            alegra_id = str(result.get("_alegra_id") or result.get("id", ""))
            via = "api"
        except Exception as bill_ex:
            # Fallback Firecrawl si API REST bloquea POST /bills
            logger.warning(f"Bill API REST falló para factura {numero_factura}: {bill_ex}. Intentando via Firecrawl...")
            try:
                from services.firecrawl.alegra_browser import get_alegra_browser
                browser = get_alegra_browser()
                items_fc = [
                    {
                        "nombre":   it.get("nombre") or it.get("name") or f"Ítem {idx}",
                        "cantidad": int(it.get("cantidad", 1)),
                        "precio":   float(it.get("precio_unit") or it.get("price") or 0),
                    }
                    for idx, it in enumerate(items_input)
                ]
                fc_bill = await browser.registrar_bill(
                    proveedor_nit=proveedor_nit,
                    numero_factura=numero_factura,
                    fecha=fecha,
                    fecha_vencimiento=fecha,
                    items_para_bill=items_fc,
                    observations=observations,
                )
                if fc_bill.get("success"):
                    alegra_id = f"firecrawl:{fc_bill.get('firecrawl_output', '')[:50]}"
                    via = "firecrawl"
                else:
                    return {
                        "success": False,
                        "error": f"API: {bill_ex} | Firecrawl: {fc_bill.get('error')}",
                    }
            except Exception as fc_ex:
                return {"success": False, "error": f"API: {bill_ex} | Firecrawl exc: {fc_ex}"}

        return {
            "success": True,
            "alegra_id": alegra_id,
            "autoretenedor": autoretenedor,
            "items_registrados": len(bill_items),
            "via": via,
            "message": f"Bill #{numero_factura} registrado en Alegra (ID {alegra_id}, via {via})",
        }
    except Exception as e:
        return {"success": False, "error": f"Error registrando compra: {str(e)}"}


async def _resolve_contact_id(
    alegra: AlegraClient,
    nit: str,
    nombre: str | None,
    autoretenedor: bool,
) -> str:
    """Find contact by NIT, create if missing. Returns contact id."""
    normalized_nit = _normalize_nit(nit)
    try:
        contacts = await alegra.get("contacts", params={"identification": normalized_nit, "limit": 30})
        if isinstance(contacts, list):
            for c in contacts:
                if isinstance(c, dict):
                    c_nit = _normalize_nit(str(c.get("identification", "")))
                    if c_nit == normalized_nit:
                        return str(c["id"])
    except Exception:
        pass  # fall through to create

    # Create contact
    payload = {
        "name": nombre or f"Proveedor {normalized_nit}",
        "identification": normalized_nit,
        "type": ["provider"],
    }
    created = await alegra.request_with_verify(
        endpoint="contacts",
        method="POST",
        payload=payload,
    )
    return str(created.get("id") or created.get("_alegra_id"))


async def handle_consultar_inventario_alegra(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """
    GET /items — stock actual desde Alegra (no MongoDB).
    Filtros opcionales: nombre, referencia, categoria_id.
    """
    try:
        params = {"limit": 30}
        if tool_input.get("nombre"):
            params["query"] = tool_input["nombre"]
        if tool_input.get("referencia"):
            params["reference"] = tool_input["referencia"]
        if tool_input.get("categoria_id"):
            params["itemCategoryId"] = tool_input["categoria_id"]

        data = await alegra.get("items", params=params)
        if not isinstance(data, list):
            return {"success": True, "data": [], "count": 0}

        # Summarize: drop inactive, return stock + name + ref
        summary = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if item.get("status") == "inactive":
                continue
            inv = item.get("inventory") or {}
            cat = item.get("itemCategory") or {}
            prices = item.get("price") or []
            price_val = prices[0].get("price", 0) if prices else 0
            summary.append({
                "id": str(item.get("id", "")),
                "nombre": item.get("name", ""),
                "referencia": item.get("reference") or "",
                "stock": int(inv.get("availableQuantity", 0) or 0),
                "precio": price_val,
                "costo": inv.get("unitCost", 0) or 0,
                "categoria": cat.get("name", ""),
                "alerta_stock_bajo": (inv.get("availableQuantity") or 0) <= 3,
            })

        return {
            "success": True,
            "data": summary,
            "count": len(summary),
        }
    except Exception as e:
        return {"success": False, "error": f"Error consultando inventario: {str(e)}"}
