"""
Sprint 3 — 3 Momentos del Crédito: DataKeeper handlers.

Momento 1: apartado.completo → create loanbook + mark moto apartada
Momento 1-bis: factura.venta.creada → create loanbook pendiente_entrega
               (venta directa sin separación)
Momento 2: entrega.realizada → activate loanbook (pendiente_entrega → activo)
Momento 3: pago.cuota.recibido → apply waterfall, update cuotas, recalc estado

All handlers are CRITICAL — loanbook writes are on the critical path.
They use pure domain logic from loanbook_model.py and write to MongoDB.
"""
import logging
import uuid
from datetime import date, datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.event_handlers import on_event
from core.events import publish_event
from core.loanbook_model import (
    crear_loanbook,
    is_valid_transition,
    aplicar_waterfall,
    calcular_dpd,
    estado_from_dpd,
    calcular_mora,
    calcular_cronograma,
    asignar_cronograma,
)

logger = logging.getLogger("datakeeper.loanbook")


# ═══════════════════════════════════════════
# Momento 1-bis: Factura venta directa
# ═══════════════════════════════════════════


async def _next_loanbook_id(db: AsyncIOMotorDatabase) -> str:
    """Generate LB-YYYY-NNN next sequential id."""
    year = date.today().year
    prefix = f"LB-{year}-"
    last = await db.loanbook.find(
        {"loanbook_id": {"$regex": f"^{prefix}"}}
    ).sort("loanbook_id", -1).limit(1).to_list(length=1)
    next_num = 1
    if last:
        try:
            tail = last[0]["loanbook_id"].split("-")[-1]
            next_num = int(tail) + 1
        except (ValueError, IndexError, KeyError):
            next_num = 1
    return f"{prefix}{next_num:04d}"


