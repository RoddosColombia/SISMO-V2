"""
test_amortizacion_service.py — Tests del motor de amortización francesa y Waterfall Opción A.

Valida:
  - tasa_periodica: conversión EA → periódica para 3 modalidades
  - generar_cronograma: fechas, capital/interés, saldo=0 al final
  - aplicar_waterfall: orden estricto ANZI→mora→vencidas→corriente→capital
  - calcular_liquidacion_anticipada: monto_liquidacion = saldo + mora

Tests puros — sin MongoDB, sin I/O.
Ref: .planning/LOANBOOK_MAESTRO_v1.1.md caps 4, 6.2, 11.5 | R-19, R-21, R-22
"""

from __future__ import annotations

from datetime import date

import pytest

from services.loanbook.amortizacion_service import (
    MORA_COP_POR_DIA,
    aplicar_waterfall,
    calcular_liquidacion_anticipada,
    generar_cronograma,
    tasa_periodica,
)


# ─────────────────────── Fixtures compartidos ────────────────────────────────

def _cuota(numero: int, fecha: str, monto_total: int, estado: str = "pendiente",
           monto_capital: int = 0, monto_interes: int = 0, monto_pagado: int = 0) -> dict:
    return {
        "numero": numero,
        "fecha_programada": fecha,
        "monto_total": monto_total,
        "monto_capital": monto_capital or monto_total,
        "monto_interes": monto_interes,
        "monto_fees": 0,
        "estado": estado,
        "monto_pagado": monto_pagado,
    }


def _lb(cuotas=None, saldo=9_000_000, mora=0, anzi_pct=0.02):
    return {
        "loanbook_id": "LB-TEST-001",
        "saldo_capital": saldo,
        "mora_acumulada_cop": mora,
        "anzi_pct": anzi_pct,
        "cuotas": cuotas or [],
    }


# ─────────────────────── BLOQUE 1 — tasa_periodica ───────────────────────────

class TestTasaPeriodica:
    """Conversión EA → tasa periódica para cada modalidad."""

    def test_semanal_39pct(self):
        """39% EA semanal → ~0.00635 (en rango 0.006–0.007)."""
        tp = tasa_periodica(0.39, "semanal")
        assert 0.006 < tp < 0.007

    def test_semanal_formula(self):
        """Verificar fórmula: (1+ea)^(1/52) - 1."""
        tp = tasa_periodica(0.39, "semanal")
        esperado = (1.39) ** (1 / 52) - 1
        assert abs(tp - esperado) < 1e-10

    def test_quincenal_39pct(self):
        """39% EA quincenal → ~0.013 (26 períodos)."""
        tp = tasa_periodica(0.39, "quincenal")
        assert 0.012 < tp < 0.015

    def test_mensual_39pct(self):
        """39% EA mensual → ~0.028 (12 períodos)."""
        tp = tasa_periodica(0.39, "mensual")
        assert 0.027 < tp < 0.030

    def test_contado_es_cero(self):
        """Contado no tiene tasa periódica — retorna 0.0."""
        assert tasa_periodica(0.0, "contado") == 0.0

    def test_tasa_cero_retorna_cero(self):
        """Tasa EA = 0 → tasa periódica = 0 (semanal)."""
        tp = tasa_periodica(0.0, "semanal")
        assert tp == pytest.approx(0.0, abs=1e-10)

    def test_modalidad_invalida_lanza_error(self):
        with pytest.raises(ValueError, match="Modalidad inválida"):
            tasa_periodica(0.39, "diario")

    def test_mayor_ea_mayor_periodica(self):
        """A mayor EA, mayor tasa periódica."""
        tp_39 = tasa_periodica(0.39, "semanal")
        tp_60 = tasa_periodica(0.60, "semanal")
        assert tp_60 > tp_39


# ─────────────────────── BLOQUE 2 — generar_cronograma ───────────────────────

