"""
services/loanbook/motor.py — Motor unificado del Loanbook RODDOS.

API pública (4 funciones):

    crear_cronograma(fecha_primer_pago, num_cuotas, cuota_valor, modalidad,
                     capital_plan, cuota_estandar_plan) -> list[dict]

    aplicar_pago(loanbook, monto, fecha_pago, cuota_numero=None) -> dict

    derivar_estado(loanbook, hoy=None) -> dict

    auditar(loanbook, hoy=None) -> dict

Reglas inviolables (LOANBOOK_MAESTRO_v1.1):
  - fecha_primer_pago la define el operador (no hay regla automática del
    miércoles +7). El día de la semana se hereda de fecha_primer_pago.
  - Intervalo entre cuotas: 7 (semanal) | 14 (quincenal) | 28 (mensual).
  - Cada cuota se desglosa en monto_capital + monto_interes (suma = monto).
  - Waterfall §4.1: ANZI 2% del pago → mora → interés cuota → capital cuota
    → abono capital anticipado.
  - Mora $2.000 COP/día sin cap.
  - 9 estados Opción B (rangos DPD v1.1):
      pendiente_entrega | al_dia (0) | mora_leve (1-7) | mora_media (8-14) |
      mora_grave (15-45) | default (46-49) | castigado (50+) |
      reestructurado | saldado.
  - Sub-buckets v1.1: Current (0) | Grace (1-7) | Warning (8-14) |
    Alert (15-21) | Critical (22-30) | Severe (31-45) | Pre-default (46-49) |
    Default (50+).

El motor es PURO (sin I/O). El caller persiste el resultado.

Reusa funciones probadas de:
  - services.loanbook.reglas_negocio.calcular_cuota_desglosada
  - core.datetime_utils.today_bogota
"""
from __future__ import annotations

import copy
from datetime import date, datetime, timedelta
from typing import Any

from core.datetime_utils import today_bogota, now_iso_bogota
from services.loanbook.reglas_negocio import calcular_cuota_desglosada


# ─────────────────────────── Constantes canónicas ─────────────────────────────

DIAS_ENTRE_CUOTAS = {
    "semanal":   7,
    "quincenal": 14,
    "mensual":   28,
}

ANZI_PCT = 0.02
MORA_COP_POR_DIA = 2_000

ESTADOS_OFICIALES = (
    "pendiente_entrega",
    "al_dia",
    "mora_leve",
    "mora_media",
    "mora_grave",
    "default",
    "castigado",
    "reestructurado",
    "saldado",
)

ESTADOS_TERMINALES = {"saldado", "castigado"}
ESTADOS_SIN_PAGO = {"pendiente_entrega"} | ESTADOS_TERMINALES


# ─────────────────────────── Helpers internos ─────────────────────────────────

def _parse_date(raw: Any) -> date | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return None


def _intervalo(modalidad: str) -> int:
    return DIAS_ENTRE_CUOTAS.get(modalidad, 7)


def _es_pagada(cuota: dict) -> bool:
    estado = (cuota.get("estado") or "").lower()
    if estado in ("pagada", "paid", "pagado"):
        return True
    return float(cuota.get("monto_pagado") or 0) >= float(cuota.get("monto") or 0)


def _clasificar_estado_dpd(dpd: int) -> str:
    """Mapea DPD a estado canónico (Opción B + rangos v1.1)."""
    if dpd <= 0:
        return "al_dia"
    if dpd <= 7:
        return "mora_leve"
    if dpd <= 14:
        return "mora_media"
    if dpd <= 45:
        return "mora_grave"
    if dpd <= 49:
        return "default"
    return "castigado"


def _clasificar_sub_bucket(dpd: int) -> str:
    """Sub-bucket v1.1 (rangos del MAESTRO §3.2)."""
    if dpd <= 0:
        return "Current"
    if dpd <= 7:
        return "Grace"
    if dpd <= 14:
        return "Warning"
    if dpd <= 21:
        return "Alert"
    if dpd <= 30:
        return "Critical"
    if dpd <= 45:
        return "Severe"
    if dpd <= 49:
        return "Pre-default"
    return "Default"


