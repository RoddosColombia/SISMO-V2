"""
Wave 2 (Phase 3) — 5 conciliacion handlers.

REGLAS:
- Confianza >= 0.70 → auto-cause via request_with_verify
- Confianza < 0.70 → Backlog directo (sin WhatsApp por ahora)
- Anti-dup 3 capas: hash extracto + hash movimiento + GET Alegra (via request_with_verify)
- BackgroundTasks + job_id para lotes > 10 movimientos
- MongoDB writes ONLY to: backlog_movimientos, conciliacion_jobs, roddos_events
"""
import datetime
import uuid
from typing import Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from services.alegra.client import AlegraClient
from core.permissions import validate_write_permission
from core.events import publish_event
from services.retenciones import calcular_retenciones
from services.bank_parsers import detect_bank, parse_bancolombia, parse_bbva, parse_davivienda, parse_nequi
from services.anti_duplicados import (
    hash_extracto, hash_movimiento,
    check_extracto_duplicado, check_movimiento_duplicado,
    registrar_extracto_procesado, registrar_movimiento_procesado,
)

CONFIDENCE_THRESHOLD = 0.70

# Alegra category IDs for journal entries
BANCO_CATEGORY_IDS = {
    "Bancolombia": "5314", "BBVA": "5319", "Davivienda": "5322",
    "Banco de Bogotá": "5321", "Banco de Bogota": "5321",
    "Nequi": "5314", "Global66": "5536",
}

PARSERS = {
    "bancolombia": parse_bancolombia,
    "bbva": parse_bbva,
    "davivienda": parse_davivienda,
    "nequi": parse_nequi,
}

# Classification patterns with confidence
CLASSIFICATION_RULES: list[tuple[str, str, int, float]] = [
    # (keyword, tipo, cuenta_id, confianza)
    ("gravamen", "impuesto_4x1000", 5505, 1.0),
    ("arriend", "arriendo", 5480, 0.90),
    ("servicio", "servicios", 5484, 0.85),
    ("telefon", "servicios", 5487, 0.85),
    ("internet", "servicios", 5487, 0.85),
    ("honorar", "honorarios_pn", 5470, 0.80),
    ("seguro", "servicios", 5510, 0.80),
    ("mantenim", "servicios", 5490, 0.80),
    ("transport", "servicios", 5491, 0.75),
    ("publicid", "servicios", 5500, 0.75),
    ("comision", "servicios", 5508, 0.80),
    ("interes", "servicios", 5533, 0.75),
    ("papeler", "servicios", 5497, 0.75),
    ("nomina", "servicios", 5462, 0.85),
    ("sueldo", "servicios", 5462, 0.85),
]

SOCIOS_CC = {"80075452": "Andrés Sanjuan", "80086601": "Iván Echeverri"}


def _classify_movement(descripcion: str, monto: float) -> dict:
    """Classify a bank movement with confidence 0-1."""
    desc_lower = descripcion.lower()

    # Socio detection — always CXC, confianza 1.0
    for cc, nombre in SOCIOS_CC.items():
        if cc in desc_lower or nombre.lower().split()[0] in desc_lower:
            return {"tipo": "cxc_socio", "cuenta_id": 1305, "confianza": 1.0, "socio_cc": cc}

    # Rule-based classification
    for keyword, tipo, cuenta_id, conf in CLASSIFICATION_RULES:
        if keyword in desc_lower:
            return {"tipo": tipo, "cuenta_id": cuenta_id, "confianza": conf}

    # Fallback — low confidence
    return {"tipo": "sin_clasificar", "cuenta_id": 5493, "confianza": 0.30}


