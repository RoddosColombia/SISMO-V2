"""
test_reparador.py — Tests de reparar_loanbook().

3 casos del sprint:
  1. Samir  — num_cuotas=28 corregido a 39, pagos vacíos preservados
  2. Jose   — cuotas 7 y 8 futuras revertidas a pendiente, cuota 6 pasada preservada
  3. Ronaldo — cuotas con referencia bancaria NO se tocan aunque sean futuras
"""
import pytest
from datetime import date, timedelta
from services.loanbook.reparador import reparar_loanbook


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _lb_samir():
    """LB-2026-0028 — P39S semanal, num_cuotas=28 (corrupto)."""
    return {
        "loanbook_id": "LB-2026-0028",
        "cliente": {"nombre": "Samir García", "cedula": "12345678"},
        "plan_codigo": "P39S",
        "plan": {
            "codigo": "P39S",
            "modalidad": "semanal",
            "cuota_valor": 204_000,
            "total_cuotas": 28,
            "cuota_inicial": 0,
        },
        "modalidad": "semanal",
        "cuota_monto": 204_000,
        "num_cuotas": 28,
        "valor_total": 28 * 204_000,
        "cuotas": [],
        "estado": "activo",
        "total_pagado": 0,
        "saldo_capital": 28 * 204_000,
    }


def _lb_jose():
    """LB-2026-0024 — cuotas 7 y 8 futuras sin evidencia (seed corrupto)."""
    hoy = date.today()
    return {
        "loanbook_id": "LB-2026-0024",
        "cliente": {"nombre": "Jose Altamiranda", "cedula": "11111111"},
        "plan_codigo": "P15S",
        "plan": {
            "codigo": "P15S",
            "modalidad": "semanal",
            "cuota_valor": 70_000,
            "total_cuotas": 15,
            "cuota_inicial": 0,
        },
        "modalidad": "semanal",
        "cuota_monto": 70_000,
        "num_cuotas": 15,
        "valor_total": 15 * 70_000,
        "estado": "activo",
        "total_pagado": 0,
        "saldo_capital": 15 * 70_000,
        "cuotas": [
            {
                "numero": 6,
                "fecha": (hoy - timedelta(days=7)).isoformat(),  # PASADA
                "estado": "pagada",
                "fecha_pago": (hoy - timedelta(days=5)).isoformat(),
                "referencia": None,
                "metodo_pago": None,
                "monto": 70_000,
            },
            {
                "numero": 7,
                "fecha": (hoy + timedelta(days=7)).isoformat(),  # FUTURA
                "estado": "pagada",    # ← seed corrupto
                "fecha_pago": None,
                "referencia": None,
                "metodo_pago": None,
                "monto": 70_000,
            },
            {
                "numero": 8,
                "fecha": (hoy + timedelta(days=14)).isoformat(),  # FUTURA
                "estado": "pagada",    # ← seed corrupto
                "fecha_pago": None,
                "referencia": None,
                "metodo_pago": None,
                "monto": 70_000,
            },
        ],
    }


def _lb_ronaldo():
    """Crédito con cuota futura pagada con referencia bancaria real (pago adelantado legítimo)."""
    hoy = date.today()
    return {
        "loanbook_id": "LB-RONALDO",
        "cliente": {"nombre": "Ronaldo Ejemplo", "cedula": "99999999"},
        "plan_codigo": "P39S",
        "plan": {
            "codigo": "P39S",
            "modalidad": "semanal",
            "cuota_valor": 204_000,
            "total_cuotas": 39,
            "cuota_inicial": 0,
        },
        "modalidad": "semanal",
        "cuota_monto": 204_000,
        "num_cuotas": 39,
        "valor_total": 39 * 204_000,
        "estado": "activo",
        "total_pagado": 204_000,
        "saldo_capital": 38 * 204_000,
        "cuotas": [
            {
                "numero": 5,
                "fecha": (hoy + timedelta(days=30)).isoformat(),  # FUTURA
                "estado": "pagada",
                "fecha_pago": hoy.isoformat(),
                "referencia": "TRF-001234",   # ← evidencia real
                "metodo_pago": "transferencia",
                "monto": 204_000,
            }
        ],
    }


