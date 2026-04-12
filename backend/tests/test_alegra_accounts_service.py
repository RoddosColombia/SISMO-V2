"""Tests for AlegraAccountsService — ROG-4 compliant account resolution."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from services.alegra_accounts import AlegraAccountsService, FALLBACK_IDS


def _make_service(categories=None):
    """Create service with mocked AlegraClient."""
    mock_alegra = MagicMock()
    if categories is not None:
        mock_alegra.get = AsyncMock(return_value=categories)
    else:
        mock_alegra.get = AsyncMock(side_effect=Exception("Alegra down"))
    return AlegraAccountsService(mock_alegra), mock_alegra


@pytest.mark.asyncio
async def test_get_cxc_socios_id():
    """CXC Socios always returns 5329."""
    svc, _ = _make_service()
    assert await svc.get_cxc_socios_id() == "5329"


@pytest.mark.asyncio
async def test_get_ingreso_id_financieros():
    """ingresos_financieros maps to 5456."""
    svc, _ = _make_service()
    assert await svc.get_ingreso_id("ingresos_financieros") == "5456"


@pytest.mark.asyncio
async def test_get_ingreso_id_otros_fallback():
    """Unknown tipo falls back to 5436 (Otros ingresos)."""
    svc, _ = _make_service()
    assert await svc.get_ingreso_id("tipo_desconocido") == "5436"


@pytest.mark.asyncio
async def test_cache_calls_alegra_once():
    """GET /categories called once, then cached for subsequent calls."""
    categories = [
        {"id": "5480", "name": "Arrendamientos", "children": []},
        {"id": "5462", "name": "Sueldos y salarios", "children": []},
    ]
    svc, mock = _make_service(categories)

    result1 = await svc.get_account_id("Arrendamientos")
    result2 = await svc.get_account_id("Sueldos y salarios")

    assert result1 == "5480"
    assert result2 == "5462"
    mock.get.assert_called_once()  # Only one API call, cached


@pytest.mark.asyncio
async def test_partial_name_match():
    """Partial name matching works."""
    categories = [
        {"id": "5487", "name": "Teléfono / Internet", "children": []},
    ]
    svc, _ = _make_service(categories)
    result = await svc.get_account_id("teléfono")
    assert result == "5487"


@pytest.mark.asyncio
async def test_nested_children_flattened():
    """Nested category tree is flattened correctly."""
    categories = [
        {
            "id": "5308",
            "name": "Bancos",
            "children": [
                {"id": "5314", "name": "Bancolombia 2029", "children": []},
                {"id": "5315", "name": "Bancolombia 2540", "children": []},
            ],
        },
    ]
    svc, _ = _make_service(categories)
    assert await svc.get_account_id("Bancolombia 2029") == "5314"
    assert await svc.get_account_id("Bancolombia 2540") == "5315"


@pytest.mark.asyncio
async def test_fallback_when_alegra_down():
    """When Alegra is unreachable, uses hardcoded fallback map."""
    svc, _ = _make_service(categories=None)  # Will raise exception
    result = await svc.get_account_id("Arrendamientos")
    assert result == "5480"  # From FALLBACK_IDS


@pytest.mark.asyncio
async def test_unknown_account_returns_fallback_gasto():
    """Unknown account name returns 5494 (fallback gasto)."""
    categories = [{"id": "5480", "name": "Arrendamientos", "children": []}]
    svc, _ = _make_service(categories)
    result = await svc.get_account_id("Cuenta Inventada XYZ")
    assert result == "5494"


@pytest.mark.asyncio
async def test_get_retencion_id():
    """Retention IDs resolve by tipo."""
    svc, _ = _make_service()
    assert await svc.get_retencion_id("arriendo") == "5386"
    assert await svc.get_retencion_id("servicios") == "5383"
    assert await svc.get_retencion_id("honorarios_pn") == "5381"
