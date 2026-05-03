"""
tests/test_motor.py — Tests del motor unificado del Loanbook.

Casos basados en el Excel oficial RODDOS_Loanbooks_V1 (43 créditos reales) +
los invariantes del LOANBOOK_MAESTRO_v1.1.

Estructura:
    1. Tests de crear_cronograma (cronograma inmutable después de activar)
    2. Tests de aplicar_pago (waterfall §4.1 del MAESTRO)
    3. Tests de derivar_estado (saldos, dpd, sub_bucket, estado canónico)
    4. Tests de auditar (detección de divergencias)
    5. Tests de invariantes del sistema (no fechas futuras, no exceder saldo, etc.)
"""
import pytest
from datetime import date, timedelta


# ════════════════════════════════════════════════════════════════════════════
# 1. CREAR_CRONOGRAMA
# ════════════════════════════════════════════════════════════════════════════


class TestCrearCronograma:
    """Genera cronograma respetando fecha_primer_pago arbitraria + intervalo modal."""

    def test_p52s_semanal_raider_LB01(self):
        """LB-01 Chenier: entrega jueves, primer pago miércoles siguiente (gap 6d)."""
        from services.loanbook.motor import crear_cronograma

        cronograma = crear_cronograma(
            fecha_primer_pago=date(2026, 3, 11),
            num_cuotas=52,
            cuota_valor=179_900,
            modalidad="semanal",
            capital_plan=7_800_000,
            cuota_estandar_plan=179_900,
        )
        assert len(cronograma) == 52
        assert cronograma[0]["fecha"] == "2026-03-11"
        assert cronograma[0]["monto"] == 179_900
        # Fechas separadas por 7 días
        assert cronograma[1]["fecha"] == "2026-03-18"
        assert cronograma[2]["fecha"] == "2026-03-25"
        # Última cuota
        assert cronograma[51]["fecha"] == "2027-03-03"
        # Desglose canónico: capital × num_cuotas = capital_plan
        suma_capital = sum(c["monto_capital"] for c in cronograma)
        assert abs(suma_capital - 7_800_000) <= 52  # tolerancia redondeo
        # capital + interes = monto en cada cuota
        for c in cronograma:
            assert abs((c["monto_capital"] + c["monto_interes"]) - c["monto"]) <= 1

    def test_p78s_sport_semanal_LB02_gap_cero(self):
        """LB-02 Jose Altamiranda: entrega y primer pago el MISMO día (gap 0d)."""
        from services.loanbook.motor import crear_cronograma

        cronograma = crear_cronograma(
            fecha_primer_pago=date(2026, 3, 5),  # jueves, mismo día entrega
            num_cuotas=78,
            cuota_valor=130_000,
            modalidad="semanal",
            capital_plan=5_750_000,
            cuota_estandar_plan=130_000,
        )
        assert len(cronograma) == 78
        assert cronograma[0]["fecha"] == "2026-03-05"
        # Cada miércoles? NO — debe ser jueves porque ese día eligió el operador
        assert date.fromisoformat(cronograma[0]["fecha"]).weekday() == 3  # jueves
        assert date.fromisoformat(cronograma[1]["fecha"]).weekday() == 3
        # Suma capital ~ capital_plan
        suma_capital = sum(c["monto_capital"] for c in cronograma)
        assert abs(suma_capital - 5_750_000) <= 78

    def test_p39s_quincenal_LB07_dia_martes(self):
        """LB-07 Moises Ascanio: quincenal, primer pago martes 2026-03-24 (gap 19d)."""
        from services.loanbook.motor import crear_cronograma

        cronograma = crear_cronograma(
            fecha_primer_pago=date(2026, 3, 24),  # martes
            num_cuotas=20,  # P39S quincenal = 20 cuotas
            cuota_valor=350_000,
            modalidad="quincenal",
            capital_plan=5_750_000,  # Sport
            cuota_estandar_plan=350_000,
        )
        assert len(cronograma) == 20
        assert cronograma[0]["fecha"] == "2026-03-24"
        assert cronograma[1]["fecha"] == "2026-04-07"  # +14 días
        # Todas en martes
        for c in cronograma:
            assert date.fromisoformat(c["fecha"]).weekday() == 1  # martes

    def test_intervalo_modalidad_semanal_7_dias(self):
        from services.loanbook.motor import crear_cronograma
        cronograma = crear_cronograma(
            fecha_primer_pago=date(2026, 5, 6),
            num_cuotas=10,
            cuota_valor=100_000,
            modalidad="semanal",
            capital_plan=900_000,
            cuota_estandar_plan=100_000,
        )
        for i in range(1, 10):
            d_prev = date.fromisoformat(cronograma[i-1]["fecha"])
            d_curr = date.fromisoformat(cronograma[i]["fecha"])
            assert (d_curr - d_prev).days == 7

    def test_intervalo_modalidad_quincenal_14_dias(self):
        from services.loanbook.motor import crear_cronograma
        cronograma = crear_cronograma(
            fecha_primer_pago=date(2026, 5, 6),
            num_cuotas=10,
            cuota_valor=200_000,
            modalidad="quincenal",
            capital_plan=1_800_000,
            cuota_estandar_plan=200_000,
        )
        for i in range(1, 10):
            d_prev = date.fromisoformat(cronograma[i-1]["fecha"])
            d_curr = date.fromisoformat(cronograma[i]["fecha"])
            assert (d_curr - d_prev).days == 14

    def test_intervalo_modalidad_mensual_28_dias(self):
        from services.loanbook.motor import crear_cronograma
        cronograma = crear_cronograma(
            fecha_primer_pago=date(2026, 5, 6),
            num_cuotas=12,
            cuota_valor=400_000,
            modalidad="mensual",
            capital_plan=4_000_000,
            cuota_estandar_plan=400_000,
        )
        for i in range(1, 12):
            d_prev = date.fromisoformat(cronograma[i-1]["fecha"])
            d_curr = date.fromisoformat(cronograma[i]["fecha"])
            assert (d_curr - d_prev).days == 28

    def test_p1s_contado_no_genera_cronograma(self):
        """P1S contado tiene num_cuotas=0 → cronograma vacío."""
        from services.loanbook.motor import crear_cronograma
        cronograma = crear_cronograma(
            fecha_primer_pago=date(2026, 5, 1),
            num_cuotas=0,
            cuota_valor=0,
            modalidad="semanal",
            capital_plan=300_000,
            cuota_estandar_plan=0,
        )
        assert cronograma == []

    def test_cuotas_inicializadas_pendiente(self):
        """Cada cuota nace en estado pendiente con monto_pagado=0."""
        from services.loanbook.motor import crear_cronograma
        cronograma = crear_cronograma(
            fecha_primer_pago=date(2026, 5, 6),
            num_cuotas=5,
            cuota_valor=100_000,
            modalidad="semanal",
            capital_plan=450_000,
            cuota_estandar_plan=100_000,
        )
        for c in cronograma:
            assert c["estado"] == "pendiente"
            assert c["monto_pagado"] == 0
            assert c["fecha_pago"] is None