@on_event("factura.venta.creada", critical=True)
async def handle_factura_venta_creada(event: dict, db: AsyncIOMotorDatabase):
    """
    Create a loanbook in pendiente_entrega when the Contador creates an invoice
    directly (flujo sin separación previa, e.g. promo "sin cuota inicial").

    Preconditions:
      - The Contador already posted the invoice to Alegra (alegra_id in event)
      - We must NOT double-process: idempotent by VIN

    Output:
      - Loanbook created in pendiente_entrega, cuotas=[] (populated on entrega)
      - Publishes loanbook.creado so the CRM listener upserts the client
    """
    datos = event["datos"]
    vin = (datos.get("vin") or "").strip()
    if not vin:
        logger.warning("factura.venta.creada sin VIN — skip loanbook creation")
        return

    # Idempotency — a loanbook per VIN
    existing = await db.loanbook.find_one({"vin": vin})
    if existing:
        logger.info(
            f"factura.venta.creada: loanbook ya existe para VIN {vin} "
            f"({existing.get('loanbook_id')}) — no-op"
        )
        return

    loanbook_id = await _next_loanbook_id(db)
    now = datetime.now(timezone.utc).isoformat()
    cliente_nombre = datos.get("cliente_nombre", "")
    cliente_cedula = datos.get("cliente_cedula", "")
    cliente_tel = datos.get("cliente_telefono", "")
    cliente_dir = datos.get("cliente_direccion", "")
    modelo = datos.get("modelo", "")
    motor = datos.get("motor", "")
    plan_codigo = datos.get("plan", "P52S")
    modalidad = datos.get("modalidad", "semanal")
    cuota_monto = int(datos.get("cuota_monto") or 0)
    num_cuotas = int(datos.get("num_cuotas") or 0)
    cuota_inicial = int(datos.get("cuota_inicial") or 0)
    modo_promocion = bool(datos.get("modo_promocion", False))
    alegra_factura_id = datos.get("alegra_id") or event.get("alegra_id")
    alegra_factura_number = datos.get("alegra_invoice_number")
    fecha_factura = datos.get("fecha") or date.today().isoformat()
    rubros = datos.get("rubros") or {}
    valor_factura = int(datos.get("valor_factura") or 0)

    doc = {
        "loanbook_id": loanbook_id,
        "tipo_producto": "moto",
        "cliente": {
            "nombre": cliente_nombre,
            "cedula": cliente_cedula,
            "telefono": cliente_tel,
            "direccion": cliente_dir,
            "telefono_alternativo": None,
        },
        "moto": {"modelo": modelo, "vin": vin, "motor": motor},
        "plan": {
            "codigo": plan_codigo,
            "modalidad": modalidad,
            "cuota_valor": cuota_monto,
            "cuota_inicial": cuota_inicial,
            "total_cuotas": num_cuotas,
        },
        "fechas": {
            "factura": fecha_factura,
            "entrega": None,
            "primera_cuota": None,
        },
        "cuotas": [],
        "estado": "pendiente_entrega",
        "valor_total": num_cuotas * cuota_monto if num_cuotas and cuota_monto else valor_factura,
        "saldo_pendiente": num_cuotas * cuota_monto if num_cuotas and cuota_monto else valor_factura,
        "cuotas_pagadas": 0,
        "cuotas_vencidas": 0,
        "cuotas_total": num_cuotas,
        "alegra_factura_id": alegra_factura_number or str(alegra_factura_id or ""),
        "alegra_invoice_alegra_id": str(alegra_factura_id or ""),
        "rubros_adicionales": rubros,
        "modo_promocion": modo_promocion,
        # Compat fields
        "vin": vin,
        "modelo": modelo,
        "modalidad": modalidad,
        "plan_codigo": plan_codigo,
        "cuota_monto": cuota_monto,
        "num_cuotas": num_cuotas,
        "saldo_capital": num_cuotas * cuota_monto if num_cuotas and cuota_monto else valor_factura,
        "total_pagado": 0,
        "total_mora_pagada": 0,
        "total_anzi_pagado": 0,
        "anzi_pct": 0.02,
        "fecha_entrega": None,
        "fecha_primer_pago": None,
        "created_at": now,
        "origen": "factura_venta_directa",
        "correlation_id": event.get("correlation_id"),
    }

    await db.loanbook.insert_one(doc)
    logger.info(
        f"Loanbook creado via factura.venta.creada: {loanbook_id} VIN {vin} "
        f"plan {plan_codigo} promo={modo_promocion}"
    )

    # Publish loanbook.creado so CRM listener upserts client
    await publish_event(
        db=db,
        event_type="loanbook.creado",
        source="datakeeper.loanbook",
        datos={
            "loanbook_id": loanbook_id,
            "vin": vin,
            "cliente": {
                "nombre": cliente_nombre,
                "cedula": cliente_cedula,
                "telefono": cliente_tel,
                "direccion": cliente_dir,
            },
        },
        alegra_id=None,
        accion_ejecutada=f"Loanbook {loanbook_id} creado via factura.venta.creada",
        correlation_id=event.get("correlation_id"),
    )


# ═══════════════════════════════════════════
# Momento 1: Apartado Completo
# ═══════════════════════════════════════════


@on_event("apartado.completo", critical=True)
async def handle_apartado_completo(event: dict, db: AsyncIOMotorDatabase):
    """
    Create a loanbook when apartado is complete.
    Fetches plan from catalogo_planes, creates loanbook doc, marks moto as apartada.
    """
    datos = event["datos"]
    vin = datos["vin"]
    cliente = datos["cliente"]
    plan_codigo = datos["plan_codigo"]
    modelo = datos["modelo"]
    modalidad = datos["modalidad"]
    fecha_entrega = date.fromisoformat(datos["fecha_entrega"])
    fecha_primer_pago_str = datos.get("fecha_primer_pago")
    fecha_primer_pago = date.fromisoformat(fecha_primer_pago_str) if fecha_primer_pago_str else None

    # Fetch plan from catalogo_planes
    plan = await db.catalogo_planes.find_one({"codigo": plan_codigo})
    if not plan:
        raise ValueError(f"Plan '{plan_codigo}' no encontrado en catalogo_planes.")

    # Create loanbook using pure domain logic (validates contado, modelo, fecha)
    lb = crear_loanbook(
        vin=vin,
        cliente=cliente,
        plan=plan,
        modelo=modelo,
        modalidad=modalidad,
        fecha_entrega=fecha_entrega,
        fecha_primer_pago=fecha_primer_pago,
    )

    # Persist to MongoDB
    await db.loanbook.insert_one(lb)

    # Mark moto as apartada in inventory
    await db.inventario_motos.update_one(
        {"vin": vin},
        {"$set": {"estado": "apartada"}},
    )

    # Publish loanbook.creado event for CRM sync
    await db.roddos_events.insert_one({
        "event_id": str(uuid.uuid4()),
        "event_type": "loanbook.creado",
        "source": "datakeeper.loanbook",
        "correlation_id": event.get("correlation_id", str(uuid.uuid4())),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "datos": {
            "loanbook_id": lb["loanbook_id"],
            "vin": vin,
            "cliente": cliente,
        },
        "alegra_id": None,
        "accion_ejecutada": f"Loanbook creado para VIN {vin}",
    })

    logger.info(
        f"Momento 1: Loanbook created for VIN {vin} — "
        f"plan={plan_codigo}, modalidad={modalidad}, cuotas={lb['num_cuotas']}"
    )


