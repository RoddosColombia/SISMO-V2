"""
Sprint 8 — Contabilidad DataKeeper handlers.

Event-driven integration: Loanbook → Contador via event bus.

cuota.pagada → create ingreso journal in Alegra
loanbook.saldado → update CRM client to saldado + publish credito.cerrado

These are DataKeeper INFRASTRUCTURE handlers, NOT agent tools.
They use AlegraClient directly because the DataKeeper has permission
to create ingreso journals for cuota payments (ROG-4 compliant).

CUENTAS ALEGRA:
- 5456: Ingresos Financiacion Motos (credito — ingreso por cuotas + capital)
- 5314/5315/5318/5319/5321/5322/5536: Bancos (debito — donde se recibe el pago)
- CUENTA_ANZI: CXP ANZI garante (credito — porcentaje para garante)
- CUENTA_MORA: Ingresos por mora (credito — intereses moratorios)
"""
import logging
import uuid
from datetime import date, datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.event_handlers import on_event

logger = logging.getLogger("datakeeper.contabilidad")

# ═══════════════════════════════════════════
# Alegra account IDs
# ═══════════════════════════════════════════

CUENTA_INGRESO_FINANCIACION = "5456"  # Ingresos Intereses Financiacion Motos
CUENTA_ANZI = "5330"  # CXP ANZI (garante) — por pagar al garante
CUENTA_MORA = "5457"  # Ingresos por mora / intereses moratorios

# Valid banco IDs
BANCOS_VALIDOS = {"5314", "5315", "5318", "5319", "5321", "5322", "5536"}


# ═══════════════════════════════════════════
# Handler 1: cuota.pagada → journal en Alegra
# ═══════════════════════════════════════════