class TestGenerarCronograma:
    """Motor de amortización francesa: fechas, desglose, saldo final."""

    _SALDO = 9_000_000
    _CUOTA = 179_900
    _TASA  = 0.39
    _MODAL = "semanal"
    _ENTREGA = date(2026, 3, 17)  # lunes
    _N = 52

    def _gen(self, **kwargs):
        defaults = dict(
            saldo_inicial=self._SALDO,
            cuota_periodica=self._CUOTA,
            tasa_ea=self._TASA,
            modalidad=self._MODAL,
            fecha_entrega=self._ENTREGA,
            n_cuotas=self._N,
        )
        defaults.update(kwargs)
        return generar_cronograma(**defaults)

    def test_n_cuotas_correctas(self):
        cuotas = self._gen()
        assert len(cuotas) == 52

    def test_primera_cuota_es_miercoles(self):
        """Regla del miércoles: fecha_entrega lunes 17 mar → primer miércoles >= 24 mar = 25 mar."""
        cuotas = self._gen()
        # fecha_programada se persiste como string ISO para BSON — convertir para comparar
        assert date.fromisoformat(cuotas[0]["fecha_programada"]).weekday() == 2

    def test_primera_fecha_es_25_marzo(self):
        """fecha_entrega 17-mar (lunes) → entrega+7 = 24-mar (lunes) → primer miércoles = 25-mar."""
        cuotas = self._gen()
        assert cuotas[0]["fecha_programada"] == "2026-03-25"

    def test_fechas_son_miercoles_consecutivos(self):
        """Todas las cuotas semanales deben caer en miércoles con 7 días de diferencia."""
        cuotas = self._gen()
        for i, c in enumerate(cuotas):
            fp = date.fromisoformat(c["fecha_programada"])
            assert fp.weekday() == 2, f"Cuota {i+1} no es miércoles"
            if i > 0:
                fp_prev = date.fromisoformat(cuotas[i-1]["fecha_programada"])
                assert (fp - fp_prev).days == 7

    def test_capital_mas_interes_igual_total(self):
        """R-19: monto_capital + monto_interes == monto_total (salvo última cuota)."""
        cuotas = self._gen()
        for c in cuotas[:-1]:
            assert abs(c["monto_capital"] + c["monto_interes"] - c["monto_total"]) <= 1, \
                f"Cuota {c['numero']}: {c['monto_capital']} + {c['monto_interes']} ≠ {c['monto_total']}"

    def test_saldo_llega_a_cero(self):
        """La última cuota ajusta el capital para que saldo_despues sea exactamente 0."""
        cuotas = self._gen()
        assert cuotas[-1]["saldo_despues"] == 0

    def test_capital_creciente_interes_decreciente(self):
        """Amortización francesa: capital crece, interés decrece cuota a cuota."""
        cuotas = self._gen()
        for i in range(1, len(cuotas) - 1):
            assert cuotas[i]["monto_capital"] >= cuotas[i-1]["monto_capital"], \
                f"Capital no crece en cuota {i+1}"
            assert cuotas[i]["monto_interes"] <= cuotas[i-1]["monto_interes"], \
                f"Interés no decrece en cuota {i+1}"

    def test_estado_inicial_pendiente(self):
        """Todas las cuotas generadas deben tener estado='pendiente'."""
        cuotas = self._gen()
        assert all(c["estado"] == "pendiente" for c in cuotas)

    def test_sin_tasa_amortizacion_lineal(self):
        """tasa_ea=0 → cuota fija, sin interés, saldo=0 al final."""
        cuotas = generar_cronograma(
            saldo_inicial=1_000_000, cuota_periodica=0,
            tasa_ea=0.0, modalidad="semanal",
            fecha_entrega=date(2026, 1, 1), n_cuotas=10,
        )
        assert len(cuotas) == 10
        assert cuotas[-1]["saldo_despues"] == 0
        assert all(c["monto_interes"] == 0 for c in cuotas)

    def test_cuota_periodica_none_usa_formula(self):
        """Si cuota_periodica=None, se calcula con la fórmula francesa."""
        cuotas = generar_cronograma(
            saldo_inicial=1_000_000, cuota_periodica=None,
            tasa_ea=0.39, modalidad="semanal",
            fecha_entrega=date(2026, 1, 1), n_cuotas=12,
        )
        assert len(cuotas) == 12
        assert cuotas[-1]["saldo_despues"] == 0

    def test_saldo_inicial_invalido_lanza_error(self):
        with pytest.raises(ValueError):
            generar_cronograma(
                saldo_inicial=0, cuota_periodica=None,
                tasa_ea=0.39, modalidad="semanal",
                fecha_entrega=date(2026, 1, 1), n_cuotas=12,
            )

    def test_n_cuotas_cero_lanza_error(self):
        with pytest.raises(ValueError):
            generar_cronograma(
                saldo_inicial=1_000_000, cuota_periodica=None,
                tasa_ea=0.39, modalidad="semanal",
                fecha_entrega=date(2026, 1, 1), n_cuotas=0,
            )

    def test_modalidad_quincenal_14_dias(self):
        """Cuotas quincenales: 14 días entre cuotas."""
        cuotas = generar_cronograma(
            saldo_inicial=2_000_000, cuota_periodica=None,
            tasa_ea=0.39, modalidad="quincenal",
            fecha_entrega=date(2026, 1, 1), n_cuotas=6,
        )
        for i in range(1, len(cuotas)):
            fp      = date.fromisoformat(cuotas[i]["fecha_programada"])
            fp_prev = date.fromisoformat(cuotas[i-1]["fecha_programada"])
            assert (fp - fp_prev).days == 14


