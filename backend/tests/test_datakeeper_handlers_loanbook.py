"""Tests para datakeeper_handlers_loanbook.py (Sprint S1.5)."""
from __future__ import annotations
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.datakeeper_handlers_loanbook import (
    handle_crear_loanbook_pendiente,
    handle_activar_cronograma_loanbook,
    handle_cerrar_loanbook_paz_salvo,
)


def _mock_db():
    """Crea un mock de db con todas las colecciones que usamos."""
    db = MagicMock()
    # find_one returns AsyncMock; insert/update_one también
    for col in ("loanbook", "catalogo_planes", "inventario_motos",
                "crm_clientes", "roddos_events"):
        c = MagicMock()
        c.find_one = AsyncMock(return_value=None)
        c.insert_one = AsyncMock()
        c.update_one = AsyncMock()
        setattr(db, col, c)
    return db


# ─────────────────────────────────────────────────────────────────────────────
# crear_loanbook_pendiente
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crear_loanbook_pendiente_omite_si_factura_sin_id():
    db = _mock_db()
    event = {"datos": {"vin": "VIN1", "modalidad": "semanal", "plan": "P52S"}}
    await handle_crear_loanbook_pendiente(event, db)
    db.loanbook.insert_one.assert_not_called()


@pytest.mark.asyncio
async def test_crear_loanbook_pendiente_omite_si_modalidad_contado():
    db = _mock_db()
    event = {
        "alegra_id": "12345",
        "datos": {"vin": "VIN1", "modalidad": "contado", "alegra_invoice_id": "12345"}
    }
    await handle_crear_loanbook_pendiente(event, db)
    db.loanbook.insert_one.assert_not_called()


@pytest.mark.asyncio
async def test_crear_loanbook_pendiente_omite_quincenal_pide_manual():
    """Quincenal/mensual requieren fecha_primer_pago. El handler difiere."""
    db = _mock_db()
    event = {
        "alegra_id": "777",
        "datos": {
            "vin": "VIN1", "modalidad": "quincenal", "plan": "P52S",
            "alegra_invoice_id": "777",
            "cliente_cedula": "1", "cliente_nombre": "X", "moto_modelo": "TVS Raider 125"
        }
    }
    await handle_crear_loanbook_pendiente(event, db)
    db.loanbook.insert_one.assert_not_called()


@pytest.mark.asyncio
async def test_crear_loanbook_pendiente_idempotente_si_existe():
    db = _mock_db()
    db.loanbook.find_one = AsyncMock(return_value={"loanbook_id": "lb-existing"})
    event = {
        "alegra_id": "555",
        "datos": {
            "vin": "VIN1", "modalidad": "semanal", "plan": "P52S",
            "alegra_invoice_id": "555",
            "cliente_cedula": "1", "cliente_nombre": "X", "moto_modelo": "TVS Raider 125"
        }
    }
    await handle_crear_loanbook_pendiente(event, db)
    db.loanbook.insert_one.assert_not_called()


@pytest.mark.asyncio
async def test_crear_loanbook_pendiente_falla_si_plan_no_existe():
    db = _mock_db()
    # plan no existe
    db.catalogo_planes.find_one = AsyncMock(return_value=None)
    event = {
        "alegra_id": "888",
        "datos": {
            "vin": "VIN1", "modalidad": "semanal", "plan": "P52S",
            "alegra_invoice_id": "888",
            "cliente_cedula": "1", "cliente_nombre": "X", "moto_modelo": "TVS Raider 125"
        }
    }
    with pytest.raises(ValueError, match="Plan P52S"):
        await handle_crear_loanbook_pendiente(event, db)