# ════════════════════════════════════════════════════════════════════════════
# 2. APLICAR_PAGO — waterfall canónico §4.1
# ════════════════════════════════════════════════════════════════════════════


def _lb_basico(estado="al_dia", cuotas_pagadas=0):
    """Helper: LB Raider P52S con N cuotas pagadas."""
    cuotas = []
    for i in range(1, 53):
        cuotas.append({
            "numero": i,
            "fecha": (date(2026, 3, 11) + timedelta(days=7 * (i - 1))).isoformat(),
            "monto": 179_900,
            "monto_capital": 150_000,
            "monto_interes": 29_900,
            "estado": "pagada" if i <= cuotas_pagadas else "pendiente",
            "monto_pagado": 179_900 if i <= cuotas_pagadas else 0,
            "fecha_pago": "2026-03-11" if i <= cuotas_pagadas else None,
            "mora_acumulada": 0,
        })
    return {
        "loanbook_id": "LB-2026-0001",
        "cliente": {"nombre": "Test", "cedula": "1283367"},
        "plan_codigo": "P52S",
        "modalidad": "semanal",
        "modelo": "Raider 125",
        "fecha_entrega": "2026-03-05",
        "fecha_primer_pago": "2026-03-11",
        "cuota_valor": 179_900,
        "cuota_estandar_plan": 179_900,
        "num_cuotas": 52,
        "capital_plan": 7_800_000,
        "valor_total": 9_354_800,
        "estado": estado,
        "cuotas": cuotas,
    }


