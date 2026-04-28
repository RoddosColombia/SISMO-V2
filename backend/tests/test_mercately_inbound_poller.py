"""Tests para services/mercately/inbound_poller.py.

Cubre:
- _iso_to_dt y _normalize_phone (puros)
- _get_global_state default 5min ago
- poll_once con mock client + mock db (escenario completo: 1 conv nueva con 2 msg inbound)
- poll_once idempotente (mismo customer_id, no reproceso de mensajes ya vistos)
- poll_once filtra outbound
- poll_once skip cuando no hay api_key
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.mercately.inbound_poller import (
    _iso_to_dt,
    _normalize_phone,
    _get_global_state,
    poll_once,
)


# ─── Pure helpers ────────────────────────────────────────────────────────────

def test_iso_to_dt_acepta_z():
    dt = _iso_to_dt("2026-04-28T13:24:00.123Z")
    assert dt is not None
    assert dt.tzinfo is not None

def test_iso_to_dt_vacio_devuelve_none():
    assert _iso_to_dt("") is None
    assert _iso_to_dt("not-iso") is None


def test_normalize_phone_co_10_dig():
    assert _normalize_phone("3001234567") == "573001234567"

def test_normalize_phone_ya_normalizado():
    assert _normalize_phone("573001234567") == "573001234567"

def test_normalize_phone_con_caracteres():
    assert _normalize_phone("+57 (300) 123-4567") == "573001234567"


# ─── Mock DB helper ──────────────────────────────────────────────────────────

def _make_mock_db():
    db = MagicMock()
    for col in (
        "mercately_polling_state",
        "crm_clientes",
        "roddos_events",
        "mercately_inbound_audit",
    ):
        c = MagicMock()
        c.find_one = AsyncMock(return_value=None)
        c.update_one = AsyncMock()
        c.insert_one = AsyncMock()
        setattr(db, col, c)
    return db


# ─── Estado global ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_global_state_sin_doc_devuelve_5min_atras():
    db = _make_mock_db()
    db.mercately_polling_state.find_one = AsyncMock(return_value=None)
    dt = await _get_global_state(db)
    delta = datetime.now(timezone.utc) - dt
    # Debe ser ~5min, dejamos margen
    assert timedelta(minutes=4) < delta < timedelta(minutes=6)


# ─── poll_once ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_poll_once_skip_si_no_api_key():
    db = _make_mock_db()
    fake_client = MagicMock()
    fake_client.api_key = ""
    with patch(
        "services.mercately.inbound_poller.get_mercately_client",
        return_value=fake_client,
    ):
        res = await poll_once(db)
    assert res == {"ok": False, "skip": "no_api_key"}


@pytest.mark.asyncio
async def test_poll_once_procesa_mensaje_inbound_nuevo():
    db = _make_mock_db()
    db.mercately_polling_state.find_one = AsyncMock(return_value=None)
    db.crm_clientes.find_one = AsyncMock(return_value={
        "_id": "obj1", "cedula": "1234567", "mercately_phone": "573001234567",
    })

    # Conversacion con last_interaction ahora (será > last_global_check default 5min ago)
    ahora = datetime.now(timezone.utc).isoformat()
    fake_client = MagicMock()
    fake_client.api_key = "fake-key"
    fake_client.list_whatsapp_conversations = AsyncMock(return_value={
        "success": True,
        "conversations": [
            {
                "customer_id": 999,
                "phone": "+573001234567",
                "first_name": "Andres",
                "last_interaction": ahora,
            },
        ],
        "total_pages": 1,
    })
    fake_client.get_customer_messages = AsyncMock(return_value={
        "success": True,
        "messages": [
            {
                "id": "msg-1",
                "direction": "inbound",
                "content_type": "text",
                "content_text": "voy a pagar manana",
                "created_time": ahora,
            },
            {
                "id": "msg-2",
                "direction": "outbound",   # debe ser ignorado
                "content_type": "text",
                "content_text": "(template enviado por SISMO)",
                "created_time": ahora,
            },
        ],
        "total_pages": 1,
    })

    with patch(
        "services.mercately.inbound_poller.get_mercately_client",
        return_value=fake_client,
    ):
        res = await poll_once(db)

    assert res["ok"] is True
    assert res["candidatas"] == 1
    assert res["mensajes_procesados"] == 1, "debe procesar SOLO inbound, no outbound"
    # publish_event escribe en roddos_events
    assert db.roddos_events.insert_one.await_count == 1
    # Append gestion al CRM
    assert db.crm_clientes.update_one.await_count == 1
    # Audit
    assert db.mercately_inbound_audit.insert_one.await_count == 1


@pytest.mark.asyncio
async def test_poll_once_no_reprocesa_mismo_msg_id():
    db = _make_mock_db()
    # Estado per-customer existente con last_seen_msg_id="msg-1"
    async def fake_find_one(query):
        if query.get("_id") == "global":
            # last_global hace 1 hora
            return {"last_global_check_iso": (
                datetime.now(timezone.utc) - timedelta(hours=1)
            ).isoformat()}
        if query.get("_id") == "customer:999":
            return {
                "customer_id": 999,
                "last_seen_msg_id": "msg-1",
                "last_seen_iso": datetime.now(timezone.utc).isoformat(),
            }
        return None
    db.mercately_polling_state.find_one = AsyncMock(side_effect=fake_find_one)
    db.crm_clientes.find_one = AsyncMock(return_value=None)

    ahora = datetime.now(timezone.utc).isoformat()
    fake_client = MagicMock()
    fake_client.api_key = "fake-key"
    fake_client.list_whatsapp_conversations = AsyncMock(return_value={
        "success": True,
        "conversations": [{
            "customer_id": 999, "phone": "+573001234567",
            "last_interaction": ahora,
        }],
        "total_pages": 1,
    })
    fake_client.get_customer_messages = AsyncMock(return_value={
        "success": True,
        "messages": [{
            "id": "msg-1",  # ya visto
            "direction": "inbound",
            "content_text": "ya vi este",
            "created_time": ahora,
        }],
        "total_pages": 1,
    })

    with patch(
        "services.mercately.inbound_poller.get_mercately_client",
        return_value=fake_client,
    ):
        res = await poll_once(db)

    assert res["ok"] is True
    assert res["mensajes_procesados"] == 0, "msg-1 ya fue visto, no reprocesar"
    assert db.roddos_events.insert_one.await_count == 0
