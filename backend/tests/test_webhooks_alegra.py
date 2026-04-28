"""Tests para routers/webhooks.py — endpoint Alegra invoice.

Usa app.dependency_overrides para inyectar un MagicMock de get_db, asi
no requerimos MongoDB real ni init_db().
"""
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
    for col in ("loanbook", "roddos_events", "inventario_motos", "crm_clientes",
                "catalogo_planes", "datakeeper_processed", "datakeeper_cursor",
                "datakeeper_retries"):
        c = MagicMock()
        c.find_one = AsyncMock(return_value=None)
        c.insert_one = AsyncMock()
        c.update_one = AsyncMock()
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
async def test_alegra_health_get_responde_200():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/webhooks/alegra/health")
    assert r.status_code == 200
    assert r.json()["ok"] == "true"


@pytest.mark.asyncio
async def test_alegra_invoice_rechaza_sin_firma_si_secret_configurado(monkeypatch, client_with_mock_db):
    monkeypatch.setenv("ALEGRA_WEBHOOK_SECRET", "topsecret")
    transport = ASGITransport(app=app)
    body = {"event": "invoice.created", "data": {"id": "1"}}
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/webhooks/alegra/invoice", json=body)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_alegra_invoice_acepta_si_firma_valida_y_publica_evento(
    monkeypatch, client_with_mock_db
):
    monkeypatch.setenv("ALEGRA_WEBHOOK_SECRET", "topsecret")
    body = {
        "event": "invoice.created",
        "data": {
            "id": "12345",
            "client": {"name": "Juan", "identification": "1", "phonePrimary": "3001234567"},
            "items": [{"name": "TVS Raider 125 - VIN: VIN001 / Motor: M1"}],
            "observations": "Plan: P52S | Modalidad: semanal",
            "total": 7800000,
            "date": "2026-04-28",
        },
    }
    raw = json.dumps(body).encode("utf-8")
    sig = _hmac_sha256("topsecret", raw)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/webhooks/alegra/invoice",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Alegra-Signature": f"sha256={sig}",
            },
        )
    assert r.status_code == 200
    body_resp = r.json()
    assert body_resp["ok"] is True
    assert body_resp["event_published"] == "factura.venta.creada"
    assert body_resp["alegra_invoice_id"] == "12345"
    assert body_resp["vin"] == "VIN001"
    # Verificar que se inserto el evento en roddos_events
    client_with_mock_db.roddos_events.insert_one.assert_called_once()


@pytest.mark.asyncio
async def test_alegra_invoice_idempotente_si_loanbook_existe(
    monkeypatch, client_with_mock_db
):
    monkeypatch.setenv("ALEGRA_WEBHOOK_SECRET", "topsecret")
    # Simular loanbook ya existente
    client_with_mock_db.loanbook.find_one = AsyncMock(
        return_value={"loanbook_id": "lb-existing", "factura_alegra_id": "12345"}
    )
    body = {"event": "invoice.created", "data": {"id": "12345", "client": {}, "items": []}}
    raw = json.dumps(body).encode("utf-8")
    sig = _hmac_sha256("topsecret", raw)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/webhooks/alegra/invoice",
            content=raw,
            headers={"X-Alegra-Signature": f"sha256={sig}"},
        )
    assert r.status_code == 200
    assert r.json()["idempotent"] is True
    assert r.json()["loanbook_id"] == "lb-existing"
    # No debe haber publicado evento
    client_with_mock_db.roddos_events.insert_one.assert_not_called()


@pytest.mark.asyncio
async def test_alegra_invoice_rechaza_body_invalido(monkeypatch, client_with_mock_db):
    monkeypatch.delenv("ALEGRA_WEBHOOK_SECRET", raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/webhooks/alegra/invoice",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )
    assert r.status_code == 400