class TestAplicarPago:
    """Aplica waterfall §4.1 del MAESTRO: ANZI 2% → mora → cuota corriente → abono."""

    def test_pago_exacto_cuota_sin_mora(self):
        from services.loanbook.motor import aplicar_pago
        lb = _lb_basico(cuotas_pagadas=0)
        resultado = aplicar_pago(lb, monto=179_900, fecha_pago=date(2026, 3, 11), cuota_numero=1)
        assert resultado["distribucion"]["anzi"] == 3_598  # 2% de 179.900
        # 179.900 - 3.598 = 176.302 disponible para mora+interes+capital
        # mora = 0 (no hay mora)
        # interes_cuota = 29.900
        # capital_cuota = 150.000
        # abono_extra absorbe el resto: 176.302 - 29.900 - 150.000 = -3.598... no alcanza
        # Aquí hay tensión entre "ANZI 2% del pago bruto" y "cuota = capital + interes" cuando el cliente paga exactamente la cuota
        # MAESTRO §4.1 dice ANZI primero del pago — entonces el cliente paga 179.900 pero cubre menos cuota
        # Verificamos que la cuota queda parcialmente pagada
        assert resultado["distribucion"]["interes"] == 29_900
        assert resultado["distribucion"]["mora"] == 0
        # Lo que queda para capital: 179.900 - 3.598 - 29.900 = 146.402
        assert resultado["distribucion"]["capital"] == 146_402
        # Total cubierto = 179.900 (todo el pago se aplicó)
        suma = (
            resultado["distribucion"]["anzi"]
            + resultado["distribucion"]["mora"]
            + resultado["distribucion"]["interes"]
            + resultado["distribucion"]["capital"]
            + resultado["distribucion"]["abono_capital"]
        )
        assert suma == 179_900

    def test_pago_con_mora_acumulada(self):
        """Cliente debe $30K de mora + cuota $179.900. Paga $200K."""
        from services.loanbook.motor import aplicar_pago
        lb = _lb_basico(cuotas_pagadas=0)
        # Marcar la cuota 1 con mora
        lb["cuotas"][0]["mora_acumulada"] = 30_000

        resultado = aplicar_pago(lb, monto=200_000, fecha_pago=date(2026, 3, 25), cuota_numero=1)
        # ANZI 2% de 200K = 4.000
        assert resultado["distribucion"]["anzi"] == 4_000
        # Mora: 30K
        assert resultado["distribucion"]["mora"] == 30_000
        # Interes: 29.900
        assert resultado["distribucion"]["interes"] == 29_900
        # Capital: 200K - 4K - 30K - 29.9K = 136.100
        assert resultado["distribucion"]["capital"] == 136_100
        # Suma total = pago
        suma = sum(resultado["distribucion"].values())
        assert suma == 200_000

    def test_pago_con_sobrante_va_a_abono_capital(self):
        """Cliente paga más que cuota → sobrante a abono_capital_anticipado."""
        from services.loanbook.motor import aplicar_pago
        lb = _lb_basico(cuotas_pagadas=0)

        resultado = aplicar_pago(lb, monto=300_000, fecha_pago=date(2026, 3, 11), cuota_numero=1)
        # ANZI 2% de 300K = 6.000
        # Mora 0
        # Interes 29.900
        # Capital cuota 150.000
        # Sobrante 300K - 6K - 29.9K - 150K = 114.100 → abono_capital
        assert resultado["distribucion"]["anzi"] == 6_000
        assert resultado["distribucion"]["interes"] == 29_900
        assert resultado["distribucion"]["capital"] == 150_000
        assert resultado["distribucion"]["abono_capital"] == 114_100

    def test_cuota_marcada_pagada_si_cubre_capital_e_interes(self):
        """Para cubrir cuota completa con ANZI primero, cliente paga $183.572.
        El monto_pagado de la CUOTA refleja solo lo aplicado a interés+capital
        (179.900); el ANZI ($3.672) va al bucket separado total_anzi_pagado."""
        from services.loanbook.motor import aplicar_pago
        lb = _lb_basico(cuotas_pagadas=0)
        resultado = aplicar_pago(lb, monto=183_572, fecha_pago=date(2026, 3, 11), cuota_numero=1)
        cuota = resultado["loanbook"]["cuotas"][0]
        assert cuota["estado"] == "pagada"
        # monto_pagado de la cuota = interés + capital aplicados
        assert cuota["monto_pagado"] == 179_900
        # ANZI va a bucket separado
        assert cuota["anzi_pagado"] == round(183_572 * 0.02)
        # Bucket persistente del LB
        assert resultado["loanbook"]["total_anzi_pagado"] == round(183_572 * 0.02)

    def test_pago_a_cuota_None_aplica_a_primera_pendiente(self):
        from services.loanbook.motor import aplicar_pago
        lb = _lb_basico(cuotas_pagadas=2)
        resultado = aplicar_pago(lb, monto=183_572, fecha_pago=date(2026, 3, 25), cuota_numero=None)
        # Debe haber aplicado a la cuota #3 (primera pendiente)
        cuota3 = resultado["loanbook"]["cuotas"][2]
        assert cuota3["estado"] == "pagada"

    def test_rechaza_fecha_futura(self):
        """fecha_pago > hoy → ValueError (regla R-07)."""
        from services.loanbook.motor import aplicar_pago
        lb = _lb_basico()
        from core.datetime_utils import today_bogota
        manana = today_bogota() + timedelta(days=1)
        with pytest.raises(ValueError, match="futuro|future"):
            aplicar_pago(lb, monto=100_000, fecha_pago=manana, cuota_numero=1)

    def test_rechaza_pago_a_credito_pendiente_entrega(self):
        """LB en pendiente_entrega no acepta pagos."""
        from services.loanbook.motor import aplicar_pago
        lb = _lb_basico(estado="pendiente_entrega")
        # Sin cuotas
        lb["cuotas"] = []
        with pytest.raises(ValueError, match="pendiente_entrega|cronograma"):
            aplicar_pago(lb, monto=100_000, fecha_pago=date(2026, 3, 11), cuota_numero=1)

    def test_rechaza_pago_a_saldado(self):
        from services.loanbook.motor import aplicar_pago
        lb = _lb_basico(estado="saldado", cuotas_pagadas=52)
        with pytest.raises(ValueError, match="saldado|cerrado"):
            aplicar_pago(lb, monto=100_000, fecha_pago=date(2026, 4, 15), cuota_numero=1)


