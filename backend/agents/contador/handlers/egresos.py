"""
Wave 3 — 7 egresos handlers.

REGLAS INAMOVIBLES:
- Toda escritura via request_with_verify() — POST → HTTP 200 → GET verify → retorna ID
- Publicar evento DESPUÉS de toda escritura exitosa
- validate_write_permission ANTES de toda escritura
- CERO writes directos a MongoDB (solo publish_event para roddos_events)
- Auteco NIT 860024781 = autoretenedor → NUNCA ReteFuente
- Socios CC 80075452/80086601 = CXC, NUNCA gasto operativo
- Fallback cuenta: 5493 (NUNCA 5495)
- Fechas: yyyy-MM-dd — NUNCA ISO-8601 con timezone
"""
import datetime
from typing import Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from services.alegra.client import AlegraClient
from core.permissions import validate_write_permission
from core.events import publish_event
from services.retenciones import calcular_retenciones

SOCIOS_CC = {"80075452": "Andrés Sanjuan", "80086601": "Iván Echeverri"}


def _prefix_obs(prefix: str, observations: str) -> str:
    """Prepend classification prefix [XX] to observations if not already present."""
    if observations.startswith(f"[{prefix}]"):
        return observations
    return f"[{prefix}] {observations}"
CXC_SOCIOS_ALEGRA_ID = "5329"  # 132505 Cuentas por cobrar a socios y accionistas
FALLBACK_GASTO_ID = "5494"     # 51991001 Deudores (hijo de Gastos Generales) — NUNCA 5495

# Alegra category IDs for journal entries — NOT NIIF codes
BANCO_CATEGORY_IDS = {
    "Bancolombia": "5314",      # default Bancolombia 2029
    "Bancolombia 2029": "5314",
    "Bancolombia 2540": "5315",
    "BBVA": "5318",             # default BBVA 0210
    "BBVA 0210": "5318",
    "BBVA 0212": "5319",
    "Davivienda": "5322",       # 11200502 Davivienda 482
    "Banco de Bogotá": "5321",  # 11200501 Banco de Bogota
    "Banco de Bogota": "5321",
    "Bogota": "5321",
    "Global66": "5536",         # 11100507 Global 66
}

TIPO_GASTO_MAP = {
    "arriend": ("arriendo", "5480"),       # 512010 Arrendamientos
    "servicio": ("servicios", "5484"),     # 513520 Procesamiento Datos
    "honorar": ("honorarios_pn", "5475"),  # 511025 Asesoría jurídica
    "telefon": ("servicios", "5487"),      # 513535 Teléfono/Internet
    "internet": ("servicios", "5487"),
    "seguro": ("servicios", "5494"),       # Fallback — no cuenta Seguros en Alegra
    "mantenim": ("servicios", "5492"),     # 514510 Construcciones y Edificaciones
    "transport": ("servicios", "5499"),    # 519545 Taxis y buses
    "papeler": ("servicios", "5497"),      # 519530 Útiles, papelería
    "publicid": ("servicios", "5494"),     # Fallback — no cuenta Publicidad en Alegra
    "comision": ("servicios", "5508"),     # 530515 Comisiones
    "interes": ("servicios", "5507"),      # 530505 Gastos bancarios
}

TIPO_RECURRENTE_MAP = {
    "arriendo": ("arriendo", "5480"),              # 512010 Arrendamientos
    "servicios_publicos": ("servicios", "5485"),   # 513525 Acueducto/Servicios Públicos
    "telefonia": ("servicios", "5487"),            # 513535 Teléfono/Internet
    "seguros": ("servicios", "5494"),              # Fallback — no cuenta Seguros en Alegra
    "mantenimiento": ("servicios", "5492"),        # 514510 Construcciones
}


def _detect_socio(tool_input: dict) -> str | None:
    """Check if the operation involves a socio (by NIT or description)."""
    nit = tool_input.get("proveedor_nit", "")
    desc = tool_input.get("descripcion", "")
    combined = f"{nit} {desc}"
    for cc in SOCIOS_CC:
        if cc in combined:
            return cc
    return None


def _classify_gasto(descripcion: str, tipo_persona: str | None = None) -> tuple[str, str]:
    """Classify expense type and Alegra category ID from description."""
    desc_lower = descripcion.lower()
    for keyword, (tipo, cuenta) in TIPO_GASTO_MAP.items():
        if keyword in desc_lower:
            if keyword == "honorar" and tipo_persona == "juridica":
                return "honorarios_pj", cuenta
            return tipo, cuenta
    return "servicios", FALLBACK_GASTO_ID


