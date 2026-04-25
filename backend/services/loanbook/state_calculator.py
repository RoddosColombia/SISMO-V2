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
from core.datetime_utils import now_bogota, today_bogota, now_iso_bogota

from core.loanbook_model import calcular_dpd, estado_from_dpd
from services.loanbook.reglas_negocio import get_num_cuotas
from services.loanbook import catalogo_service as _cs

# ─────────────────────── Constantes de negocio ────────────────────────────────

# PLANES_RODDOS — dict lazy: plan_codigo → num_cuotas_semanal.
# Se auto-popula desde catalogo_service en el primer acceso.
# En producción el cache ya está calentado por warm_catalogo() en lifespan.
# En tests conftest.py llama seed_for_tests() antes de los tests.

class _LazyPlanesRoddos(dict):
    """Dict lazy que se auto-popula desde catalogo_service en el primer acceso."""

    _loaded: bool = False

    def _refresh(self) -> None:
        self.clear()
        super().update(_cs.get_planes_roddos_dict())
        self._loaded = True

    def _ensure(self) -> None:
        if not self._loaded:
            self._refresh()

    def get(self, key, default=None):
        self._ensure()
        return super().get(key, default)

    def __getitem__(self, key):
        self._ensure()
        return super().__getitem__(key)

    def __contains__(self, key):
        self._ensure()
        return super().__contains__(key)

    def keys(self):
        self._ensure()
        return super().keys()

    def values(self):
        self._ensure()
        return super().values()

    def items(self):
        self._ensure()
        return super().items()

    def __iter__(self):
        self._ensure()
        return super().__iter__()

    def __len__(self):
        self._ensure()
        return super().__len__()

    def _invalidate(self) -> None:
        self._loaded = False
        self.clear()


PLANES_RODDOS: dict[str, int] = _LazyPlanesRoddos()

# Estados terminales — no se sobreescriben con DPD
ESTADOS_TERMINALES = {"saldado", "castigado"}

# Estado reservado para créditos no entregados — no tienen DPD
ESTADO_NO_ENTREGADO = "pendiente_entrega"


# ─────────────────────── Helpers internos ─────────────────────────────────────

def _derivar_total_cuotas(plan_codigo: str, modalidad: str) -> int | None:
    """Número canónico de cuotas según plan y modalidad.

    Delega a reglas_negocio.get_num_cuotas() — tabla fija, sin fórmulas.
    """
    return get_num_cuotas(plan_codigo, modalidad)


def _plan_codigo(lb: dict) -> str | None:
    return lb.get("plan_codigo") or lb.get("plan", {}).get("codigo")


def _modalidad(lb: dict) -> str:
    return lb.get("modalidad") or lb.get("plan", {}).get("modalidad") or "semanal"


def _cuota_inicial(lb: dict) -> float:
    return lb.get("plan", {}).get("cuota_inicial", 0) or 0


def _cuota_monto(lb: dict) -> float:
    """Valor por cuota en la modalidad del crédito (ya escalado)."""
    return (
        lb.get("cuota_periodica")
        or lb.get("cuota_monto")
        or lb.get("plan", {}).get("cuota_valor")
        or 0.0
    )


# ─────────────────────── Función principal ────────────────────────────────────

def recalcular_loanbook(lb: dict, *, hoy: date | None = None) -> dict:
    """
    Recalcula todos los campos derivados de un loanbook sin modificar el original.

    Retorna una COPIA actualizada del documento. Sin I/O.

    Parámetros:
        lb:   Documento loanbook (sin _id de MongoDB).
        hoy:  Fecha de referencia (default: today_bogota()). Inyectable para tests.

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
        hoy = today_bogota()

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
        total_pagado   = sum(c.get("monto", 0) for c in cuotas if c.get("estado") == "pagada")
        cuotas_pagadas = sum(1 for c in cuotas if c.get("estado") == "pagada")
        saldo_cuotas   = sum(c.get("monto", 0) for c in cuotas if c.get("estado") != "pagada")
    else:
        # Sin cuotas aún (crédito recién creado): saldo = total
        total_pagado   = lb.get("total_pagado", 0) or 0
        cuotas_pagadas = 0
        saldo_cuotas   = num_cuotas_efectivo * cuota_monto - total_pagado

    lb["total_pagado"] = round(total_pagado)

    # Si el loanbook tiene capital_plan (almacenado al registrar entrega), usar
    # calcular_saldos() para separar capital de intereses con la fórmula canónica.
    # Sin capital_plan (loanbooks legacy): fallback a la suma de cuotas.
    capital_plan = lb.get("capital_plan")
    if capital_plan and num_cuotas_efectivo and cuota_monto:
        from services.loanbook.reglas_negocio import calcular_saldos
        cuota_std = lb.get("cuota_estandar_plan") or int(cuota_monto)
        _s = calcular_saldos(
            int(capital_plan),
            num_cuotas_efectivo,
            int(cuota_monto),
            cuotas_pagadas,
            cuota_estandar_plan=cuota_std,
        )
        lb["saldo_capital"]   = _s["saldo_capital"]
        lb["saldo_intereses"] = _s["saldo_intereses"]
    else:
        lb["saldo_capital"] = round(max(0, saldo_cuotas))

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
    "saldo_intereses",   # calculado por calcular_saldos() cuando capital_plan disponible
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