# ═══════════════════════════════════════════
# Momento 2: Entrega Realizada
# ═══════════════════════════════════════════


@on_event("entrega.realizada", critical=True)
async def handle_entrega_realizada(event: dict, db: AsyncIOMotorDatabase):
    """
    Activate loanbook on motorcycle delivery.
    Transitions pendiente_entrega → activo, marks moto as vendida.
    """
    datos = event["datos"]
    vin = datos["vin"]

    # Find loanbook
    lb = await db.loanbook.find_one({"vin": vin})
    if not lb:
        raise ValueError(f"No existe loanbook para VIN {vin}.")

    # Validate state transition
    current_estado = lb["estado"]
    if not is_valid_transition(current_estado, "activo"):
        raise ValueError(
            f"Transición inválida: {current_estado} → activo "
            f"para VIN {vin}."
        )

    # Calculate cronograma (Wednesday Rule)
    fecha_entrega = date.fromisoformat(lb["fecha_entrega"])
    modalidad = lb["modalidad"]
    num_cuotas = lb["num_cuotas"]
    fecha_primer_pago_str = lb.get("fecha_primer_pago")
    fecha_primer_pago = date.fromisoformat(fecha_primer_pago_str) if fecha_primer_pago_str else None

    cronograma = calcular_cronograma(
        fecha_entrega=fecha_entrega,
        modalidad=modalidad,
        num_cuotas=num_cuotas,
        fecha_primer_pago=fecha_primer_pago,
    )

    # Assign dates to cuotas
    resultado = asignar_cronograma(lb["cuotas"], cronograma)

    # Update loanbook: state + cronograma
    await db.loanbook.update_one(
        {"vin": vin},
        {"$set": {
            "estado": "activo",
            "fecha_activacion": event["timestamp"],
            "cuotas": resultado["cuotas"],
            "fecha_primera_cuota": resultado["fecha_primera_cuota"],
            "fecha_ultima_cuota": resultado["fecha_ultima_cuota"],
        }},
    )

    # Mark moto as vendida
    await db.inventario_motos.update_one(
        {"vin": vin},
        {"$set": {
            "estado": "vendida",
            "fecha_venta": event["timestamp"],
        }},
    )

    logger.info(
        f"Momento 2: Loanbook activated for VIN {vin} — "
        f"cronograma {resultado['fecha_primera_cuota']} → {resultado['fecha_ultima_cuota']}"
    )


# ═══════════════════════════════════════════
# Momento 3: Pago de Cuota
# ═══════════════════════════════════════════


