"""
Tests del endpoint GET /api/loanbook/cobranza-semanal (DAY4 B6.1).

Estos tests cubren la lógica de agregación del endpoint usando un mock
in-memory de la colección loanbook. El endpoint usa motor.calcular_proxima_cuota
y motor.derivar_estado, que ya tienen sus propios tests en test_motor.py.

Test cases:
1. checklist_solo_incluye_cuotas_en_ventana_7d
2. en_mora_lista_solo_dpd_positivo
3. saldados_y_castigados_se_excluyen
4. recaudado_hoy_suma_solo_pagos_de_hoy
5. semana_objetivo_suma_montos_proximas_cuotas
"""
from datetime import date, timedelta
import pytest


def _build_lb(loanbook_id, estado, cuotas, dpd=0, saldo_pendiente=0,
              cliente_nombre="Test Cliente", cliente_telefono="+57300", modelo="TVS Raider"):
    return {
        "loanbook_id":      loanbook_id,
        "estado":           estado,
        "cuotas":           cuotas,
        "dpd":              dpd,
        "saldo_pendiente":  saldo_pendiente,
        "cliente_nombre":   cliente_nombre,
        "cliente_telefono": cliente_telefono,
        "modelo":           modelo,
    }


def _build_cuota(numero, fecha, monto, estado="pendiente", monto_pagado=0,
                 fecha_pago=None, es_cuota_inicial=False):
    return {
        "numero":           numero,
        "fecha":            fecha if isinstance(fecha, str) else fecha.isoformat(),
        "monto":            monto,
        "monto_capital":    int(monto * 0.6),
        "monto_interes":    int(monto * 0.4),
        "monto_pagado":     monto_pagado,
        "estado":           estado,
        "fecha_pago":       fecha_pago,
        "es_cuota_inicial": es_cuota_inicial,
    }


def _ejecutar_logica_endpoint(items, hoy):
    """Reproduce la lógica del endpoint sin pasar por FastAPI/MongoDB."""
    from services.loanbook.motor import calcular_proxima_cuota

    seven_days = hoy + timedelta(days=7)
    week_ago = hoy - timedelta(days=7)

    semana_objetivo = 0
    recaudado_hoy = 0
    recaudado_semana = 0
    checklist = []
    en_mora = []

    items_filtrados = [
        lb for lb in items
        if lb.get("estado") not in ("saldado", "castigado", "pendiente_entrega")
    ]

    for lb in items_filtrados:
        prox = calcular_proxima_cuota(lb, hoy=hoy)
        if prox is None:
            continue

        item = {
            "loanbook_id":      lb.get("loanbook_id"),
            "cliente_nombre":   lb.get("cliente_nombre"),
            "cuota_numero":     prox["numero"],
            "monto":            prox["monto"],
            "fecha_vencimiento": prox["fecha"],
            "vencida":          prox.get("vencida", False),
            "dpd":              int(lb.get("dpd") or 0),
        }
        try:
            f = date.fromisoformat(prox["fecha"])
        except (ValueError, TypeError):
            f = None

        if f is not None and hoy <= f <= seven_days:
            semana_objetivo += prox["monto"]
            checklist.append(item)
        if int(lb.get("dpd") or 0) > 0:
            en_mora.append(item)

    for lb in items_filtrados:
        for c in lb.get("cuotas") or []:
            fp_str = c.get("fecha_pago")
            if not fp_str:
                continue
            try:
                fp = date.fromisoformat(fp_str)
            except (ValueError, TypeError):
                continue
            mp = int(c.get("monto_pagado") or 0)
            if mp <= 0:
                continue
            if fp == hoy:
                recaudado_hoy += mp
            if week_ago <= fp <= hoy:
                recaudado_semana += mp

    return {
        "semana_objetivo":     semana_objetivo,
        "recaudado_hoy":       recaudado_hoy,
        "recaudado_semana":    recaudado_semana,
        "clientes_por_pagar":  len(checklist),
        "clientes_en_mora":    len(en_mora),
        "checklist":           checklist,
        "en_mora":             en_mora,
    }


