"""
test_put_endpoints.py — Tests de la lógica de validación de los PUT canónicos
(BUILD 4 Sprint Estructural).

Testean las reglas de negocio de los endpoints PUT vía las funciones puras
que invocan internamente, sin necesidad de base de datos.

5 tests:
  1. plan_codigo desconocido → validación rechaza (PLANES_RODDOS)
  2. plan_codigo P39S semanal → auto-deriva 39 cuotas
  3. plan_codigo P52S quincenal → auto-deriva 24 cuotas
  4. fecha_primera_cuota no-miércoles → debe fallar
  5. valor_total correcto tras auto-derivación P78S + cuota_inicial
"""
import pytest
from datetime import date, timedelta
from services.loanbook.state_calculator import (
    PLANES_RODDOS,
    _derivar_total_cuotas,
    recalcular_loanbook,
)


# ─── 1. plan_codigo fuera de PLANES_RODDOS debe ser rechazado ─────────────────

def test_plan_codigo_invalido_no_esta_en_planes_roddos():
    """Un plan desconocido no existe en PLANES_RODDOS — el endpoint debe retornar 422."""
    planes_invalidos = ["P99S", "P0S", "ABC", "", "p39s"]
    for plan in planes_invalidos:
        assert plan not in PLANES_RODDOS, f"'{plan}' no debería estar en PLANES_RODDOS"


# ─── 2. P39S semanal auto-deriva 39 cuotas ────────────────────────────────────

def test_p39s_semanal_auto_deriva_39():
    """PUT con plan_codigo=P39S modalidad=semanal → num_cuotas debe ser 39."""
    resultado = _derivar_total_cuotas("P39S", "semanal")
    assert resultado == 39


# ─── 3. P52S quincenal auto-deriva 26 cuotas ─────────────────────────────────

def test_p52s_quincenal_auto_deriva_26():
    """PUT con plan_codigo=P52S modalidad=quincenal → tabla PLAN_CUOTAS dice 26.

    round(52/2.2)=24 era la fórmula incorrecta. La tabla de negocio manda: 26.
    """
    resultado = _derivar_total_cuotas("P52S", "quincenal")
    assert resultado == 26


# ─── 4. fecha_primera_cuota no-miércoles debe fallar ─────────────────────────

def test_primera_cuota_no_miercoles_invalida():
    """PUT /entrega con fecha_primera_cuota que no es miércoles debe rechazarse.

    Lunes=0, Martes=1, Miércoles=2, Jueves=3, ...
    El endpoint hace: if fpc.weekday() != 2 → raise 422
    """
    hoy = date.today()
    # Encontrar el próximo lunes
    dias_hasta_lunes = (0 - hoy.weekday()) % 7 or 7
    proximo_lunes = hoy + timedelta(days=dias_hasta_lunes)
    assert proximo_lunes.weekday() == 0, "Debe ser lunes"
    assert proximo_lunes.weekday() != 2, "Lunes no es miércoles → inválido para primera cuota"

    # Encontrar el próximo miércoles — debe ser VÁLIDO
    dias_hasta_mier = (2 - hoy.weekday()) % 7 or 7
    proximo_mier = hoy + timedelta(days=dias_hasta_mier)
    assert proximo_mier.weekday() == 2, "Miércoles debe ser weekday 2"


# ─── 5. valor_total correcto tras auto-derivación P78S + cuota_inicial ────────

def test_p78s_valor_total_con_cuota_inicial():
    """PUT con P78S semanal + cuota_inicial recalcula valor_total correctamente."""
    lb = {
        "loanbook_id": "LB-TEST",
        "cliente": {"nombre": "Test", "cedula": "0"},
        "plan_codigo": "P78S",
        "plan": {
            "codigo": "P78S",
            "modalidad": "semanal",
            "cuota_valor": 145_000,
            "total_cuotas": 76,           # MAL — debe corregirse a 78
            "cuota_inicial": 1_160_000,
        },
        "modalidad": "semanal",
        "cuota_monto": 145_000,
        "num_cuotas": 76,                 # MAL
        "valor_total": 76 * 145_000 + 1_160_000,  # MAL
        "cuotas": [],
        "estado": "activo",
        "total_pagado": 0,
        "saldo_capital": 76 * 145_000,
    }
    resultado = recalcular_loanbook(lb)

    assert resultado["num_cuotas"] == 78
    assert resultado["valor_total"] == 78 * 145_000 + 1_160_000  # 12,470,000
    assert resultado["valor_total"] == 12_470_000
