"""
Wave 6 — 3 nomina + impuestos handlers.

REGLAS:
- Nomina: 1 journal por empleado, anti-dup por mes+empleado via GET Alegra
- Sueldos: cuenta 5462, Seguridad Social: cuenta 5471
- IVA cuatrimestral (ene-abr/may-ago/sep-dic) — NUNCA bimestral
- Auteco NIT 860024781 = autoretenedor
"""
import datetime
from typing import Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from services.alegra.client import AlegraClient
from core.permissions import validate_write_permission
from core.events import publish_event
from services.retenciones import calcular_retenciones, AUTORETENEDORES

BANCO_IDS = {
    "Bancolombia": 111005, "BBVA": 111010, "Davivienda": 111015,
    "Banco de Bogotá": 111020, "Banco de Bogota": 111020, "Global66": 11100507,
}

IVA_CUATRIMESTRES = {
    1: "ene-abr", 2: "ene-abr", 3: "ene-abr", 4: "ene-abr",
    5: "may-ago", 6: "may-ago", 7: "may-ago", 8: "may-ago",
    9: "sep-dic", 10: "sep-dic", 11: "sep-dic", 12: "sep-dic",
}


async def handle_registrar_nomina_mensual(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """1 journal por empleado con anti-dup por mes+empleado. (NOMI-01)"""
    validate_write_permission("contador", "POST /journals", "alegra")

    mes = tool_input["mes"]
    anio = tool_input["anio"]
    empleados = tool_input["empleados"]
    banco = tool_input.get("banco", "Bancolombia")
    banco_id = BANCO_IDS.get(banco, 111005)

    resultados = []
    for emp in empleados:
        nombre = emp["nombre"]
        salario = emp["salario"]
        seg_social = emp.get("seguridad_social", 0)

        # Anti-dup: check Alegra journals for this month+employee
        existing = await alegra.get("journals", params={
            "date_from": f"{anio}-{mes:02d}-01",
            "date_to": f"{anio}-{mes:02d}-28",
            "limit": 100,
        })
        if isinstance(existing, list):
            dup = any(f"Nómina {nombre}" in j.get("observations", "") for j in existing)
            if dup:
                resultados.append({"nombre": nombre, "status": "duplicado", "error": f"Nómina {nombre} {mes}/{anio} ya registrada"})
                continue

        entries = [
            {"account": {"id": 5462}, "debit": salario, "credit": 0},  # Sueldos
        ]
        total_credit = salario
        if seg_social > 0:
            entries.append({"account": {"id": 5471}, "debit": seg_social, "credit": 0})  # Seg Social
            total_credit += seg_social
            entries[0]["debit"] = salario  # keep salary separate

        entries.append({"account": {"id": banco_id}, "debit": 0, "credit": total_credit})

        # Fix balance: total debit must equal total credit
        total_debit = salario + seg_social
        entries_final = [
            {"account": {"id": 5462}, "debit": salario, "credit": 0},
        ]
        if seg_social > 0:
            entries_final.append({"account": {"id": 5471}, "debit": seg_social, "credit": 0})
        entries_final.append({"account": {"id": banco_id}, "debit": 0, "credit": total_debit})

        fecha = f"{anio}-{mes:02d}-28"
        payload = {
            "date": fecha,
            "observations": f"Nómina {nombre} {mes}/{anio}",
            "entries": [{"account": {"id": e["account"]["id"]}, "debit": e["debit"], "credit": e["credit"]} for e in entries_final],
        }
        result = await alegra.request_with_verify("journals", "POST", payload=payload)

        resultados.append({"nombre": nombre, "status": "creado", "alegra_id": result["_alegra_id"]})

    await publish_event(
        db=db,
        event_type="nomina.registrada",
        source="agente_contador",
        datos={"mes": mes, "anio": anio, "empleados": len(empleados), "resultados": resultados},
        alegra_id=None,
        accion_ejecutada=f"Nómina {mes}/{anio} — {len(empleados)} empleados",
    )

    return {"success": True, "resultados": resultados, "message": f"Nómina {mes}/{anio} procesada. {len(resultados)} empleados."}


async def handle_consultar_obligaciones_tributarias(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """IVA cuatrimestral + ReteFuente + ReteICA acumulados desde Alegra."""
    try:
        mes = tool_input.get("mes") or datetime.date.today().month
        anio = tool_input.get("anio") or datetime.date.today().year
        cuatrimestre = IVA_CUATRIMESTRES.get(mes, "ene-abr")

        # Determine period dates
        if cuatrimestre == "ene-abr":
            date_from, date_to = f"{anio}-01-01", f"{anio}-04-30"
        elif cuatrimestre == "may-ago":
            date_from, date_to = f"{anio}-05-01", f"{anio}-08-31"
        else:
            date_from, date_to = f"{anio}-09-01", f"{anio}-12-31"

        journals = await alegra.get("journals", params={"date_from": date_from, "date_to": date_to, "limit": 500})

        retefuente_total = 0.0
        reteica_total = 0.0
        if isinstance(journals, list):
            for j in journals:
                for entry in j.get("entries", []):
                    acc_id = entry.get("account", {}).get("id")
                    if acc_id == 236505:
                        retefuente_total += entry.get("credit", 0)
                    elif acc_id == 236560:
                        reteica_total += entry.get("credit", 0)

        return {
            "success": True,
            "cuatrimestre": cuatrimestre,
            "anio": anio,
            "retefuente_acumulada": round(retefuente_total, 2),
            "reteica_acumulada": round(reteica_total, 2),
            "mensaje": f"Período {cuatrimestre} {anio}: ReteFuente ${retefuente_total:,.0f}, ReteICA ${reteica_total:,.0f}",
        }
    except Exception as e:
        return {"success": False, "error": f"Error consultando obligaciones: {str(e)}"}


async def handle_calcular_retenciones(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Pure calculation — no Alegra write. Uses retenciones service."""
    tipo = tool_input.get("tipo", "servicios")
    monto = tool_input.get("monto", 0)
    nit = tool_input.get("nit")

    ret = calcular_retenciones(tipo, monto, nit)
    es_autoretenedor = nit in AUTORETENEDORES if nit else False

    return {
        "success": True,
        "data": ret,
        "autoretenedor": es_autoretenedor,
        "message": f"Retenciones para {tipo} ${monto:,.0f}: ReteFte ${ret['retefuente_monto']:,.0f} ({ret['retefuente_tasa']*100:.1f}%), ReteICA ${ret['reteica_monto']:,.0f}, Neto ${ret['neto_a_pagar']:,.0f}",
    }
