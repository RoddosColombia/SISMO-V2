"""
Loanbook Model V2 tests — pure domain logic, no MongoDB.

Tests cover:
1. State transitions (valid + invalid)
2. Mora calculation ($2,000/day from day AFTER due date)
3. Waterfall payment allocation (ANZI → mora → vencidas → corriente → capital)
4. Cuota calculation with modalidad independent of plan
5. Loanbook creation with modalidad + plan separated
6. Contado rejection
7. Quincenal/mensual fecha_primer_pago validation
8. DPD + estado derivation
"""
import pytest
from datetime import date


# ═══════════════════════════════════════════
# State transitions
# ═══════════════════════════════════════════


class TestStateTransitions:
    """Test valid and invalid state transitions."""

    def test_valid_transition_pendiente_to_activo(self):
        from core.loanbook_model import is_valid_transition
        assert is_valid_transition("pendiente_entrega", "activo") is True

    def test_valid_transition_activo_to_al_dia(self):
        from core.loanbook_model import is_valid_transition
        assert is_valid_transition("activo", "al_dia") is True

    def test_valid_transition_al_dia_to_en_riesgo(self):
        from core.loanbook_model import is_valid_transition
        assert is_valid_transition("al_dia", "en_riesgo") is True

    def test_valid_transition_en_riesgo_to_mora(self):
        from core.loanbook_model import is_valid_transition
        assert is_valid_transition("en_riesgo", "mora") is True

    def test_valid_transition_mora_to_mora_grave(self):
        from core.loanbook_model import is_valid_transition
        assert is_valid_transition("mora", "mora_grave") is True

    def test_valid_transition_any_to_saldado(self):
        from core.loanbook_model import is_valid_transition
        for state in ["activo", "al_dia", "en_riesgo", "mora", "mora_grave", "reestructurado"]:
            assert is_valid_transition(state, "saldado") is True, f"{state} → saldado should be valid"

    def test_valid_transition_mora_grave_to_castigado(self):
        from core.loanbook_model import is_valid_transition
        assert is_valid_transition("mora_grave", "castigado") is True

    def test_valid_transition_mora_to_reestructurado(self):
        from core.loanbook_model import is_valid_transition
        assert is_valid_transition("mora", "reestructurado") is True
        assert is_valid_transition("mora_grave", "reestructurado") is True

    def test_invalid_transition_pendiente_to_mora(self):
        from core.loanbook_model import is_valid_transition
        assert is_valid_transition("pendiente_entrega", "mora") is False

    def test_invalid_transition_saldado_to_anything(self):
        from core.loanbook_model import is_valid_transition
        assert is_valid_transition("saldado", "activo") is False
        assert is_valid_transition("saldado", "mora") is False

    def test_invalid_transition_castigado_to_anything(self):
        from core.loanbook_model import is_valid_transition
        assert is_valid_transition("castigado", "activo") is False

    def test_recovery_from_en_riesgo_to_al_dia(self):
        from core.loanbook_model import is_valid_transition
        assert is_valid_transition("en_riesgo", "al_dia") is True

    def test_recovery_from_mora_to_al_dia(self):
        from core.loanbook_model import is_valid_transition
        assert is_valid_transition("mora", "al_dia") is True


# ═══════════════════════════════════════════
# Mora calculation
# ═══════════════════════════════════════════


class TestMoraCalculation:
    """$2,000 COP/day from the DAY AFTER the due date."""

    def test_mora_zero_on_due_date(self):
        from core.loanbook_model import calcular_mora
        assert calcular_mora(fecha_cuota=date(2026, 4, 10), fecha_actual=date(2026, 4, 10)) == 0

    def test_mora_zero_before_due_date(self):
        from core.loanbook_model import calcular_mora
        assert calcular_mora(fecha_cuota=date(2026, 4, 10), fecha_actual=date(2026, 4, 9)) == 0

    def test_mora_one_day_late(self):
        from core.loanbook_model import calcular_mora
        assert calcular_mora(fecha_cuota=date(2026, 4, 10), fecha_actual=date(2026, 4, 11)) == 2000

    def test_mora_five_days_late(self):
        from core.loanbook_model import calcular_mora
        assert calcular_mora(fecha_cuota=date(2026, 4, 10), fecha_actual=date(2026, 4, 15)) == 10000

    def test_mora_thirty_days_late(self):
        from core.loanbook_model import calcular_mora
        assert calcular_mora(fecha_cuota=date(2026, 4, 10), fecha_actual=date(2026, 5, 10)) == 60000

    def test_mora_custom_rate(self):
        from core.loanbook_model import calcular_mora
        assert calcular_mora(
            fecha_cuota=date(2026, 4, 10),
            fecha_actual=date(2026, 4, 15),
            tasa_diaria=3000,
        ) == 15000