@on_event("cuota.pagada", critical=True)
async def handle_cuota_pagada_contabilidad(event: dict, db: AsyncIOMotorDatabase, alegra=None):
    """
    Create ingreso journal in Alegra when a cuota is paid.

    Journal structure (partida doble):
      D: Banco (monto_total)
      C: Ingresos Financiacion 5456 (cuota_corriente + vencidas + capital_extra)
      C: CXP ANZI (anzi) — if > 0
      C: Ingresos Mora (mora) — if > 0

    Args:
        event: cuota.pagada event from roddos_events
        db: MongoDB database
        alegra: AlegraClient instance (injected by DataKeeper or test)

    Raises:
        AlegraError: If Alegra POST fails → DLQ will retry
    """
    datos = event["datos"]

    # Extract fields from enriched event
    loanbook_id = datos.get("loanbook_id", "")
    vin = datos.get("vin", "")
    cliente_nombre = datos.get("cliente_nombre", "")
    cuota_numero = datos.get("cuota_numero")
    monto_total = datos["monto_total_pagado"]
    desglose = datos["desglose"]
    banco_recibo = datos.get("banco_recibo", "5314")
    fecha_pago = datos["fecha_pago"]
    modelo_moto = datos.get("modelo_moto", "")
    plan_codigo = datos.get("plan_codigo", "")

    cuota_corriente = desglose.get("cuota_corriente", 0)
    vencidas = desglose.get("vencidas", 0)
    anzi = desglose.get("anzi", 0)
    mora = desglose.get("mora", 0)
    capital_extra = desglose.get("capital_extra", 0)

    # Validate banco
    if banco_recibo not in BANCOS_VALIDOS:
        banco_recibo = "5314"  # Fallback Bancolombia 2029

    # ─── Build journal entries (partida doble) ───
    entries = []

    # DEBIT: Banco — full amount received
    entries.append({
        "id": banco_recibo,
        "debit": monto_total,
        "credit": 0,
    })

    # CREDIT: Ingreso Financiacion — cuota + vencidas + capital
    ingreso_monto = cuota_corriente + vencidas + capital_extra
    if ingreso_monto > 0:
        entries.append({
            "id": CUENTA_INGRESO_FINANCIACION,
            "debit": 0,
            "credit": ingreso_monto,
        })

    # CREDIT: ANZI (if > 0)
    if anzi > 0:
        entries.append({
            "id": CUENTA_ANZI,
            "debit": 0,
            "credit": anzi,
        })

    # CREDIT: Mora (if > 0)
    if mora > 0:
        entries.append({
            "id": CUENTA_MORA,
            "debit": 0,
            "credit": mora,
        })

    # ─── Build observations ───
    cuota_label = f"Cuota #{cuota_numero}" if cuota_numero else "Cuota"
    observations = (
        f"[RDX] {cuota_label} {cliente_nombre} — "
        f"{modelo_moto} Plan {plan_codigo} — "
        f"${monto_total:,.0f}"
    )

    # ─── Call Alegra ───
    payload = {
        "date": fecha_pago,
        "entries": entries,
        "observations": observations,
    }

    logger.info(
        f"Creating journal for cuota.pagada: VIN {vin}, "
        f"${monto_total:,.0f}, banco {banco_recibo}"
    )

    # request_with_verify: POST /journals → GET verification → returns with alegra_id
    result = await alegra.request_with_verify(
        endpoint="journals",
        method="POST",
        payload=payload,
    )

    alegra_id = str(result.get("_alegra_id") or result.get("id", ""))

    # ─── Publish ingreso.cuota.registrado event ───
    await db.roddos_events.insert_one({
        "event_id": str(uuid.uuid4()),
        "event_type": "ingreso.cuota.registrado",
        "source": "datakeeper.contabilidad",
        "correlation_id": event.get("correlation_id", str(uuid.uuid4())),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "datos": {
            "loanbook_id": loanbook_id,
            "vin": vin,
            "cuota_numero": cuota_numero,
            "monto_total": monto_total,
            "banco_recibo": banco_recibo,
        },
        "alegra_id": alegra_id,
        "accion_ejecutada": (
            f"Journal ingreso ${monto_total:,.0f} VIN {vin} — Alegra ID {alegra_id}"
        ),
    })

    logger.info(
        f"Journal created: Alegra ID {alegra_id} for VIN {vin}, "
        f"${monto_total:,.0f}"
    )


# ═══════════════════════════════════════════
# Handler 2: loanbook.saldado → CRM + cierre
# ═══════════════════════════════════════════

@on_event("loanbook.saldado", critical=True)
async def handle_loanbook_saldado(event: dict, db: AsyncIOMotorDatabase, alegra=None):
    """
    When a credit is fully paid:
    - Update CRM client estado to 'saldado'
    - Publish credito.cerrado event for CFO/audit trail
    """
    datos = event["datos"]
    loanbook_id = datos.get("loanbook_id", "")
    vin = datos.get("vin", "")
    cliente_cedula = datos.get("cliente_cedula", "")
    cliente_nombre = datos.get("cliente_nombre", "")

    # Update CRM client
    await db.crm_clientes.update_one(
        {"cedula": cliente_cedula},
        {"$set": {
            "estado": "saldado",
            "updated_at": date.today().isoformat(),
        }},
    )

    # Publish credito.cerrado event
    await db.roddos_events.insert_one({
        "event_id": str(uuid.uuid4()),
        "event_type": "credito.cerrado",
        "source": "datakeeper.contabilidad",
        "correlation_id": event.get("correlation_id", str(uuid.uuid4())),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "datos": {
            "loanbook_id": loanbook_id,
            "vin": vin,
            "cliente_cedula": cliente_cedula,
            "cliente_nombre": cliente_nombre,
        },
        "alegra_id": None,
        "accion_ejecutada": f"Credito cerrado VIN {vin} — cliente {cliente_nombre}",
    })

    logger.info(
        f"Credito cerrado: VIN {vin}, cliente {cliente_nombre} ({cliente_cedula})"
    )