async def handle_conciliar_extracto_bancario(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Upload extract → parse → classify → cause/backlog. (CONC-01, CONC-02, CONC-03)"""
    validate_write_permission("contador", "POST /journals", "alegra")

    file_path = tool_input["archivo_path"]
    banco_hint = tool_input.get("banco")

    # Detect bank
    try:
        banco = banco_hint or detect_bank(file_path)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    # Read file for anti-dup Capa 1
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    file_hash = hash_extracto(file_bytes)

    if await check_extracto_duplicado(db, file_hash):
        return {"success": False, "error": f"Este extracto ya fue procesado (hash: {file_hash[:8]}...). Anti-duplicados Capa 1."}

    # Parse
    parser = PARSERS.get(banco.lower())
    if not parser:
        return {"success": False, "error": f"Parser no disponible para banco: {banco}"}

    try:
        movements = parser(file_path)
    except Exception as e:
        return {"success": False, "error": f"Error parseando extracto {banco}: {str(e)}"}

    if not movements:
        return {"success": False, "error": "El extracto no contiene movimientos."}

    # Register extract as processed (Capa 1)
    await registrar_extracto_procesado(db, file_hash, banco, len(movements))

    # Process movements
    job_id = str(uuid.uuid4())[:8]
    causados = 0
    backlog_count = 0
    duplicados = 0
    errores = 0

    # Store job state (MongoDB operational — allowed)
    await db.conciliacion_jobs.insert_one({
        "job_id": job_id,
        "banco": banco,
        "total": len(movements),
        "estado": "procesando",
        "causados": 0,
        "backlog": 0,
        "duplicados": 0,
        "errores": 0,
        "fecha_inicio": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })

    for mov in movements:
        # Anti-dup Capa 2
        mov_hash = hash_movimiento(mov["fecha"], mov["descripcion"], mov["monto"])
        if await check_movimiento_duplicado(db, mov_hash):
            duplicados += 1
            continue

        # Classify
        classification = _classify_movement(mov["descripcion"], mov["monto"])

        if classification["confianza"] >= CONFIDENCE_THRESHOLD:
            # Auto-cause
            try:
                banco_id = BANCO_CATEGORY_IDS.get(banco.capitalize(), "5314")
                ret = calcular_retenciones(classification["tipo"], mov["monto"])

                entries = [
                    {"id": str(classification["cuenta_id"]), "debit": mov["monto"], "credit": 0},
                    {"id": str(banco_id), "debit": 0, "credit": ret["neto_a_pagar"]},
                ]
                if ret["retefuente_monto"] > 0:
                    entries.append({"id": ret["retefuente_alegra_id"], "debit": 0, "credit": ret["retefuente_monto"]})
                if ret["reteica_monto"] > 0:
                    entries.append({"id": ret["reteica_alegra_id"], "debit": 0, "credit": ret["reteica_monto"]})

                payload = {
                    "date": mov["fecha"],
                    "observations": f"Conciliación {banco}: {mov['descripcion']}",
                    "entries": entries,
                }
                result = await alegra.request_with_verify("journals", "POST", payload=payload)
                await registrar_movimiento_procesado(db, mov_hash, result["_alegra_id"])
                await publish_event(
                    db=db,
                    event_type="gasto.causado",
                    source="agente_contador",
                    datos={"alegra_id": result["_alegra_id"], "origen": "conciliacion", "banco": banco},
                    alegra_id=result["_alegra_id"],
                    accion_ejecutada=f"Conciliación auto {banco}: {mov['descripcion'][:50]}",
                )
                causados += 1
            except Exception:
                errores += 1
                # Route to backlog on error
                await db.backlog_movimientos.insert_one({
                    "fecha": mov["fecha"],
                    "banco": banco,
                    "descripcion": mov["descripcion"],
                    "monto": mov["monto"],
                    "tipo": mov["tipo"],
                    "razon_pendiente": "Error al causar en Alegra",
                    "intentos": 1,
                    "estado": "pendiente",
                    "fecha_ingreso_backlog": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "job_id": job_id,
                })
                backlog_count += 1
        else:
            # Low confidence → Backlog
            await db.backlog_movimientos.insert_one({
                "fecha": mov["fecha"],
                "banco": banco,
                "descripcion": mov["descripcion"],
                "monto": mov["monto"],
                "tipo": mov["tipo"],
                "razon_pendiente": f"Confianza {classification['confianza']:.2f} < {CONFIDENCE_THRESHOLD}",
                "clasificacion_sugerida": classification,
                "intentos": 0,
                "estado": "pendiente",
                "fecha_ingreso_backlog": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "job_id": job_id,
            })
            backlog_count += 1

    # Update job state
    await db.conciliacion_jobs.update_one(
        {"job_id": job_id},
        {"$set": {
            "estado": "completado",
            "causados": causados,
            "backlog": backlog_count,
            "duplicados": duplicados,
            "errores": errores,
            "fecha_fin": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }},
    )

    return {
        "success": True,
        "job_id": job_id,
        "total": len(movements),
        "causados": causados,
        "backlog": backlog_count,
        "duplicados": duplicados,
        "errores": errores,
        "message": f"Extracto {banco} procesado: {causados} causados, {backlog_count} en backlog, {duplicados} duplicados.",
    }


async def handle_clasificar_movimiento(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Classify single movement with confidence 0-1."""
    descripcion = tool_input["descripcion"]
    monto = tool_input["monto"]
    classification = _classify_movement(descripcion, monto)
    ret = calcular_retenciones(classification["tipo"], monto) if classification["tipo"] != "cxc_socio" else {}

    return {
        "success": True,
        "data": {**classification, "retenciones": ret},
        "message": f"Clasificado como '{classification['tipo']}' con confianza {classification['confianza']:.2f}",
    }


async def handle_enviar_movimiento_backlog(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Route movement to backlog. (BACK-01)"""
    await db.backlog_movimientos.insert_one({
        "fecha": tool_input.get("fecha", datetime.date.today().isoformat()),
        "banco": tool_input.get("banco", ""),
        "descripcion": tool_input.get("descripcion", ""),
        "monto": tool_input.get("monto", 0),
        "tipo": tool_input.get("tipo", "debito"),
        "razon_pendiente": tool_input.get("razon", "Clasificación manual requerida"),
        "intentos": 0,
        "estado": "pendiente",
        "fecha_ingreso_backlog": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    return {"success": True, "message": "Movimiento enviado al Backlog."}


async def handle_causar_desde_backlog(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """Cause a backlog movement via request_with_verify. (BACK-03)"""
    validate_write_permission("contador", "POST /journals", "alegra")

    from bson import ObjectId
    backlog_id = tool_input["backlog_id"]
    cuenta_id = tool_input["cuenta_id"]

    mov = await db.backlog_movimientos.find_one({"_id": ObjectId(backlog_id)})
    if not mov:
        return {"success": False, "error": f"Movimiento {backlog_id} no encontrado en backlog."}

    banco_id = BANCO_CATEGORY_IDS.get(mov.get("banco", ""), "5314")
    retenciones = tool_input.get("retenciones", {})
    retefuente = retenciones.get("retefuente", 0)
    reteica = retenciones.get("reteica", 0)
    neto = mov["monto"] - retefuente - reteica

    entries = [
        {"id": str(cuenta_id), "debit": mov["monto"], "credit": 0},
        {"id": str(banco_id), "debit": 0, "credit": neto},
    ]
    if retefuente > 0:
        entries.append({"id": "5383", "debit": 0, "credit": retefuente})  # 23652501 Ret servicios 4% (default)
    if reteica > 0:
        entries.append({"id": "5392", "debit": 0, "credit": reteica})  # 23680501 RteIca

    try:
        payload = {
            "date": mov["fecha"],
            "observations": f"Backlog: {mov['descripcion']}",
            "entries": entries,
        }
        result = await alegra.request_with_verify("journals", "POST", payload=payload)

        # Update backlog: causado
        await db.backlog_movimientos.update_one(
            {"_id": ObjectId(backlog_id)},
            {"$set": {"estado": "causado", "alegra_id": result["_alegra_id"]}},
        )

        await publish_event(
            db=db,
            event_type="gasto.causado",
            source="agente_contador",
            datos={"alegra_id": result["_alegra_id"], "origen": "backlog", "backlog_id": backlog_id},
            alegra_id=result["_alegra_id"],
            accion_ejecutada=f"Backlog causado — Journal #{result['_alegra_id']}",
        )

        return {
            "success": True,
            "alegra_id": result["_alegra_id"],
            "message": f"Movimiento causado desde Backlog. Journal #{result['_alegra_id']}.",
        }
    except Exception as e:
        await db.backlog_movimientos.update_one(
            {"_id": ObjectId(backlog_id)},
            {"$set": {"estado": "error", "razon_pendiente": str(e)}, "$inc": {"intentos": 1}},
        )
        return {"success": False, "error": f"Error causando desde backlog: {str(e)}"}


async def handle_consultar_movimientos_pendientes(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """List pending backlog movements. Read-only."""
    filtro = {"estado": "pendiente"}
    if tool_input.get("banco"):
        filtro["banco"] = tool_input["banco"]

    cursor = db.backlog_movimientos.find(filtro).sort("fecha_ingreso_backlog", 1).limit(
        tool_input.get("limite", 50)
    )
    movimientos = await cursor.to_list(length=tool_input.get("limite", 50))
    for m in movimientos:
        m["_id"] = str(m["_id"])

    return {"success": True, "data": movimientos, "count": len(movimientos)}
