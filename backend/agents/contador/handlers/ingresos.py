"""
Wave 4 — 4 ingresos + CXC handlers.

REGLAS:
- handle_registrar_ingreso_cuota ejecuta DOS operaciones Alegra (INGR-01):
    POST /payments PRIMERO -> POST /journals SEGUNDO
    Cuota pagada SOLO si AMBAS operaciones son verificadas HTTP 200.
- handle_registrar_cxc_socio NUNCA registra como gasto operativo (CXC-01).
- handle_consultar_cxc_socios es read-only, no escribe en MongoDB.
- NUNCA escribir datos contables en MongoDB (ROG-4).
"""
import datetime
from typing import Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from services.alegra.client import AlegraClient
from core.permissions import validate_write_permission
from core.events import publish_event

SOCIOS: dict[str, str] = {
    "80075452": "Andrés Sanjuan",
    "80086601": "Iván Echeverri",
}

CXC_SOCIOS_ALEGRA_ID = "5329"             # 132505 Cuentas por cobrar a socios
INGRESO_CREDITOS_RODDOS_ID = "5456"       # 41502001 Creditos Directos Roddos

# Alegra category IDs for journal entries
BANCO_CATEGORY_IDS: dict[str, str] = {
    "Bancolombia": "5314", "Bancolombia 2029": "5314", "Bancolombia 2540": "5315",
    "BBVA": "5318", "BBVA 0210": "5318", "BBVA 0212": "5319",
    "Davivienda": "5322",
    "Banco de Bogotá": "5321", "Banco de Bogota": "5321", "Bogota": "5321",
    "Global66": "5536",
}

# Alegra bank-account IDs for POST /payments
BANCO_PAYMENT_IDS: dict[str, int] = {
    "Bancolombia": 5, "Bancolombia 2029": 5, "Bancolombia 2540": 6,
    "BBVA": 7, "BBVA 0210": 7, "BBVA 0212": 10,
    "Davivienda": 3,
    "Banco de Bogotá": 5,  # Fallback Bancolombia (no bank-account for Bogota)
    "Banco de Bogota": 5,
    "Global66": 5,       # Fallback Bancolombia (no bank-account for Global66)
}


