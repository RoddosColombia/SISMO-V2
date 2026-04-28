"""Tests para los nuevos métodos del MercatelyClient (Sprint S2)."""
from __future__ import annotations
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from services.mercately.client import MercatelyClient, get_mercately_client


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("MERCATELY_API_KEY", "test-key")


@pytest.mark.asyncio
async def test_get_customer_by_phone_encuentra():
    client = MercatelyClient()
    fake_resp = MagicMock(status_code=200)
    fake_resp.json = MagicMock(return_value={"customers": [{"id": "abc", "phone": "573001234567"}]})

    with patch("httpx.AsyncClient") as mock_http:
        ac = AsyncMock()
        ac.get = AsyncMock(return_value=fake_resp)
        mock_http.return_value.__aenter__.return_value = ac
        out = await client.get_customer_by_phone("3001234567")
    assert out["success"] is True
    assert out["found"] is True
    assert out["customer"]["id"] == "abc"


@pytest.mark.asyncio
async def test_get_customer_by_phone_no_encuentra():
    client = MercatelyClient()
    fake_resp = MagicMock(status_code=200)
    fake_resp.json = MagicMock(return_value={"customers": []})

    with patch("httpx.AsyncClient") as mock_http:
        ac = AsyncMock()
        ac.get = AsyncMock(return_value=fake_resp)
        mock_http.return_value.__aenter__.return_value = ac
        out = await client.get_customer_by_phone("3001234567")
    assert out["success"] is True
    assert out["found"] is False


@pytest.mark.asyncio
async def test_create_customer_exito():
    client = MercatelyClient()
    fake_resp = MagicMock(status_code=201)
    fake_resp.headers = {"content-type": "application/json"}
    fake_resp.json = MagicMock(return_value={"id": "new-customer", "phone": "573001234567"})

    with patch("httpx.AsyncClient") as mock_http:
        ac = AsyncMock()
        ac.post = AsyncMock(return_value=fake_resp)
        mock_http.return_value.__aenter__.return_value = ac
        out = await client.create_customer(
            phone_number="3001234567", first_name="Juan", last_name="Perez",
            id_number="1234567", tags=["nuevo"],
        )
    assert out["success"] is True
    assert out["customer"]["id"] == "new-customer"


@pytest.mark.asyncio
async def test_update_customer_tags_noop_si_no_hay_cambios():
    client = MercatelyClient()
    out = await client.update_customer_tags("3001234567")  # sin add ni remove
    assert out["success"] is True
    assert out.get("noop") is True


@pytest.mark.asyncio
async def test_update_customer_tags_exito():
    client = MercatelyClient()
    fake_resp = MagicMock(status_code=200)
    with patch("httpx.AsyncClient") as mock_http:
        ac = AsyncMock()
        ac.patch = AsyncMock(return_value=fake_resp)
        mock_http.return_value.__aenter__.return_value = ac
        out = await client.update_customer_tags(
            "3001234567", add_tags=["mora"], remove_tags=["al_dia"]
        )
    assert out["success"] is True
    assert "mora" in out["tags_added"]
    assert "al_dia" in out["tags_removed"]


@pytest.mark.asyncio
async def test_send_text_exito():
    client = MercatelyClient()
    fake_resp = MagicMock(status_code=200)
    fake_resp.json = MagicMock(return_value={"id": "msg-123"})
    with patch("httpx.AsyncClient") as mock_http:
        ac = AsyncMock()
        ac.post = AsyncMock(return_value=fake_resp)
        mock_http.return_value.__aenter__.return_value = ac
        out = await client.send_text("3001234567", "Hola Juan")
    assert out["success"] is True
    assert out["message_id"] == "msg-123"


@pytest.mark.asyncio
async def test_get_customer_sin_apikey_devuelve_error(monkeypatch):
    monkeypatch.delenv("MERCATELY_API_KEY", raising=False)
    client = MercatelyClient()
    out = await client.get_customer_by_phone("3001234567")
    assert out["success"] is False


def test_singleton_get_mercately_client():
    a = get_mercately_client()
    b = get_mercately_client()
    assert a is b