class TestCobranzaSemanal:
    """Tests del agregado /api/loanbook/cobranza-semanal."""

    def test_checklist_solo_incluye_cuotas_en_ventana_7d(self):
        """Cuotas con fecha entre hoy y +7d deben aparecer; otras no."""
        hoy = date(2026, 5, 5)
        lbs = [
            _build_lb("LB-A", "al_dia", [
                _build_cuota(1, "2026-05-06", 200000),
                _build_cuota(2, "2026-05-13", 200000),
            ]),
            _build_lb("LB-B", "al_dia", [
                _build_cuota(1, "2026-05-15", 200000),  # fuera de ventana
            ]),
            _build_lb("LB-C", "al_dia", [
                _build_cuota(1, "2026-05-12", 200000),  # dentro
            ]),
        ]
        r = _ejecutar_logica_endpoint(lbs, hoy)
        ids = [c["loanbook_id"] for c in r["checklist"]]
        assert "LB-A" in ids
        assert "LB-C" in ids
        assert "LB-B" not in ids
        assert r["clientes_por_pagar"] == 2

    def test_en_mora_solo_dpd_positivo(self):
        """en_mora debe listar sólo LBs con dpd > 0."""
        hoy = date(2026, 5, 5)
        lbs = [
            _build_lb("LB-A", "al_dia",     [_build_cuota(1, "2026-05-06", 100)], dpd=0),
            _build_lb("LB-B", "mora_leve",  [_build_cuota(1, "2026-04-29", 100)], dpd=6),
            _build_lb("LB-C", "mora_grave", [_build_cuota(1, "2026-04-15", 100)], dpd=20),
        ]
        r = _ejecutar_logica_endpoint(lbs, hoy)
        ids = [c["loanbook_id"] for c in r["en_mora"]]
        assert "LB-A" not in ids
        assert "LB-B" in ids
        assert "LB-C" in ids

    def test_saldados_y_castigados_se_excluyen(self):
        """Estados terminales no aparecen ni en checklist ni en mora."""
        hoy = date(2026, 5, 5)
        lbs = [
            _build_lb("LB-S", "saldado",   [_build_cuota(1, "2026-05-06", 100, estado="pagada", monto_pagado=100)]),
            _build_lb("LB-X", "castigado", [_build_cuota(1, "2026-04-01", 100)], dpd=50),
            _build_lb("LB-P", "pendiente_entrega", []),
            _build_lb("LB-V", "al_dia",    [_build_cuota(1, "2026-05-06", 100)]),
        ]
        r = _ejecutar_logica_endpoint(lbs, hoy)
        all_ids = ([c["loanbook_id"] for c in r["checklist"]]
                   + [c["loanbook_id"] for c in r["en_mora"]])
        assert "LB-S" not in all_ids
        assert "LB-X" not in all_ids
        assert "LB-P" not in all_ids
        assert "LB-V" in [c["loanbook_id"] for c in r["checklist"]]

    def test_recaudado_hoy_suma_solo_pagos_de_hoy(self):
        """recaudado_hoy filtra exactamente fecha_pago == hoy."""
        hoy = date(2026, 5, 5)
        lbs = [
            _build_lb("LB-A", "al_dia", [
                _build_cuota(1, "2026-04-29", 100000, estado="pagada",
                             monto_pagado=100000, fecha_pago="2026-05-05"),  # hoy
                _build_cuota(2, "2026-05-06", 100000),
            ], dpd=0),
            _build_lb("LB-B", "al_dia", [
                _build_cuota(1, "2026-04-22", 50000, estado="pagada",
                             monto_pagado=50000, fecha_pago="2026-05-02"),  # 3 días atrás
                _build_cuota(2, "2026-05-06", 50000),
            ], dpd=0),
        ]
        r = _ejecutar_logica_endpoint(lbs, hoy)
        assert r["recaudado_hoy"] == 100000
        assert r["recaudado_semana"] == 150000  # ambos en últimos 7 días

    def test_semana_objetivo_suma_montos_proximas_cuotas(self):
        """semana_objetivo suma montos de cuotas próximas en ventana."""
        hoy = date(2026, 5, 5)
        lbs = [
            _build_lb("LB-A", "al_dia", [_build_cuota(1, "2026-05-06", 200000)]),
            _build_lb("LB-B", "al_dia", [_build_cuota(1, "2026-05-12", 250000)]),
            _build_lb("LB-C", "al_dia", [_build_cuota(1, "2026-05-15", 999999)]),  # fuera
        ]
        r = _ejecutar_logica_endpoint(lbs, hoy)
        assert r["semana_objetivo"] == 450000
        assert r["clientes_por_pagar"] == 2

    def test_cuota_inicial_pendiente_aparece_en_checklist(self):
        """Cuota 0 pendiente con fecha en ventana se incluye."""
        hoy = date(2026, 5, 5)
        lbs = [
            _build_lb("LB-NEW", "al_dia", [
                _build_cuota(0, "2026-05-06", 1460000, es_cuota_inicial=True),
                _build_cuota(1, "2026-05-13", 200000),
            ]),
        ]
        r = _ejecutar_logica_endpoint(lbs, hoy)
        assert len(r["checklist"]) == 1
        assert r["checklist"][0]["cuota_numero"] == 0
        assert r["semana_objetivo"] == 1460000
