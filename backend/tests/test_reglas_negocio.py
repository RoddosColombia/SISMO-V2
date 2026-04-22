"""
test_reglas_negocio.py — Tests de la tabla fija PLAN_CUOTAS y sus funciones.

18 tests que verifican:
  - Cada celda de PLAN_CUOTAS contra el valor acordado con operaciones
  - get_valor_cuota() con los 3 multiplicadores
  - get_valor_total() end-to-end con cuota_inicial
  - validar_fecha_pago() rechaza futuro y acepta hoy/pasado
  - Combinaciones no configuradas retornan None
  - plan_codigo desconocido retorna None

PRINCIPIO: P39S quincenal = 20, NO round(39/2.2) = 18. La tabla manda.
"""

import pytest
from datetime import date, timedelta
from services.loanbook.reglas_negocio import (
    PLAN_CUOTAS,
    get_num_cuotas,
    get_valor_cuota,
    get_valor_total,
    validar_fecha_pago,
)


# ═══════════════════════════════════════════
# BLOQUE 1 — Tabla PLAN_CUOTAS celda a celda
# ═══════════════════════════════════════════

def test_P15S_semanal_son_15():
    assert get_num_cuotas("P15S", "semanal") == 15


def test_P15S_quincenal_no_configurado():
    """P15S quincenal no existe en la tabla → None."""
    assert get_num_cuotas("P15S", "quincenal") is None


def test_P15S_mensual_no_configurado():
    assert get_num_cuotas("P15S", "mensual") is None


def test_P39S_semanal_son_39():
    assert get_num_cuotas("P39S", "semanal") == 39


def test_P39S_quincenal_son_20():
    """CRÍTICO: 20, no round(39/2.2)=18. La tabla manda."""
    resultado = get_num_cuotas("P39S", "quincenal")
    assert resultado == 20, f"P39S quincenal debe ser 20, no {resultado}"


def test_P39S_mensual_son_9():
    assert get_num_cuotas("P39S", "mensual") == 9


def test_P52S_semanal_son_52():
    assert get_num_cuotas("P52S", "semanal") == 52


def test_P52S_quincenal_son_26():
    """CRÍTICO: 26, no round(52/2.2)=24. La tabla manda."""
    resultado = get_num_cuotas("P52S", "quincenal")
    assert resultado == 26, f"P52S quincenal debe ser 26, no {resultado}"


def test_P52S_mensual_son_12():
    assert get_num_cuotas("P52S", "mensual") == 12


def test_P78S_semanal_son_78():
    assert get_num_cuotas("P78S", "semanal") == 78


def test_P78S_quincenal_son_39():
    assert get_num_cuotas("P78S", "quincenal") == 39


def test_P78S_mensual_son_18():
    assert get_num_cuotas("P78S", "mensual") == 18


def test_plan_codigo_desconocido_retorna_none():
    """Un plan que no existe en la tabla retorna None."""
    for plan in ("P99S", "P0S", "ABC", "", "p39s", "P39"):
        assert get_num_cuotas(plan, "semanal") is None, f"'{plan}' debería ser None"


# ═══════════════════════════════════════════
# BLOQUE 2 — get_valor_total() end-to-end
# ═══════════════════════════════════════════

def test_valor_total_kreyser_P39S_quincenal():
    """Caso real: P39S quincenal, cuota 420k, enganche 1.46M.

    valor_total = 20 × 420,000 + 1,460,000 = 9,860,000
    (NO 18 × 420,000 + 1,460,000 = 9,020,000 — ese era el bug)
    """
    resultado = get_valor_total("P39S", "quincenal", 420_000, cuota_inicial=1_460_000)
    assert resultado == 20 * 420_000 + 1_460_000  # 9,860,000
    assert resultado == 9_860_000


def test_valor_total_P78S_semanal_sin_inicial():
    """P78S semanal 145k sin enganche = 78 × 145,000 = 11,310,000."""
    resultado = get_valor_total("P78S", "semanal", 145_000)
    assert resultado == 78 * 145_000  # 11,310,000


def test_valor_total_combinacion_no_configurada_retorna_none():
    """P15S quincenal no tiene cuotas → get_valor_total debe retornar None."""
    resultado = get_valor_total("P15S", "quincenal", 70_000)
    assert resultado is None


# ═══════════════════════════════════════════
# BLOQUE 3 — validar_fecha_pago()
# ═══════════════════════════════════════════

def test_validar_fecha_pago_futura_lanza_error():
    """Registrar un pago con fecha de mañana es físicamente imposible."""
    manana = date.today() + timedelta(days=1)
    with pytest.raises(ValueError, match="futuro"):
        validar_fecha_pago(manana)


def test_validar_fecha_pago_hoy_pasa():
    """Un pago registrado hoy es válido."""
    hoy = date.today()
    validar_fecha_pago(hoy)  # no debe lanzar


def test_validar_fecha_pago_ayer_pasa():
    """Un pago de ayer también es válido."""
    ayer = date.today() - timedelta(days=1)
    validar_fecha_pago(ayer)  # no debe lanzar


def test_validar_fecha_pago_inyeccion_hoy():
    """hoy= inyectable para tests: fecha_pago == hoy_inyectado debe pasar."""
    hoy_fijo = date(2026, 4, 21)
    validar_fecha_pago(hoy_fijo, hoy=hoy_fijo)  # igual → válido

    fecha_futura = date(2026, 4, 22)
    with pytest.raises(ValueError):
        validar_fecha_pago(fecha_futura, hoy=hoy_fijo)