# ═══════════════════════════════════════════
# Waterfall payment allocation
# ═══════════════════════════════════════════


class TestWaterfallPayment:
    """ANZI 2% → mora → vencidas → corriente → abono capital."""

    def test_waterfall_simple_current_cuota(self):
        from core.loanbook_model import aplicar_waterfall

        result = aplicar_waterfall(
            monto_pago=100_000, anzi_pct=0.02, mora_pendiente=0,
            cuotas_vencidas_total=0, cuota_corriente=100_000, saldo_capital=500_000,
        )
        assert result["anzi"] == 2_000
        assert result["mora"] == 0
        assert result["vencidas"] == 0
        assert result["corriente"] == 98_000
        assert result["capital"] == 0
        assert result["sobrante"] == 0

    def test_waterfall_with_mora(self):
        from core.loanbook_model import aplicar_waterfall

        result = aplicar_waterfall(
            monto_pago=120_000, anzi_pct=0.02, mora_pendiente=10_000,
            cuotas_vencidas_total=0, cuota_corriente=100_000, saldo_capital=500_000,
        )
        assert result["anzi"] == 2_400
        assert result["mora"] == 10_000
        assert result["vencidas"] == 0
        assert result["corriente"] == 100_000
        assert result["capital"] == 7_600
        assert result["sobrante"] == 0

    def test_waterfall_with_vencidas(self):
        from core.loanbook_model import aplicar_waterfall

        result = aplicar_waterfall(
            monto_pago=250_000, anzi_pct=0.02, mora_pendiente=5_000,
            cuotas_vencidas_total=50_000, cuota_corriente=100_000, saldo_capital=400_000,
        )
        assert result["anzi"] == 5_000
        assert result["mora"] == 5_000
        assert result["vencidas"] == 50_000
        assert result["corriente"] == 100_000
        assert result["capital"] == 90_000
        assert result["sobrante"] == 0

    def test_waterfall_insufficient_for_cuota(self):
        from core.loanbook_model import aplicar_waterfall

        result = aplicar_waterfall(
            monto_pago=30_000, anzi_pct=0.02, mora_pendiente=20_000,
            cuotas_vencidas_total=0, cuota_corriente=100_000, saldo_capital=500_000,
        )
        assert result["anzi"] == 600
        assert result["mora"] == 20_000
        assert result["vencidas"] == 0
        assert result["corriente"] == 9_400
        assert result["capital"] == 0

    def test_waterfall_anzi_from_plan_not_hardcoded(self):
        from core.loanbook_model import aplicar_waterfall

        result = aplicar_waterfall(
            monto_pago=100_000, anzi_pct=0.03, mora_pendiente=0,
            cuotas_vencidas_total=0, cuota_corriente=100_000, saldo_capital=500_000,
        )
        assert result["anzi"] == 3_000

    def test_waterfall_zero_payment(self):
        from core.loanbook_model import aplicar_waterfall

        result = aplicar_waterfall(
            monto_pago=0, anzi_pct=0.02, mora_pendiente=10_000,
            cuotas_vencidas_total=50_000, cuota_corriente=100_000, saldo_capital=500_000,
        )
        assert result["anzi"] == 0
        assert result["mora"] == 0
        assert result["corriente"] == 0


# ═══════════════════════════════════════════
# Cuota calculation — modalidad independent of plan
# ═══════════════════════════════════════════


# Seed plan data (matches what goes in catalogo_planes MongoDB)
PLAN_P52S = {
    "codigo": "P52S",
    "nombre": "Plan 52 Semanas",
    "cuotas_base": 52,
    "anzi_pct": 0.02,
    "cuotas_modelo": {"Sport 100": 160_000, "Raider 125": 179_900},
}