# ════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PÚBLICA 1: crear_cronograma
# ════════════════════════════════════════════════════════════════════════════


def crear_cronograma(
    fecha_primer_pago: date,
    num_cuotas: int,
    cuota_valor: int,
    modalidad: str,
    capital_plan: int,
    cuota_estandar_plan: int,
    cuota_inicial: int = 0,
    fecha_cuota_inicial: date | None = None,
) -> list[dict]:
    """Genera cronograma con N cuotas según fecha_primer_pago + intervalo modal.

    Si cuota_inicial > 0, inserta al inicio una "cuota 0" con esa cantidad.
    La cuota 0 NO está sujeta al waterfall ANZI/mora — es un pago directo a capital
    (corresponde al monto pactado de cuota inicial al originar el crédito, RODDOS V2.1).

    Cada cuota regular (1..N) incluye desglose canónico capital/interés
    (calcular_cuota_desglosada).
    Si num_cuotas == 0 (caso P1S contado), retorna lista vacía o solo la cuota 0
    si cuota_inicial > 0.

    Args:
        fecha_primer_pago: fecha exacta de la primera cuota REGULAR (cuota #1).
                           El día de la semana queda fijado desde aquí.
        num_cuotas: cantidad de cuotas REGULARES (no cuenta la cuota 0).
        cuota_valor: monto periódico que paga el cliente en cada cuota regular.
        modalidad: semanal | quincenal | mensual.
        capital_plan: capital base del plan (sin intereses) — Raider 7.8M, Sport 5.75M.
        cuota_estandar_plan: cuota canónica del plan.
        cuota_inicial: monto de la cuota 0 (default 0 = sin cuota inicial pactada).
        fecha_cuota_inicial: fecha de la cuota 0. Si None, usa fecha_primer_pago como
                             referencia (se asume que la cuota 0 vence en o antes de
                             fecha_primer_pago).

    Returns:
        Lista de cuotas. Si cuota_inicial > 0, la primera entrada es la cuota 0.
        Las cuotas regulares siguen numeradas 1..N.
    """
    cronograma: list[dict] = []

    # ── Cuota 0 (si cuota_inicial > 0) ───────────────────────────────────────
    if cuota_inicial and cuota_inicial > 0:
        fecha_0 = fecha_cuota_inicial or fecha_primer_pago
        cronograma.append({
            "numero":            0,
            "fecha":             fecha_0.isoformat(),
            "monto":             int(cuota_inicial),
            "monto_capital":     int(cuota_inicial),
            "monto_interes":     0,
            "estado":            "pendiente",
            "monto_pagado":      0,
            "fecha_pago":        None,
            "mora_acumulada":    0,
            "anzi_pagado":       0,
            "mora_pagada":       0,
            "es_cuota_inicial":  True,
        })

    # ── Cuotas regulares (1..N) ──────────────────────────────────────────────
    if num_cuotas == 0:
        return cronograma

    if modalidad not in DIAS_ENTRE_CUOTAS:
        raise ValueError(f"Modalidad '{modalidad}' inválida. Use: semanal | quincenal | mensual.")

    intervalo = _intervalo(modalidad)

    # Desglose canónico capital/interés por cuota
    desglose = calcular_cuota_desglosada(
        capital_plan=int(capital_plan),
        total_cuotas=int(num_cuotas),
        cuota_estandar_plan=int(cuota_estandar_plan or cuota_valor),
    )
    capital_cuota = round(desglose["capital_cuota"])
    interes_cuota = round(desglose["interes_cuota"])

    # La última cuota absorbe redondeo para que Σ capital = capital_plan
    capital_acumulado = capital_cuota * (num_cuotas - 1)
    capital_ultima = int(capital_plan) - capital_acumulado

    for i in range(num_cuotas):
        es_ultima = (i == num_cuotas - 1)
        cap = capital_ultima if es_ultima else capital_cuota
        # interés es plano: NO varía por cuota (decisión Andrés - "interés plano Opción A")
        intr = interes_cuota
        monto = cap + intr

        # Si la cuota_valor pactada difiere de cap+intr (cuotas con descuento),
        # respetamos cuota_valor como monto y dejamos el desglose como referencia
        if cuota_valor != cap + intr:
            monto = cuota_valor

        cronograma.append({
            "numero":         i + 1,
            "fecha":          (fecha_primer_pago + timedelta(days=intervalo * i)).isoformat(),
            "monto":          int(monto),
            "monto_capital":  int(cap),
            "monto_interes":  int(intr),
            "estado":         "pendiente",
            "monto_pagado":   0,
            "fecha_pago":     None,
            "mora_acumulada": 0,
            "anzi_pagado":    0,
            "mora_pagada":    0,
            "es_cuota_inicial": False,
        })

    return cronograma


