"""
Loanbook Model V2 — Pure domain logic for motorcycle credit management.

NO MongoDB, NO Alegra, NO FastAPI. Pure functions and data structures
that can be tested without any infrastructure.

Business rules:
- 9 estados: pendiente_entrega → activo → al_dia → en_riesgo → mora → mora_grave → reestructurado → saldado → castigado
- 3 modalidades de crédito: semanal, quincenal, mensual (INDEPENDIENTES del plan)
- contado = venta directa, NO crea loanbook
- Mora: $2,000 COP/dia de atraso desde el DIA SIGUIENTE a fecha de cuota
- ANZI: % de cada cuota va a CXP ANZI (garante) — leido de catalogo_planes
- Waterfall: ANZI → mora → vencidas → corriente → abono capital
- Cuotas: plan define cuotas_base y cuotas_modelo (precio por modelo), modalidad define multiplicador/divisor
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

# ═══════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════

MORA_TASA_DIARIA = 2_000  # $2,000 COP/dia

VENTA_CONTADO = "contado"

# Modalidades de crédito — INDEPENDIENTES del plan
# multiplicador: factor sobre cuota_base del modelo
# divisor: divide cuotas_base del plan para obtener num_cuotas
# dias: intervalo entre cuotas
MODALIDADES: dict[str, dict] = {
    "semanal":    {"multiplicador": 1.0, "divisor": 1, "dias": 7},
    "quincenal":  {"multiplicador": 2.2, "divisor": 2, "dias": 14},
    "mensual":    {"multiplicador": 4.4, "divisor": 4, "dias": 28},
}

# 9 estados del credito
ESTADOS = [
    "pendiente_entrega",
    "activo",
    "al_dia",
    "en_riesgo",
    "mora",
    "mora_grave",
    "reestructurado",
    "saldado",
    "castigado",
]

# Valid state transitions — explicit directed graph
VALID_TRANSITIONS: dict[str, set[str]] = {
    "pendiente_entrega": {"activo"},
    "activo":            {"al_dia", "saldado"},
    "al_dia":            {"en_riesgo", "saldado"},
    "en_riesgo":         {"al_dia", "mora", "saldado"},
    "mora":              {"al_dia", "mora_grave", "reestructurado", "saldado"},
    "mora_grave":        {"reestructurado", "castigado", "saldado"},
    "reestructurado":    {"al_dia", "en_riesgo", "mora", "saldado"},
    "saldado":           set(),   # Terminal
    "castigado":         set(),   # Terminal
}


# ═══════════════════════════════════════════
# State transitions
# ═══════════════════════════════════════════


def is_valid_transition(from_state: str, to_state: str) -> bool:
    """Check if a state transition is valid."""
    allowed = VALID_TRANSITIONS.get(from_state, set())
    return to_state in allowed


# ═══════════════════════════════════════════
# Mora calculation
# ═══════════════════════════════════════════


def calcular_mora(
    fecha_cuota: date,
    fecha_actual: date,
    tasa_diaria: int = MORA_TASA_DIARIA,
) -> int:
    """
    Calculate mora for a single cuota.
    $2,000 COP per day of delay, starting the DAY AFTER the due date.

    Returns 0 if paid on or before due date.
    """
    dias_atraso = (fecha_actual - fecha_cuota).days
    if dias_atraso <= 0:
        return 0
    return dias_atraso * tasa_diaria


# ═══════════════════════════════════════════
# Waterfall payment allocation
# ═══════════════════════════════════════════


def aplicar_waterfall(
    monto_pago: float,
    anzi_pct: float,
    mora_pendiente: float,
    cuotas_vencidas_total: float,
    cuota_corriente: float,
    saldo_capital: float,
) -> dict[str, float]:
    """
    Apply waterfall payment allocation.
    Order: ANZI % → mora → vencidas → corriente → abono capital.

    Args:
        monto_pago: Total payment amount
        anzi_pct: ANZI percentage (from catalogo_planes, e.g. 0.02)
        mora_pendiente: Total accumulated mora pending
        cuotas_vencidas_total: Total amount of overdue cuotas
        cuota_corriente: Current cuota amount
        saldo_capital: Remaining capital balance

    Returns:
        Dict with allocation: {anzi, mora, vencidas, corriente, capital, sobrante}
    """
    remaining = float(monto_pago)

    # 1. ANZI — percentage of total payment goes to guarantor
    anzi = round(remaining * anzi_pct)
    remaining -= anzi

    # 2. Mora — cover accumulated late fees
    mora = min(remaining, mora_pendiente)
    remaining -= mora

    # 3. Vencidas — cover overdue cuotas
    vencidas = min(remaining, cuotas_vencidas_total)
    remaining -= vencidas

    # 4. Corriente — cover current cuota
    corriente = min(remaining, cuota_corriente)
    remaining -= corriente

    # 5. Capital — any surplus goes to principal reduction
    capital = min(remaining, saldo_capital)
    remaining -= capital

    # 6. Sobrante — anything left over (should be 0 normally)
    sobrante = max(remaining, 0)

    return {
        "anzi": round(anzi),
        "mora": round(mora),
        "vencidas": round(vencidas),
        "corriente": round(corriente),
        "capital": round(capital),
        "sobrante": round(sobrante),
    }


# ═══════════════════════════════════════════
# Cuota calculation — modalidad independent of plan
# ═══════════════════════════════════════════


def calcular_cuota(cuota_base: int, modalidad: str) -> int:
    """
    Calculate cuota amount from base price and modalidad.
    Multiplier comes from MODALIDADES constant.

    Formula: cuota_base × multiplicador
    """
    if modalidad not in MODALIDADES:
        raise ValueError(
            f"Modalidad '{modalidad}' no válida. "
            f"Use: {list(MODALIDADES.keys())}. "
            f"Para contado, no se crea loanbook."
        )
    multiplicador = MODALIDADES[modalidad]["multiplicador"]
    return round(cuota_base * multiplicador)


def calcular_num_cuotas(plan: dict, modalidad: str) -> int:
    """
    Calculate number of cuotas from plan and modalidad.
    Formula: cuotas_base / divisor (integer division)
    """
    if modalidad not in MODALIDADES:
        raise ValueError(f"Modalidad '{modalidad}' no válida.")
    cuotas_base = plan["cuotas_base"]
    divisor = MODALIDADES[modalidad]["divisor"]
    return cuotas_base // divisor


# ═══════════════════════════════════════════
# Loanbook creation
# ═══════════════════════════════════════════


def crear_loanbook(
    vin: str,
    cliente: dict,
    plan: dict,
    modelo: str,
    modalidad: str,
    fecha_entrega: date,
    fecha_primer_pago: date | None = None,
) -> dict[str, Any]:
    """
    Create a new loanbook document.

    Args:
        vin: Vehicle identification number
        cliente: Client info dict (nombre, cedula)
        plan: Plan from catalogo_planes (codigo, cuotas_base, cuotas_modelo, anzi_pct)
        modelo: Motorcycle model name (must exist in plan's cuotas_modelo)
        modalidad: Payment modality (semanal, quincenal, mensual) — NOT contado
        fecha_entrega: Delivery date
        fecha_primer_pago: First payment date (required for quincenal/mensual, must be Wednesday)

    Raises:
        ValueError: If contado, invalid modelo, or missing/invalid fecha_primer_pago
    """
    # Reject contado — no loanbook for cash sales
    if modalidad == VENTA_CONTADO:
        raise ValueError("Contado no crea loanbook. Venta directa sin crédito.")

    # Validate modalidad
    if modalidad not in MODALIDADES:
        raise ValueError(f"Modalidad '{modalidad}' no válida. Use: {list(MODALIDADES.keys())}.")

    # Validate modelo exists in plan
    cuotas_modelo = plan.get("cuotas_modelo", {})
    if modelo not in cuotas_modelo:
        raise ValueError(
            f"modelo '{modelo}' no existe en plan '{plan.get('codigo', '?')}'. "
            f"Modelos disponibles: {list(cuotas_modelo.keys())}"
        )

    # Quincenal/mensual require fecha_primer_pago
    if modalidad in ("quincenal", "mensual") and fecha_primer_pago is None:
        raise ValueError(
            f"Modalidad '{modalidad}' requiere fecha_primer_pago (debe ser miércoles)."
        )

    # If provided, fecha_primer_pago must be Wednesday (weekday 2)
    if fecha_primer_pago is not None and fecha_primer_pago.weekday() != 2:
        raise ValueError(
            f"fecha_primer_pago debe ser miércoles (Wednesday). "
            f"Fecha recibida: {fecha_primer_pago.isoformat()} "
            f"(dia {fecha_primer_pago.strftime('%A')})."
        )

    cuota_base = cuotas_modelo[modelo]
    cuota_monto = calcular_cuota(cuota_base, modalidad)
    num_cuotas = calcular_num_cuotas(plan, modalidad)

    cuotas = []
    for i in range(1, num_cuotas + 1):
        cuotas.append({
            "numero": i,
            "monto": cuota_monto,
            "estado": "pendiente",
            "fecha": None,       # Set by Sprint 4 Wednesday Rule
            "fecha_pago": None,
            "mora_acumulada": 0,
        })

    return {
        "loanbook_id": str(uuid.uuid4()),
        "vin": vin,
        "cliente": cliente,
        "plan_codigo": plan["codigo"],
        "modelo": modelo,
        "modalidad": modalidad,
        "estado": "pendiente_entrega",
        "cuota_monto": cuota_monto,
        "num_cuotas": num_cuotas,
        "cuotas": cuotas,
        "saldo_capital": num_cuotas * cuota_monto,
        "total_pagado": 0,
        "total_mora_pagada": 0,
        "total_anzi_pagado": 0,
        "anzi_pct": plan.get("anzi_pct", 0.02),
        "fecha_entrega": fecha_entrega.isoformat(),
        "fecha_primer_pago": fecha_primer_pago.isoformat() if fecha_primer_pago else None,
        "fecha_creacion": date.today().isoformat(),
    }


# ═══════════════════════════════════════════
# DPD (Days Past Due)
# ═══════════════════════════════════════════


def calcular_dpd(cuotas: list[dict], fecha_actual: date) -> int:
    """
    Calculate Days Past Due — days since the oldest unpaid overdue cuota.
    Used for credit scoring and state derivation.
    """
    oldest_overdue_date: date | None = None

    for cuota in cuotas:
        if cuota["estado"] == "pagada":
            continue
        fecha_str = cuota.get("fecha")
        if not fecha_str:
            continue
        fecha_cuota = date.fromisoformat(fecha_str)
        if fecha_cuota < fecha_actual:
            if oldest_overdue_date is None or fecha_cuota < oldest_overdue_date:
                oldest_overdue_date = fecha_cuota

    if oldest_overdue_date is None:
        return 0

    return (fecha_actual - oldest_overdue_date).days


# ═══════════════════════════════════════════
# Estado derivation from DPD
# ═══════════════════════════════════════════


def estado_from_dpd(dpd: int) -> str:
    """
    Derive credit state from days past due.
    - 0 days: al_dia
    - 1-15 days: en_riesgo
    - 16-60 days: mora
    - 61+ days: mora_grave
    """
    if dpd <= 0:
        return "al_dia"
    elif dpd <= 15:
        return "en_riesgo"
    elif dpd <= 60:
        return "mora"
    else:
        return "mora_grave"