# ════════════════════════════════════════════════════════════════════════════
# 3. DERIVAR_ESTADO — saldos, dpd, sub_bucket, estado
# ════════════════════════════════════════════════════════════════════════════


class TestDerivarEstado:
    """Recalcula derivados sin tocar cronograma. Idempotente."""

    def test_lb01_chenier_6_cuotas_pagadas_saldo_correcto(self):
        """LB-01 Excel: 6 cuotas pagadas → saldo $8.275.400 (Σ 46 cuotas pendientes)."""
        from services.loanbook.motor import derivar_estado
        lb = _lb_basico(cuotas_pagadas=6)
        r = derivar_estado(lb, hoy=date(2026, 4, 30))
        # saldo_pendiente = 46 cuotas × 179.900 = 8.275.400
        assert r["saldo_pendiente"] == 8_275_400
        # cuotas_pagadas derivado
        assert r["cuotas_pagadas"] == 6

    def test_estado_saldado_si_todas_pagadas(self):
        from services.loanbook.motor import derivar_estado
        lb = _lb_basico(cuotas_pagadas=52)
        r = derivar_estado(lb, hoy=date(2027, 4, 1))
        assert r["estado"] == "saldado"
        assert r["saldo_pendiente"] == 0

    def test_dpd_canonico_cero_si_al_dia(self):
        """Si la última cuota pagada coincide con hoy o futuro, dpd=0."""
        from services.loanbook.motor import derivar_estado
        lb = _lb_basico(cuotas_pagadas=2)
        # Hoy es la fecha de la cuota 3
        hoy = date(2026, 3, 25)  # cuota 3 vence hoy
        r = derivar_estado(lb, hoy=hoy)
        assert r["dpd"] == 0
        assert r["estado"] == "al_dia"

    def test_dpd_15_clasifica_mora_grave_v11(self):
        """MAESTRO v1.1: DPD 15-45 → Late Delinquency = mora_grave (opción B)."""
        from services.loanbook.motor import derivar_estado
        lb = _lb_basico(cuotas_pagadas=0)
        # cuota 1 vence 2026-03-11; hoy 2026-03-26 → dpd 15
        r = derivar_estado(lb, hoy=date(2026, 3, 26))
        assert r["dpd"] == 15
        assert r["estado"] == "mora_grave"
        assert r["sub_bucket"] == "Alert"  # 15-21

    def test_dpd_46_clasifica_default_v11(self):
        """MAESTRO v1.1: DPD 46-49 → Default."""
        from services.loanbook.motor import derivar_estado
        lb = _lb_basico(cuotas_pagadas=0)
        # cuota 1 vence 2026-03-11; +46 días = 2026-04-26
        r = derivar_estado(lb, hoy=date(2026, 4, 26))
        assert r["dpd"] == 46
        assert r["estado"] == "default"
        assert r["sub_bucket"] == "Pre-default"

    def test_dpd_50_clasifica_castigado_v11(self):
        """MAESTRO v1.1: DPD 50+ → Charge-Off = castigado."""
        from services.loanbook.motor import derivar_estado
        lb = _lb_basico(cuotas_pagadas=0)
        r = derivar_estado(lb, hoy=date(2026, 4, 30))
        # cuota 1 vence 2026-03-11; +50 días = 2026-04-30
        assert r["dpd"] == 50
        assert r["estado"] == "castigado"
        assert r["sub_bucket"] == "Default"

    def test_mora_acumulada_2k_por_dia(self):
        from services.loanbook.motor import derivar_estado
        lb = _lb_basico(cuotas_pagadas=0)
        # 14 días de atraso
        r = derivar_estado(lb, hoy=date(2026, 3, 25))
        assert r["dpd"] == 14
        assert r["mora_acumulada_cop"] == 28_000  # 14 × 2.000

    def test_idempotencia(self):
        from services.loanbook.motor import derivar_estado
        lb = _lb_basico(cuotas_pagadas=3)
        r1 = derivar_estado(lb, hoy=date(2026, 4, 30))
        r2 = derivar_estado(r1, hoy=date(2026, 4, 30))
        for k in ["saldo_pendiente", "dpd", "estado", "sub_bucket", "cuotas_pagadas", "mora_acumulada_cop"]:
            assert r1.get(k) == r2.get(k), f"campo {k} no idempotente: {r1.get(k)} vs {r2.get(k)}"

    def test_no_toca_cronograma(self):
        """derivar_estado NO debe modificar fechas ni montos del cronograma."""
        from services.loanbook.motor import derivar_estado
        import copy
        lb = _lb_basico(cuotas_pagadas=2)
        cronograma_original = copy.deepcopy(lb["cuotas"])
        r = derivar_estado(lb, hoy=date(2026, 4, 30))
        for c_orig, c_new in zip(cronograma_original, r["cuotas"]):
            assert c_orig["fecha"] == c_new["fecha"]
            assert c_orig["monto"] == c_new["monto"]
            assert c_orig["monto_capital"] == c_new["monto_capital"]
            assert c_orig["monto_interes"] == c_new["monto_interes"]


