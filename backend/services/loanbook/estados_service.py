"""
services/loanbook/estados_service.py — Máquina de estados + sub-buckets del módulo Loanbook.

Funciones puras, determinísticas, sin I/O.
Rangos DPD v1.1 Opción A según .planning/LOANBOOK_MAESTRO_v1.1.md cap 3.

Reglas aplicadas:
  R-22: mora $2.000 COP/día sin cap
  cap 3.1: rangos DPD de los 9 estados
  cap 3.2: 7 sub-buckets semanales
  cap 3.3: matriz de transiciones permitidas
"""

from __future__ import annotations

from typing import Optional, Literal

from fastapi import HTTPException


# ─────────────────────── Tipos Literal (tipado fuerte) ────────────────────────

EstadoLiteral = Literal[
    "Aprobado",
    "Current",
    "Early Delinquency",
    "Mid Delinquency",
    "Late Delinquency",
    "Default",
    "Charge-Off",
    "Modificado",
    "Pagado",
]

SubBucketLiteral = Literal[
    "Grace",
    "Warning",
    "Alert",
    "Critical",
    "Severe",
    "Pre-default",
    "Default",
]

# Todos los estados válidos para validación de entrada
ESTADOS_VALIDOS: frozenset[str] = frozenset(
    ["Aprobado", "Current", "Early Delinquency", "Mid Delinquency",
     "Late Delinquency", "Default", "Charge-Off", "Modificado", "Pagado"]
)

# Estados que representan cartera activa (no terminal)
ESTADOS_ACTIVOS: frozenset[str] = frozenset(
    ["Current", "Early Delinquency", "Mid Delinquency",
     "Late Delinquency", "Default", "Modificado", "Aprobado"]
)


# ─────────────────────── Matriz de transiciones (cap 3.3) ─────────────────────

TRANSICIONES_PERMITIDAS: dict[Optional[str], set[str]] = {
    None:                  {"Aprobado"},
    "Aprobado":            {"Current", "Pagado"},
    "Current":             {"Early Delinquency", "Pagado"},
    "Early Delinquency":   {"Current", "Mid Delinquency", "Pagado"},
    "Mid Delinquency":     {"Late Delinquency", "Current", "Pagado"},
    "Late Delinquency":    {"Default", "Current", "Pagado", "Modificado"},
    "Default":             {"Charge-Off", "Modificado", "Pagado"},
    "Charge-Off":          {"Pagado"},
    "Modificado":          {"Current", "Late Delinquency"},
    "Pagado":              set(),
}


# ─────────────────────── Constantes financieras ───────────────────────────────

MORA_COP_POR_DIA: int = 2_000  # R-22: inamovible, sin cap


# ─────────────────────── Clasificadores ──────────────────────────────────────

def clasificar_estado(
    dpd: Optional[int],
    saldo_capital: float,
    plan_codigo: str,
) -> EstadoLiteral:
    """Clasifica el estado de un loanbook según DPD, saldo y plan.

    Precedencia:
    1. saldo_capital <= 0 → Pagado (gana sobre DPD)
    2. dpd is None → Aprobado (sin cronograma aún)
    3. rangos DPD v1.1 Opción A (cap 3.1)

    Args:
        dpd:           días de atraso. 0 = al día, None = sin cronograma.
        saldo_capital: saldo restante en COP.
        plan_codigo:   código del plan (reservado para lógica P1S futura).

    Returns:
        Uno de los 9 estados oficiales.
    """
    # Regla 1: saldo cero → Pagado
    if saldo_capital <= 0:
        return "Pagado"

    # Regla 2: sin cronograma → Aprobado
    if dpd is None:
        return "Aprobado"

    # Regla 3: rangos v1.1 Opción A
    if dpd == 0:
        return "Current"
    if 1 <= dpd <= 7:
        return "Early Delinquency"
    if 8 <= dpd <= 14:
        return "Mid Delinquency"
    if 15 <= dpd <= 45:
        return "Late Delinquency"
    if 46 <= dpd <= 49:
        return "Default"
    if dpd >= 50:
        return "Charge-Off"

    # Defensivo: nunca debería llegar aquí si dpd >= 0
    raise ValueError(f"DPD inesperado: {dpd}. Debe ser None o int >= 0.")


def clasificar_sub_bucket(dpd: Optional[int]) -> Optional[SubBucketLiteral]:
    """Clasifica el sub-bucket semanal (cap 3.2).

    Solo aplica cuando hay mora (dpd > 0).

    Args:
        dpd: días de atraso. None o 0 → sin sub-bucket.

    Returns:
        None si no hay mora. Uno de los 7 sub-buckets en caso contrario.
    """
    if dpd is None or dpd <= 0:
        return None
    if 1 <= dpd <= 7:
        return "Grace"
    if 8 <= dpd <= 14:
        return "Warning"
    if 15 <= dpd <= 21:
        return "Alert"
    if 22 <= dpd <= 30:
        return "Critical"
    if 31 <= dpd <= 45:
        return "Severe"
    if 46 <= dpd <= 49:
        return "Pre-default"
    # dpd >= 50
    return "Default"


# ─────────────────────── Validación de transiciones ──────────────────────────

def validar_transicion(
    estado_actual: Optional[str],
    estado_nuevo: str,
) -> None:
    """Valida que la transición estado_actual → estado_nuevo sea permitida.

    Args:
        estado_actual: estado actual del loanbook (None si es nuevo).
        estado_nuevo:  estado al que se intenta transicionar.

    Raises:
        HTTPException 422: si la transición no está en TRANSICIONES_PERMITIDAS.
    """
    permitidas = TRANSICIONES_PERMITIDAS.get(estado_actual, set())
    if estado_nuevo not in permitidas:
        if permitidas:
            permitidas_str = sorted(permitidas)
        else:
            permitidas_str = "ninguna (estado terminal)"
        raise HTTPException(
            status_code=422,
            detail=(
                f"Transición inválida: '{estado_actual}' → '{estado_nuevo}'. "
                f"Desde '{estado_actual}' se permite: {permitidas_str}"
            ),
        )


# ─────────────────────── Mora acumulada (R-22) ───────────────────────────────

def calcular_mora_acumulada(dpd: Optional[int]) -> int:
    """Calcula mora acumulada en COP. Sin cap (R-22 inamovible).

    Args:
        dpd: días de atraso. None o <= 0 → sin mora.

    Returns:
        COP acumulados en mora.
    """
    if dpd is None or dpd <= 0:
        return 0
    return dpd * MORA_COP_POR_DIA
