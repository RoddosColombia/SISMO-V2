"""
test_auditor.py — Tests de la función pura auditar_loanbooks().

TDD estricto: validan DATOS correctos, no solo que la función no explote.
Los fixtures representan el estado corrupto real de producción.
"""
import pytest
from services.loanbook.auditor import auditar_loanbooks


# ─── Fixtures de loanbooks corruptos ──────────────────────────────────────────

def _lb_samir():
    """
    Samir García — LB-2026-0028
    Plan real: P39S semanal → correcto = 39 cuotas × $204,000 = $7,956,000
    Estado corrupto: num_cuotas=28, valor_total incorrecto
    """
    return {
        "loanbook_id": "LB-2026-0028",
        "cliente": {"nombre": "Samir García", "cedula": "12345678"},
        "plan_codigo": "P39S",
        "plan": {
            "codigo": "P39S",
            "modalidad": "semanal",
            "cuota_valor": 204_000,
            "total_cuotas": 28,  # ← MAL: debería ser 39
            "cuota_inicial": 0,
        },
        "modalidad": "semanal",
        "cuota_monto": 204_000,
        "num_cuotas": 28,  # ← MAL
        "valor_total": 28 * 204_000,  # ← MAL: 5,712,000 en vez de 7,956,000
        "cuotas": [],
        "estado": "activo",
    }


def _lb_richard():
    """
    Richard Millán — LB-2026-0027
    Plan real: P78S semanal → correcto = 78 cuotas × $145,000 + $1,160,000 = $12,470,000
    Estado corrupto: total_cuotas=76
    """
    return {
        "loanbook_id": "LB-2026-0027",
        "cliente": {"nombre": "Richard Millán", "cedula": "87654321"},
        "plan_codigo": "P78S",
        "plan": {
            "codigo": "P78S",
            "modalidad": "semanal",
            "cuota_valor": 145_000,
            "total_cuotas": 76,  # ← MAL: debería ser 78
            "cuota_inicial": 1_160_000,
        },
        "modalidad": "semanal",
        "cuota_monto": 145_000,
        "num_cuotas": 76,  # ← MAL
        "valor_total": 76 * 145_000 + 1_160_000,  # ← MAL
        "cuotas": [],
        "estado": "pendiente_entrega",
    }


def _lb_limpio_p52s():
    """Loanbook correcto — P52S semanal, 52 cuotas × $180,000 = $9,360,000."""
    return {
        "loanbook_id": "LB-2026-0001",
        "cliente": {"nombre": "Cliente Limpio", "cedula": "00000001"},
        "plan_codigo": "P52S",
        "plan": {
            "codigo": "P52S",
            "modalidad": "semanal",
            "cuota_valor": 180_000,
            "total_cuotas": 52,
            "cuota_inicial": 0,
        },
        "modalidad": "semanal",
        "cuota_monto": 180_000,
        "num_cuotas": 52,
        "valor_total": 52 * 180_000,  # $9,360,000 correcto
        "cuotas": [],
        "estado": "activo",
    }


def _lb_jose_altamiranda_comparendo():
    """
    Jose Altamiranda — comparendo P15S
    Cuotas futuras marcadas como pagadas sin referencia (seed corrupto)
    """
    from datetime import date, timedelta
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
        "valor_total": 15 * 70_000,  # correcto
        "cuotas": [
            {
                "numero": 6,
                "fecha": (hoy - timedelta(days=7)).isoformat(),
                "estado": "pagada",
                "fecha_pago": (hoy - timedelta(days=5)).isoformat(),
                "referencia": None,
                "metodo_pago": None,  # ← sin evidencia real
            },
            {
                "numero": 7,
                "fecha": (hoy + timedelta(days=7)).isoformat(),  # FUTURO
                "estado": "pagada",  # ← marcada pagada
                "fecha_pago": None,
                "referencia": None,
                "metodo_pago": None,  # ← sin evidencia
            },
            {
                "numero": 8,
                "fecha": (hoy + timedelta(days=14)).isoformat(),  # FUTURO
                "estado": "pagada",  # ← marcada pagada
                "fecha_pago": None,
                "referencia": None,
                "metodo_pago": None,  # ← sin evidencia
            },
        ],
        "estado": "activo",
    }


# ─── Tests BUILD 1 (obligatorios del sprint) ──────────────────────────────────

def test_auditor_detecta_samir_con_total_cuotas_incorrecto():
    """Samir tiene plan_codigo=P39S pero total_cuotas=28 — debe aparecer."""
    resultado = auditar_loanbooks([_lb_samir()])
    casos = resultado["casos"]["total_cuotas_incorrecto_segun_plan"]
    samir_caso = next(
        (c for c in casos if c["loanbook_id"] == "LB-2026-0028"),
        None,
    )
    assert samir_caso is not None, "Samir debe aparecer en total_cuotas_incorrecto_segun_plan"
    assert samir_caso["total_cuotas_correcto"] == 39
    assert samir_caso["total_cuotas_muestra"] == 28