# ════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PÚBLICA 2: aplicar_pago — waterfall §4.1
# ════════════════════════════════════════════════════════════════════════════


def aplicar_pago(
    loanbook: dict,
    monto: int,
    fecha_pago: date,
    cuota_numero: int | None = None,
) -> dict:
    """Aplica un pago al loanbook según waterfall canónico §4.1 del MAESTRO.

    Orden waterfall:
        1º ANZI 2% del pago bruto (comisión avalista)
        2º Mora acumulada de la cuota objetivo
        3º Interés de la cuota
        4º Capital de la cuota
        5º Abono capital anticipado (si sobra)

    Args:
        loanbook: doc del crédito.
        monto: monto pagado por el cliente.
        fecha_pago: fecha en que se recibió el pago.
        cuota_numero: cuota a la que aplica. None = primera pendiente.

    Returns:
        {
          "loanbook": doc actualizado,
          "distribucion": {anzi, mora, interes, capital, abono_capital, no_aplicado},
        }

    Raises:
        ValueError: fecha futura, LB en estado sin pago, cuota no encontrada.
    """
    # Validación 1: fecha no futura
    hoy = today_bogota()
    if fecha_pago > hoy:
        raise ValueError(
            f"fecha_pago {fecha_pago.isoformat()} está en el futuro (hoy={hoy.isoformat()}). "
            "No se acepta pago futuro (regla R-07)."
        )

    estado = (loanbook.get("estado") or "").strip()
    if estado in ESTADOS_SIN_PAGO:
        if estado == "pendiente_entrega":
            raise ValueError(
                "El crédito está en pendiente_entrega — sin cronograma. "
                "Registre la entrega antes de aceptar pagos."
            )
        raise ValueError(
            f"El crédito está en estado terminal '{estado}' (saldado/castigado). "
            "No acepta pagos nuevos."
        )

    cuotas = loanbook.get("cuotas") or []
    if not cuotas:
        raise ValueError("El loanbook no tiene cronograma — no se puede registrar pago.")

    # Identificar cuota objetivo
    target_idx = None
    if cuota_numero is None:
        for i, c in enumerate(cuotas):
            if not _es_pagada(c):
                target_idx = i
                break
        if target_idx is None:
            raise ValueError("No hay cuotas pendientes — el crédito ya está saldado.")
    else:
        for i, c in enumerate(cuotas):
            if int(c.get("numero") or 0) == int(cuota_numero):
                target_idx = i
                break
        if target_idx is None:
            raise ValueError(f"Cuota #{cuota_numero} no encontrada en el cronograma.")

    cuota = cuotas[target_idx]

    # ═══════ Excepción: cuota 0 (cuota inicial) — sin waterfall ═══════
    # La cuota 0 es el pago inicial pactado al originar el crédito (RODDOS V2.1).
    # NO se le aplica ANZI 2% ni mora — va directo a capital.
    if cuota.get("es_cuota_inicial") is True or int(cuota.get("numero") or -1) == 0:
        lb_nuevo = copy.deepcopy(loanbook)
        cuota_nueva = lb_nuevo["cuotas"][target_idx]
        ya_pagado_ini = int(cuota_nueva.get("monto_pagado") or 0)
        monto_cuota_ini = int(cuota_nueva.get("monto") or 0)
        capital_aplicado = min(int(monto), max(0, monto_cuota_ini - ya_pagado_ini))
        no_aplicado_ini = int(monto) - capital_aplicado

        cuota_nueva["monto_pagado"] = ya_pagado_ini + capital_aplicado
        cuota_nueva["fecha_pago"] = fecha_pago.isoformat()
        if cuota_nueva["monto_pagado"] >= monto_cuota_ini:
            cuota_nueva["estado"] = "pagada"
        elif cuota_nueva["monto_pagado"] > 0:
            cuota_nueva["estado"] = "parcial"

        lb_nuevo["total_capital_pagado"] = (
            int(lb_nuevo.get("total_capital_pagado") or 0) + capital_aplicado
        )
        lb_nuevo = derivar_estado(lb_nuevo, hoy=fecha_pago)
        return {
            "loanbook": lb_nuevo,
            "distribucion": {
                "anzi":          0,
                "mora":          0,
                "interes":       0,
                "capital":       capital_aplicado,
                "abono_capital": 0,
                "no_aplicado":   no_aplicado_ini,
            },
        }

    # ═══════ Waterfall §4.1 (cuotas regulares 1..N) ═══════
    rem = int(monto)

    # 1º ANZI 2% del pago bruto
    anzi = round(monto * ANZI_PCT)
    rem -= anzi

    # 2º Mora acumulada de la cuota
    mora_pendiente = max(0, int(cuota.get("mora_acumulada") or 0) - int(cuota.get("mora_pagada") or 0))
    mora = min(rem, mora_pendiente)
    rem -= mora

    # 3º Interés de la cuota
    interes_pendiente = max(0, int(cuota.get("monto_interes") or 0))
    # Si la cuota ya tiene parte pagada, calculamos lo que falta del interés
    ya_pagado = int(cuota.get("monto_pagado") or 0)
    # Aplicación parcial: el interés cubre lo que falta del componente interés
    # Asumimos que monto_pagado anterior ya cubrió interés primero, luego capital
    interes_ya_pagado = min(ya_pagado, interes_pendiente)
    interes_falta = interes_pendiente - interes_ya_pagado
    interes = min(rem, interes_falta)
    rem -= interes

    # 4º Capital de la cuota
    capital_pendiente = max(0, int(cuota.get("monto_capital") or 0))
    capital_ya_pagado = max(0, ya_pagado - interes_ya_pagado)
    capital_falta = capital_pendiente - capital_ya_pagado
    capital = min(rem, capital_falta)
    rem -= capital

    # 5º Abono a capital anticipado (limitado por saldo restante de capital del crédito)
    capital_total_pendiente = sum(
        int(c.get("monto_capital") or 0) - max(0, int(c.get("monto_pagado") or 0) - int(c.get("monto_interes") or 0))
        for c in cuotas if not _es_pagada(c) and c is not cuota
    )
    abono_capital = min(rem, capital_total_pendiente)
    rem -= abono_capital

    # Lo que quede sobrante (no debería)
    no_aplicado = max(0, rem)

    # ═══════ Actualizar la cuota ═══════
    lb_nuevo = copy.deepcopy(loanbook)
    cuota_nueva = lb_nuevo["cuotas"][target_idx]

    cuota_nueva["monto_pagado"] = ya_pagado + interes + capital
    cuota_nueva["fecha_pago"] = fecha_pago.isoformat()
    cuota_nueva["anzi_pagado"] = int(cuota_nueva.get("anzi_pagado") or 0) + anzi
    cuota_nueva["mora_pagada"] = int(cuota_nueva.get("mora_pagada") or 0) + mora

    # Estado de la cuota
    monto_total_cuota = int(cuota_nueva.get("monto") or 0)
    if cuota_nueva["monto_pagado"] >= monto_total_cuota:
        cuota_nueva["estado"] = "pagada"
    elif cuota_nueva["monto_pagado"] > 0:
        cuota_nueva["estado"] = "parcial"

    # Aplicar abono anticipado: distribuir entre capital de cuotas pendientes futuras
    # Por simplicidad: marcar el abono en la cuota actual; el motor lo refleja en saldo
    cuota_nueva["abono_capital_anticipado"] = (
        int(cuota_nueva.get("abono_capital_anticipado") or 0) + abono_capital
    )

    # ═══════ Actualizar buckets contables persistentes ═══════
    lb_nuevo["total_anzi_pagado"] = int(lb_nuevo.get("total_anzi_pagado") or 0) + anzi
    lb_nuevo["total_intereses_mora_pagados"] = int(lb_nuevo.get("total_intereses_mora_pagados") or 0) + mora
    lb_nuevo["total_intereses_cuota_pagados"] = int(lb_nuevo.get("total_intereses_cuota_pagados") or 0) + interes
    lb_nuevo["total_capital_pagado"] = int(lb_nuevo.get("total_capital_pagado") or 0) + capital + abono_capital

    # Recalcular derivados
    lb_nuevo = derivar_estado(lb_nuevo, hoy=fecha_pago)

    return {
        "loanbook": lb_nuevo,
        "distribucion": {
            "anzi":          anzi,
            "mora":          mora,
            "interes":       interes,
            "capital":       capital,
            "abono_capital": abono_capital,
            "no_aplicado":   no_aplicado,
        },
    }


