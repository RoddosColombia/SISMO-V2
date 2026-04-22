"""
services/loanbook/reglas_negocio.py — Tabla canónica de reglas de negocio Roddos.

FUENTE DE VERDAD para:
  - Número de cuotas por plan × modalidad  (tabla FIJA, no fórmula)
  - Multiplicador de valor de cuota por modalidad
  - Días entre cobros por modalidad
  - Mora diaria en COP
  - Porcentaje ANZI

PRINCIPIO: la tabla PLAN_CUOTAS es un contrato de negocio, no una derivación
matemática. round(39 / 2.2) = 18 ≠ 20. Siempre usar la tabla, nunca la fórmula.

Sin I/O — módulo de constantes puras + funciones sin efectos laterales.
"""

from datetime import date

# ─────────────────────── Tabla fija plan × modalidad ────────────────────────────
# Cada celda fue acordada con operaciones. None = combinación no configurada.

PLAN_CUOTAS: dict[str, dict[str, int | None]] = {
    "P15S": {"semanal": 15,  "quincenal": None, "mensual": None},
    "P39S": {"semanal": 39,  "quincenal": 20,   "mensual": 9},
    "P52S": {"semanal": 52,  "quincenal": 26,   "mensual": 12},
    "P78S": {"semanal": 78,  "quincenal": 39,   "mensual": 18},
}

# ─────────────────────── Constantes de cobro ──────────────────────────────────

# Factor por el que se multiplica la cuota semanal base para obtener la cuota
# en otra modalidad.
MULTIPLICADOR_PRECIO_CUOTA: dict[str, float] = {
    "semanal":   1.0,
    "quincenal": 2.2,
    "mensual":   4.4,
}

# Días calendario entre cuotas consecutivas
DIAS_ENTRE_CUOTAS: dict[str, int] = {
    "semanal":   7,
    "quincenal": 14,
    "mensual":   28,
}

# Mora fija en pesos colombianos por día de atraso
MORA_COP_POR_DIA: int = 2_000

# Porcentaje ANZI (administración de cartera) que se descuenta de cada pago
ANZI_PCT: float = 0.02


# ─────────────────────── Funciones puras ──────────────────────────────────────

def get_num_cuotas(plan_codigo: str, modalidad: str) -> int | None:
    """Número canónico de cuotas para plan × modalidad.

    Retorna None si:
      - plan_codigo no existe en PLAN_CUOTAS
      - la combinación plan × modalidad no está configurada (ej. P15S quincenal)

    Nunca hace round() ni aplica fórmulas.

    Args:
        plan_codigo: "P15S", "P39S", "P52S" o "P78S"
        modalidad:   "semanal", "quincenal" o "mensual"

    Returns:
        int  — número de cuotas según tabla de negocio
        None — combinación no configurada
    """
    plan = PLAN_CUOTAS.get(plan_codigo)
    if plan is None:
        return None
    return plan.get(modalidad)


def get_valor_cuota(cuota_base_semanal: float, modalidad: str) -> float:
    """Valor de cuota en la modalidad dada, escalado desde la cuota semanal base.

    Args:
        cuota_base_semanal: monto de la cuota si fuera semanal (precio de referencia)
        modalidad:          "semanal", "quincenal" o "mensual"

    Returns:
        float — monto de cuota en la modalidad solicitada
    """
    factor = MULTIPLICADOR_PRECIO_CUOTA.get(modalidad, 1.0)
    return round(cuota_base_semanal * factor, 2)


def get_valor_total(
    plan_codigo: str,
    modalidad: str,
    valor_cuota: float,
    cuota_inicial: float = 0,
) -> float | None:
    """Valor total del crédito según la tabla canónica.

    Formula:
        valor_total = get_num_cuotas(plan_codigo, modalidad) × valor_cuota + cuota_inicial

    Retorna None si la combinación plan × modalidad no está configurada.

    Args:
        plan_codigo:   código del plan ("P39S", "P52S", etc.)
        modalidad:     "semanal", "quincenal" o "mensual"
        valor_cuota:   monto por cuota en la modalidad del crédito
        cuota_inicial: cuota de enganche (default 0)

    Returns:
        float — valor total del crédito
        None  — combinación no configurada
    """
    n = get_num_cuotas(plan_codigo, modalidad)
    if n is None:
        return None
    return round(n * valor_cuota + cuota_inicial)


def validar_fecha_pago(fecha_pago: date, hoy: date | None = None) -> None:
    """Verifica que fecha_pago no sea en el futuro (físicamente imposible).

    Se llama en todos los endpoints de pago antes de procesar cualquier
    transacción. Un pago registrado con fecha futura es un error operativo —
    el cobrador marcó la cuota antes de que ocurriera.

    Args:
        fecha_pago: fecha del pago a registrar
        hoy:        fecha de referencia (default: date.today()). Inyectable en tests.

    Raises:
        ValueError: si fecha_pago > hoy, con mensaje descriptivo.
    """
    if hoy is None:
        hoy = date.today()
    if fecha_pago > hoy:
        raise ValueError(
            f"fecha_pago '{fecha_pago}' está en el futuro (hoy={hoy}). "
            "No se puede registrar un pago que aún no ocurrió."
        )