def _build_entries(cuenta_gasto: str, monto: float, banco_id: str, ret: dict) -> list[dict]:
    """Build balanced journal entries with retenciones. Uses real Alegra category IDs."""
    entries = [
        {"id": cuenta_gasto, "debit": monto, "credit": 0},
        {"id": banco_id, "debit": 0, "credit": ret["neto_a_pagar"]},
    ]
    if ret["retefuente_monto"] > 0:
        entries.append({"id": ret["retefuente_alegra_id"], "debit": 0, "credit": ret["retefuente_monto"]})
    if ret["reteica_monto"] > 0:
        entries.append({"id": ret["reteica_alegra_id"], "debit": 0, "credit": ret["reteica_monto"]})
    return entries


def _validate_balance(entries: list[dict]) -> bool:
    """Verify sum(debits) == sum(credits)."""
    total_debit = round(sum(e.get("debit", 0) or 0 for e in entries), 2)
    total_credit = round(sum(e.get("credit", 0) or 0 for e in entries), 2)
    return total_debit == total_credit


async def _post_journal(
    entries: list[dict],
    fecha: str,
    observations: str,
    alegra: AlegraClient,
) -> dict:
    """Build payload and POST to Alegra via request_with_verify."""
    payload = {
        "date": fecha,
        "observations": observations,
        "entries": entries,
    }
    return await alegra.request_with_verify("journals", "POST", payload=payload)


# ═══════════════════════════════════════════════════════
# HANDLER 1: crear_causacion
# ═══════════════════════════════════════════════════════