# ─────────────────────── BLOQUE 3 — aplicar_waterfall ────────────────────────

class TestWaterfall:
    """Orden estricto ANZI→mora→vencidas→corriente→capital. R-21."""

    HOY = date(2026, 4, 22)

    def test_anzi_2pct_primero(self):
        """ANZI = 2% del pago total, antes de todo lo demás."""
        lb = _lb()
        r = aplicar_waterfall(lb, 200_000, self.HOY)
        assert r["anzi_cobrado"] == 4_000  # 2% de 200K

    def test_anzi_calculado_sobre_pago_total(self):
        """ANZI se calcula sobre el monto bruto, no el neto."""
        lb = _lb()
        monto = 150_000
        r = aplicar_waterfall(lb, monto, self.HOY)
        assert r["anzi_cobrado"] == round(monto * 0.02)

    def test_mora_cobrada_despues_de_anzi(self):
        """Mora se deduce del saldo tras descontar ANZI."""
        lb = _lb(mora=10_000)
        r = aplicar_waterfall(lb, 200_000, self.HOY)
        assert r["mora_cobrada"] == 10_000

    def test_mora_parcial_si_no_alcanza(self):
        """Si el pago no cubre mora completa, se cobra lo que alcanza."""
        lb = _lb(mora=500_000)
        r = aplicar_waterfall(lb, 10_000, self.HOY)
        assert r["mora_cobrada"] <= 10_000 * 0.98  # solo lo que queda tras ANZI

    def test_capital_anticipado_si_sobra(self):
        """Si sobra dinero tras cubrir cuotas y mora, va a capital anticipado."""
        lb = _lb()  # sin cuotas pendientes
        r = aplicar_waterfall(lb, 200_000, self.HOY)
        assert r["capital_anticipado"] > 0

    def test_sin_cuotas_todo_capital_anticipado(self):
        """Sin cuotas pendientes: pago neto de ANZI y mora va a capital anticipado."""
        lb = _lb(mora=0)
        r = aplicar_waterfall(lb, 100_000, self.HOY)
        # anzi=2K, mora=0, sin cuotas → capital_anticipado = 98K
        assert r["capital_anticipado"] == 98_000
        assert r["mora_cobrada"] == 0

    def test_cuota_vencida_se_marca_pagada(self):
        """Cuota vencida cubierta completamente → estado = 'pagada'.

        Para que la cuota quede pagada, el pago debe superar el monto
        de la cuota más el ANZI (2% se deduce del total antes de aplicar
        a cuotas). pago = cuota / (1 - anzi_pct) garantiza que el neto
        cubre exactamente la cuota.
        """
        cuota = _cuota(1, "2026-04-08", 80_000, "vencida", monto_capital=50_000, monto_interes=30_000)
        lb = _lb(cuotas=[cuota])
        # pago neto tras ANZI debe cubrir 80K: pago = ceil(80_000 / 0.98)
        pago = 82_000  # ANZI=1640 → neto=80360 >= 80000 ✓
        r = aplicar_waterfall(lb, pago, self.HOY)
        pagadas = [c for c in r["cuotas_actualizadas"] if c["estado"] == "pagada"]
        assert len(pagadas) == 1

    def test_cuota_parcial_queda_en_parcial(self):
        """Pago que no cubre la cuota completa → estado = 'parcial'."""
        cuota = _cuota(1, "2026-04-08", 180_000, "vencida", monto_capital=100_000, monto_interes=80_000)
        lb = _lb(cuotas=[cuota])
        # Pago pequeño que no cubre la cuota
        r = aplicar_waterfall(lb, 50_000, self.HOY)
        if r["cuotas_actualizadas"]:
            assert r["cuotas_actualizadas"][0]["estado"] == "parcial"

    def test_saldo_se_reduce_tras_pago(self):
        """El saldo_capital_nuevo es menor que el saldo original."""
        cuota = _cuota(1, "2026-04-08", 100_000, "vencida", monto_capital=70_000, monto_interes=30_000)
        lb = _lb(cuotas=[cuota], saldo=9_000_000)
        r = aplicar_waterfall(lb, 200_000, self.HOY)
        assert r["saldo_capital_nuevo"] < 9_000_000

    def test_evento_payload_tiene_campos_requeridos(self):
        """El evento_payload incluye todos los campos del desglose."""
        lb = _lb()
        r = aplicar_waterfall(lb, 200_000, self.HOY)
        payload = r["evento_payload"]
        for campo in ("loanbook_codigo", "monto_total", "anzi", "mora",
                      "interes", "capital", "capital_anticipado", "saldo_capital_nuevo"):
            assert campo in payload, f"Falta campo '{campo}' en evento_payload"

    def test_pago_cero_retorna_ceros(self):
        """Pago de $0 no cambia nada."""
        lb = _lb()
        r = aplicar_waterfall(lb, 0, self.HOY)
        assert r["anzi_cobrado"] == 0
        assert r["mora_cobrada"] == 0
        assert r["capital_anticipado"] == 0

    def test_multiples_cuotas_vencidas_orden_antigüedad(self):
        """Con varias cuotas vencidas, se pagan de más antigua a más reciente."""
        c1 = _cuota(1, "2026-04-01", 80_000, "vencida", monto_capital=50_000, monto_interes=30_000)
        c2 = _cuota(2, "2026-04-08", 80_000, "vencida", monto_capital=50_000, monto_interes=30_000)
        lb = _lb(cuotas=[c2, c1])  # desordenadas intencionalmente
        pago_grande = 200_000
        r = aplicar_waterfall(lb, pago_grande, self.HOY)
        numeros = [c["numero"] for c in r["cuotas_actualizadas"]]
        # La cuota 1 (más antigua) debe aparecer primero
        if len(numeros) >= 2:
            assert numeros[0] == 1

    def test_p1s_contado_sin_cuotas_todo_capital(self):
        """P1S contado: sin cuotas pendientes, pago va todo a capital anticipado."""
        lb = _lb(cuotas=[], saldo=4_200_000, mora=0)
        r = aplicar_waterfall(lb, 4_200_000, self.HOY)
        # anzi = 84K, resto = capital anticipado
        assert r["capital_anticipado"] > 0
        assert r["anzi_cobrado"] == round(4_200_000 * 0.02)


