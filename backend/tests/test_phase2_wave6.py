"""Wave 6 tests — nomina + cartera + catalogo handlers."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_alegra():
    client = AsyncMock()
    client.request_with_verify = AsyncMock(return_value={"id": 333, "_alegra_id": "333"})
    client.get = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.roddos_events = MagicMock()
    db.roddos_events.insert_one = AsyncMock()
    db.loanbook = MagicMock()
    db.loanbook.find_one = AsyncMock(return_value={"loanbook_id": "LB-001", "factura_alegra_id": "500"})
    db.loanbook.update_one = AsyncMock()
    db.loanbook.find = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.sort = MagicMock(return_value=mock_cursor)
    mock_cursor.limit = MagicMock(return_value=mock_cursor)
    mock_cursor.to_list = AsyncMock(return_value=[{"loanbook_id": "LB-001", "estado": "activo"}])
    db.loanbook.find.return_value = mock_cursor
    return db


# --- Nomina tests ---

@pytest.mark.asyncio
async def test_nomina_creates_journal_per_employee(mock_alegra, mock_db):
    from agents.contador.handlers.nomina import handle_registrar_nomina_mensual
    tool_input = {
        "mes": 3, "anio": 2026,
        "empleados": [{"nombre": "Alexa", "salario": 3220000}],
    }
    with patch("agents.contador.handlers.nomina.validate_write_permission"):
        with patch("agents.contador.handlers.nomina.publish_event", new_callable=AsyncMock):
            result = await handle_registrar_nomina_mensual(tool_input, mock_alegra, mock_db, mock_db, "u1")
            assert result["success"] is True
            mock_alegra.request_with_verify.assert_called_once()


@pytest.mark.asyncio
async def test_nomina_antidup_blocks_duplicate(mock_alegra, mock_db):
    from agents.contador.handlers.nomina import handle_registrar_nomina_mensual
    mock_alegra.get = AsyncMock(return_value=[{"observations": "Nómina Alexa 3/2026", "id": 1}])
    tool_input = {
        "mes": 3, "anio": 2026,
        "empleados": [{"nombre": "Alexa", "salario": 3220000}],
    }
    with patch("agents.contador.handlers.nomina.validate_write_permission"):
        with patch("agents.contador.handlers.nomina.publish_event", new_callable=AsyncMock):
            result = await handle_registrar_nomina_mensual(tool_input, mock_alegra, mock_db, mock_db, "u1")
            assert result["resultados"][0]["status"] == "duplicado"


@pytest.mark.asyncio
async def test_obligaciones_cuatrimestral(mock_alegra, mock_db):
    from agents.contador.handlers.nomina import handle_consultar_obligaciones_tributarias
    mock_alegra.get = AsyncMock(return_value=[
        {"entries": [{"account": {"id": 236505}, "credit": 50000}, {"account": {"id": 236560}, "credit": 5000}]}
    ])
    result = await handle_consultar_obligaciones_tributarias({"mes": 2, "anio": 2026}, mock_alegra, mock_db, mock_db, "u1")
    assert result["success"] is True
    assert result["cuatrimestre"] == "ene-abr"
    assert result["retefuente_acumulada"] == 50000.0


@pytest.mark.asyncio
async def test_calcular_retenciones_handler(mock_alegra, mock_db):
    from agents.contador.handlers.nomina import handle_calcular_retenciones
    result = await handle_calcular_retenciones(
        {"tipo": "arriendo", "monto": 3614953, "nit": None}, mock_alegra, mock_db, mock_db, "u1"
    )
    assert result["success"] is True
    assert result["data"]["retefuente_tasa"] == 0.035


@pytest.mark.asyncio
async def test_calcular_retenciones_auteco(mock_alegra, mock_db):
    from agents.contador.handlers.nomina import handle_calcular_retenciones
    result = await handle_calcular_retenciones(
        {"tipo": "compras", "monto": 5000000, "nit": "860024781"}, mock_alegra, mock_db, mock_db, "u1"
    )
    assert result["autoretenedor"] is True
    assert result["data"]["retefuente_monto"] == 0.0


# --- Cartera tests ---

@pytest.mark.asyncio
async def test_pago_cuota_posts_payment(mock_alegra, mock_db):
    from agents.contador.handlers.cartera import handle_registrar_pago_cuota
    tool_input = {"loanbook_id": "LB-001", "monto": 175000, "banco": "Bancolombia", "numero_cuota": 5}
    with patch("agents.contador.handlers.cartera.validate_write_permission"):
        with patch("agents.contador.handlers.cartera.publish_event", new_callable=AsyncMock):
            result = await handle_registrar_pago_cuota(tool_input, mock_alegra, mock_db, mock_db, "u1")
            assert result["success"] is True
            mock_alegra.request_with_verify.assert_called_once()


@pytest.mark.asyncio
async def test_consultar_cartera_readonly(mock_alegra, mock_db):
    from agents.contador.handlers.cartera import handle_consultar_cartera
    result = await handle_consultar_cartera({}, mock_alegra, mock_db, mock_db, "u1")
    assert result["success"] is True
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_catalogo_roddos_returns_data(mock_alegra, mock_db):
    from agents.contador.handlers.cartera import handle_consultar_catalogo_roddos
    result = await handle_consultar_catalogo_roddos({}, mock_alegra, mock_db, mock_db, "u1")
    assert result["success"] is True
    assert 5462 in result["data"]["gastos"]
    assert 5493 in result["data"]["gastos"]
    assert "860024781" in str(result["data"]["autoretenedores"])


def test_wave6_no_forbidden_mongodb_writes():
    import pathlib
    for fname in ["nomina.py", "cartera.py"]:
        path = pathlib.Path(f"backend/agents/contador/handlers/{fname}")
        if path.exists():
            content = path.read_text(encoding="utf-8")
            for op in ["insert_one", "insert_many", "replace_one"]:
                if op in content and "roddos_events" not in content.split(op)[0][-50:] and "loanbook" not in content.split(op)[0][-50:]:
                    lines = [f"L{i}: {l.strip()}" for i, l in enumerate(content.split("\n"), 1)
                             if op in l and "loanbook" not in l and "roddos_events" not in l]
                    assert len(lines) == 0, f"{fname} has forbidden writes: {lines}"
