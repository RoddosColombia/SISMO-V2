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

from datetime import date, timedelta
from math import ceil
from core.datetime_utils import now_bogota, today_bogota, now_iso_bogota

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
        hoy:        fecha de referencia (default: today_bogota()). Inyectable en tests.

    Raises:
        ValueError: si fecha_pago > hoy, con mensaje descriptivo.
    """
    if hoy is None:
        hoy = today_bogota()
    if fecha_pago > hoy:
        raise ValueError(
            f"fecha_pago '{fecha_pago}' está en el futuro (hoy={hoy}). "
            "No se puede registrar un pago que aún no ocurrió."
        )


def calcular_saldos(
    capital_plan: int,
    total_cuotas: int,
    cuota_periodica: int,
    cuotas_pagadas: int,
    cuota_estandar_plan: int | None = None,
    moto_valor_origen: int | None = None,
) -> dict:
    """Calcula saldo_capital, saldo_intereses, monto_original y ltv.

    Fuente de verdad: Excel loanbook_roddos_2026-04-25.xlsx.

    capital_plan: precio venta base sin extras ni IVA.
        Raider 125     = 7_800_000
        TVS Sport 100  = 5_750_000
        RODANTE        = monto_original del producto

    cuota_estandar_plan: cuota del catalogo_planes. Puede diferir de
        cuota_periodica si el conductor tiene condición especial.
        Si None, se usa cuota_periodica.

    REGLA CRÍTICA: saldo_intereses usa cuota_estandar_plan, NO cuota_periodica.
    El interés es propiedad del plan financiero, no de la cuota negociada.

    Casos verificados (diff=0):
        LB-0001 P52S Raider  sc=6_900_000  si=1_375_400
        LB-0002 P78S Sport   sc=5_307_692  si=4_052_308
        LB-0003 P78S Raider  sc=7_200_000  si=3_592_800
        LB-0027 P78S Sport   cuota_real=145_000 cuota_std=130_000  si=4_390_000
        LB-0028 P39S Sport   cuota_real=204_000 cuota_std=175_000  si=1_069_750
    """
    if total_cuotas == 0:
        return {
            "cuotas_pendientes": 0,
            "capital_por_cuota": 0.0,
            "interes_por_cuota": 0.0,
            "saldo_capital":     0,
            "saldo_intereses":   0,
            "monto_original":    0,
            "ltv":               None,
        }
    cuota_std = cuota_estandar_plan if cuota_estandar_plan else cuota_periodica
    pendientes  = total_cuotas - cuotas_pagadas
    cap_cuota   = capital_plan / total_cuotas
    int_cuota   = (cuota_std * total_cuotas - capital_plan) / total_cuotas
    sc  = round(cap_cuota * pendientes)
    si  = round(int_cuota * pendientes)
    mo  = cuota_periodica * total_cuotas
    ltv = round(mo / moto_valor_origen, 4) if moto_valor_origen else None
    return {
        "cuotas_pendientes": pendientes,
        "capital_por_cuota": round(cap_cuota, 2),
        "interes_por_cuota": round(int_cuota, 2),
        "saldo_capital":     sc,
        "saldo_intereses":   si,
        "monto_original":    mo,
        "ltv":               ltv,
    }


def primer_miercoles_cobro(fecha_entrega: date) -> date:
    """Calcula la fecha de la primera cuota según la Regla del Miércoles RODDOS.

    Primera cuota = primer miércoles >= fecha_entrega + 7 días.

    Si la entrega cae un miércoles, el primer pago es el miércoles SIGUIENTE
    (mínimo 7 días después, nunca el mismo día).

    Args:
        fecha_entrega: fecha en que se entregó la moto al cliente

    Returns:
        date — fecha del primer miércoles de cobro

    Casos verificados:
        entrega 2026-03-05 (jue) → primera cuota 2026-03-18 (mié)
        entrega 2026-03-10 (mar) → primera cuota 2026-03-18 (mié)
        entrega 2026-03-24 (mar) → primera cuota 2026-04-01 (mié)
        entrega 2026-03-25 (mié) → primera cuota 2026-04-01 (mié)
        entrega 2026-03-27 (vie) → primera cuota 2026-04-08 (mié)
        entrega 2026-03-28 (sáb) → primera cuota 2026-04-08 (mié)
        entrega 2026-04-08 (mié) → primera cuota 2026-04-15 (mié)  ← entrega=mié
        entrega 2026-04-10 (vie) → primera cuota 2026-04-22 (mié)
    """
    start = fecha_entrega + timedelta(days=7)
    days_until_wed = (2 - start.weekday()) % 7
    return start + timedelta(days=days_until_wed)


# ============================================================
# MOTOR FINANCIERO RODDOS
# Fuente de verdad: Excel loanbook_roddos_2026-04-25.xlsx
# Todas las fórmulas verificadas contra casos reales con diff=0
# ============================================================


def calcular_cuota_desglosada(
    capital_plan: int,
    total_cuotas: int,
    cuota_estandar_plan: int,
) -> dict:
    """Desglose de capital e interés por cuota individual.

    Usado al generar el cronograma y al contabilizar cada pago.

    Casos verificados contra Hoja1 del Excel:
        Raider P52S semanal:  capital=150_000  interes=29_900
        Raider P78S semanal:  capital=100_000  interes=49_900
        Sport  P78S semanal:  capital=73_718   interes=56_282
        Raider P39S semanal:  capital=200_154  interes=9_846
    """
    if total_cuotas == 0:
        return {"capital_cuota": 0.0, "interes_cuota": 0.0}
    capital_cuota = capital_plan / total_cuotas
    interes_cuota = (cuota_estandar_plan * total_cuotas - capital_plan) / total_cuotas
    return {
        "capital_cuota": round(capital_cuota, 2),
        "interes_cuota": round(interes_cuota, 2),
    }


def calcular_pago_aplicado(
    monto_pagado: int,
    mora_pendiente: int,
    capital_cuota: float,
    interes_cuota: float,
    saldo_capital_actual: int,
) -> dict:
    """Waterfall de pago — Opción A (interés plano, confirmado por Andrés Sanjuan).

    Orden de prioridad:
        1. Mora / ANZI
        2. Interés de la cuota
        3. Capital de la cuota
        4. Abono extra a capital (si el conductor paga más)

    Interés plano: el interés por cuota NO varía aunque haya abono a capital.
    """
    rem = monto_pagado

    anzi = min(rem, mora_pendiente)
    rem -= anzi

    interes = min(rem, round(interes_cuota))
    rem -= interes

    capital = min(rem, round(capital_cuota))
    rem -= capital

    abono_extra = min(rem, max(0, saldo_capital_actual - round(capital_cuota)))
    rem -= abono_extra

    return {
        "anzi_pagado":          anzi,
        "interes_pagado":       interes,
        "capital_pagado":       capital,
        "abono_capital_extra":  abono_extra,
        "no_aplicado":          rem,
        "capital_total_pagado": capital + abono_extra,
    }


def calcular_mora(
    dpd: int,
    tasa_mora_diaria_cop: int = MORA_COP_POR_DIA,
) -> dict:
    """Mora acumulada en COP y sub_bucket según DPD.

    Tasa: 2.000 COP/día (LOANBOOK_MAESTRO_v1.1). Sin cap (R-22).

    Sub-buckets calibrados para cobro semanal RODDOS:
        0       → Current
        1-7     → Grace
        8-14    → Warning
        15-21   → Alert
        22-30   → Critical
        31-60   → Severe
        61-89   → Pre-Default
        90-119  → Default
        120+    → Charge-Off
    """
    mora_cop = dpd * tasa_mora_diaria_cop
    if dpd == 0:
        bucket = "Current"
    elif dpd <= 7:
        bucket = "Grace"
    elif dpd <= 14:
        bucket = "Warning"
    elif dpd <= 21:
        bucket = "Alert"
    elif dpd <= 30:
        bucket = "Critical"
    elif dpd <= 60:
        bucket = "Severe"
    elif dpd <= 89:
        bucket = "Pre-Default"
    elif dpd <= 119:
        bucket = "Default"
    else:
        bucket = "Charge-Off"
    return {
        "mora_acumulada_cop":  mora_cop,
        "sub_bucket_semanal":  bucket,
    }


def calcular_fecha_vencimiento(
    fecha_primer_cobro: date,
    total_cuotas: int,
    modalidad_pago: str,
) -> date:
    """Fecha de la última cuota del crédito."""
    dias = (total_cuotas - 1) * DIAS_ENTRE_CUOTAS.get(modalidad_pago, 7)
    return fecha_primer_cobro + timedelta(days=dias)


def generar_cronograma(
    loanbook_id: str,
    cliente_nombre: str,
    fecha_primer_cobro: date,
    total_cuotas: int,
    cuota_periodica: int,
    capital_cuota: float,
    interes_cuota: float,
    modalidad_pago: str,
    saldo_inicial: int,
) -> list:
    """Genera el cronograma completo de cuotas.

    La última cuota absorbe diferencias de redondeo para que saldo_despues=0.
    """
    intervalo = DIAS_ENTRE_CUOTAS.get(modalidad_pago, 7)
    cronograma = []
    saldo = saldo_inicial

    for i in range(total_cuotas):
        fecha = fecha_primer_cobro + timedelta(days=i * intervalo)
        es_ultima = (i == total_cuotas - 1)

        if es_ultima:
            cap = saldo
            intr = max(0, cuota_periodica - cap)
            monto = cap + intr
        else:
            cap = min(round(capital_cuota), saldo)
            intr = round(interes_cuota)
            monto = cuota_periodica

        saldo_despues = max(0, saldo - cap)
        cronograma.append({
            "loanbook_codigo":  loanbook_id,
            "cliente_nombre":   cliente_nombre,
            "numero_cuota":     i + 1,
            "fecha_programada": fecha.isoformat(),
            "monto_total":      monto,
            "monto_capital":    cap,
            "monto_interes":    intr,
            "monto_fees":       0,
            "estado":           "pendiente",
            "fecha_pago":       None,
            "monto_pagado":     0,
            "metodo_pago":      None,
            "banco":            None,
            "referencia":       None,
            "mora_acumulada":   0,
            "mora_pagada":      0,
            "anzi_pagado":      0,
            "saldo_despues":    saldo_despues,
        })
        saldo = saldo_despues

    return cronograma


# ─────────────────── Calculadora comercial ────────────────────────────────────
# Usada antes de la entrega para calcular cuota dada inicial o viceversa.


def calcular_cuota_dado_inicial(
    capital_plan: int,
    cuota_inicial: int,
    total_cuotas: int,
    cuota_estandar_plan: int,
) -> dict:
    """Calculadora comercial: dado cuota_inicial → cuota periódica resultante.

    La cuota inicial reduce el capital a financiar proporcionalmente.
    El interés se mantiene proporcional al capital neto.

    Ejemplo: Raider P52S, cuota_inicial=1_460_000
        capital_neto = 7_800_000 - 1_460_000 = 6_340_000
        ratio        = 6_340_000 / 7_800_000  = 0.8128
        cuota        = round(179_900 × 0.8128) = 146_222
    """
    if cuota_inicial >= capital_plan:
        return {"error": "Cuota inicial cubre o supera el capital del plan"}
    capital_neto  = capital_plan - cuota_inicial
    ratio         = capital_neto / capital_plan
    nueva_cuota   = round(cuota_estandar_plan * ratio)
    recaudo_total = nueva_cuota * total_cuotas
    interes_total = recaudo_total - capital_neto
    return {
        "capital_neto":    capital_neto,
        "cuota_periodica": nueva_cuota,
        "recaudo_total":   recaudo_total,
        "interes_total":   interes_total,
        "total_cuotas":    total_cuotas,
    }


def calcular_inicial_dado_cuota(
    capital_plan: int,
    cuota_periodica_deseada: int,
    cuota_estandar_plan: int,
) -> dict:
    """Calculadora comercial: dado cuota deseada → cuota inicial requerida.

    Si cuota_deseada >= cuota_estandar: no necesita cuota inicial.
    Si cuota_deseada < cuota_estandar: cuota_inicial = capital × (1 - ratio).
    """
    if cuota_periodica_deseada >= cuota_estandar_plan:
        return {
            "cuota_inicial_requerida": 0,
            "nota": "No necesita cuota inicial con esa cuota",
        }
    ratio         = cuota_periodica_deseada / cuota_estandar_plan
    cuota_inicial = round(capital_plan * (1 - ratio))
    return {
        "cuota_inicial_requerida": cuota_inicial,
        "capital_neto":            capital_plan - cuota_inicial,
        "cuota_periodica":         cuota_periodica_deseada,
    }


# ─────────────────── Abono a capital durante crédito activo ───────────────────
# Interés plano (Opción A — confirmado por Andrés Sanjuan).
# El interés por cuota NO varía aunque se abone capital.


def recalcular_tras_abono(
    saldo_capital_actual: int,
    abono_extra: int,
    cuotas_pendientes: int,
    cuota_periodica: int,
    interes_cuota: float,
    opcion: str = "reducir_plazo",
) -> dict:
    """Recalcula el crédito después de un abono extra a capital.

    Opción A — reducir_plazo (default):
        Misma cuota periódica, menos cuotas pendientes.
        nuevas_cuotas = ceil(nuevo_saldo / capital_cuota_original)

    Opción B — reducir_cuota:
        Mismo número de cuotas, cuota periódica menor.
        nueva_cuota = nueva_capital_cuota + interes_cuota (plano)

    REGLA: Interés plano — interes_cuota no varía con el abono.
    """
    nuevo_saldo = saldo_capital_actual - abono_extra
    if nuevo_saldo < 0:
        return {"error": "Abono supera el saldo de capital pendiente"}
    if nuevo_saldo == 0:
        return {
            "opcion":                   opcion,
            "nuevo_saldo_capital":      0,
            "nuevas_cuotas_pendientes": 0,
            "nota":                     "Crédito saldado con este abono",
        }

    if opcion == "reducir_plazo":
        capital_cuota_original = saldo_capital_actual / cuotas_pendientes if cuotas_pendientes else 0
        nuevas_cuotas = ceil(nuevo_saldo / capital_cuota_original) if capital_cuota_original else 0
        return {
            "opcion":                   "reducir_plazo",
            "nuevo_saldo_capital":      nuevo_saldo,
            "nuevas_cuotas_pendientes": nuevas_cuotas,
            "cuota_periodica":          cuota_periodica,
            "cuotas_reducidas":         cuotas_pendientes - nuevas_cuotas,
        }
    else:
        nueva_cap_cuota = nuevo_saldo / cuotas_pendientes if cuotas_pendientes else 0
        nueva_cuota     = round(nueva_cap_cuota + interes_cuota)
        return {
            "opcion":                "reducir_cuota",
            "nuevo_saldo_capital":   nuevo_saldo,
            "cuotas_pendientes":     cuotas_pendientes,
            "nueva_cuota_periodica": nueva_cuota,
            "cuota_reducida_en":     cuota_periodica - nueva_cuota,
        }
