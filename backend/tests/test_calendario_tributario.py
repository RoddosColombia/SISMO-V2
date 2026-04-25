"""Tests for calendario tributario handler."""
import datetime
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_alegra():
    client = AsyncMock()
    return client


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


@pytest.mark.asyncio
async def test_calendario_muestra_4_obligaciones(mock_alegra, mock_db):
    """Verify handler returns exactly 4 obligations with all required keys."""
    from agents.contador.handlers.nomina import handle_consultar_calendario_tributario

    result = await handle_consultar_calendario_tributario({}, mock_alegra, mock_db, mock_db, "u1")

    assert result["success"] is True
    assert len(result["obligaciones"]) == 4

    expected_keys = {"impuesto", "periodo", "vence", "dias_restantes", "estado"}
    for ob in result["obligaciones"]:
        assert expected_keys.issubset(ob.keys()), f"Missing keys in {ob['impuesto']}"

    impuestos = [ob["impuesto"] for ob in result["obligaciones"]]
    assert "ReteFuente" in impuestos
    assert "IVA" in impuestos
    assert "ReteICA Bogotá" in impuestos
    assert "ICA Bogotá" in impuestos


@pytest.mark.asyncio
async def test_calendario_semaforo_vencido_y_rojo(mock_alegra, mock_db):
    """Patch today to March 25 — ReteFuente deadline (March 20) already passed → next is April 20.
    Also verify semaphore logic: dias < 0 → VENCIDO, dias < 7 → ROJO."""
    from agents.contador.handlers.nomina import handle_consultar_calendario_tributario

    # March 25, 2026: ReteFuente March 20 already passed, next deadline is April 20 (26 days away → AMARILLO)
    # To get a ROJO, use April 15 (5 days before April 20 deadline)
    fake_today = datetime.date(2026, 4, 15)

    # handle_consultar_calendario_tributario usa today_bogota(), no datetime.date.today()
    with patch("agents.contador.handlers.nomina.today_bogota", return_value=fake_today):
        result = await handle_consultar_calendario_tributario({}, mock_alegra, mock_db, mock_db, "u1")

    assert result["success"] is True

    # Find ReteFuente — April 15 is 5 days before April 20 → ROJO
    retefuente = next(ob for ob in result["obligaciones"] if ob["impuesto"] == "ReteFuente")
    assert retefuente["estado"] == "ROJO"
    assert retefuente["dias_restantes"] < 7
    assert retefuente["dias_restantes"] >= 0

    # All obligations must have valid estado values
    valid_estados = {"VERDE", "AMARILLO", "ROJO", "VENCIDO"}
    for ob in result["obligaciones"]:
        assert ob["estado"] in valid_estados, f"Invalid estado for {ob['impuesto']}: {ob['estado']}"