@pytest.mark.asyncio
async def test_crear_loanbook_pendiente_exito(monkeypatch):
    """Caso feliz: factura semanal, plan existe, crea loanbook + marca moto vendida."""
    db = _mock_db()
    # plan presente con cuotas_modelo
    plan_doc = {
        "plan_codigo": "P52S",
        "codigo": "P52S",
        "cuotas_base": 52,
        "cuotas_modelo": {"TVS Raider 125": 150_000},
        "anzi_pct": 0.02,
    }
    db.catalogo_planes.find_one = AsyncMock(return_value=plan_doc)

    event = {
        "alegra_id": "999",
        "correlation_id": "corr-1",
        "datos": {
            "alegra_invoice_id": "999",
            "vin": "VIN-OK",
            "modalidad": "semanal",
            "plan": "P52S",
            "cliente_cedula": "1234567",
            "cliente_nombre": "Juan Perez",
            "cliente_telefono": "3001234567",
            "moto_modelo": "TVS Raider 125",
            "fecha": "2026-04-28",
        }
    }

    # publish_event: mock para no escribir realmente
    publish_calls = []
    from core import datakeeper_handlers_loanbook as mod
    async def fake_publish(**kw):
        publish_calls.append(kw)
        return None
    monkeypatch.setattr(mod, "publish_event", fake_publish)

    await handle_crear_loanbook_pendiente(event, db)

    # Verificaciones
    db.loanbook.insert_one.assert_called_once()
    inserted = db.loanbook.insert_one.call_args[0][0]
    assert inserted["vin"] == "VIN-OK"
    assert inserted["estado"] == "pendiente_entrega"
    assert inserted["factura_alegra_id"] == "999"
    assert inserted["origen_creacion"] == "datakeeper.factura.venta.creada"

    # Moto marcada vendida
    db.inventario_motos.update_one.assert_called_once()
    args = db.inventario_motos.update_one.call_args
    assert args[0][0] == {"vin": "VIN-OK"}
    assert args[0][1]["$set"]["estado"] == "vendida"

    # publish_event de loanbook.creado disparado
    assert len(publish_calls) == 1
    assert publish_calls[0]["event_type"] == "loanbook.creado"
    assert publish_calls[0]["alegra_id"] == "999"


# ─────────────────────────────────────────────────────────────────────────────
# activar_cronograma_loanbook
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_activar_cronograma_omite_si_loanbook_no_existe():
    db = _mock_db()
    db.loanbook.find_one = AsyncMock(return_value=None)
    event = {"datos": {"vin": "VIN-NOEXISTE"}}
    await handle_activar_cronograma_loanbook(event, db)
    db.loanbook.update_one.assert_not_called()


@pytest.mark.asyncio
async def test_activar_cronograma_omite_si_ya_activo():
    db = _mock_db()
    db.loanbook.find_one = AsyncMock(return_value={
        "vin": "V1", "estado": "activo", "modalidad": "semanal", "cuotas": []
    })
    event = {"datos": {"vin": "V1"}}
    await handle_activar_cronograma_loanbook(event, db)
    db.loanbook.update_one.assert_not_called()


@pytest.mark.asyncio
async def test_activar_cronograma_genera_fechas_y_estado_activo():
    db = _mock_db()
    db.loanbook.find_one = AsyncMock(return_value={
        "loanbook_id": "lb-1", "vin": "V1", "estado": "pendiente_entrega",
        "modalidad": "semanal",
        "cuotas": [{"numero": 1, "fecha": None}, {"numero": 2, "fecha": None}],
    })
    # 2026-04-28 es martes → primer miércoles >= entrega+7 = 2026-05-06
    event = {"datos": {"vin": "V1", "fecha_entrega": "2026-04-28"}}
    await handle_activar_cronograma_loanbook(event, db)
    args = db.loanbook.update_one.call_args
    update = args[0][1]["$set"]
    assert update["estado"] == "activo"
    assert update["fecha_entrega"] == "2026-04-28"
    assert all(c["fecha"] for c in update["cuotas"])


# ─────────────────────────────────────────────────────────────────────────────
# cerrar_loanbook_paz_salvo
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cerrar_paz_salvo_actualiza_crm():
    db = _mock_db()
    event = {
        "datos": {
            "cliente_cedula": "1234567",
            "vin": "V1",
            "loanbook_id": "lb-1",
        }
    }
    await handle_cerrar_loanbook_paz_salvo(event, db)
    db.crm_clientes.update_one.assert_called_once()
    args = db.crm_clientes.update_one.call_args
    assert args[0][0] == {"cedula": "1234567"}
    update = args[0][1]
    assert update["$set"]["estado"] == "saldado"
    assert "paz_y_salvo" in update["$addToSet"]["tags"]


@pytest.mark.asyncio
async def test_cerrar_paz_salvo_omite_sin_cedula():
    db = _mock_db()
    event = {"datos": {"vin": "V1"}}
    await handle_cerrar_loanbook_paz_salvo(event, db)
    db.crm_clientes.update_one.assert_not_called()
