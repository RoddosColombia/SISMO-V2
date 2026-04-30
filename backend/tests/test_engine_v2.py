"""Smoke test del engine.recalcular."""
from datetime import date
from services.loanbook.engine import recalcular, crear_loanbook, auditar


def test_recalcular_regenera_cronograma_canonico():
    lb_malo = {
        "loanbook_id": "TEST-19",
        "cliente": {"nombre": "Andres Soto"},
        "plan_codigo": "P26S",
        "modelo": "Raider 125",
        "modalidad": "quincenal",
        "fecha_entrega": "2026-03-25",
        "fecha_primer_pago": "2026-04-15",
        "cuota_monto": 329780,
        "estado": "al_dia",
        "cuotas": [
            {"numero": 1, "fecha": "2026-04-21", "monto": 329780, "estado": "pagada", "monto_pagado": 329780},
            {"numero": 2, "fecha": "2026-05-05", "monto": 329780, "estado": "pendiente", "monto_pagado": 0},
        ],
    }
    r = recalcular(lb_malo)
    fechas = [c["fecha"] for c in r["cuotas"]]
    # Las fechas deben ser miércoles según override fecha_primer_pago=2026-04-15 + 14 días cada una
    assert fechas[0] == "2026-04-15", f"Cuota 1: {fechas[0]}"
    # Pago preservado
    assert r["cuotas"][0]["estado"] == "pagada"


def test_recalcular_limpia_modelo_plan_codigo():
    lb = {
        "loanbook_id": "TEST-32",
        "cliente": {"nombre": "Lina"},
        "plan_codigo": "P78S",
        "modelo": "P78S",  # BUG
        "modalidad": "semanal",
        "fecha_entrega": "2026-04-30",
        "fecha_primer_pago": "2026-05-06",
        "cuota_monto": 145000,
        "capital_plan": 5_750_000,
        "estado": "al_dia",
        "cuotas": [],
    }
    r = recalcular(lb)
    assert r["modelo"] == "", f"modelo no limpiado: {r['modelo']!r}"
    assert len(r["cuotas"]) > 0, "cronograma no regenerado"


def test_idempotencia():
    lb = {
        "loanbook_id": "TEST-IDEMP",
        "cliente": {"nombre": "X"},
        "plan_codigo": "P52S",
        "modelo": "Raider 125",
        "modalidad": "semanal",
        "fecha_entrega": "2026-03-05",
        "cuota_monto": 179900,
        "capital_plan": 7_800_000,
        "estado": "al_dia",
        "cuotas": [],
    }
    r1 = recalcular(lb)
    r2 = recalcular(r1)
    for k in ["num_cuotas", "saldo_capital", "saldo_intereses", "saldo_pendiente", "modelo"]:
        assert r1.get(k) == r2.get(k), f"{k}: {r1.get(k)} != {r2.get(k)}"


def test_crear_loanbook_pendiente_entrega_sin_cronograma():
    """Por diseño: LB recién creado en pendiente_entrega NO tiene cronograma.
    El cronograma se genera al entregar la moto."""
    doc = crear_loanbook(
        loanbook_id="LB-NEW-001",
        cliente={"nombre": "Nuevo Cliente", "cedula": "999"},
        plan_codigo="P52S",
        modelo="Raider 125",
        modalidad="semanal",
        fecha_entrega=date(2026, 5, 13),
        cuota_monto=179900,
    )
    assert doc["modelo"] == "Raider 125"
    assert doc["capital_plan"] == 7_800_000
    assert doc["num_cuotas"] == 52
    assert doc["estado"] == "pendiente_entrega"
    assert len(doc["cuotas"]) == 0


def test_crear_loanbook_activo_genera_cronograma_canonico():
    """LB ya activado (estado=al_dia) sí tiene cronograma canónico."""
    doc = crear_loanbook(
        loanbook_id="LB-NEW-002",
        cliente={"nombre": "Nuevo"},
        plan_codigo="P52S",
        modelo="Raider 125",
        modalidad="semanal",
        fecha_entrega=date(2026, 5, 13),
        cuota_monto=179900,
        estado="al_dia",
    )
    assert doc["num_cuotas"] == 52
    assert len(doc["cuotas"]) == 52
    for c in doc["cuotas"]:
        d = date.fromisoformat(c["fecha"])
        assert d.weekday()