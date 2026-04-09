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

BANCO_IDS = {
    "Bancolombia": 111005,
    "BBVA": 111010,
    "Davivienda": 111015,
    "Banco de Bogotá": 111020,
    "Banco de Bogota": 111020,
    "Global66": 11100507,
}

TIPO_GASTO_MAP = {
    "arriend": ("arriendo", 5480),
    "servicio": ("servicios", 5484),
    "honorar": ("honorarios_pn", 5470),
    "telefon": ("servicios", 5487),
    "internet": ("servicios", 5487),
    "seguro": ("servicios", 5510),
    "mantenim": ("servicios", 5490),
    "transport": ("servicios", 5491),
    "papeler": ("servicios", 5497),
    "publicid": ("servicios", 5500),
    "comision": ("servicios", 5508),
    "interes": ("servicios", 5533),
}

TIPO_RECURRENTE_MAP = {
    "arriendo": ("arriendo", 5480),
    "servicios_publicos": ("servicios", 5484),
    "telefonia": ("servicios", 5487),
    "seguros": ("servicios", 5510),
    "mantenimiento": ("servicios", 5490),
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


def _classify_gasto(descripcion: str, tipo_persona: str | None = None) -> tuple[str, int]:
    """Classify expense type and account ID from description."""
    desc_lower = descripcion.lower()
    for keyword, (tipo, cuenta) in TIPO_GASTO_MAP.items():
        if keyword in desc_lower:
            if keyword == "honorar" and tipo_persona == "juridica":
                return "honorarios_pj", cuenta
            return tipo, cuenta
    return "servicios", 5493  # FALLBACK — NUNCA 5495


def _build_entries(cuenta_gasto: int, monto: float, banco_id: int, ret: dict) -> list[dict]:
    """Build balanced journal entries with retenciones."""
    entries = [
        {"account": {"id": cuenta_gasto}, "debit": monto, "credit": 0},
        {"account": {"id": banco_id}, "debit": 0, "credit": ret["neto_a_pagar"]},
    ]
    if ret["retefuente_monto"] > 0:
        entries.append({"account": {"id": 236505}, "debit": 0, "credit": ret["retefuente_monto"]})
    if ret["reteica_monto"] > 0:
        entries.append({"account": {"id": 236560}, "debit": 0, "credit": ret["reteica_monto"]})
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

    entries = [{"account": {"id": e["id"]}, "debit": e["debit"], "credit": e["credit"]} for e in raw_entries]
    result = await _post_journal(entries, tool_input["date"], tool_input["observations"], alegra)

    await publish_event(
        db=db,
        event_type="gasto.causado",
        source="agente_contador",
        datos={"alegra_id": result["_alegra_id"], "entries": len(entries), "observations": tool_input["observations"]},
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
    banco_id = BANCO_IDS.get(tool_input["banco"], 111005)
    fecha = tool_input.get("fecha") or datetime.date.today().isoformat()
    descripcion = tool_input["descripcion"]
    nit = tool_input.get("proveedor_nit")

    # CXC socio check
    socio_cc = _detect_socio(tool_input)
    if socio_cc:
        socio_name = SOCIOS_CC[socio_cc]
        entries = [
            {"account": {"id": 1305}, "debit": monto, "credit": 0},  # CXC Socio
            {"account": {"id": banco_id}, "debit": 0, "credit": monto},
        ]
        result = await _post_journal(entries, fecha, f"CXC Socio {socio_name}: {descripcion}", alegra)
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
    result = await _post_journal(entries, fecha, descripcion, alegra)

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
    tipo, cuenta_gasto = TIPO_RECURRENTE_MAP.get(tipo_gasto, ("servicios", 5493))
    monto = tool_input["monto"]
    banco_id = BANCO_IDS.get(tool_input["banco"], 111005)
    fecha = tool_input.get("fecha") or datetime.date.today().isoformat()
    nit = tool_input.get("proveedor_nit")
    periodo = tool_input.get("periodo", "")

    ret = calcular_retenciones(tipo, monto, nit)
    entries = _build_entries(cuenta_gasto, monto, banco_id, ret)
    result = await _post_journal(entries, fecha, f"{tipo_gasto} {periodo}", alegra)

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
    banco_id = BANCO_IDS.get(tool_input.get("banco", ""), 111005)
    fecha = tool_input.get("fecha") or datetime.date.today().isoformat()
    nit = tool_input.get("proveedor_nit")

    tipo, cuenta_gasto = _classify_gasto(descripcion)
    ret = calcular_retenciones(tipo, monto, nit)
    entries = _build_entries(cuenta_gasto, monto, banco_id, ret)
    result = await _post_journal(entries, fecha, descripcion, alegra)

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
        {"account": {"id": cuenta_destino}, "debit": monto, "credit": 0},
        {"account": {"id": cuenta_origen}, "debit": 0, "credit": monto},
    ]
    result = await _post_journal(entries, fecha, f"Ajuste: {motivo}", alegra)

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

    entries = [
        {"account": {"id": 5493}, "debit": monto, "credit": 0},  # Gasto depreciacion
        {"account": {"id": 5493}, "debit": 0, "credit": monto},  # Contra activo (fallback)
    ]
    result = await _post_journal(entries, fecha, f"Depreciación {activo} {periodo}", alegra)

    await publish_event(
        db=db,
        event_type="gasto.causado",
        source="agente_contador",
        datos={"alegra_id": result["_alegra_id"], "tipo": "depreciacion", "activo": activo, "monto": monto},
        alegra_id=result["_alegra_id"],
        accion_ejecutada=f"Depreciación {activo} {periodo} ${monto:,.0f}",
    )
    return {
        "success": True,
        "alegra_id": result["_alegra_id"],
        "message": f"Depreciación registrada. Journal #{result['_alegra_id']} — {activo} {periodo}",
    }