# ─── Tests BUILD 3 ────────────────────────────────────────────────────────────

def test_samir_num_cuotas_corregido_a_39():
    """Samir: num_cuotas=28 → reparar detecta y corrige a 39."""
    resultado = reparar_loanbook(_lb_samir(), dry_run=True)
    assert resultado["tiene_problemas"] is True
    tipos = [r["tipo"] for r in resultado["reparaciones"]]
    assert "num_cuotas_corregido" in tipos
    correccion = next(r for r in resultado["reparaciones"] if r["tipo"] == "num_cuotas_corregido")
    assert correccion["valor_anterior"] == 28
    assert correccion["valor_nuevo"] == 39


def test_samir_apply_produce_documento_con_39_cuotas():
    """Samir con dry_run=False devuelve documento_reparado con num_cuotas=39."""
    resultado = reparar_loanbook(_lb_samir(), dry_run=False)
    assert resultado["documento_reparado"] is not None
    assert resultado["documento_reparado"]["num_cuotas"] == 39
    assert resultado["documento_reparado"]["valor_total"] == 39 * 204_000


def test_jose_cuotas_futuras_revertidas_a_pendiente():
    """Jose: cuotas 7 y 8 futuras sin evidencia → revertidas a pendiente."""
    resultado = reparar_loanbook(_lb_jose(), dry_run=True)
    assert resultado["tiene_problemas"] is True
    cuotas_revertidas = [
        r for r in resultado["reparaciones"]
        if r["tipo"] == "cuota_seed_revertida"
    ]
    numeros = [r["cuota_numero"] for r in cuotas_revertidas]
    assert 7 in numeros
    assert 8 in numeros
    # Cuota 6 es pasada — no debe aparecer
    assert 6 not in numeros


def test_jose_cuota_6_pasada_no_se_toca():
    """Jose cuota 6 es pasada (aunque sin evidencia) — no debe revertirse."""
    resultado = reparar_loanbook(_lb_jose(), dry_run=False)
    doc = resultado["documento_reparado"]
    cuota6 = next((c for c in doc["cuotas"] if c["numero"] == 6), None)
    assert cuota6 is not None
    assert cuota6["estado"] == "pagada"  # preservada


def test_jose_apply_cuotas_revertidas_son_pendiente():
    """Con dry_run=False, cuotas 7 y 8 en el documento tienen estado=pendiente."""
    resultado = reparar_loanbook(_lb_jose(), dry_run=False)
    doc = resultado["documento_reparado"]
    cuota7 = next((c for c in doc["cuotas"] if c["numero"] == 7), None)
    cuota8 = next((c for c in doc["cuotas"] if c["numero"] == 8), None)
    assert cuota7["estado"] == "pendiente"
    assert cuota8["estado"] == "pendiente"
    assert cuota7["fecha_pago"] is None
    assert cuota8["fecha_pago"] is None


def test_ronaldo_pago_adelantado_con_referencia_preservado():
    """Ronaldo: cuota futura con referencia bancaria real NO se revierte."""
    resultado = reparar_loanbook(_lb_ronaldo(), dry_run=True)
    cuotas_revertidas = [
        r for r in resultado["reparaciones"]
        if r["tipo"] == "cuota_seed_revertida"
    ]
    assert len(cuotas_revertidas) == 0, "Pago legítimo con referencia no debe revertirse"


def test_dry_run_no_muta_original():
    """dry_run=True nunca modifica el documento original."""
    lb = _lb_jose()
    cuota7_original = next(c for c in lb["cuotas"] if c["numero"] == 7)
    estado_original = cuota7_original["estado"]

    reparar_loanbook(lb, dry_run=True)

    assert cuota7_original["estado"] == estado_original, "dry_run mutó el original"
