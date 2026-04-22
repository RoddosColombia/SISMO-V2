"""
test_estados_service.py — Tests de la máquina de estados del módulo Loanbook.

Valida:
  - clasificar_estado: 9 estados, rangos DPD v1.1 Opción A, precedencia saldo
  - clasificar_sub_bucket: 7 sub-buckets, bordes de rango exactos
  - calcular_mora_acumulada: R-22 sin cap, $2K/día
  - validar_transicion: matriz cap 3.3, HTTPException 422 para inválidas

Tests puros — sin MongoDB, sin I/O.
Fixture seed_catalogos de conftest.py está activo (autouse).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.loanbook.estados_service import (
    ESTADOS_ACTIVOS,
    ESTADOS_VALIDOS,
    MORA_COP_POR_DIA,
    TRANSICIONES_PERMITIDAS,
    calcular_mora_acumulada,
    clasificar_estado,
    clasificar_sub_bucket,
    validar_transicion,
)


# ─────────────────────── BLOQUE 1 — clasificar_estado ────────────────────────

class TestClasificarEstado:
    """Rangos DPD v1.1 Opción A + reglas de precedencia."""

    # Regla 1: saldo cero → Pagado (gana sobre cualquier DPD)
    def test_saldo_cero_dpd_cero_es_pagado(self):
        assert clasificar_estado(0, 0.0, "P52S") == "Pagado"

    def test_saldo_cero_dpd_alto_es_pagado(self):
        """Saldo 0 gana incluso con DPD de 100 días."""
        assert clasificar_estado(100, 0.0, "P52S") == "Pagado"

    def test_saldo_cero_dpd_none_es_pagado(self):
        assert clasificar_estado(None, 0.0, "P39S") == "Pagado"

    def test_saldo_negativo_es_pagado(self):
        """Saldo negativo también cuenta como pagado."""
        assert clasificar_estado(5, -100.0, "P52S") == "Pagado"

    # Regla 2: dpd None → Aprobado
    def test_dpd_none_con_saldo_es_aprobado(self):
        assert clasificar_estado(None, 1_000_000, "P52S") == "Aprobado"

    def test_dpd_none_cualquier_plan_es_aprobado(self):
        assert clasificar_estado(None, 500_000, "P1S") == "Aprobado"

    # Regla 3: rangos v1.1 Opción A
    def test_dpd_0_es_current(self):
        assert clasificar_estado(0, 1_000_000, "P52S") == "Current"

    def test_dpd_1_es_early(self):
        assert clasificar_estado(1, 1_000_000, "P52S") == "Early Delinquency"

    def test_dpd_7_es_early(self):
        """Borde superior de Early Delinquency."""
        assert clasificar_estado(7, 1_000_000, "P52S") == "Early Delinquency"

    def test_dpd_8_es_mid(self):
        """Borde inferior de Mid Delinquency."""
        assert clasificar_estado(8, 1_000_000, "P52S") == "Mid Delinquency"

    def test_dpd_14_es_mid(self):
        """Borde superior de Mid Delinquency."""
        assert clasificar_estado(14, 1_000_000, "P52S") == "Mid Delinquency"

    def test_dpd_15_es_late(self):
        """Borde inferior de Late Delinquency (E-03)."""
        assert clasificar_estado(15, 1_000_000, "P52S") == "Late Delinquency"

    def test_dpd_30_es_late(self):
        assert clasificar_estado(30, 1_000_000, "P52S") == "Late Delinquency"

    def test_dpd_40_es_late(self):
        """E-03 explícito: dpd=40 → Late Delinquency."""
        assert clasificar_estado(40, 1_000_000, "P52S") == "Late Delinquency"

    def test_dpd_45_es_late(self):
        """Borde superior de Late Delinquency."""
        assert clasificar_estado(45, 1_000_000, "P52S") == "Late Delinquency"

    def test_dpd_46_es_default(self):
        """Borde inferior de Default."""
        assert clasificar_estado(46, 1_000_000, "P52S") == "Default"

    def test_dpd_47_es_default(self):
        """E-04 explícito: dpd=47 → Default."""
        assert clasificar_estado(47, 1_000_000, "P52S") == "Default"

    def test_dpd_49_es_default(self):
        """Borde superior de Default."""
        assert clasificar_estado(49, 1_000_000, "P52S") == "Default"

    def test_dpd_50_es_chargeoff(self):
        """Borde inferior de Charge-Off (E-05)."""
        assert clasificar_estado(50, 1_000_000, "P52S") == "Charge-Off"

    def test_dpd_60_es_chargeoff(self):
        """E-05 explícito: dpd=60 → Charge-Off."""
        assert clasificar_estado(60, 1_000_000, "P52S") == "Charge-Off"

    def test_dpd_100_es_chargeoff(self):
        assert clasificar_estado(100, 1_000_000, "P52S") == "Charge-Off"

    def test_dpd_365_es_chargeoff(self):
        """DPD extremo → sigue siendo Charge-Off."""
        assert clasificar_estado(365, 1_000_000, "P52S") == "Charge-Off"

    def test_plan_no_afecta_clasificacion_dpd(self):
        """El plan no cambia la clasificación — es reservado para lógica futura."""
        for plan in ("P1S", "P15S", "P39S", "P78S"):
            assert clasificar_estado(10, 500_000, plan) == "Mid Delinquency"


# ─────────────────────── BLOQUE 2 — clasificar_sub_bucket ────────────────────

class TestClasificarSubBucket:
    """7 sub-buckets con bordes exactos (cap 3.2)."""

    def test_dpd_none_retorna_none(self):
        assert clasificar_sub_bucket(None) is None

    def test_dpd_0_retorna_none(self):
        """Sin mora — sin sub-bucket."""
        assert clasificar_sub_bucket(0) is None

    # Grace: 1–7
    def test_dpd_1_es_grace(self):
        assert clasificar_sub_bucket(1) == "Grace"

    def test_dpd_7_es_grace(self):
        assert clasificar_sub_bucket(7) == "Grace"

    # Warning: 8–14
    def test_dpd_8_es_warning(self):
        assert clasificar_sub_bucket(8) == "Warning"

    def test_dpd_14_es_warning(self):
        assert clasificar_sub_bucket(14) == "Warning"

    # Alert: 15–21
    def test_dpd_15_es_alert(self):
        assert clasificar_sub_bucket(15) == "Alert"

    def test_dpd_21_es_alert(self):
        assert clasificar_sub_bucket(21) == "Alert"

    # Critical: 22–30
    def test_dpd_22_es_critical(self):
        assert clasificar_sub_bucket(22) == "Critical"

    def test_dpd_30_es_critical(self):
        assert clasificar_sub_bucket(30) == "Critical"

    # Severe: 31–45
    def test_dpd_31_es_severe(self):
        assert clasificar_sub_bucket(31) == "Severe"

    def test_dpd_45_es_severe(self):
        assert clasificar_sub_bucket(45) == "Severe"

    # Pre-default: 46–49
    def test_dpd_46_es_predefault(self):
        assert clasificar_sub_bucket(46) == "Pre-default"

    def test_dpd_49_es_predefault(self):
        assert clasificar_sub_bucket(49) == "Pre-default"

    # Default: 50+
    def test_dpd_50_es_default(self):
        assert clasificar_sub_bucket(50) == "Default"

    def test_dpd_200_es_default(self):
        assert clasificar_sub_bucket(200) == "Default"

    def test_todos_los_bordes_consecutivos(self):
        """Verifica que no hay gap entre rangos — cada DPD tiene sub-bucket."""
        for dpd in range(1, 101):
            resultado = clasificar_sub_bucket(dpd)
            assert resultado is not None, f"DPD={dpd} no tiene sub-bucket"


# ─────────────────────── BLOQUE 3 — calcular_mora_acumulada (R-22) ───────────

class TestMoraAcumulada:
    """R-22: mora $2.000 COP/día, sin cap."""

    def test_dpd_none_retorna_cero(self):
        assert calcular_mora_acumulada(None) == 0

    def test_dpd_0_retorna_cero(self):
        assert calcular_mora_acumulada(0) == 0

    def test_dpd_negativo_retorna_cero(self):
        assert calcular_mora_acumulada(-5) == 0

    def test_dpd_1_es_2000(self):
        assert calcular_mora_acumulada(1) == 2_000

    def test_dpd_10_es_20000(self):
        """E-08: mora $2K × 10 días = $20.000."""
        assert calcular_mora_acumulada(10) == 20_000

    def test_dpd_50_es_100000(self):
        assert calcular_mora_acumulada(50) == 100_000

    def test_mora_sin_cap_R22(self):
        """R-22: NO hay cap — puede crecer indefinidamente."""
        assert calcular_mora_acumulada(365) == 730_000
        assert calcular_mora_acumulada(1000) == 2_000_000

    def test_mora_cop_por_dia_es_2000(self):
        """Constante MORA_COP_POR_DIA no debe cambiar sin autorización."""
        assert MORA_COP_POR_DIA == 2_000

    def test_mora_lineal(self):
        """La mora crece linealmente con el DPD."""
        for dpd in range(1, 60):
            assert calcular_mora_acumulada(dpd) == dpd * 2_000


# ─────────────────────── BLOQUE 4 — validar_transicion ───────────────────────

class TestTransiciones:
    """Matriz de transiciones cap 3.3 del maestro."""

    # Transiciones válidas
    def test_nuevo_a_aprobado_ok(self):
        validar_transicion(None, "Aprobado")  # no debe lanzar

    def test_aprobado_a_current_ok(self):
        validar_transicion("Aprobado", "Current")

    def test_aprobado_a_pagado_ok(self):
        """P1S contado: Aprobado → Pagado directo."""
        validar_transicion("Aprobado", "Pagado")

    def test_current_a_early_ok(self):
        validar_transicion("Current", "Early Delinquency")

    def test_current_a_pagado_ok(self):
        validar_transicion("Current", "Pagado")

    def test_early_a_current_ok(self):
        """Cure: paga cuota vencida → vuelve a Current."""
        validar_transicion("Early Delinquency", "Current")

    def test_early_a_mid_ok(self):
        validar_transicion("Early Delinquency", "Mid Delinquency")

    def test_mid_a_late_ok(self):
        validar_transicion("Mid Delinquency", "Late Delinquency")

    def test_mid_a_current_ok(self):
        """Cure desde Mid."""
        validar_transicion("Mid Delinquency", "Current")

    def test_late_a_default_ok(self):
        validar_transicion("Late Delinquency", "Default")

    def test_late_a_current_ok(self):
        """Cure masivo desde Late."""
        validar_transicion("Late Delinquency", "Current")

    def test_late_a_modificado_ok(self):
        """Acuerdo de pago desde Late Delinquency."""
        validar_transicion("Late Delinquency", "Modificado")

    def test_default_a_chargeoff_ok(self):
        validar_transicion("Default", "Charge-Off")

    def test_default_a_modificado_ok(self):
        validar_transicion("Default", "Modificado")

    def test_default_a_pagado_ok(self):
        validar_transicion("Default", "Pagado")

    def test_chargeoff_a_pagado_ok(self):
        """Recuperación post-castigo."""
        validar_transicion("Charge-Off", "Pagado")

    def test_modificado_a_current_ok(self):
        validar_transicion("Modificado", "Current")

    def test_modificado_a_late_ok(self):
        """Cliente incumple acuerdo → vuelve a Late."""
        validar_transicion("Modificado", "Late Delinquency")

    # Transiciones inválidas — deben lanzar HTTPException 422
    def test_current_a_chargeoff_invalida(self):
        """E-09: Current → Charge-Off es inválido."""
        with pytest.raises(HTTPException) as exc_info:
            validar_transicion("Current", "Charge-Off")
        assert exc_info.value.status_code == 422

    def test_chargeoff_a_current_invalida(self):
        with pytest.raises(HTTPException) as exc_info:
            validar_transicion("Charge-Off", "Current")
        assert exc_info.value.status_code == 422

    def test_pagado_es_terminal(self):
        """Pagado es estado terminal — ninguna transición saliente."""
        for estado_nuevo in ["Current", "Aprobado", "Early Delinquency", "Default"]:
            with pytest.raises(HTTPException):
                validar_transicion("Pagado", estado_nuevo)

    def test_aprobado_a_chargeoff_invalida(self):
        with pytest.raises(HTTPException) as exc_info:
            validar_transicion("Aprobado", "Charge-Off")
        assert exc_info.value.status_code == 422

    def test_early_a_chargeoff_invalida(self):
        with pytest.raises(HTTPException):
            validar_transicion("Early Delinquency", "Charge-Off")

    def test_none_a_current_invalida(self):
        """Nuevo loanbook solo puede ir a Aprobado."""
        with pytest.raises(HTTPException):
            validar_transicion(None, "Current")

    def test_mensaje_error_descriptivo(self):
        """El mensaje debe mencionar el estado actual y el propuesto."""
        with pytest.raises(HTTPException) as exc_info:
            validar_transicion("Current", "Charge-Off")
        detail = exc_info.value.detail
        assert "Current" in detail
        assert "Charge-Off" in detail


# ─────────────────────── BLOQUE 5 — Constantes y enums ───────────────────────

class TestConstantesYEnums:
    """Verifica que los enums tienen los valores correctos."""

    def test_estados_validos_tiene_9(self):
        assert len(ESTADOS_VALIDOS) == 9

    def test_estados_activos_incluye_expected(self):
        for estado in ["Current", "Early Delinquency", "Late Delinquency", "Default"]:
            assert estado in ESTADOS_ACTIVOS

    def test_pagado_no_es_activo(self):
        assert "Pagado" not in ESTADOS_ACTIVOS

    def test_chargeoff_no_es_activo(self):
        assert "Charge-Off" not in ESTADOS_ACTIVOS

    def test_transiciones_tiene_todos_los_estados(self):
        """La matriz debe tener entrada para todos los 9 estados + None."""
        estados_en_matriz = set(k for k in TRANSICIONES_PERMITIDAS.keys() if k is not None)
        assert estados_en_matriz == ESTADOS_VALIDOS

    def test_transiciones_pagado_es_vacio(self):
        """Pagado es estado terminal — conjunto vacío."""
        assert TRANSICIONES_PERMITIDAS["Pagado"] == set()

    def test_transiciones_chargeoff_solo_pagado(self):
        """Charge-Off solo puede ir a Pagado (recuperación)."""
        assert TRANSICIONES_PERMITIDAS["Charge-Off"] == {"Pagado"}