async def handle_crear_causacion(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Create a double-entry journal in Alegra. Validates balance before POST."""
    raw_entries = tool_input["entries"]

    # Validate balance
    total_debit = round(sum(e.get("debit", 0) or 0 for e in raw_entries), 2)
    total_credit = round(sum(e.get("credit", 0) or 0 for e in raw_entries), 2)
    if total_debit != total_credit:
        return {
            "success": False,
            "error": f"Asiento desbalanceado: débitos ({total_debit:,.2f}) != créditos ({total_credit:,.2f})",
        }

    validate_write_permission("contador", "POST /journals", "alegra")

    entries = [{"id": str(e["id"]), "debit": e["debit"], "credit": e["credit"]} for e in raw_entries]
    obs = _prefix_obs("AC", tool_input["observations"])
    result = await _post_journal(entries, tool_input["date"], obs, alegra)

    await publish_event(
        db=db,
        event_type="gasto.causado",
        source="agente_contador",
        datos={"alegra_id": result["_alegra_id"], "entries": len(entries), "observations": obs},
        alegra_id=result["_alegra_id"],
        accion_ejecutada=f"Journal #{result['_alegra_id']} creado. {tool_input['observations']}",
    )

    return {
        "success": True,
        "alegra_id": result["_alegra_id"],
        "message": f"Journal #{result['_alegra_id']} creado en Alegra. {tool_input['observations']}",
    }


# ═══════════════════════════════════════════════════════
# HANDLER 2: registrar_gasto
# ═══════════════════════════════════════════════════════

async def handle_registrar_gasto(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Register expense from natural language. Auto-classifies and calculates retenciones."""
    validate_write_permission("contador", "POST /journals", "alegra")

    monto = tool_input["monto"]
    banco_id = BANCO_CATEGORY_IDS.get(tool_input["banco"], "5314")
    fecha = tool_input.get("fecha") or datetime.date.today().isoformat()
    descripcion = tool_input["descripcion"]
    nit = tool_input.get("proveedor_nit")

    # CXC socio check
    socio_cc = _detect_socio(tool_input)
    if socio_cc:
        socio_name = SOCIOS_CC[socio_cc]
        entries = [
            {"id": CXC_SOCIOS_ALEGRA_ID, "debit": monto, "credit": 0},  # 132505 CXC Socios
            {"id": banco_id, "debit": 0, "credit": monto},
        ]
        result = await _post_journal(entries, fecha, _prefix_obs("CXC", f"CXC Socio {socio_name}: {descripcion}"), alegra)
        await publish_event(
            db=db,
            event_type="cxc.socio.registrada",
            source="agente_contador",
            datos={"alegra_id": result["_alegra_id"], "socio": socio_name, "cc": socio_cc, "monto": monto},
            alegra_id=result["_alegra_id"],
            accion_ejecutada=f"CXC Socio {socio_name} ${monto:,.0f}",
        )
        return {
            "success": True,
            "alegra_id": result["_alegra_id"],
            "message": f"CXC Socio {socio_name} registrada. Journal #{result['_alegra_id']} — ${monto:,.0f}",
        }

    # Normal expense
    tipo, cuenta_gasto = _classify_gasto(descripcion, tool_input.get("tipo_persona"))
    ret = calcular_retenciones(tipo, monto, nit)
    entries = _build_entries(cuenta_gasto, monto, banco_id, ret)
    result = await _post_journal(entries, fecha, _prefix_obs("AC", descripcion), alegra)

    await publish_event(
        db=db,
        event_type="gasto.causado",
        source="agente_contador",
        datos={"alegra_id": result["_alegra_id"], "tipo": tipo, "monto": monto, "cuenta": cuenta_gasto},
        alegra_id=result["_alegra_id"],
        accion_ejecutada=f"Gasto {tipo} ${monto:,.0f} — Journal #{result['_alegra_id']}",
    )
    return {
        "success": True,
        "alegra_id": result["_alegra_id"],
        "message": f"Gasto registrado. Journal #{result['_alegra_id']} — {descripcion} ${monto:,.0f}",
    }


# ═══════════════════════════════════════════════════════
# HANDLER 3: registrar_gasto_recurrente
# ═══════════════════════════════════════════════════════

async def handle_registrar_gasto_recurrente(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Register a recurring fixed expense (rent, utilities, phone, insurance)."""
    validate_write_permission("contador", "POST /journals", "alegra")

    tipo_gasto = tool_input["tipo_gasto"]
    tipo, cuenta_gasto = TIPO_RECURRENTE_MAP.get(tipo_gasto, ("servicios", FALLBACK_GASTO_ID))
    monto = tool_input["monto"]
    banco_id = BANCO_CATEGORY_IDS.get(tool_input["banco"], "5314")
    fecha = tool_input.get("fecha") or datetime.date.today().isoformat()
    nit = tool_input.get("proveedor_nit")
    periodo = tool_input.get("periodo", "")

    ret = calcular_retenciones(tipo, monto, nit)
    entries = _build_entries(cuenta_gasto, monto, banco_id, ret)
    result = await _post_journal(entries, fecha, _prefix_obs("AC", f"{tipo_gasto} {periodo}"), alegra)

    await publish_event(
        db=db,
        event_type="gasto.causado",
        source="agente_contador",
        datos={"alegra_id": result["_alegra_id"], "tipo": tipo_gasto, "monto": monto, "periodo": periodo},
        alegra_id=result["_alegra_id"],
        accion_ejecutada=f"Gasto recurrente {tipo_gasto} {periodo} ${monto:,.0f}",
    )
    return {
        "success": True,
        "alegra_id": result["_alegra_id"],
        "message": f"Gasto recurrente registrado. Journal #{result['_alegra_id']} — {tipo_gasto} {periodo}",
    }


# ═══════════════════════════════════════════════════════
# HANDLER 4: anular_causacion
# ═══════════════════════════════════════════════════════

async def handle_anular_causacion(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Delete a journal from Alegra. Three-step: GET verify exists → DELETE → GET confirm 404."""
    validate_write_permission("contador", "DELETE /journals", "alegra")

    journal_id = tool_input["journal_id"]
    motivo = tool_input["motivo"]

    # Step 1: Verify journal exists
    try:
        await alegra.get(f"journals/{journal_id}")
    except Exception:
        return {"success": False, "error": f"Journal {journal_id} no encontrado en Alegra."}

    # Step 2: DELETE
    await alegra.request_with_verify(f"journals/{journal_id}", "DELETE")

    # Step 3: Verify deletion (should be 404)
    try:
        await alegra.get(f"journals/{journal_id}")
        return {"success": False, "error": f"Journal {journal_id} sigue existiendo después de DELETE."}
    except Exception:
        pass  # Expected: 404 means successfully deleted

    await publish_event(
        db=db,
        event_type="cleanup.journals.ejecutado",
        source="agente_contador",
        datos={"journal_id": journal_id, "motivo": motivo},
        alegra_id=str(journal_id),
        accion_ejecutada=f"Journal #{journal_id} anulado. Motivo: {motivo}",
    )
    return {"success": True, "anulado_id": journal_id, "motivo": motivo, "message": f"Journal #{journal_id} anulado exitosamente."}


# ═══════════════════════════════════════════════════════
# HANDLER 5: causar_movimiento_bancario
# ═══════════════════════════════════════════════════════

async def handle_causar_movimiento_bancario(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Classify and cause a bank movement described in chat."""
    validate_write_permission("contador", "POST /journals", "alegra")

    descripcion = tool_input["descripcion"]
    monto = tool_input["monto"]
    banco_id = BANCO_CATEGORY_IDS.get(tool_input.get("banco", ""), "5314")
    fecha = tool_input.get("fecha") or datetime.date.today().isoformat()
    nit = tool_input.get("proveedor_nit")

    tipo, cuenta_gasto = _classify_gasto(descripcion)
    ret = calcular_retenciones(tipo, monto, nit)
    entries = _build_entries(cuenta_gasto, monto, banco_id, ret)
    result = await _post_journal(entries, fecha, _prefix_obs("AC", descripcion), alegra)

    await publish_event(
        db=db,
        event_type="gasto.causado",
        source="agente_contador",
        datos={"alegra_id": result["_alegra_id"], "tipo": tipo, "monto": monto, "origen": "movimiento_bancario"},
        alegra_id=result["_alegra_id"],
        accion_ejecutada=f"Movimiento bancario causado — Journal #{result['_alegra_id']}",
    )
    return {
        "success": True,
        "alegra_id": result["_alegra_id"],
        "message": f"Movimiento causado. Journal #{result['_alegra_id']} — {descripcion}",
    }


# ═══════════════════════════════════════════════════════
# HANDLER 6: registrar_ajuste_contable
# ═══════════════════════════════════════════════════════

async def handle_registrar_ajuste_contable(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Register accounting adjustment between accounts (reclassification)."""
    validate_write_permission("contador", "POST /journals", "alegra")

    cuenta_origen = tool_input["cuenta_origen_id"]
    cuenta_destino = tool_input["cuenta_destino_id"]
    monto = tool_input["monto"]
    motivo = tool_input["motivo"]
    fecha = tool_input.get("fecha") or datetime.date.today().isoformat()

    entries = [
        {"id": str(cuenta_destino), "debit": monto, "credit": 0},
        {"id": str(cuenta_origen), "debit": 0, "credit": monto},
    ]
    result = await _post_journal(entries, fecha, _prefix_obs("AC", f"Ajuste: {motivo}"), alegra)

    await publish_event(
        db=db,
        event_type="gasto.causado",
        source="agente_contador",
        datos={"alegra_id": result["_alegra_id"], "tipo": "ajuste", "motivo": motivo},
        alegra_id=result["_alegra_id"],
        accion_ejecutada=f"Ajuste contable — Journal #{result['_alegra_id']}",
    )
    return {
        "success": True,
        "alegra_id": result["_alegra_id"],
        "message": f"Ajuste registrado. Journal #{result['_alegra_id']} — {motivo}",
    }


# ═══════════════════════════════════════════════════════
# HANDLER 7: registrar_depreciacion
# ═══════════════════════════════════════════════════════

# Art. 137 ET — Vida útil fiscal Colombia (línea recta)
VIDA_UTIL_FISCAL = {
    "edificaciones": {"anios": 20, "mensual_pct": 0.00417},
    "maquinaria": {"anios": 10, "mensual_pct": 0.00833},
    "vehiculos": {"anios": 5, "mensual_pct": 0.01667},
    "equipo_computo": {"anios": 5, "mensual_pct": 0.01667},
    "muebles": {"anios": 10, "mensual_pct": 0.00833},
}

# Alegra accounts per asset type: {gasto_id, contra_activo_id}
DEPRECIACION_CUENTAS = {
    "equipo_computo": {"gasto": "5503", "contra": "5360"},   # 516020 / 15922001
    "muebles": {"gasto": "5502", "contra": "5358"},          # 516015 / 15921501
    "vehiculos": {"gasto": "5504", "contra": "5358"},        # 523040 / fallback 15921501
}


async def handle_registrar_depreciacion(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Register asset depreciation as journal in Alegra."""
    validate_write_permission("contador", "POST /journals", "alegra")

    activo = tool_input["activo"]
    monto = tool_input["monto"]
    periodo = tool_input.get("periodo", "")
    fecha = tool_input.get("fecha") or datetime.date.today().isoformat()
    tipo_activo = tool_input.get("tipo_activo", "equipo_computo")

    # Look up accounts for asset type, fall back to equipo_computo
    cuentas = DEPRECIACION_CUENTAS.get(tipo_activo, DEPRECIACION_CUENTAS["equipo_computo"])

    # Anti-dup: GET /journals checking for existing depreciation with same observation
    obs_text = _prefix_obs("D", f"Depreciación {activo} {periodo}")
    existing = await alegra.get("journals", params={"limit": 100})
    if isinstance(existing, list):
        dup = any(obs_text in j.get("observations", "") for j in existing)
        if dup:
            return {
                "success": False,
                "error": f"Depreciación duplicada: '{obs_text}' ya existe en Alegra.",
            }

    entries = [
        {"id": cuentas["gasto"], "debit": monto, "credit": 0},
        {"id": cuentas["contra"], "debit": 0, "credit": monto},
    ]
    result = await _post_journal(entries, fecha, obs_text, alegra)

    await publish_event(
        db=db,
        event_type="gasto.causado",
        source="agente_contador",
        datos={
            "alegra_id": result["_alegra_id"],
            "tipo": "depreciacion",
            "activo": activo,
            "tipo_activo": tipo_activo,
            "monto": monto,
        },
        alegra_id=result["_alegra_id"],
        accion_ejecutada=f"Depreciación {activo} ({tipo_activo}) {periodo} ${monto:,.0f}",
    )
    return {
        "success": True,
        "alegra_id": result["_alegra_id"],
        "message": f"Depreciación registrada. Journal #{result['_alegra_id']} — {activo} ({tipo_activo}) {periodo}",
    }
