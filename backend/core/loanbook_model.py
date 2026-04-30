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
from datetime import date, timedelta
from core.datetime_utils import now_bogota, today_bogota, now_iso_bogota
from typing import Any

# ═══════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════

MORA_TASA_DIARIA = 2_000  # $2,000 COP/dia

VENTA_CONTADO = "contado"

# Tipos de producto financiable
TIPO_PRODUCTO_MOTO = "moto"
TIPO_PRODUCTO_COMPARENDO = "comparendo"
TIPO_PRODUCTO_LICENCIA = "licencia"
TIPOS_PRODUCTO_VALIDOS = {
    TIPO_PRODUCTO_MOTO,
    TIPO_PRODUCTO_COMPARENDO,
    TIPO_PRODUCTO_LICENCIA,
}
TIPOS_PRODUCTO_SIN_VIN = {
    TIPO_PRODUCTO_COMPARENDO,
    TIPO_PRODUCTO_LICENCIA,
}

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
    vin: str | None,
    cliente: dict,
    plan: dict,
    modelo: str,
    modalidad: str,
    fecha_entrega: date,
    fecha_primer_pago: date | None = None,
    tipo_producto: str = TIPO_PRODUCTO_MOTO,
) -> dict[str, Any]:
    """
    Create a new loanbook document.

    Args:
        vin: Vehicle identification number (required for tipo_producto='moto'; optional otherwise)
        cliente: Client info dict (nombre, cedula)
        plan: Plan from catalogo_planes (codigo, cuotas_base, cuotas_modelo, anzi_pct)
        modelo: Model/product name (must exist in plan's cuotas_modelo or 'modelos' list)
        modalidad: Payment modality (semanal, quincenal, mensual) — NOT contado
        fecha_entrega: Delivery date
        fecha_primer_pago: First payment date (required for quincenal/mensual, must be Wednesday)
        tipo_producto: "moto" | "comparendo" | "licencia" (default "moto")

    Raises:
        ValueError: If contado, invalid modelo, tipo_producto, or missing/invalid fecha_primer_pago
    """
    # Validate tipo_producto
    if tipo_producto not in TIPOS_PRODUCTO_VALIDOS:
        raise ValueError(
            f"tipo_producto '{tipo_producto}' no válido. "
            f"Use: {list(TIPOS_PRODUCTO_VALIDOS)}."
        )

    # VIN rules: required for motos, optional for comparendo/licencia
    if tipo_producto == TIPO_PRODUCTO_MOTO and not vin:
        raise ValueError("VIN es obligatorio para tipo_producto='moto'.")

    # Reject contado — no loanbook for cash sales
    if modalidad == VENTA_CONTADO:
        raise ValueError("Contado no crea loanbook. Venta directa sin crédito.")

    # Validate modalidad
    if modalidad not in MODALIDADES:
        raise ValueError(f"Modalidad '{modalidad}' no válida. Use: {list(MODALIDADES.keys())}.")

    # Validate modelo: for motos use cuotas_modelo; for comparendo/licencia check plan.modelos
    cuotas_modelo = plan.get("cuotas_modelo", {})
    if tipo_producto == TIPO_PRODUCTO_MOTO:
        if modelo not in cuotas_modelo:
            raise ValueError(
                f"modelo '{modelo}' no existe en plan '{plan.get('codigo', '?')}'. "
                f"Modelos disponibles: {list(cuotas_modelo.keys())}"
            )
    else:
        modelos_servicio = plan.get("modelos") or []
        if modelos_servicio and modelo not in modelos_servicio:
            raise ValueError(
                f"modelo '{modelo}' no existe en plan '{plan.get('codigo', '?')}'. "
                f"Modelos disponibles: {modelos_servicio}"
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

    # Calculate cuota amount: motos use cuotas_modelo price; services use plan-defined cuota_valor
    if tipo_producto == TIPO_PRODUCTO_MOTO:
        cuota_base = cuotas_modelo[modelo]
        cuota_monto = calcular_cuota(cuota_base, modalidad)
    else:
        # For comparendo/licencia, cuota is fixed per plan (plan.cuota_valor) or 0
        cuota_monto = plan.get("cuota_valor", 0)

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
        "tipo_producto": tipo_producto,
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
        "fecha_creacion": today_bogota().isoformat(),
    }


# ═══════════════════════════════════════════
# Cronograma de cuotas — Regla del Miércoles
# ═══════════════════════════════════════════

WEDNESDAY = 2  # date.weekday() == 2

# Mapping from Spanish weekday names to Python weekday() numbers.
# Used for EXCEPTIONAL cases only (default is always miercoles).
DIAS_COBRO: dict[str, int] = {
    "lunes": 0, "martes": 1, "miercoles": 2, "miércoles": 2,
    "jueves": 3, "viernes": 4, "sabado": 5, "sábado": 5, "domingo": 6,
}


def _next_weekday(d: date, weekday: int) -> date:
    """Return d if it matches weekday, otherwise the next occurrence after d."""
    days_ahead = weekday - d.weekday()
    if days_ahead < 0:
        days_ahead += 7
    elif days_ahead == 0:
        return d
    return d + timedelta(days=days_ahead)


def _next_wednesday(d: date) -> date:
    """Backward-compat: return next Wednesday (or d if Wednesday)."""
    return _next_weekday(d, WEDNESDAY)


