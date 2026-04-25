"""
test_calcular_saldos.py — Tests para calcular_saldos() en reglas_negocio.

Valida las fórmulas contra el Excel loanbook_roddos_2026-04-25.xlsx.
"""
from __future__ import annotations

from services.loanbook.reglas_negocio import calcular_saldos


class TestCalcularSaldos:

    def test_chenier_p52s_raider(self):
        """LB-0001 P52S Raider: 7_800_000/52 × 46 = 6_900_000."""
        r = calcular_saldos(7_800_000, 52, 179_900, 6)
        assert r["saldo_capital"]   == 6_900_000
        assert r["saldo_intereses"] == 1_375_400

    def test_ernesto_p78s_raider(self):
        """LB-0003 P78S Raider: 7_800_000/78 × 72 = 7_200_000."""
        r = calcular_saldos(7_800_000, 78, 149_900, 6)
        assert r["saldo_capital"]   == 7_200_000
        assert r["saldo_intereses"] == 3_592_800

    def test_jose_p78s_sport(self):
        """LB-0002 P78S Sport: 5_750_000/78 × 72 = 5_307_692."""
        r = calcular_saldos(5_750_000, 78, 130_000, 6)
        assert r["saldo_capital"]   == 5_307_692
        assert r["saldo_intereses"] == 4_052_308

    def test_zero_cuotas_pagadas(self):
        """Con 0 cuotas pagadas saldo_capital debe igualar capital_plan."""
        r = calcular_saldos(5_750_000, 39, 204_000, 0)
        # La suma total de cuotas menos la diferencia de redondeo
        assert r["saldo_capital"] + r["saldo_intereses"] == 204_000 * 39 - (
            r["saldo_capital"] - round(5_750_000 / 39 * 39)
        )
        # saldo_capital == capital_plan cuando cuotas_pagadas=0
        assert r["saldo_capital"] == 5_750_000

    def test_contado_total_cuotas_cero(self):
        """total_cuotas=0 (contado) → todos los saldos en cero, sin ZeroDivisionError."""
        r = calcular_saldos(7_800_000, 0, 0, 0)
        assert r["saldo_capital"]   == 0
        assert r["saldo_intereses"] == 0

    # ── Invariantes ──────────────────────────────────────────────────────────────

    def test_retorna_dict_con_campos_esperados(self):
        r = calcular_saldos(5_750_000, 39, 204_000, 10)
        for campo in ("cuotas_pendientes", "capital_por_cuota",
                      "saldo_capital", "saldo_intereses", "monto_original"):
            assert campo in r, f"Falta campo: {campo}"

    def test_saldo_capital_nunca_negativo(self):
        """Si cuotas_pagadas == total_cuotas, saldo_capital = 0."""
        r = calcular_saldos(7_800_000, 52, 179_900, 52)
        assert r["saldo_capital"]   == 0
        assert r["saldo_intereses"] == 0
        assert r["cuotas_pendientes"] == 0

    def test_monto_original_es_cuota_por_total(self):
        r = calcular_saldos(5_750_000, 39, 204_000, 5)
        assert r["monto_original"] == 204_000 * 39

    def test_cuotas_pendientes_correcto(self):
        r = calcular_saldos(7_800_000, 78, 149_900, 15)
        assert r["cuotas_pendientes"] == 63

    def test_saldo_intereses_positivo_cuando_cuota_mayor_que_capital_por_cuota(self):
        """saldo_intereses >= 0 cuando cuota > capital_por_cuota (caso típico crédito)."""
        r = calcular_saldos(5_750_000, 39, 204_000, 0)
        # capital_por_cuota = 147_435 < cuota_periodica = 204_000 → intereses positivos
        assert r["saldo_intereses"] >= 0