# ─────────────────────── BLOQUE 4 — calcular_liquidacion_anticipada ──────────

class TestLiquidacionAnticipada:
    """Proyección del monto de liquidación anticipada."""

    HOY = date(2026, 4, 22)

    def _lb_con_cuotas(self, saldo=5_000_000, mora=0, dpd=0):
        return {
            "loanbook_id": "LB-LIQ-001",
            "saldo_capital": saldo,
            "mora_acumulada_cop": mora,
            "dpd": dpd,
            "cuotas": [
                _cuota(1, "2026-03-25", 100_000, "pagada"),
                _cuota(2, "2026-04-01", 100_000, "vencida", monto_capital=70_000, monto_interes=30_000),
                _cuota(3, "2026-04-08", 100_000, "pendiente", monto_capital=72_000, monto_interes=28_000),
                _cuota(4, "2026-04-15", 100_000, "pendiente", monto_capital=74_000, monto_interes=26_000),
            ],
        }

    def test_retorna_dict_con_campos_requeridos(self):
        lb = self._lb_con_cuotas()
        r = calcular_liquidacion_anticipada(lb, self.HOY)
        for campo in ("loanbook_codigo", "fecha_liquidacion", "saldo_capital",
                      "mora_acumulada", "monto_liquidacion",
                      "cuotas_pendientes_valor", "descuento_intereses_futuros"):
            assert campo in r, f"Falta campo '{campo}'"

    def test_monto_liquidacion_igual_saldo_mas_mora(self):
        """monto_liquidacion = saldo_capital + mora_acumulada."""
        lb = self._lb_con_cuotas(saldo=5_000_000, mora=20_000)
        r = calcular_liquidacion_anticipada(lb, self.HOY)
        assert r["monto_liquidacion"] == r["saldo_capital"] + r["mora_acumulada"]

    def test_saldo_cero_liquidacion_cero(self):
        lb = self._lb_con_cuotas(saldo=0, mora=0)
        r = calcular_liquidacion_anticipada(lb, self.HOY)
        assert r["monto_liquidacion"] == 0

    def test_descuento_es_no_negativo(self):
        """El descuento por pago anticipado nunca puede ser negativo."""
        lb = self._lb_con_cuotas()
        r = calcular_liquidacion_anticipada(lb, self.HOY)
        assert r["descuento_intereses_futuros"] >= 0

    def test_fecha_liquidacion_en_respuesta(self):
        lb = self._lb_con_cuotas()
        r = calcular_liquidacion_anticipada(lb, date(2026, 5, 1))
        assert r["fecha_liquidacion"] == "2026-05-01"

    def test_loanbook_codigo_en_respuesta(self):
        lb = self._lb_con_cuotas()
        r = calcular_liquidacion_anticipada(lb, self.HOY)
        assert r["loanbook_codigo"] == "LB-LIQ-001"


# ─────────────────────── BLOQUE 5 — Constantes ───────────────────────────────

class TestConstantes:
    def test_mora_cop_por_dia_es_2000(self):
        """R-22: mora $2.000 COP/día. No cambiar sin autorización."""
        assert MORA_COP_POR_DIA == 2_000
