"""
test_state_calculator.py — Tests de recalcular_loanbook().

TDD estricto: validan valores concretos, no solo que no explote.
14 tests cubre: derivación de plan, modalidad, financials, DPD, estado, terminales.
"""
import pytest
from datetime import date, timedelta
from services.loanbook.state_calculator import recalcular_loanbook, patch_set_from_recalculo


# ─── Helpers de fixtures ──────────────────────────────────────────────────────

def _make_lb(
    plan_codigo="P39S",
    modalidad="semanal",
    cuota_monto=204_000,
    num_cuotas=28,          # deliberadamente incorrecto para probar corrección
    cuotas=None,
    estado="activo",
    cuota_inicial=0,
):
    return {
        "loanbook_id": "LB-TEST",
        "cliente": {"nombre": "Test", "cedula": "0"},
        "plan_codigo": plan_codigo,
        "plan": {
            "codigo": plan_codigo,
            "modalidad": modalidad,
            "cuota_valor": cuota_monto,
            "total_cuotas": num_cuotas,
            "cuota_inicial": cuota_inicial,
        },
        "modalidad": modalidad,
        "cuota_monto": cuota_monto,
        "num_cuotas": num_cuotas,
        "valor_total": num_cuotas * cuota_monto + cuota_inicial,  # might be wrong
        "cuotas": cuotas or [],
        "estado": estado,
        "total_pagado": 0,
        "saldo_capital": num_cuotas * cuota_monto,
    }


def _cuota_pagada(numero, monto, dias_atras=5):
    hoy = date.today()
    return {
        "numero": numero,
        "fecha": (hoy - timedelta(days=dias_atras * 7)).isoformat(),
        "estado": "pagada",
        "monto": monto,
        "fecha_pago": (hoy - timedelta(days=dias_atras * 7 - 1)).isoformat(),
    }


def _cuota_pendiente(numero, monto, dias_futuros=7):
    hoy = date.today()
    return {
        "numero": numero,
        "fecha": (hoy + timedelta(days=dias_futuros)).isoformat(),
        "estado": "pendiente",
        "monto": monto,
        "fecha_pago": None,
    }


def _cuota_vencida(numero, monto, dias_atras=10):
    hoy = date.today()
    return {
        "numero": numero,
        "fecha": (hoy - timedelta(days=dias_atras)).isoformat(),
        "estado": "pendiente",
        "monto": monto,
        "fecha_pago": None,
    }


# ─── Tests de derivación de plan (núm. cuotas) ────────────────────────────────

def test_p39s_semanal_corrige_a_39():
    """P39S semanal siempre = 39 cuotas, sin importar qué tenga num_cuotas."""
    lb = _make_lb(plan_codigo="P39S", modalidad="semanal", num_cuotas=28)
    resultado = recalcular_loanbook(lb)
    assert resultado["num_cuotas"] == 39


def test_p78s_semanal_corrige_a_78():
    """P78S semanal siempre = 78 cuotas."""
    lb = _make_lb(plan_codigo="P78S", modalidad="semanal", cuota_monto=145_000, num_cuotas=76)
    resultado = recalcular_loanbook(lb)
    assert resultado["num_cuotas"] == 78


def test_p52s_semanal_corrige_a_52():
    """P52S semanal = 52 cuotas."""
    lb = _make_lb(plan_codigo="P52S", modalidad="semanal", cuota_monto=180_000, num_cuotas=50)
    resultado = recalcular_loanbook(lb)
    assert resultado["num_cuotas"] == 52


def test_p15s_semanal_corrige_a_15():
    """P15S semanal = 15 cuotas (comparendo)."""
    lb = _make_lb(plan_codigo="P15S", modalidad="semanal", cuota_monto=70_000, num_cuotas=10)
    resultado = recalcular_loanbook(lb)
    assert resultado["num_cuotas"] == 15


def test_p52s_quincenal_tabla_fija_26():
    """P52S quincenal → tabla PLAN_CUOTAS dice 26 (no round(52/2.2)=24)."""
    lb = _make_lb(plan_codigo="P52S", modalidad="quincenal", cuota_monto=180_000 * 2, num_cuotas=99)
    resultado = recalcular_loanbook(lb)
    assert resultado["num_cuotas"] == 26


def test_p39s_mensual_tabla_fija_9():
    """P39S mensual → tabla PLAN_CUOTAS dice 9 (coincide con round(39/4.4)=9)."""
    lb = _make_lb(plan_codigo="P39S", modalidad="mensual", cuota_monto=204_000 * 4, num_cuotas=99)
    resultado = recalcular_loanbook(lb)
    assert resultado["num_cuotas"] == 9


# ─── Tests de valor_total ─────────────────────────────────────────────────────