def calcular_cronograma(
    fecha_entrega: date,
    modalidad: str,
    num_cuotas: int,
    fecha_primer_pago: date | None = None,
    dia_cobro_especial: str | None = None,
) -> list[date]:
    """
    Calculate cuota schedule respecting the Wednesday Rule.

    Regla canónica RODDOS (alineada con reglas_negocio.primer_miercoles_cobro):
      - Sin fecha_primer_pago + semanal:
          primer cobro = primer miércoles >= fecha_entrega + 7 días
          (gap mínimo de 7 días es canónico — ver CLAUDE.md y docstring de
          services/loanbook/reglas_negocio.py::primer_miercoles_cobro)
      - Con fecha_primer_pago explícita:
          se RESPETA siempre que (a) caiga en el día de cobro objetivo
          (miércoles por defecto), (b) sea estrictamente posterior a
          fecha_entrega. NO se aplica el gap canónico de +7 días — el
          override está para excepciones operativas legítimas.
      - Sin fecha_primer_pago + quincenal/mensual:
          ValueError (la fecha es obligatoria en estas modalidades).

    Después del primer cobro: cada N días según modalidad (7/14/28).

    Default: ALL dates son miércoles. Pass `dia_cobro_especial` para excepciones
    (e.g. cliente solo cobra jueves por su esquema de ingreso).
    """
    # Importación local para evitar ciclo si reglas_negocio importa de aquí
    from services.loanbook.reglas_negocio import primer_miercoles_cobro

    if modalidad not in MODALIDADES:
        raise ValueError(f"Modalidad '{modalidad}' no válida.")

    # Resolve target weekday (default Wednesday)
    if dia_cobro_especial:
        key = dia_cobro_especial.strip().lower()
        if key not in DIAS_COBRO:
            raise ValueError(
                f"dia_cobro_especial '{dia_cobro_especial}' no válido. "
                f"Use: {list(DIAS_COBRO.keys())}."
            )
        target_weekday = DIAS_COBRO[key]
    else:
        target_weekday = WEDNESDAY

    dias = MODALIDADES[modalidad]["dias"]

    if fecha_primer_pago is not None:
        # Override explícito: respetar la fecha que el operador eligió.
        # Sólo se valida (a) que sea posterior a la entrega y (b) que caiga
        # en el weekday objetivo. NO se aplica el gap canónico de +7 días.
        if fecha_primer_pago <= fecha_entrega:
            raise ValueError(
                f"fecha_primer_pago ({fecha_primer_pago.isoformat()}) debe ser "
                f"posterior a fecha_entrega ({fecha_entrega.isoformat()})."
            )
        if fecha_primer_pago.weekday() != target_weekday:
            dia_nombre = dia_cobro_especial or "miércoles"
            raise ValueError(
                f"fecha_primer_pago debe caer en {dia_nombre}. "
                f"Fecha recibida: {fecha_primer_pago.isoformat()} "
                f"({['lun','mar','mié','jue','vie','sáb','dom'][fecha_primer_pago.weekday()]})."
            )
        primer_cobro = fecha_primer_pago
    elif modalidad == "semanal":
        # Auto-calculate canónico: delega a primer_miercoles_cobro() que aplica
        # la regla "primer miércoles >= fecha_entrega + 7 días" (CLAUDE.md).
        # Si dia_cobro_especial pide otro día, se cae a una versión análoga
        # +7 días sobre ese weekday.
        if target_weekday == WEDNESDAY:
            primer_cobro = primer_miercoles_cobro(fecha_entrega)
        else:
            start = fecha_entrega + timedelta(days=7)
            primer_cobro = _next_weekday(start, target_weekday)
    else:
        # Quincenal/mensual REQUIERE fecha_primer_pago explícita
        raise ValueError(
            f"Modalidad '{modalidad}' requiere fecha_primer_pago."
        )

    # Generate all dates
    fechas = []
    for i in range(num_cuotas):
        fechas.append(primer_cobro + timedelta(days=dias * i))

    return fechas


def asignar_cronograma(
    cuotas: list[dict],
    fechas: list[date],
) -> dict:
    """
    Assign calculated dates to loanbook cuotas.

    Returns dict with:
    - cuotas: updated cuotas list with fecha set
    - fecha_primera_cuota: first date ISO string
    - fecha_ultima_cuota: last date ISO string
    """
    if len(cuotas) != len(fechas):
        raise ValueError(
            f"Mismatch: {len(cuotas)} cuotas vs {len(fechas)} fechas."
        )

    for cuota, fecha in zip(cuotas, fechas):
        cuota["fecha"] = fecha.isoformat()

    return {
        "cuotas": cuotas,
        "fecha_primera_cuota": fechas[0].isoformat(),
        "fecha_ultima_cuota": fechas[-1].isoformat(),
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
        fecha_str = cuota.get("fecha") or cuota.get("fecha_programada")
        if not fecha_str:
            continue
        fecha_cuota = date.fromisoformat(fecha_str) if isinstance(fecha_str, str) else fecha_str
        if fecha_cuota >= fecha_actual:
            continue  # cuota futura, no overdue
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
    Derive credit state from days past due (DPD).

    Mapping (calibrado para cobro semanal RODDOS):
        DPD 0       → "al_dia"
        DPD 1-15    → "en_riesgo"
        DPD 16-60   → "mora"
        DPD 61+     → "mora_grave"

    Estados terminales (saldado, castigado) se manejan aparte —
    esta función no transiciona desde ellos.
    """
    if dpd <= 0:
        return "al_dia"
    if dpd <= 15:
        return "en_riesgo"
    if dpd <= 60:
        return "mora"
    return "mora_grave"
