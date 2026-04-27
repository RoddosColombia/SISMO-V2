"""
Tests para el sistema de API keys read-only de integraciones externas (ARGOS).

test_health_sin_key_devuelve_200          — /health es público, sin key → 200
test_repuestos_sin_key_devuelve_401       — /repuestos sin key → 401
test_repuestos_con_key_valida_devuelve_lista — key válida → 200 con lista
test_repuestos_estructura_campos          — campos requeridos presentes y sin PII
test_cartera_resumen_con_key_valida       — cartera/resumen con key válida → 200
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient


# ─────────────────────── Helpers ─────────────────────────────────────────────

def _make_api_key_doc(scope: str = "read_only", active: bool = True) -> dict:
    return {
        "_id": "fake-oid",
        "key": "sk-sismo-testkey1234",
        "name": "ARGOS Integration",
        "scope": scope,
        "active": active,
        "last_used_at": None,
    }


def _make_app(
    api_key_doc: dict | None = None,
    repuestos: list | None = None,
    motos: list | None = None,
    loanbook: list | None = None,
):
    """Construye la FastAPI app con db totalmente mockeada."""
    from fastapi import FastAPI
    from routers.integraciones import router
    from core.database import get_db

    app = FastAPI()
    app.include_router(router)

    mock_db = MagicMock()

    # api_keys
    mock_db.api_keys.find_one = AsyncMock(return_value=api_key_doc)
    mock_db.api_keys.update_one = AsyncMock()

    # inventario_repuestos
    rep_cursor = MagicMock()
    rep_cursor.to_list = AsyncMock(return_value=repuestos or [])
    mock_db.inventario_repuestos.find = MagicMock(return_value=rep_cursor)

    # inventario_motos
    moto_cursor = MagicMock()
    moto_cursor.to_list = AsyncMock(return_value=motos or [])
    mock_db.inventario_motos.find = MagicMock(return_value=moto_cursor)

    # loanbook
    lb_cursor = MagicMock()
    lb_cursor.to_list = AsyncMock(return_value=loanbook or [])
    mock_db.loanbook.find = MagicMock(return_value=lb_cursor)

    app.dependency_overrides[get_db] = lambda: mock_db
    return app


_REPUESTOS_SEED = [
    {
        "sku": "REP-TVS-CDI-001",
        "nombre": "CDI TVS Sport 100",
        "categoria": "electrico",
        "marca_compatible": "TVS Sport 100",
        "precio_venta": 85_000,
        "precio_costo": 55_000,
        "stock": 0,
        "estado": "agotado",
        "proveedor": "Auteco",
        "ultima_actualizacion": "2026-04-25T00:00:00+00:00",
    },
    {
        "sku": "REP-RAI-BUJIA-006",
        "nombre": "Bujía Raider 125 (NGK)",
        "categoria": "encendido",
        "marca_compatible": "Raider 125",
        "precio_venta": 15_000,
        "precio_costo": 8_000,
        "stock": 2,
        "estado": "disponible",
        "proveedor": "NGK",
        "ultima_actualizacion": "2026-04-25T00:00:00+00:00",
    },
]


# ─────────────────────── Test 1 — /health público ────────────────────────────

def test_health_sin_key_devuelve_200():
    """/health no requiere API key — cualquier request → 200."""
    app = _make_app()
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/api/integraciones/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["fuente"] == "sismo_v2"
    assert "timestamp" in data


# ─────────────────────── Test 2 — /repuestos sin key ─────────────────────────

def test_repuestos_sin_key_devuelve_401():
    """/repuestos sin X-API-Key header → 401."""
    app = _make_app(api_key_doc=_make_api_key_doc())
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/api/integraciones/repuestos")

    assert resp.status_code == 401
    detail = resp.json().get("detail", "")
    assert "X-API-Key" in detail or "api" in detail.lower()


# ─────────────────────── Test 3 — /repuestos con key válida ──────────────────

def test_repuestos_con_key_valida_devuelve_lista():
    """Key válida con scope=read_only → 200 con lista de repuestos."""
    app = _make_app(api_key_doc=_make_api_key_doc(), repuestos=_REPUESTOS_SEED)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get(
        "/api/integraciones/repuestos",
        headers={"X-API-Key": "sk-sismo-testkey1234"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["disponibles"] == 1          # solo REP-RAI-BUJIA-006 tiene stock > 0
    assert len(data["repuestos"]) == 2
    assert data["fuente"] == "sismo_v2"
    assert "timestamp" in data


# ─────────────────────── Test 4 — estructura de campos ───────────────────────

def test_repuestos_estructura_campos():
    """Cada repuesto tiene los campos requeridos y NINGÚN campo PII."""
    app = _make_app(api_key_doc=_make_api_key_doc(), repuestos=_REPUESTOS_SEED)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get(
        "/api/integraciones/repuestos",
        headers={"X-API-Key": "sk-sismo-testkey1234"},
    )

    assert resp.status_code == 200
    campos_requeridos = {
        "sku", "nombre", "categoria", "marca_compatible",
        "precio_venta", "precio_costo", "stock", "estado",
        "proveedor", "ultima_actualizacion",
    }
    campos_pii = {"cliente", "nombre_cliente", "cedula", "telefono", "direccion"}

    for rep in resp.json()["repuestos"]:
        assert campos_requeridos.issubset(rep.keys()), \
            f"Faltan campos en: {rep.get('sku')}"
        for pii in campos_pii:
            assert pii not in rep, f"Campo PII encontrado: {pii}"

    # El primer repuesto coincide con seed
    primer = resp.json()["repuestos"][0]
    assert primer["sku"] == "REP-TVS-CDI-001"
    assert primer["precio_venta"] == 85_000
    assert primer["stock"] == 0
    assert primer["estado"] == "agotado"


# ─────────────────────── Test 5 — cartera/resumen con key ────────────────────

def test_cartera_resumen_con_key_valida():
    """cartera/resumen con key válida → 200 con KPIs."""
    lb_data = [
        {
            "estado": "activo",
            "saldo_capital": 5_000_000,
            "saldo_intereses": 200_000,
            "dpd": 0,
            "modalidad": "semanal",
            "cuota_monto": 120_000,
        },
        {
            "estado": "activo",
            "saldo_capital": 3_500_000,
            "saldo_intereses": 80_000,
            "dpd": 8,
            "modalidad": "quincenal",
            "cuota_monto": 200_000,
        },
    ]
    app = _make_app(api_key_doc=_make_api_key_doc(), loanbook=lb_data)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get(
        "/api/integraciones/cartera/resumen",
        headers={"X-API-Key": "sk-sismo-testkey1234"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["creditos_activos"] == 2
    assert data["creditos_en_mora"] == 1
    assert data["cartera_total_cop"] == 5_000_000 + 200_000 + 3_500_000 + 80_000
    assert data["recaudo_semanal_proyectado_cop"] == 120_000 + 100_000  # 200k quincenal / 2
    assert data["tasa_mora_pct"] == 50.0
    assert data["fuente"] == "sismo_v2"
    assert "fecha" in data
    # Sin PII
    assert "cliente" not in data
    assert "nombre" not in data