PLAN_P39S = {
    "codigo": "P39S",
    "nombre": "Plan 39 Semanas",
    "cuotas_base": 39,
    "anzi_pct": 0.02,
    "cuotas_modelo": {"Sport 100": 175_000, "Raider 125": 210_000},
}

PLAN_P78S = {
    "codigo": "P78S",
    "nombre": "Plan 78 Semanas",
    "cuotas_base": 78,
    "anzi_pct": 0.02,
    "cuotas_modelo": {"Sport 100": 130_000, "Raider 125": 149_900},
}


class TestCuotaCalculation:
    """Modalidad is independent of plan. Multipliers from MODALIDADES constant."""

    def test_p52s_semanal_sport100(self):
        from core.loanbook_model import calcular_cuota, calcular_num_cuotas

        num = calcular_num_cuotas(PLAN_P52S, "semanal")
        cuota = calcular_cuota(cuota_base=160_000, modalidad="semanal")

        assert num == 52          # 52 / 1
        assert cuota == 160_000   # 160k × 1.0

    def test_p52s_quincenal_sport100(self):
        from core.loanbook_model import calcular_cuota, calcular_num_cuotas

        num = calcular_num_cuotas(PLAN_P52S, "quincenal")
        cuota = calcular_cuota(cuota_base=160_000, modalidad="quincenal")

        assert num == 26          # 52 / 2
        assert cuota == 352_000   # 160k × 2.2

    def test_p52s_mensual_sport100(self):
        from core.loanbook_model import calcular_cuota, calcular_num_cuotas

        num = calcular_num_cuotas(PLAN_P52S, "mensual")
        cuota = calcular_cuota(cuota_base=160_000, modalidad="mensual")

        assert num == 13          # 52 / 4
        assert cuota == 704_000   # 160k × 4.4

    def test_p39s_semanal_raider(self):
        from core.loanbook_model import calcular_cuota, calcular_num_cuotas

        num = calcular_num_cuotas(PLAN_P39S, "semanal")
        cuota = calcular_cuota(cuota_base=210_000, modalidad="semanal")

        assert num == 39
        assert cuota == 210_000   # 210k × 1.0

    def test_p78s_mensual_sport100(self):
        from core.loanbook_model import calcular_cuota, calcular_num_cuotas

        num = calcular_num_cuotas(PLAN_P78S, "mensual")
        cuota = calcular_cuota(cuota_base=130_000, modalidad="mensual")

        assert num == 19          # 78 / 4 = 19.5 → 19
        assert cuota == 572_000   # 130k × 4.4

    def test_invalid_modalidad_raises(self):
        from core.loanbook_model import calcular_cuota

        with pytest.raises(ValueError, match="contado"):
            calcular_cuota(cuota_base=160_000, modalidad="contado")

    def test_modalidades_constant_exposed(self):
        from core.loanbook_model import MODALIDADES

        assert "semanal" in MODALIDADES
        assert "quincenal" in MODALIDADES
        assert "mensual" in MODALIDADES
        assert MODALIDADES["semanal"]["multiplicador"] == 1.0
        assert MODALIDADES["quincenal"]["multiplicador"] == 2.2
        assert MODALIDADES["mensual"]["multiplicador"] == 4.4


# ═══════════════════════════════════════════
# Contado — no loanbook
# ═══════════════════════════════════════════


class TestContado:
    """Contado sales do NOT create loanbooks."""

    def test_contado_constant_exists(self):
        from core.loanbook_model import VENTA_CONTADO
        assert VENTA_CONTADO == "contado"

    def test_crear_loanbook_rejects_contado(self):
        from core.loanbook_model import crear_loanbook

        with pytest.raises(ValueError, match="[Cc]ontado"):
            crear_loanbook(
                vin="ABC123",
                cliente={"nombre": "Juan", "cedula": "123"},
                plan=PLAN_P52S,
                modelo="Sport 100",
                modalidad="contado",
                fecha_entrega=date(2026, 4, 14),
            )


# ═══════════════════════════════════════════
# Loanbook creation — new API
# ═══════════════════════════════════════════