async def handle_registrar_ingreso_cuota(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """
    Dual-operation: POST /payments + POST /journals.
    Cuota marked pagada only if BOTH succeed. (INGR-01)
    """
    validate_write_permission("contador", "POST /payments", "alegra")
    validate_write_permission("contador", "POST /journals", "alegra")

    loanbook_id = tool_input["loanbook_id"]
    monto = tool_input["monto"]
    banco = tool_input["banco"]
    numero_cuota = tool_input.get("numero_cuota", "?")
    fecha = tool_input.get("fecha") or datetime.date.today().isoformat()
    banco_category_id = BANCO_CATEGORY_IDS.get(banco, "5314")
    banco_payment_id = BANCO_PAYMENT_IDS.get(banco, 5)

    # ROG-4 OK: lectura operativa Loanbook, no dato contable
    loanbook = await db.loanbook.find_one({"loanbook_id": loanbook_id})
    if not loanbook:
        return {"success": False, "error": f"Loanbook {loanbook_id} no encontrado"}
    invoice_alegra_id = loanbook.get("factura_alegra_id")
    if not invoice_alegra_id:
        return {"success": False, "error": f"Loanbook {loanbook_id} no tiene factura Alegra vinculada"}

    # Operation 1: POST /payments (uses bank-account ID, not category ID)
    try:
        payment_payload = {
            "date": fecha,
            "bankAccount": {"id": banco_payment_id},
            "invoiceId": invoice_alegra_id,
            "amount": monto,
            "observations": f"Pago cuota {numero_cuota} — loanbook {loanbook_id}",
        }
        payment_result = await alegra.request_with_verify("payments", "POST", payload=payment_payload)
        payment_id = payment_result["_alegra_id"]
    except Exception as e:
        return {"success": False, "error": f"Error registrando pago en Alegra: {str(e)}"}

    # Operation 2: POST /journals — only if payment succeeded
    try:
        journal_payload = {
            "date": fecha,
            "observations": f"Ingreso cuota {numero_cuota} — loanbook {loanbook_id}",
            "entries": [
                {"id": banco_category_id, "debit": monto, "credit": 0},
                {"id": INGRESO_CREDITOS_RODDOS_ID, "debit": 0, "credit": monto},
            ],
        }
        journal_result = await alegra.request_with_verify("journals", "POST", payload=journal_payload)
        journal_id = journal_result["_alegra_id"]
    except Exception as e:
        return {"success": False, "error": f"Pago registrado (ID {payment_id}) pero error en journal: {str(e)}. Revisar manualmente."}

    # Both succeeded — publish event
    await publish_event(
        db=db,
        event_type="pago.cuota.registrado",
        source="agente_contador",
        datos={
            "loanbook_id": loanbook_id,
            "numero_cuota": numero_cuota,
            "monto": monto,
            "payment_alegra_id": payment_id,
            "journal_alegra_id": journal_id,
        },
        alegra_id=payment_id,
        accion_ejecutada=f"Pago cuota {numero_cuota} loanbook {loanbook_id} — Payment #{payment_id}, Journal #{journal_id}",
    )

    return {
        "success": True,
        "payment_id": payment_id,
        "journal_id": journal_id,
        "message": f"Pago cuota {numero_cuota} registrado. Payment #{payment_id}, Journal #{journal_id}. Loanbook: {loanbook_id}",
    }


async def handle_registrar_ingreso_no_operacional(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """POST /journals para ingresos no operacionales (intereses, recuperacion motos, otros)."""
    validate_write_permission("contador", "POST /journals", "alegra")

    tipo = tool_input.get("tipo", "otros")
    monto = tool_input["monto"]
    banco = tool_input.get("banco", "Bancolombia")
    fecha = tool_input.get("fecha") or datetime.date.today().isoformat()
    descripcion = tool_input.get("descripcion", f"Ingreso no operacional — {tipo}")
    banco_category_id = BANCO_CATEGORY_IDS.get(banco, "5314")

    # ROG-4: resolve from Alegra, not MongoDB
    from services.alegra_accounts import AlegraAccountsService
    accounts = AlegraAccountsService(alegra)
    ingreso_id = await accounts.get_ingreso_id(tipo)

    journal_payload = {
        "date": fecha,
        "observations": descripcion,
        "entries": [
            {"id": banco_category_id, "debit": monto, "credit": 0},
            {"id": str(ingreso_id), "debit": 0, "credit": monto},
        ],
    }
    result = await alegra.request_with_verify("journals", "POST", payload=journal_payload)

    await publish_event(
        db=db,
        event_type="ingreso.no_operacional.registrado",
        source="agente_contador",
        datos={"alegra_id": result["_alegra_id"], "monto": monto, "tipo": tipo},
        alegra_id=result["_alegra_id"],
        accion_ejecutada=f"Ingreso no operacional {tipo} ${monto:,.0f} — Journal #{result['_alegra_id']}",
    )

    return {
        "success": True,
        "alegra_id": result["_alegra_id"],
        "message": f"Ingreso no operacional registrado. Journal #{result['_alegra_id']} — {descripcion} ${monto:,.0f}",
    }


async def handle_registrar_cxc_socio(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """
    Registra retiro personal de socio como CXC (balance sheet) — NUNCA gasto operativo.
    (CXC-01, EGRE-03)
    """
    validate_write_permission("contador", "POST /journals", "alegra")

    cc = str(tool_input.get("socio_cedula", ""))
    if cc not in SOCIOS:
        return {"success": False, "error": f"CC {cc} no corresponde a socio registrado. Socios: Andrés 80075452, Iván 80086601"}

    nombre_socio = SOCIOS[cc]
    monto = tool_input["monto"]
    banco = tool_input.get("banco", "Bancolombia")
    fecha = tool_input.get("fecha") or datetime.date.today().isoformat()
    descripcion = tool_input.get("descripcion", f"Retiro personal socio {nombre_socio}")
    banco_category_id = BANCO_CATEGORY_IDS.get(banco, "5314")

    # ROG-4: resolve CXC Socios from Alegra service, not MongoDB
    from services.alegra_accounts import AlegraAccountsService
    accounts = AlegraAccountsService(alegra)
    cxc_id = await accounts.get_cxc_socios_id()

    journal_payload = {
        "date": fecha,
        "observations": f"CXC Socio {nombre_socio} — {descripcion}",
        "entries": [
            {"id": str(cxc_id), "debit": monto, "credit": 0},
            {"id": banco_category_id, "debit": 0, "credit": monto},
        ],
    }
    result = await alegra.request_with_verify("journals", "POST", payload=journal_payload)

    await publish_event(
        db=db,
        event_type="cxc.socio.registrada",
        source="agente_contador",
        datos={"alegra_id": result["_alegra_id"], "socio_cc": cc, "socio_nombre": nombre_socio, "monto": monto},
        alegra_id=result["_alegra_id"],
        accion_ejecutada=f"CXC Socio {nombre_socio} ${monto:,.0f} — Journal #{result['_alegra_id']}",
    )

    return {
        "success": True,
        "alegra_id": result["_alegra_id"],
        "message": f"CXC Socio {nombre_socio} registrada. Journal #{result['_alegra_id']} — ${monto:,.0f} (balance sheet, no P&L)",
    }


async def handle_consultar_cxc_socios(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Read-only: saldo CXC pendiente por socio desde journals Alegra. No MongoDB write. (CXC-02)"""
    try:
        from services.alegra_accounts import AlegraAccountsService
        accounts = AlegraAccountsService(alegra)
        cxc_id = await accounts.get_cxc_socios_id()

        resultado = []
        for cc, nombre in SOCIOS.items():

            journals = await alegra.get("journals", params={"account": cxc_id, "limit": 200})
            saldo = 0.0
            if isinstance(journals, list):
                for j in journals:
                    for entry in j.get("entries", []):
                        if entry.get("account", {}).get("id") == cxc_id:
                            saldo += entry.get("debit", 0) - entry.get("credit", 0)

            resultado.append({
                "nombre": nombre,
                "cc": cc,
                "saldo_pendiente": round(saldo, 2),
                "cuenta_alegra_id": cxc_id,
            })

        return {"success": True, "socios": resultado, "count": len(resultado)}
    except Exception as e:
        return {"success": False, "error": f"Error consultando CXC socios: {str(e)}"}