# ════════════════════════════════════════════════════════════════════════════
# 4. AUDITAR — divergencias persistido vs canónico
# ════════════════════════════════════════════════════════════════════════════


class TestAuditar:

    def test_lb_correcto_no_violaciones(self):
        from services.loanbook.motor import auditar, derivar_estado
        lb = derivar_estado(_lb_basico(cuotas_pagadas=3), hoy=date(2026, 4, 8))
        a = auditar(lb, hoy=date(2026, 4, 8))
        assert a["ok"] is True
        assert a["severidad"] == "verde"
        assert a["violaciones"] == []

    def test_lb_con_saldo_inflado_detecta_amarilla(self):
        from services.loanbook.motor import auditar
        lb = _lb_basico(cuotas_pagadas=3)
        lb["saldo_pendiente"] = 99_999_999  # bug
        a = auditar(lb, hoy=date(2026, 4, 8))
        assert a["ok"] is False
        campos = [v["campo"] for v in a["violaciones"]]
        assert "saldo_pendiente" in campos

    def test_lb_pendiente_entrega_sin_cronograma_es_verde(self):
        """LB recién creado por factura está en pendiente_entrega sin cuotas — eso es válido."""
        from services.loanbook.motor import auditar
        lb = _lb_basico(estado="pendiente_entrega")
        lb["cuotas"] = []
        a = auditar(lb, hoy=date(2026, 4, 30))
        assert a["ok"] is True


# ════════════════════════════════════════════════════════════════════════════
# 5. INVARIANTES DEL SISTEMA
# ════════════════════════════════════════════════════════════════════════════


