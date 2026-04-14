"""
Loanbook Model V2 — Pure domain logic for motorcycle credit management.

NO MongoDB, NO Alegra, NO FastAPI. Pure functions and data structures
that can be tested without any infrastructure.

Business rules:
- 9 estados: pendiente_entrega → activo → al_dia → en_riesgo → mora → mora_grave → reestructurado → saldado → castigado
- 4 modalidades: semanal (×plan), quincenal (×plan), mensual (×plan), cuota_unica
- Mora: $2,000 COP/dia de atraso desde el DIA SIGUIENTE a fecha de cuota
- ANZI: % de cada cuota va a CXP ANZI (garante) — leido de catalogo_planes
- Waterfall: ANZI → mora → vencidas → corriente → abono capital
- Multiplicadores: leidos de catalogo_planes, NUNCA hardcodeados
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

# ═══════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════

MORA_TASA_DIARIA = 2_000  # $2,000 COP/dia

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
# Cuota calculation
# ═══════════════════════════════════════════


def calcular_cuota(monto_financiar: float, plan: dict) -> int:
    """
    Calculate cuota amount from financing amount and plan.
    Multiplier comes from the plan (catalogo_planes), NEVER hardcoded.

    Formula: (monto_financiar / num_cuotas) * multiplicador
    """
    num_cuotas = plan["cuotas"]
    multiplicador = plan["multiplicador"]
    return round((monto_financiar / num_cuotas) * multiplicador)


# ═══════════════════════════════════════════
# Loanbook creation
# ═══════════════════════════════════════════


def crear_loanbook(
    vin: str,
    cliente: dict,
    plan: dict,
    monto_financiar: float,
    fecha_entrega: date,
) -> dict[str, Any]:
    """
    Create a new loanbook document.
    Cuota dates are NOT calculated here — that's Sprint 4 (Wednesday Rule).
    """
    cuota_monto = calcular_cuota(monto_financiar, plan)
    num_cuotas = plan["cuotas"]

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
        "plan": plan,
        "modalidad": plan["modalidad"],
        "estado": "pendiente_entrega",
        "monto_financiar": monto_financiar,
        "cuota_monto": cuota_monto,
        "num_cuotas": num_cuotas,
        "cuotas": cuotas,
        "saldo_capital": monto_financiar,
        "total_pagado": 0,
        "total_mora_pagada": 0,
        "total_anzi_pagado": 0,
        "fecha_entrega": fecha_entrega.isoformat(),
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