# ════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PÚBLICA 3: derivar_estado
# ════════════════════════════════════════════════════════════════════════════


def derivar_estado(loanbook: dict, hoy: date | None = None) -> dict:
    """Recalcula derivados del loanbook sin tocar cronograma.

    Derivados que recalcula:
      - cuotas_pagadas, cuotas_vencidas
      - saldo_pendiente, total_pagado
      - dpd (días desde la cuota más antigua sin pagar)
      - mora_acumulada_cop = dpd × 2.000
      - sub_bucket (canónico v1.1)
      - estado (derivado del DPD, respeta terminales saldado/castigado/reestructurado)

    NO modifica:
      - cronograma (fechas, montos, desglose)
      - identidad del crédito
      - términos pactados

    Idempotente: derivar_estado(derivar_estado(lb)) == derivar_estado(lb).
    """
    if hoy is None:
        hoy = today_bogota()

    lb = copy.deepcopy(loanbook)
    estado_actual = (lb.get("estado") or "").strip()

    # Caso: pendiente_entrega o sin cronograma → no recalcula nada
    if estado_actual == "pendiente_entrega" or not lb.get("cuotas"):
        lb["saldo_pendiente"] = int(lb.get("valor_total") or 0)
        lb["total_pagado"] = 0
        lb["dpd"] = 0
        lb["sub_bucket"] = "Current"
        lb["mora_acumulada_cop"] = 0
        lb["cuotas_pagadas"] = 0
        lb["cuotas_vencidas"] = 0
        lb["fecha_ultima_recalculacion"] = now_iso_bogota()
        return lb

    cuotas = lb["cuotas"]
    # valor_total = SUMA DE TODAS las cuotas (incluye cuota 0 si existe)
    valor_total = int(lb.get("valor_total") or sum(int(c.get("monto") or 0) for c in cuotas))

    # ── Suma de pagos (incluye pagos a cuota 0)
    total_pagado = sum(int(c.get("monto_pagado") or 0) for c in cuotas)
    saldo_pendiente = max(0, valor_total - total_pagado)

    # ── Conteos
    cuotas_pagadas = sum(1 for c in cuotas if _es_pagada(c))
    cuotas_vencidas = sum(
        1 for c in cuotas
        if not _es_pagada(c) and _parse_date(c.get("fecha")) and _parse_date(c.get("fecha")) < hoy
    )

    # ── DPD canónico: días desde la cuota REGULAR más antigua sin pagar
    # IMPORTANTE: la cuota 0 (cuota_inicial) NO genera mora ni cuenta para DPD.
    # El cliente puede tener cuota_inicial pendiente sin que eso lo ponga en mora —
    # la cuota_inicial se cobra aparte según política comercial.
    dpd = 0
    fecha_mas_antigua = None
    for c in cuotas:
        # Saltar cuota 0 (no aporta DPD ni mora)
        if c.get("es_cuota_inicial") is True or int(c.get("numero") or -1) == 0:
            continue
        if _es_pagada(c):
            continue
        f = _parse_date(c.get("fecha"))
        if f is None:
            continue
        if f >= hoy:
            continue  # cuota futura, no atrasada
        if fecha_mas_antigua is None or f < fecha_mas_antigua:
            fecha_mas_antigua = f
    if fecha_mas_antigua is not None:
        dpd = max(0, (hoy - fecha_mas_antigua).days)

    # ── Estado derivado
    # saldado solo si TODAS las cuotas (incluyendo cuota 0) están cubiertas
    if total_pagado >= valor_total or saldo_pendiente == 0:
        estado_nuevo = "saldado"
    elif estado_actual in ("reestructurado", "castigado"):
        # Estados terminales/especiales no se sobrescriben automáticamente
        estado_nuevo = estado_actual
    else:
        estado_nuevo = _clasificar_estado_dpd(dpd)

    sub_bucket = _clasificar_sub_bucket(dpd)
    mora_cop = dpd * MORA_COP_POR_DIA

    # ── Persistir derivados
    lb["total_pagado"] = total_pagado
    lb["saldo_pendiente"] = saldo_pendiente
    lb["cuotas_pagadas"] = cuotas_pagadas
    lb["cuotas_vencidas"] = cuotas_vencidas
    lb["dpd"] = dpd
    lb["estado"] = estado_nuevo
    lb["sub_bucket"] = sub_bucket
    lb["mora_acumulada_cop"] = mora_cop
    lb["fecha_ultima_recalculacion"] = now_iso_bogota()

    return lb