class TestInvariantes:

    def test_capital_mas_interes_iguala_monto_en_cada_cuota(self):
        from services.loanbook.motor import crear_cronograma
        cronograma = crear_cronograma(
            fecha_primer_pago=date(2026, 3, 11),
            num_cuotas=52,
            cuota_valor=179_900,
            modalidad="semanal",
            capital_plan=7_800_000,
            cuota_estandar_plan=179_900,
        )
        for c in cronograma:
            diff = abs((c["monto_capital"] + c["monto_interes"]) - c["monto"])
            assert diff <= 1, f"Cuota {c['numero']}: capital+interes={c['monto_capital']+c['monto_interes']} vs monto={c['monto']}"

    def test_saldo_nunca_negativo(self):
        from services.loanbook.motor import derivar_estado
        lb = _lb_basico(cuotas_pagadas=52)
        r = derivar_estado(lb, hoy=date(2027, 4, 1))
        assert r["saldo_pendiente"] >= 0

    def test_dpd_nunca_negativo(self):
        from services.loanbook.motor import derivar_estado
        lb = _lb_basico(cuotas_pagadas=0)
        r = derivar_estado(lb, hoy=date(2026, 3, 1))  # antes de la primera cuota
        assert r["dpd"] == 0  # ni negativo, ni futuro

    def test_suma_pagos_no_excede_valor_total(self):
        """No se puede pagar más que el valor_total del crédito."""
        from services.loanbook.motor import aplicar_pago
        lb = _lb_basico(cuotas_pagadas=0)
        # Simulamos que el cliente paga $20M (el doble del valor_total)
        try:
            r = aplicar_pago(lb, monto=20_000_000, fecha_pago=date(2026, 3, 11), cuota_numero=1)
            distribucion = r["distribucion"]
            capital_total = distribucion["capital"] + distribucion["abono_capital"]
            assert capital_total <= 7_800_000
        except ValueError:
            pass



# ════════════════════════════════════════════════════════════════════════════
# 6. CUOTA INICIAL (CUOTA 0) — RODDOS V2.1
# ════════════════════════════════════════════════════════════════════════════


