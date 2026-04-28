"""Tests para webhook entrante POST /api/webhooks/mercately/inbound."""
from __future__ import annotations
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from main import app
from core.database import get_db


def _hmac_sha256(secret: str, body_bytes: bytes) -> str:
    return hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()


@pytest.fixture
def mock_db():
    db = MagicMock()
    for col in ("crm_clientes", "roddos_events"):
        c = MagicMock()
        c.find_one = AsyncMock(return_value=None)
        c.update_one = AsyncMock()
        c.insert_one = AsyncMock()
        setattr(db, col, c)
    return db


@pytest.fixture
def client_with_mock_db(mock_db):
    async def fake_get_db():
        return mock_db
    app.dependency_overrides[get_db] = fake_get_db
    yield mock_db
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_mercately_health_responde_200():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/webhooks/mercately/health")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_mercately_inbound_rechaza_sin_firma_si_secret_configurado(monkeypatch, client_with_mock_db):
    monkeypatch.setenv("MERCATELY_WEBHOOK_SECRET", "secretmercately")
    transport = ASGITransport(app=app)
    body = {"event": "incoming_message", "data": {"phone_number": "573001234567", "message": "ok"}}
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/webhooks/mercately/inbound", json=body)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_mercately_inbound_acepta_firma_valida_publica_evento(monkeypatch, client_with_mock_db):
    monkeypatch.setenv("MERCATELY_WEBHOOK_SECRET", "secretmercately")
    body = {
        "event": "incoming_message",
        "data": {
            "phone_number": "573001234567",
            "message": "voy a pagar mañana",
            "type": "text",
        },
    }
    raw = json.dumps(body).encode()
    sig = _hmac_sha256("secretmercately", raw)

    # Simular cliente CRM existente con ese phone
    client_with_mock_db.crm_clientes.find_one = AsyncMock(
        return_value={"_id": "obj1", "cedula": "1234567", "mercately_phone": "573001234567"}
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/webhooks/mercately/inbound",
            content=raw,
            headers={"X-Mercately-Signature": f"sha256={sig}"},
        )
    assert r.status_code == 200
    body_resp = r.json()
    assert body_resp["ok"] is True
    assert body_resp["cliente_encontrado"] is True
    assert body_resp["cedula"] == "1234567"
    # Verifica que se publico el evento
    client_with_mock_db.roddos_events.insert_one.assert_called_once()
    client_with_mock_db.crm_clientes.update_one.assert_called_once()


@pytest.mark.asyncio
async def test_mercately_inbound_phone_invalido_rechaza(monkeypatch, client_with_mock_db):
    monkeypatch.delenv("MERCATELY_WEBHOOK_SECRET", raising=False)
    body = {"event": "incoming_message", "data": {"phone_number": "abc", "message": "x"}}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/webhooks/mercately/inbound", json=body)
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert r.json()["reason"] == "phone_invalid"
