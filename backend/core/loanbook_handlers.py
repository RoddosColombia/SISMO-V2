"""
Sprint 3 — 3 Momentos del Crédito: DataKeeper handlers.

Momento 1: apartado.completo → create loanbook + mark moto apartada
Momento 2: entrega.realizada → activate loanbook (pendiente_entrega → activo)
Momento 3: pago.cuota.recibido → apply waterfall, update cuotas, recalc estado

All handlers are CRITICAL — loanbook writes are on the critical path.
They use pure domain logic from loanbook_model.py and write to MongoDB.
"""
import logging
from datetime import date
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.event_handlers import on_event
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