@on_event("pago.cuota.recibido", critical=True)
async def handle_pago_cuota(event: dict, db: AsyncIOMotorDatabase):
    """
    Apply payment using waterfall allocation.
    Updates cuotas, saldo_capital, totals, and derives new estado from DPD.
    """
    datos = event["datos"]
    vin = datos["vin"]
    monto_pago = datos["monto_pago"]
    fecha_pago_str = datos["fecha_pago"]
    fecha_pago = date.fromisoformat(fecha_pago_str)

    # Find loanbook
    lb = await db.loanbook.find_one({"vin": vin})
    if not lb:
        raise ValueError(f"No existe loanbook para VIN {vin}.")

    cuotas = lb["cuotas"]
    anzi_pct = lb.get("anzi_pct", 0.02)

    # Calculate mora for overdue unpaid cuotas
    mora_pendiente = 0
    for cuota in cuotas:
        if cuota["estado"] == "pagada":
            continue
        if cuota.get("fecha"):
            fecha_cuota = date.fromisoformat(cuota["fecha"])
            mora = calcular_mora(fecha_cuota, fecha_pago)
            cuota["mora_acumulada"] = mora
            mora_pendiente += mora

    # Identify vencidas (overdue unpaid cuotas)
    cuotas_vencidas_total = 0
    for cuota in cuotas:
        if cuota["estado"] == "pagada":
            continue
        if cuota.get("fecha"):
            fecha_cuota = date.fromisoformat(cuota["fecha"])
            if fecha_cuota < fecha_pago:
                cuotas_vencidas_total += cuota["monto"]

    # Find current cuota (first unpaid non-overdue, or first unpaid)
    cuota_corriente_monto = 0
    for cuota in cuotas:
        if cuota["estado"] != "pagada":
            if cuota.get("fecha"):
                fecha_cuota = date.fromisoformat(cuota["fecha"])
                if fecha_cuota >= fecha_pago:
                    cuota_corriente_monto = cuota["monto"]
                    break
            else:
                cuota_corriente_monto = cuota["monto"]
                break

    saldo_capital = lb["saldo_capital"]

    # Apply waterfall
    allocation = aplicar_waterfall(
        monto_pago=monto_pago,
        anzi_pct=anzi_pct,
        mora_pendiente=mora_pendiente,
        cuotas_vencidas_total=cuotas_vencidas_total,
        cuota_corriente=cuota_corriente_monto,
        saldo_capital=saldo_capital,
    )

    # Mark cuotas as paid based on waterfall allocation
    remaining_for_vencidas = allocation["vencidas"]
    remaining_for_corriente = allocation["corriente"]

    for cuota in cuotas:
        if cuota["estado"] == "pagada":
            continue

        if cuota.get("fecha"):
            fecha_cuota = date.fromisoformat(cuota["fecha"])

            # Pay overdue cuotas
            if fecha_cuota < fecha_pago and remaining_for_vencidas >= cuota["monto"]:
                cuota["estado"] = "pagada"
                cuota["fecha_pago"] = fecha_pago_str
                cuota["mora_acumulada"] = 0
                remaining_for_vencidas -= cuota["monto"]
                continue

            # Pay current cuota
            if fecha_cuota >= fecha_pago and remaining_for_corriente >= cuota["monto"]:
                cuota["estado"] = "pagada"
                cuota["fecha_pago"] = fecha_pago_str
                cuota["mora_acumulada"] = 0
                remaining_for_corriente -= cuota["monto"]
                break  # Only pay one current cuota per payment
        else:
            # Cuota without date — pay if we have corriente allocation
            if remaining_for_corriente >= cuota["monto"]:
                cuota["estado"] = "pagada"
                cuota["fecha_pago"] = fecha_pago_str
                remaining_for_corriente -= cuota["monto"]
                break

    # Update totals
    new_saldo = saldo_capital - allocation["corriente"] - allocation["vencidas"] - allocation["capital"]
    new_total_pagado = lb["total_pagado"] + monto_pago
    new_total_mora = lb["total_mora_pagada"] + allocation["mora"]
    new_total_anzi = lb["total_anzi_pagado"] + allocation["anzi"]

    # Derive new estado from DPD
    dpd = calcular_dpd(cuotas, fecha_pago)
    new_estado = estado_from_dpd(dpd)

    # Persist all updates
    await db.loanbook.update_one(
        {"vin": vin},
        {"$set": {
            "cuotas": cuotas,
            "saldo_capital": max(new_saldo, 0),
            "total_pagado": new_total_pagado,
            "total_mora_pagada": new_total_mora,
            "total_anzi_pagado": new_total_anzi,
            "estado": new_estado,
        }},
    )

    logger.info(
        f"Momento 3: Pago ${monto_pago:,.0f} applied to VIN {vin} — "
        f"ANZI={allocation['anzi']}, mora={allocation['mora']}, "
        f"corriente={allocation['corriente']}, estado={new_estado}"
    )
