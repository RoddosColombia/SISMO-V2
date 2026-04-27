"""
Tests para el sistema de API keys read-only de integraciones externas.

test_api_key_invalida_devuelve_401      — key no registrada → 401
test_api_key_valida_devuelve_inventario — key válida → 200 con inventario
test_jwt_normal_no_accede_sin_key       — sin X-API-Key header → 401
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


# ─────────────────────── App fixture ─────────────────────────────────────────

def _make_api_key_doc(scope: str = "read_only", active: bool = True) -> dict:
    return {
        "_id": "fake-oid",
        "key": "sk-sismo-testkey1234",
        "name": "Test Integration",
        "scope": scope,
        "active": active,
        "last_used_at": None,
    }


def _make_app(api_key_doc: dict | None = None, inventario: list | None = None):
    """Construye la FastAPI app con db mockeada."""
    from fastapi import FastAPI
    from routers.integraciones import router

    app = FastAPI()
    app.include_router(router)

    # Mock db
    mock_db = MagicMock()

    # api_keys.find_one: retorna doc o None
    mock_db.api_keys.find_one = AsyncMock(return_value=api_key_doc)
    mock_db.api_keys.update_one = AsyncMock()

    # inventario_motos.find().to_list()
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=inventario or [])
    mock_db.inventario_motos.find = MagicMock(return_value=mock_cursor)

    # loanbook.find().to_list()
    lb_cursor = MagicMock()
    lb_cursor.to_list = AsyncMock(return_value=[])
    mock_db.loanbook.find = MagicMock(return_value=lb_cursor)

    # Override get_db dependency
    from core.database import get_db
    app.dependency_overrides[get_db] = lambda: mock_db

    return app


# ─────────────────────── Test 1 — key inválida → 401 ─────────────────────────

def test_api_key_invalida_devuelve_401():
    """Key no registrada en MongoDB → 401 Unauthorized."""
    # api_keys.find_one retorna None (key no existe)
    app = _make_app(api_key_doc=None)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get(
        "/api/integraciones/inventario",
        headers={"X-API-Key": "sk-sismo-keyinvalida"},
    )

    assert resp.status_code == 401
    assert "inválida" in resp.json().get("detail", "").lower() or \
           "invalida" in resp.json().get("detail", "").lower()


# ─────────────────────── Test 2 — key válida → inventario ────────────────────

def test_api_key_valida_devuelve_inventario():
    """Key válida con scope=read_only → 200 con lista de inventario."""
    motos = [
        {"vin": "VIN001", "modelo": "Raider 125", "estado": "disponible", "color": "rojo", "placa": ""},
        {"vin": "VIN002", "modelo": "TVS Sport",  "estado": "entregada",  "color": "azul", "placa": "XYZ123"},
    ]
    app = _make_app(api_key_doc=_make_api_key_doc(), inventario=motos)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get(
        "/api/integraciones/inventario",
        headers={"X-API-Key": "sk-sismo-testkey1234"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["inventario"]) == 2
    assert data["inventario"][0]["vin"] == "VIN001"
    assert data["fuente"] == "sismo_v2"
    # Sin PII — no hay campos de cliente
    for item in data["inventario"]:
        assert "cliente" not in item
        assert "nombre" not in item
        assert "cedula" not in item


# ─────────────────────── Test 3 — sin key → 401 ──────────────────────────────

def test_jwt_normal_no_accede_sin_key():
    """Sin X-API-Key header (aunque tenga JWT en Authorization) → 401."""
    app = _make_app(api_key_doc=_make_api_key_doc())
    client = TestClient(app, raise_server_exceptions=False)

    # Sin X-API-Key header
    resp = client.get(
        "/api/integraciones/inventario",
        headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.fake.jwt"},
    )

    assert resp.status_code == 401
    detail = resp.json().get("detail", "")
    assert "X-API-Key" in detail or "api" in detail.lower()
