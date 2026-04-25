"""
test_motor_financiero.py — Tests del motor financiero Roddos.
Verifica todas las funciones de reglas_negocio.py contra casos reales del Excel.
"""
from __future__ import annotations

from datetime import date

from services.loanbook.reglas_negocio import (
    calcular_saldos,
    calcular_cuota_desglosada,
    calcular_pago_aplicado,
    calcular_mora,
    calcular_fecha_vencimiento,
    generar_cronograma,
    calcular_cuota_dado_inicial,
    calcular_inicial_dado_cuota,
    recalcular_tras_abono,
)


# ── calcular_saldos ────────────────────────────────────────────────────────────

def test_saldos_lb0001_p52s_raider():
    r = calcular_saldos(7_800_000, 52, 179_900, 6)
    assert r["saldo_capital"]   == 6_900_000
    assert r["saldo_intereses"] == 1_375_400


def test_saldos_lb0002_p78s_sport():
    r = calcular_saldos(5_750_000, 78, 130_000, 6)
    assert r["saldo_capital"]   == 5_307_692
    assert r["saldo_intereses"] == 4_052_308


def test_saldos_lb0027_cuota_especial():
    # cuota_real=145_000, cuota_std=130_000
    r = calcular_saldos(5_750_000, 78, 145_000, 0, cuota_estandar_plan=130_000)
    assert r["saldo_capital"]   == 5_750_000
    assert r["saldo_intereses"] == 4_390_000


def test_saldos_lb0028_cuota_especial():
    # cuota_real=204_000, cuota_std=175_000
    # si = 175_000 × 39 − 5_750_000 = 6_825_000 − 5_750_000 = 1_075_000
    r = calcular_saldos(5_750_000, 39, 204_000, 0, cuota_estandar_plan=175_000)
    assert r["saldo_capital"]   == 5_750_000
    assert r["saldo_intereses"] == 1_075_000


def test_saldos_contado():
    r = calcular_saldos(7_800_000, 0, 0, 0)
    assert r["saldo_capital"]   == 0
    assert r["saldo_intereses"] == 0


def test_saldos_ltv():
    r = calcular_saldos(7_800_000, 52, 179_900, 6, moto_valor_origen=5_638_974)
    assert r["ltv"] is not None
    assert r["ltv"] > 1.0


# ── calcular_cuota_desglosada ──────────────────────────────────────────────────

def test_desglose_p52s_raider():
    r = calcular_cuota_desglosada(7_800_000, 52, 179_900)
    assert round(r["capital_cuota"]) == 150_000
    assert round(r["interes_cuota"]) == 29_900


def test_desglose_p78s_raider():
    r = calcular_cuota_desglosada(7_800_000, 78, 149_900)
    assert round(r["capital_cuota"]) == 100_000
    assert round(r["interes_cuota"]) == 49_900


def test_desglose_p78s_sport():
    r = calcular_cuota_desglosada(5_750_000, 78, 130_000)
    assert abs(r["capital_cuota"] - 73_717.95) < 1
    assert abs(r["interes_cuota"] - 56_282.05) < 1


# ── calcular_pago_aplicado ─────────────────────────────────────────────────────

def test_pago_sin_mora():
    r = calcular_pago_aplicado(179_900, 0, 150_000, 29_900, 6_900_000)
    assert r["anzi_pagado"]     == 0
    assert r["interes_pagado"]  == 29_900
    assert r["capital_pagado"]  == 150_000
    assert r["no_aplicado"]     == 0


def test_pago_con_mora():
    r = calcular_pago_aplicado(181_900, 2_000, 150_000, 29_900, 6_900_000)
    assert r["anzi_pagado"]     == 2_000
    assert r["interes_pagado"]  == 29_900
    assert r["capital_pagado"]  == 150_000
    assert r["no_aplicado"]     == 0


def test_pago_con_abono_extra():
    r = calcular_pago_aplicado(279_900, 0, 150_000, 29_900, 6_900_000)
    assert r["capital_pagado"]       == 150_000
    assert r["abono_capital_extra"]  == 100_000
    assert r["no_aplicado"]          == 0