class TestCuotaInicial:
    """Cuota 0 = pago inicial pactado. Sin waterfall ANZI/mora. Suma a valor_total."""

    def test_cuota_inicial_se_inserta_como_cuota_0(self):
        """Si cuota_inicial > 0, se inserta cuota 0 al inicio del cronograma."""
        from services.loanbook.motor import crear_cronograma
        cronograma = crear_cronograma(
            fecha_primer_pago=date(2026, 5, 6),
            num_cuotas=39,
            cuota_valor=210_000,
            modalidad="semanal",
            capital_plan=7_800_000,
            cuota_estandar_plan=210_000,
            cuota_inicial=1_460_000,
            fecha_cuota_inicial=date(2026, 4, 30),
        )
        # Total: 1 cuota 0 + 39 regulares = 40 entries
        assert len(cronograma) == 40
        # Primera entry es cuota 0
        c0 = cronograma[0]
        assert c0["numero"] == 0
        assert c0["monto"] == 1_460_000
        assert c0["monto_capital"] == 1_460_000
        assert c0["monto_interes"] == 0
        assert c0["estado"] == "pendiente"
        assert c0["es_cuota_inicial"] is True
        assert c0["fecha"] == "2026-04-30"
        # Cuotas regulares siguen numeradas 1..39
        assert cronograma[1]["numero"] == 1
        assert cronograma[1]["fecha"] == "2026-05-06"
        assert cronograma[39]["numero"] == 39

    def test_cuota_inicial_cero_no_genera_cuota_0(self):
        """Si cuota_inicial = 0 (caso aceleración comercial), cronograma sin cuota 0."""
        from services.loanbook.motor import crear_cronograma
        cronograma = crear_cronograma(
            fecha_primer_pago=date(2026, 5, 6),
            num_cuotas=39,
            cuota_valor=210_000,
            modalidad="semanal",
            capital_plan=7_800_000,
            cuota_estandar_plan=210_000,
            cuota_inicial=0,
        )
        # Solo 39 cuotas regulares, sin cuota 0
        assert len(cronograma) == 39
        assert cronograma[0]["numero"] == 1
        # Ninguna cuota es es_cuota_inicial
        for c in cronograma:
            assert c.get("es_cuota_inicial", False) is False

    def test_aplicar_pago_a_cuota_0_sin_waterfall(self):
        """Pago a cuota 0: NO aplica ANZI 2%, NO aplica mora — todo va a capital."""
        from services.loanbook.motor import crear_cronograma, aplicar_pago

        # Crear LB con cuota inicial pactada
        cronograma = crear_cronograma(
            fecha_primer_pago=date(2026, 5, 6),
            num_cuotas=39,
            cuota_valor=210_000,
            modalidad="semanal",
            capital_plan=7_800_000,
            cuota_estandar_plan=210_000,
            cuota_inicial=1_460_000,
            fecha_cuota_inicial=date(2026, 4, 30),
        )
        lb = {
            "loanbook_id": "LB-TEST-INICIAL",
            "cliente": {"nombre": "Test Cuota Inicial"},
            "estado": "al_dia",
            "valor_total": sum(c["monto"] for c in cronograma),
            "cuotas": cronograma,
        }
        # Cliente paga la cuota inicial completa
        result = aplicar_pago(lb, monto=1_460_000, fecha_pago=date(2026, 4, 30), cuota_numero=0)
        d = result["distribucion"]
        # ANZI = 0, mora = 0, interes = 0 (no aplica waterfall a cuota 0)
        assert d["anzi"] == 0, f"ANZI debe ser 0 en cuota 0, fue {d['anzi']}"
        assert d["mora"] == 0
        assert d["interes"] == 0
        # Todo al capital
        assert d["capital"] == 1_460_000
        assert d["abono_capital"] == 0
        assert d["no_aplicado"] == 0
        # Cuota 0 marcada pagada
        cuota_0 = result["loanbook"]["cuotas"][0]
        assert cuota_0["numero"] == 0
        assert cuota_0["estado"] == "pagada"
        assert cuota_0["monto_pagado"] == 1_460_000

    def test_valor_total_incluye_cuota_inicial(self):
        """valor_total = cuota_inicial + (cuota_valor × num_cuotas)."""
        from services.loanbook.motor import crear_cronograma, derivar_estado
        cronograma = crear_cronograma(
            fecha_primer_pago=date(2026, 5, 6),
            num_cuotas=39,
            cuota_valor=210_000,
            modalidad="semanal",
            capital_plan=7_800_000,
            cuota_estandar_plan=210_000,
            cuota_inicial=1_460_000,
            fecha_cuota_inicial=date(2026, 4, 30),
        )
        # Suma de todas las cuotas (con cuota 0)
        suma_total = sum(c["monto"] for c in cronograma)
        # Esperado: 1.460.000 + 39 * 210.000 = 1.460.000 + 8.190.000 = 9.650.000
        assert suma_total == 9_650_000

        # Verificar via derivar_estado
        lb = {
            "loanbook_id": "LB-TEST-VT",
            "cliente": {"nombre": "Test"},
            "estado": "al_dia",
            "valor_total": suma_total,
            "cuotas": cronograma,
        }
        r = derivar_estado(lb, hoy=date(2026, 5, 1))
        assert r["saldo_pendiente"] == 9_650_000  # nada pagado todavia
        assert r["total_pagado"] == 0

    def test_dpd_no_se_genera_por_cuota_0_vencida(self):
        """Si solo la cuota 0 está vencida, dpd debe ser 0 (no genera mora).

        Política RODDOS: la cuota inicial puede quedar pendiente sin mover al
        cliente a estado de mora — se cobra aparte segun politica comercial.
        """
        from services.loanbook.motor import crear_cronograma, derivar_estado
        cronograma = crear_cronograma(
            fecha_primer_pago=date(2026, 5, 13),  # cuotas regulares en futuro
            num_cuotas=39,
            cuota_valor=210_000,
            modalidad="semanal",
            capital_plan=7_800_000,
            cuota_estandar_plan=210_000,
            cuota_inicial=1_460_000,
            fecha_cuota_inicial=date(2026, 4, 30),  # cuota 0 vencida hace 6 dias
        )
        lb = {
            "loanbook_id": "LB-TEST-CI-VENCIDA",
            "cliente": {"nombre": "Test"},
            "estado": "al_dia",
            "valor_total": sum(c["monto"] for c in cronograma),
            "cuotas": cronograma,
        }
        # Hoy 2026-05-06: cuota 0 vencida hace 6 dias, cuotas regulares aun no vencen
        r = derivar_estado(lb, hoy=date(2026, 5, 6))
        # DPD debe ser 0 — cuota 0 NO genera mora ni mueve estado
        assert r["dpd"] == 0
        assert r["estado"] == "al_dia"
        assert r["mora_acumulada_cop"] == 0
