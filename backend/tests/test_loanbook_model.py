"""
Loanbook Model V2 tests — pure domain logic, no MongoDB.

Tests:
1. State transitions (valid + invalid)
2. Mora calculation ($2,000/day from day AFTER due date)
3. Waterfall payment allocation (ANZI → mora → vencidas → corriente → capital)
4. Cuota multipliers by modality (read from plan, not hardcoded)
5. Plan catalog loading
6. Loanbook creation from plan
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
        # Any active state can go to saldado (paid off)
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
        # Saldado is terminal
        assert is_valid_transition("saldado", "activo") is False
        assert is_valid_transition("saldado", "mora") is False

    def test_invalid_transition_castigado_to_anything(self):
        from core.loanbook_model import is_valid_transition
        # Castigado is terminal
        assert is_valid_transition("castigado", "activo") is False

    def test_recovery_from_en_riesgo_to_al_dia(self):
        from core.loanbook_model import is_valid_transition
        # Paying overdue allows recovery
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
        # Paying on due date = no mora
        assert calcular_mora(fecha_cuota=date(2026, 4, 10), fecha_actual=date(2026, 4, 10)) == 0

    def test_mora_zero_before_due_date(self):
        from core.loanbook_model import calcular_mora
        assert calcular_mora(fecha_cuota=date(2026, 4, 10), fecha_actual=date(2026, 4, 9)) == 0

    def test_mora_one_day_late(self):
        from core.loanbook_model import calcular_mora
        # 1 day late = $2,000
        assert calcular_mora(fecha_cuota=date(2026, 4, 10), fecha_actual=date(2026, 4, 11)) == 2000

    def test_mora_five_days_late(self):
        from core.loanbook_model import calcular_mora
        assert calcular_mora(fecha_cuota=date(2026, 4, 10), fecha_actual=date(2026, 4, 15)) == 10000

    def test_mora_thirty_days_late(self):
        from core.loanbook_model import calcular_mora
        assert calcular_mora(fecha_cuota=date(2026, 4, 10), fecha_actual=date(2026, 5, 10)) == 60000

    def test_mora_custom_rate(self):
        from core.loanbook_model import calcular_mora
        # Future-proof: allow custom mora rate
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

        # Simple case: pay a $100,000 cuota with no mora, no overdue
        result = aplicar_waterfall(
            monto_pago=100_000,
            anzi_pct=0.02,
            mora_pendiente=0,
            cuotas_vencidas_total=0,
            cuota_corriente=100_000,
            saldo_capital=500_000,
        )

        assert result["anzi"] == 2_000          # 2% of 100k
        assert result["mora"] == 0
        assert result["vencidas"] == 0
        assert result["corriente"] == 98_000     # 100k - 2k ANZI
        assert result["capital"] == 0
        assert result["sobrante"] == 0

    def test_waterfall_with_mora(self):
        from core.loanbook_model import aplicar_waterfall

        # Pay $120,000 with $10,000 mora accumulated
        result = aplicar_waterfall(
            monto_pago=120_000,
            anzi_pct=0.02,
            mora_pendiente=10_000,
            cuotas_vencidas_total=0,
            cuota_corriente=100_000,
            saldo_capital=500_000,
        )

        assert result["anzi"] == 2_400          # 2% of 120k
        assert result["mora"] == 10_000          # Full mora covered
        assert result["vencidas"] == 0
        assert result["corriente"] == 100_000    # Capped at cuota amount
        # Remaining: 120k - 2.4k - 10k - 100k = 7,600 → capital
        assert result["capital"] == 7_600
        assert result["sobrante"] == 0

    def test_waterfall_with_vencidas(self):
        from core.loanbook_model import aplicar_waterfall

        # Pay $250,000 with $50,000 in overdue cuotas + $100,000 current
        result = aplicar_waterfall(
            monto_pago=250_000,
            anzi_pct=0.02,
            mora_pendiente=5_000,
            cuotas_vencidas_total=50_000,
            cuota_corriente=100_000,
            saldo_capital=400_000,
        )

        assert result["anzi"] == 5_000          # 2% of 250k
        assert result["mora"] == 5_000           # Full mora
        assert result["vencidas"] == 50_000      # All overdue covered
        assert result["corriente"] == 100_000    # Current cuota covered
        # Remaining: 250k - 5k - 5k - 50k - 100k = 90k → capital
        assert result["capital"] == 90_000
        assert result["sobrante"] == 0

    def test_waterfall_insufficient_for_cuota(self):
        from core.loanbook_model import aplicar_waterfall

        # Pay $30,000 when cuota is $100,000 and mora is $20,000
        result = aplicar_waterfall(
            monto_pago=30_000,
            anzi_pct=0.02,
            mora_pendiente=20_000,
            cuotas_vencidas_total=0,
            cuota_corriente=100_000,
            saldo_capital=500_000,
        )

        assert result["anzi"] == 600            # 2% of 30k
        assert result["mora"] == 20_000          # Full mora (29.4k available, covers 20k)
        assert result["vencidas"] == 0
        # Remaining after ANZI + mora: 30k - 600 - 20k = 9,400 → partial corriente
        assert result["corriente"] == 9_400
        assert result["capital"] == 0
        assert result["sobrante"] == 0

    def test_waterfall_anzi_from_plan_not_hardcoded(self):
        from core.loanbook_model import aplicar_waterfall

        # Different ANZI percentage (e.g., 3% for a different plan)
        result = aplicar_waterfall(
            monto_pago=100_000,
            anzi_pct=0.03,
            mora_pendiente=0,
            cuotas_vencidas_total=0,
            cuota_corriente=100_000,
            saldo_capital=500_000,
        )

        assert result["anzi"] == 3_000  # 3%, not hardcoded 2%

    def test_waterfall_zero_payment(self):
        from core.loanbook_model import aplicar_waterfall

        result = aplicar_waterfall(
            monto_pago=0,
            anzi_pct=0.02,
            mora_pendiente=10_000,
            cuotas_vencidas_total=50_000,
            cuota_corriente=100_000,
            saldo_capital=500_000,
        )

        assert result["anzi"] == 0
        assert result["mora"] == 0
        assert result["vencidas"] == 0
        assert result["corriente"] == 0
        assert result["capital"] == 0


# ═══════════════════════════════════════════
# Cuota multipliers by modality
# ═══════════════════════════════════════════


class TestCuotaMultipliers:
    """Multipliers come from catalogo_planes, never hardcoded."""

    def test_calcular_cuota_semanal(self):
        from core.loanbook_model import calcular_cuota

        # P52S: 52 cuotas semanales, multiplicador 1.0
        plan = {
            "codigo": "P52S",
            "cuotas": 52,
            "modalidad": "semanal",
            "multiplicador": 1.0,
            "anzi_pct": 0.02,
        }
        cuota = calcular_cuota(monto_financiar=5_200_000, plan=plan)
        assert cuota == 100_000  # 5.2M / 52 * 1.0

    def test_calcular_cuota_quincenal(self):
        from core.loanbook_model import calcular_cuota

        plan = {
            "codigo": "P52S",
            "cuotas": 26,  # 52 weeks / 2
            "modalidad": "quincenal",
            "multiplicador": 2.2,
            "anzi_pct": 0.02,
        }
        cuota = calcular_cuota(monto_financiar=5_200_000, plan=plan)
        # (5.2M / 26) * 2.2 = 200k * 2.2 = 440k
        assert cuota == 440_000

    def test_calcular_cuota_mensual(self):
        from core.loanbook_model import calcular_cuota

        plan = {
            "codigo": "P52S",
            "cuotas": 13,  # 52 weeks / 4
            "modalidad": "mensual",
            "multiplicador": 4.4,
            "anzi_pct": 0.02,
        }
        cuota = calcular_cuota(monto_financiar=5_200_000, plan=plan)
        # (5.2M / 13) * 4.4 = 400k * 4.4 = 1,760,000
        assert cuota == 1_760_000

    def test_calcular_cuota_reads_multiplier_from_plan(self):
        from core.loanbook_model import calcular_cuota

        # Custom plan with non-standard multiplier
        plan = {
            "codigo": "CUSTOM",
            "cuotas": 10,
            "modalidad": "semanal",
            "multiplicador": 1.5,
            "anzi_pct": 0.02,
        }
        cuota = calcular_cuota(monto_financiar=1_000_000, plan=plan)
        assert cuota == 150_000  # (1M / 10) * 1.5


# ═══════════════════════════════════════════
# Loanbook creation
# ═══════════════════════════════════════════


class TestLoanbookCreation:
    """Create a loanbook from a plan and verify structure."""

    def test_crear_loanbook_structure(self):
        from core.loanbook_model import crear_loanbook

        plan = {
            "codigo": "P39S",
            "cuotas": 39,
            "modalidad": "semanal",
            "multiplicador": 1.0,
            "anzi_pct": 0.02,
        }

        lb = crear_loanbook(
            vin="ABC123",
            cliente={"nombre": "Juan Perez", "cedula": "123456"},
            plan=plan,
            monto_financiar=3_900_000,
            fecha_entrega=date(2026, 4, 14),
        )

        assert lb["vin"] == "ABC123"
        assert lb["cliente"]["nombre"] == "Juan Perez"
        assert lb["plan"]["codigo"] == "P39S"
        assert lb["modalidad"] == "semanal"
        assert lb["estado"] == "pendiente_entrega"
        assert lb["monto_financiar"] == 3_900_000
        assert lb["cuota_monto"] == 100_000  # 3.9M / 39 * 1.0
        assert len(lb["cuotas"]) == 39

    def test_crear_loanbook_cuotas_all_pendiente(self):
        from core.loanbook_model import crear_loanbook

        plan = {
            "codigo": "P39S",
            "cuotas": 39,
            "modalidad": "semanal",
            "multiplicador": 1.0,
            "anzi_pct": 0.02,
        }

        lb = crear_loanbook(
            vin="ABC123",
            cliente={"nombre": "Juan", "cedula": "123"},
            plan=plan,
            monto_financiar=3_900_000,
            fecha_entrega=date(2026, 4, 14),
        )

        for cuota in lb["cuotas"]:
            assert cuota["estado"] == "pendiente"
            assert cuota["monto"] == 100_000
            assert cuota["mora_acumulada"] == 0
            assert cuota["fecha_pago"] is None

    def test_crear_loanbook_cuotas_numbered(self):
        from core.loanbook_model import crear_loanbook

        plan = {
            "codigo": "P52S",
            "cuotas": 52,
            "modalidad": "semanal",
            "multiplicador": 1.0,
            "anzi_pct": 0.02,
        }

        lb = crear_loanbook(
            vin="XYZ789",
            cliente={"nombre": "Maria", "cedula": "789"},
            plan=plan,
            monto_financiar=5_200_000,
            fecha_entrega=date(2026, 4, 14),
        )

        numeros = [c["numero"] for c in lb["cuotas"]]
        assert numeros == list(range(1, 53))

    def test_crear_loanbook_saldo_capital(self):
        from core.loanbook_model import crear_loanbook

        plan = {
            "codigo": "P39S",
            "cuotas": 39,
            "modalidad": "semanal",
            "multiplicador": 1.0,
            "anzi_pct": 0.02,
        }

        lb = crear_loanbook(
            vin="ABC123",
            cliente={"nombre": "Juan", "cedula": "123"},
            plan=plan,
            monto_financiar=3_900_000,
            fecha_entrega=date(2026, 4, 14),
        )

        assert lb["saldo_capital"] == 3_900_000
        assert lb["total_pagado"] == 0
        assert lb["total_mora_pagada"] == 0
        assert lb["total_anzi_pagado"] == 0


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
        # All paid or not yet due
        assert calcular_dpd(cuotas, fecha_actual=date(2026, 4, 15)) == 0

    def test_dpd_one_cuota_overdue(self):
        from core.loanbook_model import calcular_dpd

        cuotas = [
            {"numero": 1, "estado": "pendiente", "fecha": "2026-04-10"},
            {"numero": 2, "estado": "pendiente", "fecha": "2026-04-17"},
        ]
        # Cuota 1 is 5 days overdue
        assert calcular_dpd(cuotas, fecha_actual=date(2026, 4, 15)) == 5

    def test_dpd_multiple_overdue_uses_oldest(self):
        from core.loanbook_model import calcular_dpd

        cuotas = [
            {"numero": 1, "estado": "pendiente", "fecha": "2026-04-01"},
            {"numero": 2, "estado": "pendiente", "fecha": "2026-04-08"},
            {"numero": 3, "estado": "pendiente", "fecha": "2026-04-15"},
        ]
        # Oldest unpaid: April 1 → 14 days overdue on April 15
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