class TestLoanbookCreation:
    """Create a loanbook with plan + modalidad separated."""

    def test_crear_loanbook_structure(self):
        from core.loanbook_model import crear_loanbook

        lb = crear_loanbook(
            vin="ABC123",
            cliente={"nombre": "Juan Perez", "cedula": "123456"},
            plan=PLAN_P39S,
            modelo="Sport 100",
            modalidad="semanal",
            fecha_entrega=date(2026, 4, 14),
        )

        assert lb["vin"] == "ABC123"
        assert lb["cliente"]["nombre"] == "Juan Perez"
        assert lb["plan_codigo"] == "P39S"
        assert lb["modalidad"] == "semanal"
        assert lb["estado"] == "pendiente_entrega"
        assert lb["cuota_monto"] == 175_000   # Sport 100 × 1.0
        assert lb["num_cuotas"] == 39
        assert len(lb["cuotas"]) == 39

    def test_crear_loanbook_quincenal(self):
        from core.loanbook_model import crear_loanbook

        # 2026-04-22 is a Wednesday
        lb = crear_loanbook(
            vin="DEF456",
            cliente={"nombre": "Maria", "cedula": "456"},
            plan=PLAN_P52S,
            modelo="Sport 100",
            modalidad="quincenal",
            fecha_entrega=date(2026, 4, 14),
            fecha_primer_pago=date(2026, 4, 22),  # Wednesday
        )

        assert lb["num_cuotas"] == 26           # 52 / 2
        assert lb["cuota_monto"] == 352_000     # 160k × 2.2
        assert lb["fecha_primer_pago"] == "2026-04-22"

    def test_crear_loanbook_cuotas_all_pendiente(self):
        from core.loanbook_model import crear_loanbook

        lb = crear_loanbook(
            vin="ABC123",
            cliente={"nombre": "Juan", "cedula": "123"},
            plan=PLAN_P39S,
            modelo="Sport 100",
            modalidad="semanal",
            fecha_entrega=date(2026, 4, 14),
        )

        for cuota in lb["cuotas"]:
            assert cuota["estado"] == "pendiente"
            assert cuota["monto"] == 175_000
            assert cuota["mora_acumulada"] == 0
            assert cuota["fecha_pago"] is None

    def test_crear_loanbook_cuotas_numbered(self):
        from core.loanbook_model import crear_loanbook

        lb = crear_loanbook(
            vin="XYZ789",
            cliente={"nombre": "Maria", "cedula": "789"},
            plan=PLAN_P52S,
            modelo="Sport 100",
            modalidad="semanal",
            fecha_entrega=date(2026, 4, 14),
        )

        numeros = [c["numero"] for c in lb["cuotas"]]
        assert numeros == list(range(1, 53))

    def test_crear_loanbook_saldo_capital(self):
        from core.loanbook_model import crear_loanbook

        lb = crear_loanbook(
            vin="ABC123",
            cliente={"nombre": "Juan", "cedula": "123"},
            plan=PLAN_P39S,
            modelo="Sport 100",
            modalidad="semanal",
            fecha_entrega=date(2026, 4, 14),
        )

        # saldo_capital = num_cuotas × cuota_monto (total to be financed)
        assert lb["saldo_capital"] == 39 * 175_000
        assert lb["total_pagado"] == 0
        assert lb["total_mora_pagada"] == 0
        assert lb["total_anzi_pagado"] == 0


# ═══════════════════════════════════════════
# Fecha primer pago validation
# ═══════════════════════════════════════════


