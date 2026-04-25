"""
Wave 6 — 2 cartera handlers + 1 catalogo handler.

REGLAS:
- Cartera reads from MongoDB loanbook (operational data, allowed)
- Pago cuota: POST /payments en Alegra + publish event (Loanbook listener actualiza MongoDB)
- Contador SOLO escribe en Alegra + publica eventos (ROG-4 reforzada)
- Catalogo: returns embedded catalog from tools.py description (no API call)
"""
import datetime
from core.datetime_utils import now_bogota, today_bogota, now_iso_bogota
from typing import Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from services.alegra.client import AlegraClient
from core.permissions import validate_write_permission
from core.events import publish_event

# Alegra bank-account IDs for POST /payments
BANCO_PAYMENT_IDS = {
    "Bancolombia": 5, "Bancolombia 2029": 5, "Bancolombia 2540": 6,
    "BBVA": 7, "BBVA 0210": 7, "BBVA 0212": 10,
    "Davivienda": 3,
    "Banco de Bogotá": 5, "Banco de Bogota": 5, "Bogota": 5,
    "Global66": 5,
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
    fecha = tool_input.get("fecha") or today_bogota().isoformat()
    banco_id = BANCO_PAYMENT_IDS.get(banco, 5)

    # ROG-4 OK: lectura operativa Loanbook, no dato contable
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

    # Publish event — Loanbook listener handles cuota state update in MongoDB
    await publish_event(
        db=db,
        event_type="pago.cuota.registrado",
        source="agente_contador",
        datos={
            "loanbook_id": loanbook_id,
            "cuota": numero_cuota,
            "monto": monto,
            "payment_id": result["_alegra_id"],
            "fecha_pago": fecha,
        },
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


async def handle_resumen_cartera(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Resumen ejecutivo de cartera — suma saldo_capital + saldo_intereses de loanbooks activos."""
    try:
        lbs = await db.loanbook.find(
            {"estado": {"$nin": ["Pagado", "pagado", "saldado", "castigado", "pendiente_entrega"]}}
        ).to_list(None)

        cartera_total = sum(
            (lb.get("saldo_capital") or 0) + (lb.get("saldo_intereses") or 0)
            for lb in lbs
        )
        en_mora = [lb for lb in lbs if (lb.get("dpd") or 0) > 0]
        al_dia = [lb for lb in lbs if (lb.get("dpd") or 0) == 0]
        recaudo = sum(lb.get("cuota_periodica") or 0 for lb in lbs)

        return {
            "success": True,
            "cartera_total_cop": cartera_total,
            "total_creditos_activos": len(lbs),
            "creditos_al_dia": len(al_dia),
            "creditos_en_mora": len(en_mora),
            "recaudo_semanal_proyectado_cop": recaudo,
            "mensaje": (
                f"Cartera total activa: ${cartera_total:,.0f} COP. "
                f"{len(lbs)} créditos activos — {len(al_dia)} al día, {len(en_mora)} en mora."
            ),
        }
    except Exception as e:
        return {"success": False, "error": f"Error calculando cartera: {str(e)}"}


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
                "5462": "Sueldos y salarios (510506)", "5475": "Asesoría jurídica (511025)",
                "5476": "Asesoría financiera (511030)", "5471": "Aportes ARL (510568)",
                "5472": "Aportes pensiones (510570)", "5473": "Aportes cajas (510572)",
                "5480": "Arrendamientos (512010)", "5485": "Acueducto (513525)",
                "5486": "Energía eléctrica (313530)", "5487": "Teléfono/Internet (513535)",
                "5492": "Construcciones (514510)", "5497": "Útiles papelería (519530)",
                "5499": "Taxis y buses (519545)", "5507": "Gastos bancarios (530505)",
                "5508": "Comisiones bancarias (530515)", "5509": "Gravamen 4x1000 (531520)",
                "5494": "FALLBACK Deudores (51991001) — bajo Gastos Generales",
            },
            "retenciones_por_pagar": {
                "5381": "Ret honorarios 10%", "5382": "Ret honorarios 11%",
                "5383": "Ret servicios 4%", "5386": "Ret arriendo 3.5%",
                "5388": "Ret compras 2.5%", "5392": "RteIca 11,04", "5393": "RteIca 9,66",
            },
            "bancos_journal": {
                "5314": "Bancolombia 2029", "5315": "Bancolombia 2540",
                "5318": "BBVA 0210", "5319": "BBVA 0212",
                "5322": "Davivienda 482", "5321": "Banco de Bogota",
                "5536": "Global 66",
            },
            "cxc": {
                "5329": "CXC Socios (132505)", "5327": "Créditos Directos Roddos (13050502)",
            },
            "ingresos": {
                "5456": "Créditos Directos Roddos (41502001)", "5442": "Motos (41350501)",
                "5436": "Otros ingresos (42)",
            },
            "tasas_2026": {
                "arriendo": "3.5%", "servicios": "4%", "honorarios_pn": "10%",
                "honorarios_pj": "11%", "compras": "2.5% (base >$1.344.573)", "reteica": "0.414%",
            },
            "autoretenedores": ["860024781 (Auteco)"],
            "socios": {"80075452": "Andrés Sanjuan", "80086601": "Iván Echeverri"},
            "nota": "NUNCA usar ID 5495 ni 5493 (accumulative). IVA cuatrimestral (ene-abr/may-ago/sep-dic).",
        },
        "message": "Catálogo de cuentas RODDOS con IDs reales de Alegra.",
    }
