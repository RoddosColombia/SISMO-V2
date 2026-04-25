"""
Tests for manual operation endpoints on /api/loanbook.

- POST /{id}/registrar-pago
- POST /{id}/registrar-pago-inicial
- POST /{id}/registrar-entrega
"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from routers.loanbook import (
    RegistrarEntregaBody,
    RegistrarPagoBody,
    RegistrarPagoInicialBody,
    registrar_entrega,
    registrar_pago_inicial,
    registrar_pago_manual,
)


def _mock_db_with_loanbook(doc: dict) -> MagicMock:
    db = MagicMock()
    db.loanbook = MagicMock()
    db.loanbook.find_one = AsyncMock(return_value=doc)
    db.loanbook.update_one = AsyncMock()
    db.roddos_events = MagicMock()
    db.roddos_events.insert_one = AsyncMock()
    return db


def _active_loanbook_doc():
    return {
        "_id": "x",
        "loanbook_id": "LB-2026-TEST",
        "vin": "VIN123",
        "estado": "activo",
        "modalidad": "semanal",
        "anzi_pct": 0.02,
        "cuota_monto": 100_000,
        "num_cuotas": 10,
        "saldo_capital": 900_000,
        "total_pagado": 100_000,
        "total_mora_pagada": 0,
        "total_anzi_pagado": 0,
        "cuotas": [
            {"numero": 1, "monto": 100_000, "estado": "pagada",
             "fecha": "2026-04-01", "fecha_pago": "2026-04-01", "mora_acumulada": 0},
            {"numero": 2, "monto": 100_000, "estado": "pendiente",
             "fecha": date.today().isoformat(), "fecha_pago": None, "mora_acumulada": 0},
            {"numero": 3, "monto": 100_000, "estado": "pendiente",
             "fecha": "2099-01-01", "fecha_pago": None, "mora_acumulada": 0},
        ],
    }


# ── registrar_pago ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_registrar_pago_marks_cuota_paid_and_publishes_event():
    db = _mock_db_with_loanbook(_active_loanbook_doc())
    # Pagar 102_041 cubre ANZI 2% + 100_000 cuota exacta
    body = RegistrarPagoBody(monto_pago=102_041, metodo_pago="bancolombia")
    result = await registrar_pago_manual("LB-2026-TEST", body, db=db)
    assert result["success"] is True
    assert result["cuotas_pagadas"] == 2  # 1 previa + 1 nueva
    # Debe haber actualizado el loanbook Y publicado el evento
    # _recalcular_y_persistir añade una segunda llamada — verificamos que se llamó al menos una vez
    assert db.loanbook.update_one.called
    db.roddos_events.insert_one.assert_called_once()
    event_doc = db.roddos_events.insert_one.call_args[0][0]
    assert event_doc["event_type"] == "pago.cuota.registrado"
    assert event_doc["datos"]["metodo_pago"] == "bancolombia"


@pytest.mark.asyncio
async def test_registrar_pago_rejects_invalid_metodo():
    db = _mock_db_with_loanbook(_active_loanbook_doc())
    body = RegistrarPagoBody(monto_pago=100_000, metodo_pago="btc")
    with pytest.raises(HTTPException) as exc:
        await registrar_pago_manual("LB-2026-TEST", body, db=db)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_registrar_pago_404_when_loanbook_missing():
    db = MagicMock()
    db.loanbook = MagicMock()
    db.loanbook.find_one = AsyncMock(return_value=None)
    body = RegistrarPagoBody(monto_pago=100_000)
    with pytest.raises(HTTPException) as exc:
        await registrar_pago_manual("LB-NOPE", body, db=db)
    assert exc.value.status_code == 404


# ── registrar_pago_inicial ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_registrar_pago_inicial_only_on_pendiente_entrega():
    doc = _active_loanbook_doc()
    doc["estado"] = "activo"
    db = _mock_db_with_loanbook(doc)
    body = RegistrarPagoInicialBody(monto_pago=500_000)
    with pytest.raises(HTTPException) as exc:
        await registrar_pago_inicial("LB-2026-TEST", body, db=db)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_registrar_pago_inicial_success():
    doc = _active_loanbook_doc()
    doc["estado"] = "pendiente_entrega"
    db = _mock_db_with_loanbook(doc)
    body = RegistrarPagoInicialBody(monto_pago=1_460_000, metodo_pago="nequi")
    result = await registrar_pago_inicial("LB-2026-TEST", body, db=db)
    assert result["success"] is True
    db.loanbook.update_one.assert_called_once()
    db.roddos_events.insert_one.assert_called_once()
    assert db.roddos_events.insert_one.call_args[0][0]["event_type"] == "pago.inicial.registrado"


# ── registrar_entrega ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_registrar_entrega_activa_y_genera_cronograma():
    doc = _active_loanbook_doc()
    doc["estado"] = "pendiente_entrega"
    db = _mock_db_with_loanbook(doc)
    body = RegistrarEntregaBody(fecha_entrega="2026-04-13")
    result = await registrar_entrega("LB-2026-TEST", body, db=db)
    assert result["success"] is True
    assert result["estado"] == "activo"
    assert result["num_cuotas"] == 10
    # Verificar que el cronograma se guardó (primera llamada = entrega, segunda = recalculation)
    update = db.loanbook.update_one.call_args_list[0][0][1]["$set"]
    assert update["estado"] == "activo"
    assert len(update["cuotas"]) == 10


@pytest.mark.asyncio
async def test_registrar_entrega_con_dia_cobro_especial_jueves():
    doc = _active_loanbook_doc()
    doc["estado"] = "pendiente_entrega"
    db = _mock_db_with_loanbook(doc)
    body = RegistrarEntregaBody(
        fecha_entrega="2026-04-10",
        fecha_primera_cuota="2026-04-16",  # Thursday
        dia_cobro_especial="jueves",
    )
    result = await registrar_entrega("LB-2026-TEST", body, db=db)
    assert result["success"] is True
    assert result["fecha_primera_cuota"] == "2026-04-16"
    update = db.loanbook.update_one.call_args_list[0][0][1]["$set"]
    assert update["dia_cobro_especial"] == "jueves"
    # All cuota dates must be Thursdays
    for c in update["cuotas"]:
        d = date.fromisoformat(c["fecha"])
        assert d.weekday() == 3, f"Cuota {c['numero']} fecha {c['fecha']} no es jueves"
