"""
services/loanbook/amortizacion_service.py — Motor de amortización francesa y Waterfall Opción A.

Funciones puras sin I/O de DB:
  - tasa_periodica: convierte tasa EA a tasa del período de pago
  - generar_cronograma: produce lista de cuotas con monto_capital + monto_interes reales
  - aplicar_waterfall: distribuye un pago según prioridad ANZI→mora→vencidas→corriente→capital
  - calcular_liquidacion_anticipada: proyecta el monto exacto para saldar anticipadamente

Ref: .planning/LOANBOOK_MAESTRO_v1.1.md caps 4, 6.2, 11.5
Reglas: R-19 (capital/interés por cuota), R-21 (waterfall Opción A), R-22 (mora $2K/día)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

# ─────────────────────── Constantes ──────────────────────────────────────────

MORA_COP_POR_DIA: int = 2_000  # R-22: mora sin cap
ANZI_PCT_DEFAULT: float = 0.02  # 2% del monto del pago

# Días de cobro por modalidad (para fechas del cronograma)
_DIAS_MODALIDAD: dict[str, int] = {
    "semanal":   7,
    "quincenal": 14,
    "mensual":   28,
    "contado":   0,
}

WEDNESDAY = 2  # date.weekday()


# ─────────────────────── Helpers internos ────────────────────────────────────

def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _a_fecha(x: Any) -> Optional[date]:
    """Normaliza date / datetime / str ISO a date. Retorna None si no parseable."""
    if x is None:
        return None
    if isinstance(x, date) and not isinstance(x, __import__("datetime").datetime):
        return x
    try:
        from datetime import datetime
        if isinstance(x, datetime):
            return x.date()
        return date.fromisoformat(str(x)[:10])
    except (ValueError, TypeError):
        return None


def _next_wednesday(d: date) -> date:
    """Primer miércoles >= d."""
    days_ahead = (WEDNESDAY - d.weekday()) % 7
    return d + timedelta(days=days_ahead)


# ─────────────────────── 1. tasa_periodica ───────────────────────────────────

def tasa_periodica(tasa_ea: float, modalidad: str) -> float:
    """
    Convierte tasa efectiva anual (EA) a tasa periódica según modalidad.

    Fórmula: (1 + tasa_ea)^(1/n) - 1
    donde n = períodos en el año (52 semanal, 26 quincenal, 12 mensual).

    Args:
        tasa_ea:   Tasa efectiva anual como decimal (ej: 0.39 = 39% EA).
        modalidad: "semanal" | "quincenal" | "mensual" | "contado".

    Returns:
        Tasa periódica como decimal (ej: ~0.00635 para 39% EA semanal).

    Raises:
        ValueError: si modalidad no es reconocida.
    """
    if modalidad == "contado":
        return 0.0
    periodos = {
        "semanal":   52,
        "quincenal": 26,
        "mensual":   12,
    }
    if modalidad not in periodos:
        raise ValueError(f"Modalidad inválida: '{modalidad}'. Use: {list(periodos)}")
    n = periodos[modalidad]
    return (1 + tasa_ea) ** (1 / n) - 1


# ─────────────────────── 2. generar_cronograma ───────────────────────────────

def generar_cronograma(
    saldo_inicial: float,
    cuota_periodica: Optional[float],
    tasa_ea: float,
    modalidad: str,
    fecha_entrega: date,
    n_cuotas: int,
    fecha_primer_pago: Optional[date] = None,
) -> list[dict]:
    """
    Genera el cronograma de amortización francesa (cuota fija, capital creciente).

    Calcula monto_capital + monto_interes reales por cuota según R-19.
    Respeta la Regla del Miércoles: primer cobro = primer miércoles >= entrega + 7 días.

    Args:
        saldo_inicial:    Capital original del loanbook.
        cuota_periodica:  Monto fijo de la cuota (pre-calculado). Si es None o 0,
                          se calcula con la fórmula francesa.
        tasa_ea:          Tasa efectiva anual como decimal.
        modalidad:        "semanal" | "quincenal" | "mensual".
        fecha_entrega:    Fecha de entrega del producto.
        n_cuotas:         Número total de cuotas del plan.
        fecha_primer_pago: Fecha del primer cobro (opcional; para quincenal/mensual).

    Returns:
        Lista de dicts con:
          numero, fecha_programada, monto_total, monto_capital, monto_interes,
          monto_fees, estado, saldo_despues
    """
    if modalidad not in _DIAS_MODALIDAD:
        raise ValueError(f"Modalidad inválida: '{modalidad}'")
    if n_cuotas <= 0:
        raise ValueError("n_cuotas debe ser > 0")
    if saldo_inicial <= 0:
        raise ValueError("saldo_inicial debe ser > 0")

    # Tasa periódica
    i = tasa_periodica(tasa_ea, modalidad) if tasa_ea else 0.0

    # Cuota fija (usa valor pre-calculado si existe, sino aplica fórmula francesa)
    if cuota_periodica and cuota_periodica > 0:
        cuota = float(cuota_periodica)
    elif i > 0:
        cuota = saldo_inicial * i * (1 + i) ** n_cuotas / ((1 + i) ** n_cuotas - 1)
    else:
        cuota = saldo_inicial / n_cuotas

    # Fechas de cobro (Regla del Miércoles)
    dias = _DIAS_MODALIDAD.get(modalidad, 7)
    if fecha_primer_pago:
        primer_cobro = fecha_primer_pago
    else:
        min_fecha = fecha_entrega + timedelta(days=7)
        primer_cobro = _next_wednesday(min_fecha)

    saldo = float(saldo_inicial)
    cronograma: list[dict] = []

    for k in range(1, n_cuotas + 1):
        fecha_programada = primer_cobro + timedelta(days=dias * (k - 1))
        es_ultima = (k == n_cuotas)

        if i > 0:
            monto_interes = round(saldo * i)
            if es_ultima:
                # Última cuota: capital = saldo exacto para llegar a 0
                monto_capital = round(saldo)
                monto_total = monto_capital + monto_interes
            else:
                monto_capital = round(cuota - monto_interes)
                monto_total = round(cuota)
        else:
            # Sin interés (contado o tasa 0): amortización lineal
            if es_ultima:
                monto_capital = round(saldo)
            else:
                monto_capital = round(cuota)
            monto_interes = 0
            monto_total = monto_capital

        saldo = max(0.0, saldo - monto_capital)

        cronograma.append({
            "numero": k,
            "fecha_programada": fecha_programada,
            "monto_total": monto_total,
            "monto_capital": monto_capital,
            "monto_interes": monto_interes,
            "monto_fees": 0,
            "estado": "pendiente",
            "saldo_despues": round(saldo),
        })

    return cronograma


# ─────────────────────── 3. aplicar_waterfall ────────────────────────────────

def aplicar_waterfall(
    lb: dict,
    monto_pago: float,
    fecha_pago: date,
    metodo_pago: str = "transferencia",
    referencia: Optional[str] = None,
) -> dict:
    """
    Aplica el Waterfall Opción A a un pago. Referencia: R-21.

    Orden estricto de distribución:
      1. ANZI 2% del monto total del pago
      2. Mora acumulada
      3. Cuotas vencidas (más antigua primero): capital + interés
      4. Cuota corriente
      5. Abono a capital anticipado (sobrante)

    Args:
        lb:          Documento del loanbook (dict de MongoDB).
        monto_pago:  Monto total recibido (COP).
        fecha_pago:  Fecha del pago (debe ser <= hoy, validada por el caller).
        metodo_pago: "transferencia" | "efectivo" | etc.
        referencia:  Referencia bancaria / comprobante.

    Returns:
        dict con:
          anzi_cobrado, mora_cobrada, interes_cobrado, capital_cobrado,
          capital_anticipado, cuotas_actualizadas, saldo_capital_nuevo,
          evento_payload
    """
    saldo_restante = float(monto_pago)

    # ── Paso 1: ANZI 2% ──────────────────────────────────────────────────────
    anzi_pct = _safe_float(lb.get("anzi_pct", ANZI_PCT_DEFAULT))
    anzi_cobrado = round(saldo_restante * anzi_pct)
    saldo_restante -= anzi_cobrado

    # ── Paso 2: Mora acumulada ────────────────────────────────────────────────
    mora_pendiente = _safe_float(lb.get("mora_acumulada_cop", 0))
    mora_cobrada = min(saldo_restante, mora_pendiente)
    saldo_restante -= mora_cobrada

    # ── Pasos 3+4: Cuotas (vencidas primero, luego corriente) ─────────────────
    cuotas_raw = lb.get("cuotas") or []

    # Separar cuotas que necesitan pago (pendiente / vencida / parcial)
    cuotas_ordenadas = sorted(
        [c for c in cuotas_raw if c.get("estado") not in ("pagada",)],
        key=lambda c: (
            _a_fecha(c.get("fecha_programada") or c.get("fecha")) or date.max,
            c.get("numero", 9999),
        ),
    )

    cuotas_actualizadas: list[dict] = []
    capital_cobrado = 0.0
    interes_cobrado = 0.0

    for cuota in cuotas_ordenadas:
        if saldo_restante <= 0:
            break

        fecha_cuota = _a_fecha(cuota.get("fecha_programada") or cuota.get("fecha"))
        es_vencida = fecha_cuota is not None and fecha_cuota < fecha_pago
        es_corriente = not es_vencida

        # Solo procesar vencidas en el paso 3; corriente en paso 4
        # Procesamos en orden natural ya que ordenamos por fecha
        monto_pendiente = (
            _safe_float(cuota.get("monto_total") or cuota.get("monto", 0))
            - _safe_float(cuota.get("monto_pagado", 0))
        )
        if monto_pendiente <= 0:
            continue

        pagado_esta = min(saldo_restante, monto_pendiente)
        saldo_restante -= pagado_esta

        # Distribuir entre capital e interés proporcionalmente al pendiente
        monto_total_cuota = _safe_float(cuota.get("monto_total") or cuota.get("monto", 1))
        pct_capital = (
            _safe_float(cuota.get("monto_capital", 0)) / monto_total_cuota
            if monto_total_cuota > 0
            else 1.0
        )
        capital_esta = round(pagado_esta * pct_capital)
        interes_esta = round(pagado_esta - capital_esta)

        capital_cobrado += capital_esta
        interes_cobrado += interes_esta

        nuevo_monto_pagado = _safe_float(cuota.get("monto_pagado", 0)) + pagado_esta
        nueva_cuota = {
            **cuota,
            "monto_pagado": round(nuevo_monto_pagado),
            "fecha_pago": fecha_pago.isoformat(),
            "metodo_pago": metodo_pago,
            "referencia": referencia,
        }
        if nuevo_monto_pagado >= monto_total_cuota - 0.5:
            nueva_cuota["estado"] = "pagada"
            nueva_cuota["mora_acumulada"] = 0
        else:
            nueva_cuota["estado"] = "parcial"

        cuotas_actualizadas.append(nueva_cuota)

        # Solo procesar la corriente (es_corriente) una vez — stop después
        if es_corriente:
            break

    # ── Paso 5: Abono a capital anticipado ───────────────────────────────────
    capital_anticipado = max(0.0, round(saldo_restante))

    # Nuevo saldo capital
    saldo_capital_actual = _safe_float(lb.get("saldo_capital") or lb.get("saldo_pendiente", 0))
    saldo_capital_nuevo = max(0.0, saldo_capital_actual - capital_cobrado - capital_anticipado)

    lb_codigo = lb.get("loanbook_id") or lb.get("loanbook_codigo") or ""

    evento_payload = {
        "loanbook_codigo": lb_codigo,
        "monto_total": round(monto_pago),
        "anzi": round(anzi_cobrado),
        "mora": round(mora_cobrada),
        "interes": round(interes_cobrado),
        "capital": round(capital_cobrado),
        "capital_anticipado": round(capital_anticipado),
        "saldo_capital_nuevo": round(saldo_capital_nuevo),
        "cuotas_modificadas": len(cuotas_actualizadas),
        "metodo_pago": metodo_pago,
        "referencia": referencia,
        "fecha_pago": fecha_pago.isoformat(),
    }

    return {
        "anzi_cobrado": round(anzi_cobrado),
        "mora_cobrada": round(mora_cobrada),
        "interes_cobrado": round(interes_cobrado),
        "capital_cobrado": round(capital_cobrado),
        "capital_anticipado": round(capital_anticipado),
        "cuotas_actualizadas": cuotas_actualizadas,
        "saldo_capital_nuevo": round(saldo_capital_nuevo),
        "evento_payload": evento_payload,
    }


# ─────────────────────── 4. calcular_liquidacion_anticipada ──────────────────

def calcular_liquidacion_anticipada(
    lb: dict,
    fecha_liquidacion: date,
) -> dict:
    """
    Calcula el monto exacto para saldar anticipadamente el loanbook.

    El cliente paga solo el saldo de capital + mora acumulada hasta la fecha.
    Ahorra los intereses futuros (beneficio de la amortización francesa).

    Args:
        lb:                Documento del loanbook.
        fecha_liquidacion: Fecha propuesta para el pago total.

    Returns:
        dict con saldo_capital, mora_acumulada, monto_liquidacion,
        cuotas_pendientes_valor, descuento_intereses_futuros.
    """
    saldo_capital = _safe_float(lb.get("saldo_capital") or lb.get("saldo_pendiente", 0))

    # Mora acumulada: usar la del documento o calcular desde DPD
    mora_acumulada = _safe_float(lb.get("mora_acumulada_cop", 0))
    dpd = _safe_int(lb.get("dpd", 0))
    if saldo_capital > 0 and dpd == 0 and mora_acumulada == 0:
        # Buscar cuotas vencidas a fecha_liquidacion para proyectar mora
        cuotas = lb.get("cuotas") or []
        for c in sorted(cuotas, key=lambda x: _a_fecha(x.get("fecha_programada") or x.get("fecha")) or date.max):
            if c.get("estado") in ("pagada",):
                continue
            fecha_c = _a_fecha(c.get("fecha_programada") or c.get("fecha"))
            if fecha_c and fecha_c < fecha_liquidacion:
                dias_mora = (fecha_liquidacion - fecha_c).days
                mora_acumulada = dias_mora * MORA_COP_POR_DIA
                break

    # Total de cuotas pendientes (valor nominal: capital + intereses futuros)
    cuotas_pendientes_valor = sum(
        _safe_float(c.get("monto_total") or c.get("monto", 0))
        - _safe_float(c.get("monto_pagado", 0))
        for c in (lb.get("cuotas") or [])
        if c.get("estado") not in ("pagada",)
    )

    # Monto a pagar para liquidar = saldo capital + mora
    monto_liquidacion = saldo_capital + mora_acumulada

    # Descuento = intereses futuros que el cliente se ahorra
    descuento_intereses_futuros = max(0.0, cuotas_pendientes_valor - monto_liquidacion)

    return {
        "loanbook_codigo": lb.get("loanbook_id") or lb.get("loanbook_codigo"),
        "fecha_liquidacion": fecha_liquidacion.isoformat(),
        "saldo_capital": round(saldo_capital),
        "mora_acumulada": round(mora_acumulada),
        "cuotas_pendientes_valor": round(cuotas_pendientes_valor),
        "monto_liquidacion": round(monto_liquidacion),
        "descuento_intereses_futuros": round(descuento_intereses_futuros),
    }
