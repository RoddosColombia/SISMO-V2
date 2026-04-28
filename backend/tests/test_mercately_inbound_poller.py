"""Tests para services/mercately/inbound_poller.py (S2.5c — phones activos)."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.mercately.inbound_poller import (
    _iso_to_dt,
    _normalize_phone,
    _get_global_state,
    _obtener_phones_activos,
    poll_once,
)


# Pure helpers --------------------------------------------------------------

def test_iso_to_dt_acepta_z():
    dt = _iso_to_dt("2026-04-28T13:24:00.123Z")
    assert dt is not None and dt.tzinfo is not None

def test_iso_to_dt_vacio_devuelve_none():
    assert _iso_to_dt("") is None
    assert _iso_to_dt("not-iso") is None

def test_normalize_phone_co_10_dig():
    assert _normalize_phone("3001234567") == "573001234567"

def test_normalize_phone_ya_normalizado():
    assert _normalize_phone("573001234567") == "573001234567"

def test_normalize_phone_con_caracteres():
    assert _normalize_phone("+57 (300) 123-4567") == "573001234567"


# Mock helpers --------------------------------------------------------------

class _Cursor:
    def __init__(self, items):
        self._items = list(items)
    def limit(self, n):
        self._items = self._items[:n]
        return self
    def __aiter__(self):
        return self._gen()
    async def _gen(self):
        for it in self._items:
            yield it


def _empty_cursor():
    return _Cursor([])


def _make_mock_db():
    db = MagicMock()
    for col in ("mercately_polling_state", "crm_clientes", "roddos_events",
                "mercately_inbound_audit", "loanbook", "radar_alertas"):
        c = MagicMock()
        c.find_one = AsyncMock(return_value=None)
        c.update_one = AsyncMock()
        c.insert_one = AsyncMock()
        c.find = MagicMock(return_value=_empty_cursor())
        c.aggregate = MagicMock(return_value=_empty_cursor())
        setattr(db, col, c)
    return db


# Estado global --------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_global_state_sin_doc_devuelve_5min_atras():
    db = _make_mock_db()
    db.mercately_polling_state.find_one = AsyncMock(return_value=None)
    dt = await _get_global_state(db)
    delta = datetime.now(timezone.utc) - dt
    assert timedelta(minutes=4) < delta < timedelta(minutes=6)


# _obtener_phones_activos ----------------------------------------------------

@pytest.mark.asyncio
async def test_obtener_phones_activos_lee_loanbook_y_crm():
    db = _make_mock_db()
    db.loanbook.find = MagicMock(return_value=_Cursor([
        {"telefono": "3001111111", "dpd": 5},
        {"telefono": "3002222222", "dpd": 15},
    ]))
    db.crm_clientes.find = MagicMock(return_value=_Cursor([
        {"mercately_phone": "573003333333", "tags": ["mora"]},
    ]))
    db.radar_alertas.find = MagicMock(return_value=_Cursor([
        {"telefono": "3004444444"},
    ]))

    phones = await _obtener_phones_activos(db, limit=10)
    assert "573001111111" in phones
    assert "573002222222" in phones
    assert "573003333333" in phones
    assert "573004444444" in phones
    # DPD 15 prioridad sobre DPD 5
    assert phones.index("573002222222") < phones.index("573001111111")


@pytest.mark.asyncio
async def test_obtener_phones_activos_devuelve_vacio_sin_datos():
    db = _make_mock_db()
    phones = await _obtener_phones_activos(db, limit=10)
    assert phones == []


# poll_once ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_once_skip_si_no_api_key():
    db = _make_mock_db()
    fake_client = MagicMock()
    fake_client.api_key = ""
    with patch("services.mercately.inbound_poller.get_mercately_client",
               return_value=fake_client):
        res = await poll_once(db)
    assert res == {"ok": False, "skip": "no_api_key"}


@pytest.mark.asyncio
async def test_poll_once_sin_phones_activos_devuelve_ok():
    db = _make_mock_db()
    fake_client = MagicMock()
    fake_client.api_key = "fake"
    with patch("services.mercately.inbound_poller.get_mercately_client",
               return_value=fake_client):
        res = await poll_once(db)
    assert res["ok"] is True
    assert res["phones_consultados"] == 0


@pytest.mark.asyncio
async def test_poll_once_procesa_inbound_filtra_outbound():
    db = _make_mock_db()
    db.mercately_polling_state.find_one = AsyncMock(return_value=None)
    db.crm_clientes.find_one = AsyncMock(return_value={
        "_id": "obj1", "cedula": "12345", "mercately_phone": "573102511280",
    })
    db.loanbook.find = MagicMock(return_value=_Cursor([
        {"telefono": "3102511280", "dpd": 0},
    ]))

    ahora = datetime.now(timezone.utc).isoformat()
    fake_client = MagicMock()
    fake_client.api_key = "fake"
    fake_client.get_whatsapp_conversations_by_phone = AsyncMock(return_value={
        "success": True,
        "messages": [
            {"id": "msg-1", "direction": "inbound", "content_text": "voy a pagar",
             "content_type": "text", "created_time": ahora},
            {"id": "msg-2", "direction": "outbound", "content_text": "(template)",
             "content_type": "text", "created_time": ahora},
        ],
        "total_pages": 1,
    })

    with patch("services.mercately.inbound_poller.get_mercately_client",
               return_value=fake_client):
        res = await poll_once(db)

    assert res["ok"] is True
    assert res["phones_consultados"] == 1
    assert res["mensajes_procesados"] == 1
    assert db.roddos_events.insert_one.await_count == 1
    assert db.mercately_inbound_audit.insert_one.await_count == 1


@pytest.mark.asyncio
async def test_poll_once_no_reprocesa_msg_ya_visto():
    db = _make_mock_db()
    async def fake_find_one(query):
        if query.get("_id") == "phone:573102511280":
            return {
                "phone": "573102511280",
                "last_seen_msg_id": "msg-1",
                "last_seen_iso": datetime.now(timezone.utc).isoformat(),
            }
        return None
    db.mercately_polling_state.find_one = AsyncMock(side_effect=fake_find_one)
    db.crm_clientes.find_one = AsyncMock(return_value=None)
    db.loanbook.find = MagicMock(return_value=_Cursor([
        {"telefono": "3102511280", "dpd": 0},
    ]))

    ahora = datetime.now(timezone.utc).isoformat()
    fake_client = MagicMock()
    fake_client.api_key = "fake"
    fake_client.get_whatsapp_conversations_by_phone = AsyncMock(return_value={
        "success": True,
        "messages": [{
            "id": "msg-1", "direction": "inbound", "content_text": "ya vi",
            "content_type": "text", "created_time": ahora,
        }],
        "total_pages": 1,
    })

    with patch("services.mercately.inbound_poller.get_mercately_client",
               return_value=fake_client):
        res = await poll_once(db)

    assert res["ok"] is True
    assert res["mensajes_procesados"] == 0


@pytest.mark.asyncio
async def test_poll_once_devuelve_ok_false_si_todos_los_phones_dan_error():
    db = _make_mock_db()
    db.mercately_polling_state.find_one = AsyncMock(return_value=None)
    db.crm_clientes.find_one = AsyncMock(return_value=None)
    db.loanbook.find = MagicMock(return_value=_Cursor([
        {"telefono": "3001111111", "dpd": 5},
        {"telefono": "3002222222", "dpd": 10},
    ]))

    fake_client = MagicMock()
    fake_client.api_key = "fake"
    fake_client.get_whatsapp_conversations_by_phone = AsyncMock(return_value={
        "success": False, "messages": [], "error": "HTTP 500", "raw": "boom",
    })

    with patch("services.mercately.inbound_poller.get_mercately_client",
               return_value=fake_client):
        res = await poll_once(db)

    assert res["ok"] is False
    assert res["phones_consultados"] == 2
    assert res["errores_http"] == 2
    assert res["mensajes_procesados"] == 0