# ── calcular_mora ──────────────────────────────────────────────────────────────

def test_mora_current():
    r = calcular_mora(0)
    assert r["mora_acumulada_cop"]  == 0
    assert r["sub_bucket_semanal"]  == "Current"


def test_mora_grace():
    r = calcular_mora(3)
    assert r["mora_acumulada_cop"]  == 6_000
    assert r["sub_bucket_semanal"]  == "Grace"


def test_mora_default():
    r = calcular_mora(95)
    assert r["mora_acumulada_cop"]  == 190_000
    assert r["sub_bucket_semanal"]  == "Default"


def test_mora_chargeoff():
    r = calcular_mora(125)
    assert r["sub_bucket_semanal"]  == "Charge-Off"


# ── calcular_fecha_vencimiento ─────────────────────────────────────────────────

def test_fecha_vencimiento_p52s_semanal():
    # primer=2026-03-18 + (52-1)×7 = 357 días → 2027-03-10
    primer = date(2026, 3, 18)
    fin = calcular_fecha_vencimiento(primer, 52, "semanal")
    assert fin == date(2027, 3, 10)


# ── generar_cronograma ─────────────────────────────────────────────────────────

def test_cronograma_longitud():
    c = generar_cronograma(
        "LB-TEST", "Test", date(2026, 3, 18),
        52, 179_900, 150_000, 29_900, "semanal", 7_800_000,
    )
    assert len(c) == 52


def test_cronograma_saldo_final_cero():
    c = generar_cronograma(
        "LB-TEST", "Test", date(2026, 3, 18),
        52, 179_900, 150_000, 29_900, "semanal", 7_800_000,
    )
    assert c[-1]["saldo_despues"] == 0


def test_cronograma_primer_miercoles():
    c = generar_cronograma(
        "LB-TEST", "Test", date(2026, 3, 18),
        52, 179_900, 150_000, 29_900, "semanal", 7_800_000,
    )
    assert c[0]["fecha_programada"] == "2026-03-18"


# ── calcular_cuota_dado_inicial ────────────────────────────────────────────────

def test_cuota_dado_inicial_raider_p52s():
    r = calcular_cuota_dado_inicial(7_800_000, 1_460_000, 52, 179_900)
    assert r["capital_neto"]    == 6_340_000
    assert r["cuota_periodica"] < 179_900


def test_cuota_dado_inicial_cero():
    r = calcular_cuota_dado_inicial(7_800_000, 0, 52, 179_900)
    assert r["cuota_periodica"] == 179_900


# ── calcular_inicial_dado_cuota ────────────────────────────────────────────────

def test_inicial_dado_cuota_menor():
    r = calcular_inicial_dado_cuota(7_800_000, 150_000, 179_900)
    assert r["cuota_inicial_requerida"] > 0


def test_inicial_dado_cuota_igual():
    r = calcular_inicial_dado_cuota(7_800_000, 179_900, 179_900)
    assert r["cuota_inicial_requerida"] == 0


# ── recalcular_tras_abono ──────────────────────────────────────────────────────

def test_abono_reducir_plazo():
    r = recalcular_tras_abono(6_900_000, 1_000_000, 46, 179_900, 29_900, "reducir_plazo")
    assert r["nuevo_saldo_capital"]      == 5_900_000
    assert r["cuotas_reducidas"]         > 0
    assert r["nuevas_cuotas_pendientes"] < 46


def test_abono_reducir_cuota():
    r = recalcular_tras_abono(6_900_000, 1_000_000, 46, 179_900, 29_900, "reducir_cuota")
    assert r["nuevo_saldo_capital"]   == 5_900_000
    assert r["nueva_cuota_periodica"] < 179_900


def test_abono_salda_credito():
    r = recalcular_tras_abono(6_900_000, 6_900_000, 46, 179_900, 29_900)
    assert r["nuevo_saldo_capital"]      == 0
    assert r["nuevas_cuotas_pendientes"] == 0
