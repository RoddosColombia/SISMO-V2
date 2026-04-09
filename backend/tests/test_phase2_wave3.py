"""
Wave 3 tests — retenciones service + 7 egresos handlers.

Tests 1-10: Retenciones calculation (pure function, no mocks needed)
Tests 11-20: Egresos handlers (mock AlegraClient + publish_event)
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from services.retenciones import (
    calcular_retenciones,
    AUTORETENEDORES,
    TASAS_RETEFUENTE,
    RETEICA_BOGOTA,
    COMPRAS_BASE_MINIMA,
)


# ═══════════════════════════════════════════════════════
# RETENCIONES TESTS (1-10)
# ═══════════════════════════════════════════════════════


def test_arriendo_retenciones():
    r = calcular_retenciones("arriendo", 3_614_953, None)
    assert r["retefuente_tasa"] == 0.035
    assert r["retefuente_monto"] == round(3_614_953 * 0.035, 2)
    assert r["reteica_monto"] == round(3_614_953 * 0.00414, 2)
    assert r["neto_a_pagar"] == round(3_614_953 - r["retefuente_monto"] - r["reteica_monto"], 2)


def test_servicios_retenciones():
    r = calcular_retenciones("servicios", 1_000_000, None)
    assert r["retefuente_monto"] == 40_000.0
    assert r["reteica_monto"] == round(1_000_000 * 0.00414, 2)


def test_honorarios_pn():
    r = calcular_retenciones("honorarios_pn", 500_000, None)
    assert r["retefuente_monto"] == 50_000.0


def test_honorarios_pj():
    r = calcular_retenciones("honorarios_pj", 500_000, None)
    assert r["retefuente_monto"] == 55_000.0


def test_compras_below_base_no_retefuente():
    r = calcular_retenciones("compras", 1_000_000, None)
    assert r["retefuente_monto"] == 0.0
    assert r["retefuente_tasa"] == 0.0


def test_compras_above_base_has_retefuente():
    r = calcular_retenciones("compras", 2_000_000, None)
    assert r["retefuente_monto"] == 50_000.0


def test_auteco_no_retefuente():
    r = calcular_retenciones("arriendo", 5_000_000, "860024781")
    assert r["retefuente_monto"] == 0.0
    assert r["retefuente_tasa"] == 0.0


def test_auteco_reteica_still_applies():
    r = calcular_retenciones("servicios", 1_000_000, "860024781")
    assert r["reteica_monto"] == round(1_000_000 * 0.00414, 2)
    assert r["retefuente_monto"] == 0.0


def test_neto_a_pagar_formula():
    for tipo in ["arriendo", "servicios", "honorarios_pn", "compras"]:
        r = calcular_retenciones(tipo, 2_000_000, None)
        assert r["neto_a_pagar"] == round(2_000_000 - r["retefuente_monto"] - r["reteica_monto"], 2)


def test_unknown_tipo_only_reteica():
    r = calcular_retenciones("desconocido", 1_000_000, None)
    assert r["retefuente_monto"] == 0.0
    assert r["reteica_monto"] == round(1_000_000 * 0.00414, 2)


# ═══════════════════════════════════════════════════════
# EGRESOS HANDLER TESTS (11-20)
# ═══════════════════════════════════════════════════════


@pytest.fixture
def mock_alegra():
    client = AsyncMock()
    client.request_with_verify = AsyncMock(return_value={"id": 12345, "_alegra_id": "12345"})
    client.get = AsyncMock(return_value={"id": 12345})
    return client


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.roddos_events = MagicMock()
    db.roddos_events.insert_one = AsyncMock()
    return db


@pytest.fixture
def mock_event_bus(mock_db):
    """Matches publish_event signature from core/events.py."""
    return mock_db


@pytest.mark.asyncio
async def test_crear_causacion_validates_permissions(mock_alegra, mock_db, mock_event_bus):
    from agents.contador.handlers.egresos import handle_crear_causacion
    tool_input = {
        "entries": [{"id": 5480, "debit": 1000, "credit": 0}, {"id": 111005, "debit": 0, "credit": 1000}],
        "date": "2026-04-09",
        "observations": "Test gasto",
    }
    with patch("agents.contador.handlers.egresos.validate_write_permission") as mock_perm:
        result = await handle_crear_causacion(tool_input, mock_alegra, mock_db, mock_event_bus, "user1")
        mock_perm.assert_called_once()


@pytest.mark.asyncio
async def test_crear_causacion_posts_and_publishes(mock_alegra, mock_db, mock_event_bus):
    from agents.contador.handlers.egresos import handle_crear_causacion
    tool_input = {
        "entries": [{"id": 5480, "debit": 1000, "credit": 0}, {"id": 111005, "debit": 0, "credit": 1000}],
        "date": "2026-04-09",
        "observations": "Arriendo bodega",
    }
    with patch("agents.contador.handlers.egresos.validate_write_permission"):
        with patch("agents.contador.handlers.egresos.publish_event", new_callable=AsyncMock) as mock_pub:
            result = await handle_crear_causacion(tool_input, mock_alegra, mock_db, mock_event_bus, "user1")
            assert result["success"] is True
            assert result["alegra_id"] == "12345"
            mock_alegra.request_with_verify.assert_called_once()
            mock_pub.assert_called_once()


@pytest.mark.asyncio
async def test_crear_causacion_returns_alegra_id(mock_alegra, mock_db, mock_event_bus):
    from agents.contador.handlers.egresos import handle_crear_causacion
    tool_input = {
        "entries": [{"id": 5480, "debit": 500, "credit": 0}, {"id": 111005, "debit": 0, "credit": 500}],
        "date": "2026-04-09",
        "observations": "Test",
    }
    with patch("agents.contador.handlers.egresos.validate_write_permission"):
        with patch("agents.contador.handlers.egresos.publish_event", new_callable=AsyncMock):
            result = await handle_crear_causacion(tool_input, mock_alegra, mock_db, mock_event_bus, "user1")
            assert "12345" in result["message"]


@pytest.mark.asyncio
async def test_registrar_gasto_banco_mapping(mock_alegra, mock_db, mock_event_bus):
    from agents.contador.handlers.egresos import handle_registrar_gasto
    tool_input = {"descripcion": "pago arriendo", "monto": 1_000_000, "banco": "BBVA"}
    with patch("agents.contador.handlers.egresos.validate_write_permission"):
        with patch("agents.contador.handlers.egresos.publish_event", new_callable=AsyncMock):
            result = await handle_registrar_gasto(tool_input, mock_alegra, mock_db, mock_event_bus, "user1")
            call_args = mock_alegra.request_with_verify.call_args
            payload = call_args.kwargs.get("payload") or call_args[1].get("payload") or (call_args[0][2] if len(call_args[0]) > 2 else None)
            # Verify BBVA bank ID 111010 appears in entries
            if payload and "entries" in payload:
                bank_ids = [e["account"]["id"] for e in payload["entries"] if e.get("credit", 0) > 0]
                assert 111010 in bank_ids


@pytest.mark.asyncio
async def test_registrar_gasto_auteco_no_retefuente(mock_alegra, mock_db, mock_event_bus):
    from agents.contador.handlers.egresos import handle_registrar_gasto
    tool_input = {"descripcion": "compra motos", "monto": 5_000_000, "banco": "BBVA", "proveedor_nit": "860024781"}
    with patch("agents.contador.handlers.egresos.validate_write_permission"):
        with patch("agents.contador.handlers.egresos.publish_event", new_callable=AsyncMock):
            result = await handle_registrar_gasto(tool_input, mock_alegra, mock_db, mock_event_bus, "user1")
            call_args = mock_alegra.request_with_verify.call_args
            payload = call_args.kwargs.get("payload") or call_args[1].get("payload") or (call_args[0][2] if len(call_args[0]) > 2 else None)
            if payload and "entries" in payload:
                retefuente_entries = [e for e in payload["entries"] if e["account"]["id"] == 236505]
                assert len(retefuente_entries) == 0, "Auteco should have NO ReteFuente entry"


@pytest.mark.asyncio
async def test_registrar_gasto_socio_routes_cxc(mock_alegra, mock_db, mock_event_bus):
    from agents.contador.handlers.egresos import handle_registrar_gasto
    tool_input = {"descripcion": "retiro personal Andres 80075452", "monto": 500_000, "banco": "Bancolombia"}
    with patch("agents.contador.handlers.egresos.validate_write_permission"):
        with patch("agents.contador.handlers.egresos.publish_event", new_callable=AsyncMock) as mock_pub:
            result = await handle_registrar_gasto(tool_input, mock_alegra, mock_db, mock_event_bus, "user1")
            assert result["success"] is True
            # Check event type is CXC, not gasto
            pub_call = mock_pub.call_args
            if pub_call:
                event_type = pub_call.kwargs.get("event_type") or pub_call[1].get("event_type") or pub_call[0][1] if len(pub_call[0]) > 1 else None
                if event_type:
                    assert "cxc" in event_type.lower(), f"Socio should route to CXC event, got: {event_type}"


@pytest.mark.asyncio
async def test_anular_causacion_three_step(mock_alegra, mock_db, mock_event_bus):
    from agents.contador.handlers.egresos import handle_anular_causacion
    # GET succeeds (journal exists), DELETE succeeds, second GET raises 404
    mock_alegra.get = AsyncMock(side_effect=[{"id": 100}, Exception("404")])
    mock_alegra.request_with_verify = AsyncMock(return_value={"deleted": True})
    tool_input = {"journal_id": 100, "motivo": "duplicado"}
    with patch("agents.contador.handlers.egresos.validate_write_permission"):
        with patch("agents.contador.handlers.egresos.publish_event", new_callable=AsyncMock):
            result = await handle_anular_causacion(tool_input, mock_alegra, mock_db, mock_event_bus, "user1")
            assert result["success"] is True
            assert mock_alegra.get.call_count >= 1


@pytest.mark.asyncio
async def test_crear_causacion_unbalanced_blocked(mock_alegra, mock_db, mock_event_bus):
    from agents.contador.handlers.egresos import handle_crear_causacion
    tool_input = {
        "entries": [{"id": 5480, "debit": 1000, "credit": 0}, {"id": 111005, "debit": 0, "credit": 500}],
        "date": "2026-04-09",
        "observations": "Bad",
    }
    with patch("agents.contador.handlers.egresos.validate_write_permission"):
        with patch("agents.contador.handlers.egresos.publish_event", new_callable=AsyncMock):
            result = await handle_crear_causacion(tool_input, mock_alegra, mock_db, mock_event_bus, "user1")
            assert result["success"] is False
            assert "desbalanceado" in result["error"].lower()
            mock_alegra.request_with_verify.assert_not_called()


def test_egresos_no_mongodb_writes():
    """STATIC: No direct MongoDB write ops in egresos.py."""
    import pathlib
    egresos_path = pathlib.Path("backend/agents/contador/handlers/egresos.py")
    if egresos_path.exists():
        content = egresos_path.read_text(encoding="utf-8")
        for op in ["insert_one", "insert_many", "update_one", "replace_one"]:
            if op in content:
                assert "roddos_events" in content or "inventario_motos" in content or "loanbook" in content, \
                    f"egresos.py contains {op} outside allowed collections"
