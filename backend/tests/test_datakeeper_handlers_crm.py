"""Tests para datakeeper_handlers_crm.py (Sprint S1.5)."""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.datakeeper_handlers_crm import (
    handle_sync_mercately_contacto_inicial,
    handle_sync_mercately_contacto_update,
    handle_registrar_gestion_pago_crm,
    _normalizar_phone_57,
)


def _mock_db():
    db = MagicMock()
    for col in ("crm_clientes", "roddos_events"):
        c = MagicMock()
        c.find_one = AsyncMock(return_value=None)
        c.update_one = AsyncMock()
        c.insert_one = AsyncMock()
        setattr(db, col, c)
    return db


# ─────────────────────────────────────────────────────────────────────────────
# _normalizar_phone_57
# ─────────────────────────────────────────────────────────────────────────────

def test_normalizar_phone_acepta_10digitos():
    assert _normalizar_phone_57("3001234567") == "573001234567"


def test_normalizar_phone_acepta_57_prefix():
    assert _normalizar_phone_57("573001234567") == "573001234567"


def test_normalizar_phone_quita_caracteres_y_zero():
    assert _normalizar_phone_57("+57 (300) 123-4567") == "573001234567"
    assert _normalizar_phone_57("0573001234567") == "573001234567"


def test_normalizar_phone_rechaza_invalidos():
    assert _normalizar_phone_57("") == ""
    assert _normalizar_phone_57("123") == ""
    assert _normalizar_phone_57("99999999999999") == ""


# ─────────────────────────────────────────────────────────────────────────────
# sync_mercately_contacto_inicial
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_mercately_omite_sin_apikey(monkeypatch):
    monkeypatch.delenv("MERCATELY_API_KEY", raising=False)
    db = _mock_db()
    event = {"datos": {"cliente": {"cedula": "1", "nombre": "X", "telefono": "3001234567"}}}
    await handle_sync_mercately_contacto_inicial(event, db)
    db.crm_clientes.update_one.assert_not_called()


@pytest.mark.asyncio
async def test_sync_mercately_omite_telefono_invalido(monkeypatch):
    monkeypatch.setenv("MERCATELY_API_KEY", "test")
    db = _mock_db()
    event = {"datos": {"cliente": {"cedula": "1", "nombre": "X", "telefono": "123"}}}
    await handle_sync_mercately_contacto_inicial(event, db)
    db.crm_clientes.update_one.assert_not_called()


@pytest.mark.asyncio
async def test_sync_mercately_omite_si_crm_no_existe(monkeypatch):
    monkeypatch.setenv("MERCATELY_API_KEY", "test")
    db = _mock_db()
    db.crm_clientes.find_one = AsyncMock(return_value=None)
    event = {"datos": {"cliente": {"cedula": "1", "nombre": "X", "telefono": "3001234567"}}}
    await handle_sync_mercately_contacto_inicial(event, db)
    db.crm_clientes.update_one.assert_not_called()


@pytest.mark.asyncio
async def test_sync_mercately_marca_synced_si_ok(monkeypatch):
    monkeypatch.setenv("MERCATELY_API_KEY", "test")
    db = _mock_db()
    db.crm_clientes.find_one = AsyncMock(return_value={"cedula": "1", "nombre": "Juan"})
    event = {"datos": {"cliente": {"cedula": "1", "nombre": "Juan", "telefono": "3001234567"}}}
    await handle_sync_mercately_contacto_inicial(event, db)
    db.crm_clientes.update_one.assert_called_once()
    args = db.crm_clientes.update_one.call_args
    assert args[0][0] == {"cedula": "1"}
    update = args[0][1]["$set"]
    assert update["mercately_phone"] == "573001234567"
    assert "mercately_synced_at" in update


# ─────────────────────────────────────────────────────────────────────────────
# registrar_gestion_pago_crm
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_registrar_gestion_pago_agrega_timeline():
    db = _mock_db()
    event = {
        "datos": {
            "cliente_cedula": "1",
            "vin": "V1",
            "cuota_numero": 3,
            "monto_total_pagado": 150_000,
            "nuevo_estado": "al_dia",
        }
    }
    await handle_registrar_gestion_pago_crm(event, db)
    db.crm_clientes.update_one.assert_called_once()
    args = db.crm_clientes.update_one.call_args
    update = args[0][1]
    gestion = update["$push"]["gestiones"]
    assert gestion["tipo"] == "pago_cuota"
    assert gestion["cuota_numero"] == 3
    assert gestion["monto"] == 150_000
    assert "al_dia" in update["$addToSet"]["tags"]


@pytest.mark.asyncio
async def test_registrar_gestion_pago_omite_sin_cedula():
    db = _mock_db()
    event = {"datos": {"vin": "V1"}}
    await handle_registrar_gestion_pago_crm(event, db)
    db.crm_clientes.update_one.assert_not_called()


@pytest.mark.asyncio
async def test_registrar_gestion_pago_tag_mora_si_estado_mora():
    db = _mock_db()
    event = {
        "datos": {
            "cliente_cedula": "9", "vin": "V9", "cuota_numero": 5,
            "monto_total_pagado": 50_000, "nuevo_estado": "mora_grave",
        }
    }
    await handle_registrar_gestion_pago_crm(event, db)
    update = db.crm_clientes.update_one.call_args[0][1]
    assert "mora" in update["$addToSet"]["tags"]