def test_auditor_detecta_richard_con_total_cuotas_incorrecto():
    """Richard tiene P78S pero total_cuotas=76."""
    resultado = auditar_loanbooks([_lb_richard()])
    casos = resultado["casos"]["total_cuotas_incorrecto_segun_plan"]
    richard = next(
        (c for c in casos if c["loanbook_id"] == "LB-2026-0027"),
        None,
    )
    assert richard is not None, "Richard debe aparecer en total_cuotas_incorrecto_segun_plan"
    assert richard["total_cuotas_correcto"] == 78
    assert richard["total_cuotas_muestra"] == 76


# ─── Tests adicionales de robustez ────────────────────────────────────────────

def test_auditor_detecta_valor_total_incorrecto_samir():
    """Samir: valor_total=5,712,000 pero debería ser 7,956,000."""
    resultado = auditar_loanbooks([_lb_samir()])
    casos = resultado["casos"]["valor_total_incorrecto"]
    samir = next((c for c in casos if c["loanbook_id"] == "LB-2026-0028"), None)
    assert samir is not None
    assert samir["deberia_ser"] == 39 * 204_000  # 7,956,000
    assert samir["muestra"] == 28 * 204_000      # 5,712,000


def test_auditor_no_reporta_loanbook_limpio():
    """Un loanbook correcto no debe aparecer en ninguna categoría."""
    resultado = auditar_loanbooks([_lb_limpio_p52s()])
    assert resultado["resumen"]["valor_total_incorrecto"] == 0
    assert resultado["resumen"]["total_cuotas_incorrecto_segun_plan"] == 0
    assert resultado["resumen"]["cuotas_pagadas_con_fecha_imposible"] == 0


def test_auditor_detecta_cuotas_futuras_sin_evidencia():
    """Jose tiene cuotas 7 y 8 marcadas pagadas en el futuro sin referencia."""
    resultado = auditar_loanbooks([_lb_jose_altamiranda_comparendo()])
    casos = resultado["casos"]["cuotas_pagadas_fecha_imposible"]
    jose = next((c for c in casos if c["loanbook_id"] == "LB-2026-0024"), None)
    assert jose is not None
    numeros = [c["numero"] for c in jose["cuotas"]]
    assert 7 in numeros
    assert 8 in numeros
    # Cuota 6 es pasada — NO debe aparecer aunque no tenga evidencia
    assert 6 not in numeros


def test_auditor_no_reporta_cuota_futura_con_evidencia():
    """Si una cuota futura tiene referencia bancaria, NO es seed corrupto."""
    from datetime import date, timedelta
    hoy = date.today()
    lb = {
        "loanbook_id": "LB-TEST",
        "cliente": {"nombre": "Test", "cedula": "0"},
        "plan_codigo": "P39S",
        "plan": {"codigo": "P39S", "modalidad": "semanal", "cuota_valor": 100_000, "total_cuotas": 39, "cuota_inicial": 0},
        "modalidad": "semanal",
        "cuota_monto": 100_000,
        "num_cuotas": 39,
        "valor_total": 39 * 100_000,
        "cuotas": [
            {
                "numero": 5,
                "fecha": (hoy + timedelta(days=30)).isoformat(),
                "estado": "pagada",
                "fecha_pago": hoy.isoformat(),
                "referencia": "TRF-001234",  # ← tiene evidencia
                "metodo_pago": "transferencia",
            }
        ],
        "estado": "activo",
    }
    resultado = auditar_loanbooks([lb])
    casos = resultado["casos"]["cuotas_pagadas_fecha_imposible"]
    assert len(casos) == 0


def test_auditor_resumen_agrega_multiples_loanbooks():
    """Con Samir + Richard + Jose, el resumen suma correctamente."""
    resultado = auditar_loanbooks([
        _lb_samir(),
        _lb_richard(),
        _lb_jose_altamiranda_comparendo(),
        _lb_limpio_p52s(),
    ])
    assert resultado["total_loanbooks"] == 4
    assert resultado["resumen"]["valor_total_incorrecto"] >= 2       # Samir + Richard
    assert resultado["resumen"]["total_cuotas_incorrecto_segun_plan"] >= 2  # Samir + Richard
    assert resultado["resumen"]["cuotas_pagadas_con_fecha_imposible"] >= 1  # Jose


def test_auditor_p15s_comparendo_total_cuotas_correcto():
    """P15S semanal siempre = 15 cuotas."""
    lb = {
        "loanbook_id": "LB-CMP",
        "cliente": {"nombre": "Comparendo Test", "cedula": "0"},
        "plan_codigo": "P15S",
        "plan": {"codigo": "P15S", "modalidad": "semanal", "cuota_valor": 70_000, "total_cuotas": 10, "cuota_inicial": 0},
        "modalidad": "semanal",
        "cuota_monto": 70_000,
        "num_cuotas": 10,  # ← MAL: debería ser 15
        "valor_total": 10 * 70_000,
        "cuotas": [],
        "estado": "activo",
    }
    resultado = auditar_loanbooks([lb])
    caso = next(
        (c for c in resultado["casos"]["total_cuotas_incorrecto_segun_plan"] if c["loanbook_id"] == "LB-CMP"),
        None,
    )
    assert caso is not None
    assert caso["total_cuotas_correcto"] == 15
