"""
BUILD 0.1 (V2) test-gate — cartera_legacy router

Tests:
  1. Schema LoanbookLegacyDoc instanciable con campos requeridos
  2. Schema acepta pagos_recibidos
  3. GET /api/cartera-legacy/stats → 200 con success=True
  4. GET /api/cartera-legacy → 200 con success=True + lista vacía
  5. GET /api/cartera-legacy/{codigo} → 404 cuando no existe
  6. GET /api/cartera-legacy/{codigo} → 200 con _id eliminado
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

# ── 1-2. Schema unit tests (no DB needed) ─────────────────────────────────────

def test_loanbook_legacy_schema_minimal():
    """LoanbookLegacyDoc acepta los campos requeridos mínimos."""
    from routers.cartera_legacy import LoanbookLegacyDoc

    doc = LoanbookLegacyDoc(
        codigo_sismo="LG-80075452-45541",
        cedula="80075452",
        numero_credito_original="45541",
        nombre_completo="Andrés Sanjuan",
        aliado="RODDOS_Directo",
        estado="activo",
        estado_legacy_excel="En Mora",
        saldo_actual=5_000_000.0,
        saldo_inicial=5_000_000.0,
    )
    assert doc.codigo_sismo == "LG-80075452-45541"
    assert doc.saldo_actual == 5_000_000.0
    assert doc.pagos_recibidos == []
    assert doc.alegra_contact_id is None
    assert doc.placa is None


def test_loanbook_legacy_schema_con_pagos():
    """LoanbookLegacyDoc acepta pagos_recibidos."""
    from routers.cartera_legacy import LoanbookLegacyDoc, PagoRegistrado

    pago = PagoRegistrado(fecha="2026-03-15", monto=500_000.0, alegra_journal_id="J-123")
    doc = LoanbookLegacyDoc(
        codigo_sismo="LG-123-1",
        cedula="123",
        numero_credito_original="1",
        nombre_completo="Test Cliente",
        aliado="Motai",
        estado="activo",
        estado_legacy_excel="Al Día",
        saldo_actual=3_000_000.0,
        saldo_inicial=3_500_000.0,
        pagos_recibidos=[pago],
    )
    assert len(doc.pagos_recibidos) == 1
    assert doc.pagos_recibidos[0].monto == 500_000.0


# ── 3-6. Endpoint tests (mock get_db) ─────────────────────────────────────────

def _make_mock_db():
    """Return a MagicMock that mimics AsyncIOMotorDatabase."""
    mock_db = MagicMock()

    # aggregate returns an async iterator
    async def _empty_agg(*args, **kwargs):
        return
        yield  # noqa: unreachable — makes it an async generator

    mock_db.loanbook_legacy.aggregate = lambda pipeline: _empty_agg()
    mock_db.loanbook_legacy.count_documents = AsyncMock(return_value=0)

    # find().sort().skip().limit() chain → async iterator
    async def _empty_cursor():
        return
        yield

    mock_cursor = MagicMock()
    mock_cursor.sort.return_value = mock_cursor
    mock_cursor.skip.return_value = mock_cursor
    mock_cursor.limit.return_value = mock_cursor
    mock_cursor.to_list = AsyncMock(return_value=[])
    mock_db.loanbook_legacy.find.return_value = mock_cursor

    mock_db.loanbook_legacy.find_one = AsyncMock(return_value=None)
    return mock_db


@pytest.mark.asyncio
async def test_stats_returns_success():
    """GET /api/cartera-legacy/stats → success=True even with empty DB."""
    from routers.cartera_legacy import get_cartera_legacy_stats

    mock_db = _make_mock_db()

    result = await get_cartera_legacy_stats(
        db=mock_db,
        current_user={"id": "test", "role": "admin"},
    )

    assert result["success"] is True
    assert "data" in result


@pytest.mark.asyncio
async def test_list_returns_empty():
    """GET /api/cartera-legacy → success=True + [] cuando DB vacía."""
    from routers.cartera_legacy import list_cartera_legacy

    mock_db = _make_mock_db()

    result = await list_cartera_legacy(
        estado=None, aliado=None, en_mora=None,
        page=1, limit=50,
        db=mock_db,
        current_user={"id": "test", "role": "admin"},
    )

    assert result["success"] is True
    assert result["data"] == []
    assert result["total"] == 0


@pytest.mark.asyncio
async def test_detalle_404_on_unknown():
    """GET /api/cartera-legacy/{codigo} → 404 cuando no existe."""
    from routers.cartera_legacy import get_cartera_legacy_detalle
    from fastapi import HTTPException

    mock_db = _make_mock_db()
    # find_one already returns None in _make_mock_db

    with pytest.raises(HTTPException) as exc:
        await get_cartera_legacy_detalle(
            codigo="LG-NOEXISTE-99",
            db=mock_db,
            current_user={"id": "test", "role": "admin"},
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_detalle_200_strips_id():
    """GET /api/cartera-legacy/{codigo} → 200, _id eliminado del response."""
    from routers.cartera_legacy import get_cartera_legacy_detalle

    mock_doc = {
        "_id": "fake_oid",
        "codigo_sismo": "LG-80075452-45541",
        "cedula": "80075452",
        "numero_credito_original": "45541",
        "nombre_completo": "Andrés Sanjuan",
        "aliado": "RODDOS_Directo",
        "estado": "activo",
        "estado_legacy_excel": "En Mora",
        "saldo_actual": 5_000_000.0,
        "saldo_inicial": 5_000_000.0,
        "pagos_recibidos": [],
    }

    mock_db = _make_mock_db()
    mock_db.loanbook_legacy.find_one = AsyncMock(return_value=mock_doc)

    result = await get_cartera_legacy_detalle(
        codigo="LG-80075452-45541",
        db=mock_db,
        current_user={"id": "test", "role": "admin"},
    )

    assert result["success"] is True
    assert result["data"]["codigo_sismo"] == "LG-80075452-45541"
    assert "_id" not in result["data"]
