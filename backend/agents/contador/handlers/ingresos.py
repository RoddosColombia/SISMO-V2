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

BANCO_IDS: dict[str, int] = {
    "Bancolombia": 111005,
    "BBVA": 111010,
    "Davivienda": 111015,
    "Banco de Bogotá": 111020,
    "Banco de Bogota": 111020,
    "Global66": 11100507,
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
    banco_id = BANCO_IDS.get(banco, 111005)

    # Look up invoice from loanbook (MongoDB operational data — allowed)
    loanbook = await db.loanbook.find_one({"loanbook_id": loanbook_id})
    if not loanbook:
        return {"success": False, "error": f"Loanbook {loanbook_id} no encontrado"}
    invoice_alegra_id = loanbook.get("factura_alegra_id")
    if not invoice_alegra_id:
        return {"success": False, "error": f"Loanbook {loanbook_id} no tiene factura Alegra vinculada"}

    # Operation 1: POST /payments
    try:
        payment_payload = {
            "date": fecha,
            "bankAccount": {"id": banco_id},
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
        ingreso_account = await db.plan_ingresos_roddos.find_one({"tipo": "ingresos_financieros"})
        ingreso_id = ingreso_account["alegra_id"] if ingreso_account else None
        if not ingreso_id:
            return {"success": False, "error": f"Pago registrado (ID {payment_id}) pero cuenta de ingresos financieros no configurada. Revisar manualmente."}

        journal_payload = {
            "date": fecha,
            "observations": f"Ingreso cuota {numero_cuota} — loanbook {loanbook_id}",
            "entries": [
                {"account": {"id": banco_id}, "debit": monto, "credit": 0},
                {"account": {"id": ingreso_id}, "debit": 0, "credit": monto},
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
    banco_id = BANCO_IDS.get(banco, 111005)

    # Read ingreso account from plan_ingresos_roddos (not hardcoded)
    ingreso_account = await db.plan_ingresos_roddos.find_one({"tipo": tipo})
    if not ingreso_account:
        return {"success": False, "error": f"Cuenta de ingreso para tipo '{tipo}' no encontrada en plan_ingresos_roddos"}
    ingreso_id = ingreso_account["alegra_id"]

    journal_payload = {
        "date": fecha,
        "observations": descripcion,
        "entries": [
            {"account": {"id": banco_id}, "debit": monto, "credit": 0},
            {"account": {"id": ingreso_id}, "debit": 0, "credit": monto},
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
    banco_id = BANCO_IDS.get(banco, 111005)

    # CXC account from plan_cuentas_roddos
    cxc_record = await db.plan_cuentas_roddos.find_one({"tipo": "cxc_socios", "cc": cc})
    if not cxc_record:
        cxc_record = await db.plan_cuentas_roddos.find_one({"tipo": "cxc_socios"})
    if not cxc_record:
        return {"success": False, "error": f"Cuenta CXC Socios no configurada en plan_cuentas_roddos para CC {cc}"}
    cxc_id = cxc_record["alegra_id"]

    journal_payload = {
        "date": fecha,
        "observations": f"CXC Socio {nombre_socio} — {descripcion}",
        "entries": [
            {"account": {"id": cxc_id}, "debit": monto, "credit": 0},
            {"account": {"id": banco_id}, "debit": 0, "credit": monto},
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
        resultado = []
        for cc, nombre in SOCIOS.items():
            cxc_record = await db.plan_cuentas_roddos.find_one({"tipo": "cxc_socios", "cc": cc})
            if not cxc_record:
                cxc_record = await db.plan_cuentas_roddos.find_one({"tipo": "cxc_socios"})
            if not cxc_record:
                resultado.append({"nombre": nombre, "cc": cc, "saldo_pendiente": 0, "error": "Cuenta CXC no configurada"})
                continue
            cxc_id = cxc_record["alegra_id"]

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