def test_valor_total_formula_sin_inicial():
    """valor_total = num_cuotas × cuota_monto (sin cuota_inicial)."""
    lb = _make_lb(plan_codigo="P39S", modalidad="semanal", cuota_monto=204_000, num_cuotas=28)
    resultado = recalcular_loanbook(lb)
    assert resultado["valor_total"] == 39 * 204_000


def test_valor_total_formula_con_inicial():
    """valor_total = num_cuotas × cuota_monto + cuota_inicial."""
    lb = _make_lb(
        plan_codigo="P78S", modalidad="semanal",
        cuota_monto=145_000, num_cuotas=76,
        cuota_inicial=1_160_000,
    )
    resultado = recalcular_loanbook(lb)
    assert resultado["valor_total"] == 78 * 145_000 + 1_160_000


# ─── Tests de financials desde cuotas ────────────────────────────────────────

def test_total_pagado_suma_cuotas_pagadas():
    """total_pagado = suma de cuotas con estado='pagada'."""
    cuotas = [
        _cuota_pagada(1, 204_000),
        _cuota_pagada(2, 204_000),
        _cuota_pendiente(3, 204_000),
    ]
    lb = _make_lb(plan_codigo="P39S", cuota_monto=204_000, cuotas=cuotas)
    resultado = recalcular_loanbook(lb)
    assert resultado["total_pagado"] == 2 * 204_000


def test_saldo_capital_suma_cuotas_no_pagadas():
    """saldo_capital = suma de cuotas pendientes."""
    cuotas = [
        _cuota_pagada(1, 204_000),
        _cuota_pagada(2, 204_000),
        _cuota_pendiente(3, 204_000),
        _cuota_pendiente(4, 204_000),
    ]
    lb = _make_lb(plan_codigo="P39S", cuota_monto=204_000, cuotas=cuotas)
    resultado = recalcular_loanbook(lb)
    assert resultado["saldo_capital"] == 2 * 204_000


# ─── Tests de DPD y estado ────────────────────────────────────────────────────

def test_dpd_cero_da_estado_al_dia():
    """Sin cuotas vencidas → DPD=0 → estado='al_dia'."""
    cuotas = [_cuota_pendiente(1, 204_000, dias_futuros=7)]
    lb = _make_lb(plan_codigo="P39S", cuota_monto=204_000, cuotas=cuotas, estado="en_riesgo")
    resultado = recalcular_loanbook(lb)
    assert resultado["dpd"] == 0
    assert resultado["estado"] == "al_dia"


def test_dpd_5_dias_da_estado_en_riesgo():
    """5 días vencida → estado='en_riesgo'."""
    cuotas = [_cuota_vencida(1, 204_000, dias_atras=5)]
    lb = _make_lb(plan_codigo="P39S", cuota_monto=204_000, cuotas=cuotas)
    resultado = recalcular_loanbook(lb)
    assert resultado["dpd"] == 5
    assert resultado["estado"] == "en_riesgo"


def test_dpd_20_dias_da_estado_mora():
    """20 días vencida → estado='mora'."""
    cuotas = [_cuota_vencida(1, 204_000, dias_atras=20)]
    lb = _make_lb(plan_codigo="P39S", cuota_monto=204_000, cuotas=cuotas)
    resultado = recalcular_loanbook(lb)
    assert resultado["dpd"] == 20
    assert resultado["estado"] == "mora"


def test_estado_terminal_saldado_no_se_sobreescribe():
    """Un crédito saldado no debe cambiar de estado aunque tenga cuotas raras."""
    cuotas = [_cuota_vencida(1, 204_000, dias_atras=30)]
    lb = _make_lb(plan_codigo="P39S", cuota_monto=204_000, cuotas=cuotas, estado="saldado")
    resultado = recalcular_loanbook(lb)
    assert resultado["estado"] == "saldado"


def test_estado_pendiente_entrega_no_se_sobreescribe():
    """Un crédito pendiente de entrega no cambia de estado."""
    lb = _make_lb(plan_codigo="P39S", estado="pendiente_entrega")
    resultado = recalcular_loanbook(lb)
    assert resultado["estado"] == "pendiente_entrega"


# ─── Test del helper patch_set ────────────────────────────────────────────────

def test_patch_set_contiene_campos_clave():
    """patch_set_from_recalculo devuelve los campos listos para MongoDB $set."""
    lb = _make_lb(plan_codigo="P39S", modalidad="semanal", cuota_monto=204_000, num_cuotas=28)
    patch = patch_set_from_recalculo(lb)
    assert "num_cuotas" in patch
    assert "valor_total" in patch
    assert "saldo_capital" in patch
    assert patch["num_cuotas"] == 39
    assert patch["valor_total"] == 39 * 204_000
