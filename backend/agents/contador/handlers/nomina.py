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

# Alegra category IDs for journal entries
BANCO_CATEGORY_IDS = {
    "Bancolombia": "5314", "Bancolombia 2029": "5314", "Bancolombia 2540": "5315",
    "BBVA": "5318", "BBVA 0210": "5318", "BBVA 0212": "5319",
    "Davivienda": "5322",
    "Banco de Bogotá": "5321", "Banco de Bogota": "5321", "Bogota": "5321",
    "Global66": "5536",
}

# SGSSS + Parafiscales Colombia 2026
SGSSS_TASAS = {
    "salud_empleador": 0.085,
    "salud_empleado": 0.04,
    "pension_empleador": 0.12,
    "pension_empleado": 0.04,
    "arl": 0.00522,  # Riesgo I
    "ccf": 0.04,     # Caja Compensación — NUNCA exento
    "sena": 0.02,    # Exento < 10 SMMLV Art. 114-1 ET
    "icbf": 0.03,    # Exento < 10 SMMLV Art. 114-1 ET
}
SMMLV_2026 = 1_300_000
EXENCION_PARAFISCALES_TOPE = 10 * SMMLV_2026

# Alegra IDs for SGSSS CxP accounts
SGSSS_CUENTAS = {
    "salud": "5394",    # 237005 Aportes a EPS
    "pension": "5395",  # 237006 Aportes a ARP (actually pension fund)
    "arl": "5396",      # 237010 Aportes ICBF/SENA/Cajas (general parafiscal)
    "ccf": "5396",      # Same account for parafiscales
}
# Gasto accounts (débito P&L)
SGSSS_GASTO_CUENTAS = {
    "salud": "5471",    # 510568 Aportes a ARL (closest existing)
    "pension": "5472",  # 510570 Aportes fondo de pensiones
    "arl": "5471",      # Same category
    "ccf": "5473",      # 510572 Aportes cajas de compensación
}