# ════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PÚBLICA 4: auditar
# ════════════════════════════════════════════════════════════════════════════


def auditar(loanbook: dict, hoy: date | None = None) -> dict:
    """Compara doc actual vs versión canónica recalculada y lista divergencias.

    Útil para semáforo verde/amarilla/roja del módulo:
      verde:    sin divergencias
      amarilla: divergencias en derivados (saldo, dpd, sub_bucket, estado)
      roja:    divergencias estructurales (num_cuotas, capital_plan, valor_total)
    """
    if hoy is None:
        hoy = today_bogota()

    canonico = derivar_estado(loanbook, hoy=hoy)
    violaciones = []

    campos_derivados = [
        "saldo_pendiente", "total_pagado", "cuotas_pagadas", "cuotas_vencidas",
        "dpd", "estado", "sub_bucket", "mora_acumulada_cop",
    ]
    for k in campos_derivados:
        v_actual = loanbook.get(k)
        v_canonico = canonico.get(k)
        # Si el campo no existe en el doc original, NO es violacion — el motor
        # lo agrega como derivado canonico (no es divergencia, es enriquecimiento)
        if v_actual is None:
            continue
        if v_actual == v_canonico:
            continue
        violaciones.append({
            "campo":   k,
            "antes":   v_actual,
            "despues": v_canonico,
            "tipo":    "derivado",
        })

    # Estructurales (no se recalculan, deberian coincidir)
    estado_actual = (loanbook.get("estado") or "").strip()
    if estado_actual != "pendiente_entrega":
        valor_total_calc = sum(int(c.get("monto") or 0) for c in (loanbook.get("cuotas") or []))
        v_actual = loanbook.get("valor_total")
        if v_actual and valor_total_calc:
            diff = abs(v_actual - valor_total_calc)
            tolerancia = max(100, int(v_actual * 0.01))
            if diff > tolerancia:
                tipo = "estructural" if diff > int(v_actual * 0.05) else "derivado"
                violaciones.append({
                    "campo":   "valor_total",
                    "antes":   v_actual,
                    "despues": valor_total_calc,
                    "tipo":    tipo,
                })

    severidad = "verde"
    if violaciones:
        severidad = "roja" if any(v["tipo"] == "estructural" for v in violaciones) else "amarilla"

    return {
        "loanbook_id": loanbook.get("loanbook_id") or loanbook.get("loanbook_codigo"),
        "cliente":     (loanbook.get("cliente") or {}).get("nombre")
                       or loanbook.get("cliente_nombre"),
        "ok":          len(violaciones) == 0,
        "severidad":   severidad,
        "violaciones": violaciones,
    }

