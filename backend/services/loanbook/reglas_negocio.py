"""
services/loanbook/reglas_negocio.py — Reglas de negocio Roddos (sin hardcoding).

FUENTE DE VERDAD para:
  - Número de cuotas por plan × modalidad  → leído de catalogo_service (MongoDB)
  - Multiplicador de valor de cuota por modalidad
  - Días entre cobros por modalidad
  - Mora diaria en COP
  - Porcentaje ANZI

REGLA R-06: PLAN_CUOTAS nunca se hardcodea en Python.
La tabla vive en la colección `catalogo_planes` de MongoDB. Este módulo
la expone a través de una interfaz lazy que lee del cache en memoria
calentado por catalogo_service.warm_catalogo() al inicio del proceso.

En tests unitarios, conftest.py llama a catalogo_service.seed_for_tests()
antes de que corra cualquier test, con los mismos datos que poblar_catalogos.py.

Sin I/O propio — todas las funciones son síncronas y usan el cache en memoria.
"""

from datetime import date

from services.loanbook import catalogo_service as _cs

# ─────────────────────── Constantes de cobro ──────────────────────────────────
# Estas constantes NO son datos de catálogo — son parámetros fijos del negocio
# aprobados por operaciones. No van a MongoDB.

# Factor por el que se multiplica la cuota semanal base para obtener la cuota
# en otra modalidad. Solo aplica a RDX P39S+.
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

# Mora fija en pesos colombianos por día de atraso (sin cap — R-22)
MORA_COP_POR_DIA: int = 2_000

# Porcentaje ANZI (administración de cartera) — prioridad 1 del waterfall (R-21)
ANZI_PCT: float = 0.02


# ─────────────────────── PLAN_CUOTAS lazy (R-06) ──────────────────────────────
# PLAN_CUOTAS ya no es un dict literal. Es una vista lazy del cache en memoria.
# Comportamiento idéntico al antiguo dict para código consumidor — soporta
# .get(), __contains__, .items(), .keys(), .values(), y subscript.
#
# Criterio C-03: grep "PLAN_CUOTAS.*=.*{" → 0 resultados. ✓

class _LazyPlanCuotas(dict):
    """Dict lazy que se auto-popula desde catalogo_service en el primer acceso.

    Internamente es un dict vacío hasta que se llama cualquier método.
    Al primer uso, llama a catalogo_service.get_planes_cuotas_dict() y
    carga los datos del cache en memoria.

    Diseño:
    - En producción: el cache ya está calentado por warm_catalogo() en lifespan.
    - En tests: conftest.py llama seed_for_tests() antes de los tests.
    - El flag _loaded previene refresh infinito cuando el cache está vacío.
    """

    _loaded: bool = False

    def _refresh(self) -> None:
        data = _cs.get_planes_cuotas_dict()
        self.clear()
        super().update(data)
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

    def items(self):
        self._ensure()
        return super().items()

    def keys(self):
        self._ensure()
        return super().keys()

    def values(self):
        self._ensure()
        return super().values()

    def __iter__(self):
        self._ensure()
        return super().__iter__()

    def __len__(self):
        self._ensure()
        return super().__len__()

    def _invalidate(self) -> None:
        """Fuerza recarga en el próximo acceso. Útil en tests."""
        self._loaded = False
        self.clear()


PLAN_CUOTAS: dict[str, dict[str, int | None]] = _LazyPlanCuotas()


# ─────────────────────── Funciones puras ──────────────────────────────────────

def get_num_cuotas(plan_codigo: str, modalidad: str) -> int | None:
    """Número canónico de cuotas para plan × modalidad.

    Lee del cache en memoria (calentado desde catalogo_planes en MongoDB).
    Nunca hace round() ni aplica fórmulas.

    Retorna None si:
      - plan_codigo no existe en el catálogo
      - la combinación plan × modalidad no está configurada (ej. P15S quincenal)

    Args:
        plan_codigo: "P1S", "P2S", ..., "P78S"
        modalidad:   "semanal", "quincenal" o "mensual"

    Returns:
        int  — número de cuotas según tabla maestra
        None — combinación no configurada
    """
    return _cs.get_num_cuotas_sync(plan_codigo, modalidad)


def get_valor_cuota(cuota_base_semanal: float, modalidad: str) -> float:
    """Valor de cuota en la modalidad dada, escalado desde la cuota semanal base.

    Solo aplica a RDX P39S+. Para RODANTE siempre es ×1.0.

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
    transacción. Un pago registrado con fecha futura es un error operativo.

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