# Alegra IDs for retención accounts used in read queries
RETEFUENTE_ACCOUNT_IDS = {"5381", "5382", "5383", "5384", "5386", "5388"}
RETEICA_ACCOUNT_IDS = {"5392", "5393"}

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
    banco_id = BANCO_CATEGORY_IDS.get(banco, "5314")

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

        incluir_sgsss = tool_input.get("incluir_sgsss", True)

        if incluir_sgsss and seg_social == 0:
            # Auto-calculate SGSSS
            salud_er = round(salario * SGSSS_TASAS["salud_empleador"], 2)
            salud_ee = round(salario * SGSSS_TASAS["salud_empleado"], 2)
            pension_er = round(salario * SGSSS_TASAS["pension_empleador"], 2)
            pension_ee = round(salario * SGSSS_TASAS["pension_empleado"], 2)
            arl = round(salario * SGSSS_TASAS["arl"], 2)
            ccf = round(salario * SGSSS_TASAS["ccf"], 2)

            # SENA/ICBF exento si < 10 SMMLV (Art. 114-1 ET)
            sena = round(salario * SGSSS_TASAS["sena"], 2) if salario >= EXENCION_PARAFISCALES_TOPE else 0
            icbf = round(salario * SGSSS_TASAS["icbf"], 2) if salario >= EXENCION_PARAFISCALES_TOPE else 0

            neto_empleado = salario - salud_ee - pension_ee

            entries_final = [
                # DÉBITOS (gastos P&L)
                {"id": "5462", "debit": salario, "credit": 0},           # Sueldos
                {"id": SGSSS_GASTO_CUENTAS["salud"], "debit": salud_er, "credit": 0},
                {"id": SGSSS_GASTO_CUENTAS["pension"], "debit": pension_er, "credit": 0},
                {"id": SGSSS_GASTO_CUENTAS["arl"], "debit": arl, "credit": 0},
                {"id": SGSSS_GASTO_CUENTAS["ccf"], "debit": ccf, "credit": 0},
            ]
            # CRÉDITOS
            entries_final.extend([
                {"id": str(banco_id), "debit": 0, "credit": neto_empleado},           # Banco (neto)
                {"id": SGSSS_CUENTAS["salud"], "debit": 0, "credit": salud_er + salud_ee},  # CxP Salud
                {"id": SGSSS_CUENTAS["pension"], "debit": 0, "credit": pension_er + pension_ee},  # CxP Pensión
                {"id": SGSSS_CUENTAS["arl"], "debit": 0, "credit": arl},              # CxP ARL
                {"id": SGSSS_CUENTAS["ccf"], "debit": 0, "credit": ccf},              # CxP CCF
            ])
        else:
            # Legacy: simple salary + manual seg_social
            total_debit = salario + seg_social
            entries_final = [
                {"id": "5462", "debit": salario, "credit": 0},
            ]
            if seg_social > 0:
                entries_final.append({"id": "5471", "debit": seg_social, "credit": 0})
            entries_final.append({"id": str(banco_id), "debit": 0, "credit": total_debit})

        fecha = f"{anio}-{mes:02d}-28"
        payload = {
            "date": fecha,
            "observations": f"Nómina {nombre} {mes}/{anio}",
            "entries": entries_final,
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
                    acc_id = str(entry.get("account", {}).get("id", ""))
                    if acc_id in RETEFUENTE_ACCOUNT_IDS:
                        retefuente_total += entry.get("credit", 0)
                    elif acc_id in RETEICA_ACCOUNT_IDS:
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


# ---------------------------------------------------------------------------
# Prestaciones sociales — porcentajes sobre salario base (Art. 306 CST + Art. 249 CST)
# ---------------------------------------------------------------------------
PRESTACIONES_PORCENTAJES = {
    "prima": 0.0833,          # 8.33%
    "cesantias": 0.0833,      # 8.33%
    "int_cesantias": 0.01,    # 1.00%
    "vacaciones": 0.0417,     # 4.17%
}

# Alegra IDs — Gasto (P&L débito) y Provisión (Balance crédito)
PRESTACIONES_CUENTAS = {
    "prima":         {"gasto": "5468", "provision": "5418"},  # 510536 / 252005
    "cesantias":     {"gasto": "5466", "provision": "5416"},  # 510530 / 251010
    "int_cesantias": {"gasto": "5467", "provision": "5417"},  # 510533 / 251505
    "vacaciones":    {"gasto": "5469", "provision": "5415"},  # 510539 / 250505
}

EMPLEADOS_DEFAULT = [
    {"nombre": "Alexa", "salario": 4_500_000},
    {"nombre": "Liz", "salario": 2_200_000},
]


async def handle_provisionar_prestaciones(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Provisión mensual de prestaciones sociales por empleado. (PREST-01)"""
    validate_write_permission("contador", "POST /journals", "alegra")

    mes = tool_input["mes"]  # yyyy-MM format
    empleados = tool_input.get("empleados") or EMPLEADOS_DEFAULT

    # Derive date range from yyyy-MM
    date_from = f"{mes}-01"
    date_to = f"{mes}-28"

    resultados = []
    for emp in empleados:
        nombre = emp["nombre"]
        salario = emp["salario"]

        # Anti-dup: check Alegra journals for this month+employee
        existing = await alegra.get("journals", params={
            "date_from": date_from,
            "date_to": date_to,
            "limit": 100,
        })
        if isinstance(existing, list):
            dup = any(
                f"Prestaciones {nombre} {mes}" in j.get("observations", "")
                for j in existing
            )
            if dup:
                resultados.append({
                    "nombre": nombre,
                    "status": "duplicado",
                    "error": f"Prestaciones {nombre} {mes} ya provisionadas",
                })
                continue

        # Build journal entries: 4 debit (gasto) + 4 credit (provisión)
        entries = []
        for concepto, pct in PRESTACIONES_PORCENTAJES.items():
            monto = round(salario * pct, 2)
            cuentas = PRESTACIONES_CUENTAS[concepto]
            entries.append({"id": cuentas["gasto"], "debit": monto, "credit": 0})
            entries.append({"id": cuentas["provision"], "debit": 0, "credit": monto})

        payload = {
            "date": date_to,
            "observations": f"Prestaciones {nombre} {mes}",
            "entries": entries,
        }
        result = await alegra.request_with_verify("journals", "POST", payload=payload)

        resultados.append({
            "nombre": nombre,
            "status": "creado",
            "alegra_id": result["_alegra_id"],
        })

    await publish_event(
        db=db,
        event_type="prestaciones.provisionadas",
        source="agente_contador",
        datos={"mes": mes, "empleados": len(empleados), "resultados": resultados},
        alegra_id=None,
        accion_ejecutada=f"Prestaciones {mes} — {len(empleados)} empleados",
    )

    return {
        "success": True,
        "resultados": resultados,
        "message": f"Prestaciones {mes} procesadas. {len(resultados)} empleados.",
    }


# ---------------------------------------------------------------------------
# Calendario tributario RODDOS
# ---------------------------------------------------------------------------

OBLIGACIONES_TRIBUTARIAS = [
    {
        "impuesto": "ReteFuente",
        "periodicidad": "Mensual",
        "descripcion": "Retención en la fuente practicada",
    },
    {
        "impuesto": "IVA",
        "periodicidad": "Cuatrimestral",
        "descripcion": "IVA régimen cuatrimestral (ene-abr / may-ago / sep-dic)",
    },
    {
        "impuesto": "ReteICA Bogotá",
        "periodicidad": "Bimestral",
        "descripcion": "Retención ICA Bogotá",
    },
    {
        "impuesto": "ICA Bogotá",
        "periodicidad": "Anual",
        "descripcion": "Impuesto de Industria y Comercio Bogotá",
    },
]


def _next_retefuente_vencimiento(hoy: datetime.date) -> tuple[str, datetime.date]:
    """ReteFuente: vence día 20 del mes siguiente al período."""
    # Current period is previous month
    if hoy.day <= 20:
        # We're before the deadline for last month's period
        periodo_mes = hoy.month - 1 if hoy.month > 1 else 12
        periodo_anio = hoy.year if hoy.month > 1 else hoy.year - 1
        vence = datetime.date(hoy.year, hoy.month, 20)
    else:
        # Past this month's deadline, next is for current month
        periodo_mes = hoy.month
        periodo_anio = hoy.year
        next_month = hoy.month + 1 if hoy.month < 12 else 1
        next_year = hoy.year if hoy.month < 12 else hoy.year + 1
        vence = datetime.date(next_year, next_month, 20)
    periodo = f"{periodo_anio}-{periodo_mes:02d}"
    return periodo, vence


def _next_iva_vencimiento(hoy: datetime.date) -> tuple[str, datetime.date]:
    """IVA cuatrimestral: ene-abr vence mayo, may-ago vence sep, sep-dic vence ene."""
    mes = hoy.month
    if mes <= 4:
        return "ene-abr", datetime.date(hoy.year, 5, 20)
    elif mes <= 8:
        return "may-ago", datetime.date(hoy.year, 9, 20)
    else:
        return "sep-dic", datetime.date(hoy.year + 1, 1, 20)


def _next_reteica_vencimiento(hoy: datetime.date) -> tuple[str, datetime.date]:
    """ReteICA Bogotá bimestral: vence mes siguiente al bimestre."""
    mes = hoy.month
    # Bimestres: ene-feb, mar-abr, may-jun, jul-ago, sep-oct, nov-dic
    bimestre_end = ((mes - 1) // 2 + 1) * 2  # 2, 4, 6, 8, 10, 12
    bimestre_start = bimestre_end - 1
    vence_month = bimestre_end + 1 if bimestre_end < 12 else 1
    vence_year = hoy.year if bimestre_end < 12 else hoy.year + 1
    vence = datetime.date(vence_year, vence_month, 20)
    if hoy > vence:
        # Move to next bimestre
        bimestre_end = min(bimestre_end + 2, 12)
        bimestre_start = bimestre_end - 1
        vence_month = bimestre_end + 1 if bimestre_end < 12 else 1
        vence_year = hoy.year if bimestre_end < 12 else hoy.year + 1
        vence = datetime.date(vence_year, vence_month, 20)
    nombres_meses = {1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
                     7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic"}
    periodo = f"{nombres_meses[bimestre_start]}-{nombres_meses[bimestre_end]}"
    return periodo, vence


def _next_ica_vencimiento(hoy: datetime.date) -> tuple[str, datetime.date]:
    """ICA Bogotá anual: vence agosto del año siguiente."""
    if hoy.month <= 8:
        return str(hoy.year - 1), datetime.date(hoy.year, 8, 20)
    else:
        return str(hoy.year), datetime.date(hoy.year + 1, 8, 20)


async def handle_consultar_calendario_tributario(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Calendario tributario RODDOS con semáforo por proximidad de vencimiento."""
    hoy = datetime.date.today()

    calculadores = [
        ("ReteFuente", _next_retefuente_vencimiento),
        ("IVA", _next_iva_vencimiento),
        ("ReteICA Bogotá", _next_reteica_vencimiento),
        ("ICA Bogotá", _next_ica_vencimiento),
    ]

    obligaciones = []
    for nombre, calc in calculadores:
        periodo, vence = calc(hoy)
        dias = (vence - hoy).days
        if dias < 0:
            estado = "VENCIDO"
        elif dias < 7:
            estado = "ROJO"
        elif dias <= 30:
            estado = "AMARILLO"
        else:
            estado = "VERDE"

        obligaciones.append({
            "impuesto": nombre,
            "periodo": periodo,
            "vence": vence.isoformat(),
            "dias_restantes": dias,
            "estado": estado,
        })

    return {
        "success": True,
        "fecha_consulta": hoy.isoformat(),
        "obligaciones": obligaciones,
        "message": f"Calendario tributario al {hoy.isoformat()} — {len(obligaciones)} obligaciones",
    }