class TestFechaPrimerPago:
    """Quincenal/mensual require fecha_primer_pago that is a Wednesday."""

    def test_quincenal_without_fecha_raises(self):
        from core.loanbook_model import crear_loanbook

        with pytest.raises(ValueError, match="fecha_primer_pago"):
            crear_loanbook(
                vin="ABC123",
                cliente={"nombre": "Juan", "cedula": "123"},
                plan=PLAN_P52S,
                modelo="Sport 100",
                modalidad="quincenal",
                fecha_entrega=date(2026, 4, 14),
                # No fecha_primer_pago!
            )

    def test_mensual_without_fecha_raises(self):
        from core.loanbook_model import crear_loanbook

        with pytest.raises(ValueError, match="fecha_primer_pago"):
            crear_loanbook(
                vin="ABC123",
                cliente={"nombre": "Juan", "cedula": "123"},
                plan=PLAN_P52S,
                modelo="Sport 100",
                modalidad="mensual",
                fecha_entrega=date(2026, 4, 14),
            )

    def test_fecha_primer_pago_not_wednesday_raises(self):
        from core.loanbook_model import crear_loanbook

        # 2026-04-23 is Thursday, not Wednesday
        with pytest.raises(ValueError, match="[Mm]i.rcoles|[Ww]ednesday"):
            crear_loanbook(
                vin="ABC123",
                cliente={"nombre": "Juan", "cedula": "123"},
                plan=PLAN_P52S,
                modelo="Sport 100",
                modalidad="quincenal",
                fecha_entrega=date(2026, 4, 14),
                fecha_primer_pago=date(2026, 4, 23),  # Thursday
            )

    def test_semanal_without_fecha_ok(self):
        from core.loanbook_model import crear_loanbook

        # Semanal doesn't require fecha_primer_pago (auto-calculated in Sprint 4)
        lb = crear_loanbook(
            vin="ABC123",
            cliente={"nombre": "Juan", "cedula": "123"},
            plan=PLAN_P39S,
            modelo="Sport 100",
            modalidad="semanal",
            fecha_entrega=date(2026, 4, 14),
        )
        assert lb["fecha_primer_pago"] is None  # Calculated by Sprint 4

    def test_modelo_not_in_plan_raises(self):
        from core.loanbook_model import crear_loanbook

        with pytest.raises(ValueError, match="modelo"):
            crear_loanbook(
                vin="ABC123",
                cliente={"nombre": "Juan", "cedula": "123"},
                plan=PLAN_P52S,
                modelo="Apache 200",  # Not in P52S
                modalidad="semanal",
                fecha_entrega=date(2026, 4, 14),
            )


# ═══════════════════════════════════════════
# DPD (Days Past Due) calculation
# ═══════════════════════════════════════════


class TestDPD:
    """Days past due for credit scoring."""

    def test_dpd_no_overdue(self):
        from core.loanbook_model import calcular_dpd

        cuotas = [
            {"numero": 1, "estado": "pagada", "fecha": "2026-04-10"},
            {"numero": 2, "estado": "pendiente", "fecha": "2026-04-17"},
        ]
        assert calcular_dpd(cuotas, fecha_actual=date(2026, 4, 15)) == 0

    def test_dpd_one_cuota_overdue(self):
        from core.loanbook_model import calcular_dpd

        cuotas = [
            {"numero": 1, "estado": "pendiente", "fecha": "2026-04-10"},
            {"numero": 2, "estado": "pendiente", "fecha": "2026-04-17"},
        ]
        assert calcular_dpd(cuotas, fecha_actual=date(2026, 4, 15)) == 5

    def test_dpd_multiple_overdue_uses_oldest(self):
        from core.loanbook_model import calcular_dpd

        cuotas = [
            {"numero": 1, "estado": "pendiente", "fecha": "2026-04-01"},
            {"numero": 2, "estado": "pendiente", "fecha": "2026-04-08"},
            {"numero": 3, "estado": "pendiente", "fecha": "2026-04-15"},
        ]
        assert calcular_dpd(cuotas, fecha_actual=date(2026, 4, 15)) == 14


# ═══════════════════════════════════════════
# Estado derivation from DPD
# ═══════════════════════════════════════════


class TestEstadoFromDPD:
    """Derive credit state from days past due."""

    def test_al_dia_dpd_zero(self):
        from core.loanbook_model import estado_from_dpd
        assert estado_from_dpd(0) == "al_dia"

    def test_en_riesgo_dpd_1_to_15(self):
        from core.loanbook_model import estado_from_dpd
        assert estado_from_dpd(1) == "en_riesgo"
        assert estado_from_dpd(15) == "en_riesgo"

    def test_mora_dpd_16_to_60(self):
        from core.loanbook_model import estado_from_dpd
        assert estado_from_dpd(16) == "mora"
        assert estado_from_dpd(60) == "mora"

    def test_mora_grave_dpd_over_60(self):
        from core.loanbook_model import estado_from_dpd
        assert estado_from_dpd(61) == "mora_grave"
        assert estado_from_dpd(120) == "mora_grave"
