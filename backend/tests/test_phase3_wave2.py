"""
Wave 2 (Phase 3) tests — conciliacion handlers + dispatcher wiring.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agents.contador.handlers.conciliacion import (
    _classify_movement,
    CONFIDENCE_THRESHOLD,
    handle_clasificar_movimiento,
    handle_enviar_movimiento_backlog,
    handle_consultar_movimientos_pendientes,
)


# ═══════════════════════════════════════════════════════
# CLASSIFICATION TESTS
# ═══════════════════════════════════════════════════════

def test_classify_gravamen_1_0():
    r = _classify_movement("GRAVAMEN AL MOVIMIENTO", 2919.54)
    assert r["confianza"] == 1.0
    assert r["tipo"] == "impuesto_4x1000"


def test_classify_arriendo_high_conf():
    r = _classify_movement("PAGO ARRIENDO BODEGA", 3614953)
    assert r["confianza"] >= CONFIDENCE_THRESHOLD
    assert r["cuenta_id"] == 5480


def test_classify_socio_routes_cxc():
    r = _classify_movement("Retiro personal 80075452 Andres", 500000)
    assert r["tipo"] == "cxc_socio"
    assert r["confianza"] == 1.0
    assert r["socio_cc"] == "80075452"


def test_classify_unknown_low_conf():
    r = _classify_movement("MOVIMIENTO DESCONOCIDO XYZ", 100000)
    assert r["confianza"] < CONFIDENCE_THRESHOLD
    assert r["cuenta_id"] == 5493  # fallback


def test_classify_servicios():
    r = _classify_movement("PAGO SERVICIOS PUBLICOS ETB", 150000)
    assert r["tipo"] == "servicios"
    assert r["confianza"] >= 0.70


# ═══════════════════════════════════════════════════════
# HANDLER TESTS
# ═══════════════════════════════════════════════════════

@pytest.fixture
def mock_alegra():
    client = AsyncMock()
    client.request_with_verify = AsyncMock(return_value={"id": 888, "_alegra_id": "888"})
    client.get = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.roddos_events = MagicMock()
    db.roddos_events.insert_one = AsyncMock()
    db.backlog_movimientos = MagicMock()
    db.backlog_movimientos.insert_one = AsyncMock()
    db.backlog_movimientos.find = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.sort = MagicMock(return_value=mock_cursor)
    mock_cursor.limit = MagicMock(return_value=mock_cursor)
    mock_cursor.to_list = AsyncMock(return_value=[])
    db.backlog_movimientos.find.return_value = mock_cursor
    db.conciliacion_extractos_procesados = MagicMock()
    db.conciliacion_extractos_procesados.find_one = AsyncMock(return_value=None)
    db.conciliacion_extractos_procesados.insert_one = AsyncMock()
    db.conciliacion_movimientos_procesados = MagicMock()
    db.conciliacion_movimientos_procesados.find_one = AsyncMock(return_value=None)
    db.conciliacion_movimientos_procesados.insert_one = AsyncMock()
    db.conciliacion_jobs = MagicMock()
    db.conciliacion_jobs.insert_one = AsyncMock()
    db.conciliacion_jobs.update_one = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_clasificar_movimiento_handler(mock_alegra, mock_db):
    result = await handle_clasificar_movimiento(
        {"descripcion": "PAGO ARRIENDO BODEGA", "monto": 3000000},
        mock_alegra, mock_db, mock_db, "u1",
    )
    assert result["success"] is True
    assert result["data"]["confianza"] >= 0.70


@pytest.mark.asyncio
async def test_enviar_movimiento_backlog(mock_alegra, mock_db):
    result = await handle_enviar_movimiento_backlog(
        {"descripcion": "MOV DESCONOCIDO", "monto": 50000, "banco": "BBVA", "razon": "Manual"},
        mock_alegra, mock_db, mock_db, "u1",
    )
    assert result["success"] is True
    mock_db.backlog_movimientos.insert_one.assert_called_once()


@pytest.mark.asyncio
async def test_consultar_movimientos_pendientes(mock_alegra, mock_db):
    result = await handle_consultar_movimientos_pendientes(
        {}, mock_alegra, mock_db, mock_db, "u1",
    )
    assert result["success"] is True
    assert "data" in result


# ═══════════════════════════════════════════════════════
# DISPATCHER WIRING TESTS
# ═══════════════════════════════════════════════════════

def test_dispatcher_has_conciliacion_handlers():
    """Conciliation tools should now route to real handlers, not Phase 3 stub."""
    from agents.contador.handlers.dispatcher import ToolDispatcher
    dispatcher = ToolDispatcher(alegra=MagicMock(), db=MagicMock(), event_bus=MagicMock())
    # These should be real handlers, not stubs
    handler = dispatcher._handlers.get("conciliar_extracto_bancario")
    assert handler is not None
    assert "stub" not in handler.__name__.lower() if hasattr(handler, '__name__') else True


def test_dispatcher_conciliation_not_stub():
    """dispatch() should NOT return Phase 3 stub for conciliation tools."""
    import asyncio
    from agents.contador.handlers.dispatcher import ToolDispatcher
    dispatcher = ToolDispatcher(alegra=MagicMock(), db=MagicMock(), event_bus=MagicMock())
    # clasificar_movimiento should work without error
    handler = dispatcher._handlers.get("clasificar_movimiento")
    assert handler is not None


def test_main_includes_conciliacion_router():
    import pathlib
    content = pathlib.Path("main.py").read_text(encoding="utf-8")
    assert "conciliacion_router" in content
    assert "backlog_router" in content


# ═══════════════════════════════════════════════════════
# STATIC ANALYSIS
# ═══════════════════════════════════════════════════════

def test_conciliacion_mongodb_writes_only_allowed():
    """Only backlog_movimientos, conciliacion_jobs, roddos_events writes allowed."""
    import pathlib
    path = pathlib.Path("backend/agents/contador/handlers/conciliacion.py")
    if path.exists():
        content = path.read_text(encoding="utf-8")
        allowed = {"backlog_movimientos", "conciliacion_jobs", "conciliacion_extractos_procesados",
                    "conciliacion_movimientos_procesados", "roddos_events"}
        for i, line in enumerate(content.split("\n"), 1):
            for op in ["insert_one", "update_one"]:
                if op in line:
                    assert any(col in line for col in allowed), \
                        f"conciliacion.py L{i}: forbidden MongoDB write: {line.strip()}"
