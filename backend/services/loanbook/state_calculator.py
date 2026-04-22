"""
services/loanbook/state_calculator.py — Fuente única de verdad para el estado calculado
de un loanbook.

Función principal:
    recalcular_loanbook(lb: dict) -> dict

Recalcula TODOS los campos derivados a partir de las fuentes autoritativas:
  - plan_codigo + modalidad  → total_cuotas canónico
  - cuota_monto (per-period) → valor_total
  - lista cuotas             → total_pagado, saldo_capital
  - cuotas + hoy             → dpd
  - dpd                      → estado (respeta terminales: saldado, castigado)

Sin I/O — el caller es responsable de persistir el resultado en MongoDB.

Constantes compartidas con auditor.py (BUILD 1). En un refactor posterior
se pueden unificar en un solo módulo de constantes de negocio.
"""

import copy
from datetime import date

from core.loanbook_model import calcular_dpd, estado_from_dpd

# ─────────────────────── Constantes de negocio ────────────────────────────────

PLANES_RODDOS: dict[str, int] = {
    "P15S": 15,   # Comparendos — 15 cuotas semanales
    "P39S": 39,   # Motos estándar — 39 semanas ≈ 9 meses
    "P52S": 52,   # Motos estándar — 52 semanas = 1 año
    "P78S": 78,   # Motos premium — 78 semanas ≈ 18 meses
}

MULTIPLICADOR_TOTAL_CUOTAS: dict[str, float] = {
    "semanal":   1.0,
    "quincenal": 1 / 2.2,   # round(39/2.2) = 18
    "mensual":   1 / 4.4,   # round(39/4.4) = 9
}

MULTIPLICADOR_VALOR_CUOTA: dict[str, float] = {
    "semanal":   1.0,
    "quincenal": 2.2,
    "mensual":   4.4,
}

# Estados terminales — no se sobreescriben con DPD
ESTADOS_TERMINALES = {"saldado", "castigado"}

# Estado reservado para créditos no entregados — no tienen DPD
ESTADO_NO_ENTREGADO = "pendiente_entrega"


# ─────────────────────── Helpers internos ─────────────────────────────────────

def _derivar_total_cuotas(plan_codigo: str, modalidad: str) -> int | None:
    """Número canónico de cuotas según plan y modalidad."""
    base = PLANES_RODDOS.get(plan_codigo)
    if base is None:
        return None
    factor = MULTIPLICADOR_TOTAL_CUOTAS.get(modalidad, 1.0)
    return round(base * factor)


def _plan_codigo(lb: dict) -> str | None:
    return lb.get("plan_codigo") or lb.get("plan", {}).get("codigo")


def _modalidad(lb: dict) -> str:
    return lb.get("modalidad") or lb.get("plan", {}).get("modalidad") or "semanal"


def _cuota_inicial(lb: dict) -> float:
    return lb.get("plan", {}).get("cuota_inicial", 0) or 0


def _cuota_monto(lb: dict) -> float:
    """Valor por cuota en la modalidad del crédito (ya escalado)."""
    return lb.get("cuota_monto") or lb.get("plan", {}).get("cuota_valor") or 0.0


# ─────────────────────── Función principal ────────────────────────────────────

def recalcular_loanbook(lb: dict, *, hoy: date | None = None) -> dict:
    """
    Recalcula todos los campos derivados de un loanbook sin modificar el original.

    Retorna una COPIA actualizada del documento. Sin I/O.

    Parámetros:
        lb:   Documento loanbook (sin _id de MongoDB).
        hoy:  Fecha de referencia (default: date.today()). Inyectable para tests.

    Campos recalculados:
        num_cuotas     ← PLANES_RODDOS[plan_codigo] × MULTIPLICADOR_TOTAL_CUOTAS[modalidad]
        valor_total    ← num_cuotas × cuota_monto + cuota_inicial
        total_pagado   ← Σ monto de cuotas con estado="pagada"
        saldo_capital  ← Σ monto de cuotas con estado != "pagada"
        dpd            ← días desde la cuota vencida más antigua sin pagar
        estado         ← derivado de dpd (respeta terminales: saldado, castigado)
        plan.total_cuotas ← sincronizado con num_cuotas si existe subdoc plan
    """
    if hoy is None:
        hoy = date.today()

    lb = copy.deepcopy(lb)

    plan_codigo = _plan_codigo(lb)
    modalidad = _modalidad(lb)
    cuota_monto = _cuota_monto(lb)
    cuota_inicial = _cuota_inicial(lb)
    cuotas: list[dict] = lb.get("cuotas", [])

    # ── 1. Corregir num_cuotas desde PLANES_RODDOS ───────────────────────────
    total_cuotas_correcto = _derivar_total_cuotas(plan_codigo, modalidad) if plan_codigo else None

    if total_cuotas_correcto is not None:
        lb["num_cuotas"] = total_cuotas_correcto
        # Sincronizar subdoc plan si existe
        if isinstance(lb.get("plan"), dict):
            lb["plan"]["total_cuotas"] = total_cuotas_correcto

    num_cuotas_efectivo = lb.get("num_cuotas") or 0

    # ── 2. Corregir valor_total ───────────────────────────────────────────────
    if num_cuotas_efectivo and cuota_monto:
        lb["valor_total"] = round(num_cuotas_efectivo * cuota_monto + cuota_inicial)

    # ── 3. Recalcular financials desde lista de cuotas ───────────────────────
    if cuotas:
        total_pagado = sum(c.get("monto", 0) for c in cuotas if c.get("estado") == "pagada")
        saldo_capital = sum(c.get("monto", 0) for c in cuotas if c.get("estado") != "pagada")
    else:
        # Sin cuotas aún (crédito recién creado): saldo = total
        total_pagado = lb.get("total_pagado", 0) or 0
        saldo_capital = num_cuotas_efectivo * cuota_monto - total_pagado

    lb["total_pagado"] = round(total_pagado)
    lb["saldo_capital"] = round(max(0, saldo_capital))

    # ── 4. DPD y estado ──────────────────────────────────────────────────────
    estado_actual = lb.get("estado", "activo")

    if estado_actual in ESTADOS_TERMINALES or estado_actual == ESTADO_NO_ENTREGADO:
        # No tocar terminales ni créditos pendientes de entrega
        pass
    else:
        dpd = calcular_dpd(cuotas, hoy)
        lb["dpd"] = dpd
        lb["estado"] = estado_from_dpd(dpd)

    return lb


# ─────────────────────── Campos que son $set para MongoDB ─────────────────────

CAMPOS_RECALCULADOS = (
    "num_cuotas",
    "valor_total",
    "total_pagado",
    "saldo_capital",
    "dpd",
    "estado",
    "plan",
)


def patch_set_from_recalculo(lb_original: dict) -> dict:
    """
    Atajo que devuelve solo los campos recalculados listos para MongoDB $set.

    Uso:
        patch = patch_set_from_recalculo(lb_doc)
        await db.loanbook.update_one({"loanbook_id": lb_id}, {"$set": patch})
    """
    recalculado = recalcular_loanbook(lb_original)
    return {k: recalculado[k] for k in CAMPOS_RECALCULADOS if k in recalculado}
