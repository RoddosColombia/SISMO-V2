"""Wave 5 tests — 4 facturacion handlers with VIN enforcement."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_alegra():
    client = AsyncMock()
    client.request_with_verify = AsyncMock(return_value={"id": 777, "_alegra_id": "777"})
    client.get = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.roddos_events = MagicMock()
    db.roddos_events.insert_one = AsyncMock()
    db.inventario_motos = MagicMock()
    db.inventario_motos.find_one = AsyncMock(return_value={
        "vin": "9FL25AF31VDB95058", "motor": "BF3AT18C2356",
        "modelo": "TVS Raider 125", "color": "Negro Nebulosa",
        "estado": "disponible", "precio": 8500000,
    })
    db.inventario_motos.update_one = AsyncMock()
    db.loanbook = MagicMock()
    db.loanbook.insert_one = AsyncMock()
    db.loanbook.update_one = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_factura_blocks_without_vin(mock_alegra, mock_db):
    from agents.contador.handlers.facturacion import handle_crear_factura_venta_moto
    tool_input = {"cliente_nombre": "Juan", "cliente_cedula": "123", "moto_vin": "", "plan": "P52S"}
    with patch("agents.contador.handlers.facturacion.validate_write_permission"):
        result = await handle_crear_factura_venta_moto(tool_input, mock_alegra, mock_db, mock_db, "u1")
        assert result["success"] is False
        assert "VIN" in result["error"]
        mock_alegra.request_with_verify.assert_not_called()


@pytest.mark.asyncio
async def test_factura_blocks_without_motor(mock_alegra, mock_db):
    from agents.contador.handlers.facturacion import handle_crear_factura_venta_moto
    mock_db.inventario_motos.find_one = AsyncMock(return_value={
        "vin": "ABC123", "motor": "", "modelo": "TVS", "color": "Rojo", "estado": "disponible",
    })
    tool_input = {"cliente_nombre": "Juan", "cliente_cedula": "123", "moto_vin": "ABC123", "plan": "P52S"}
    with patch("agents.contador.handlers.facturacion.validate_write_permission"):
        result = await handle_crear_factura_venta_moto(tool_input, mock_alegra, mock_db, mock_db, "u1")
        assert result["success"] is False
        assert "motor" in result["error"].lower()


@pytest.mark.asyncio
async def test_factura_blocks_non_disponible(mock_alegra, mock_db):
    from agents.contador.handlers.facturacion import handle_crear_factura_venta_moto
    mock_db.inventario_motos.find_one = AsyncMock(return_value={
        "vin": "ABC123", "motor": "M123", "modelo": "TVS", "color": "Azul", "estado": "Vendida",
    })
    tool_input = {"cliente_nombre": "Juan", "cliente_cedula": "123", "moto_vin": "ABC123", "plan": "P39S"}
    with patch("agents.contador.handlers.facturacion.validate_write_permission"):
        result = await handle_crear_factura_venta_moto(tool_input, mock_alegra, mock_db, mock_db, "u1")
        assert result["success"] is False
        assert "disponible" in result["error"].lower()


@pytest.mark.asyncio
async def test_factura_item_format_correct(mock_alegra, mock_db):
    from agents.contador.handlers.facturacion import handle_crear_factura_venta_moto
    tool_input = {"cliente_nombre": "Juan", "cliente_cedula": "123", "moto_vin": "9FL25AF31VDB95058", "plan": "P52S"}
    with patch("agents.contador.handlers.facturacion.validate_write_permission"):
        with patch("agents.contador.handlers.facturacion.publish_event", new_callable=AsyncMock):
            result = await handle_crear_factura_venta_moto(tool_input, mock_alegra, mock_db, mock_db, "u1")
            assert result["success"] is True
            call_args = mock_alegra.request_with_verify.call_args
            payload = call_args.kwargs.get("payload", {})
            item_name = payload["items"][0]["name"]
            assert "VIN:" in item_name
            assert "Motor:" in item_name
            assert "9FL25AF31VDB95058" in item_name


@pytest.mark.asyncio
async def test_factura_cascade_inventario_loanbook(mock_alegra, mock_db):
    from agents.contador.handlers.facturacion import handle_crear_factura_venta_moto
    tool_input = {"cliente_nombre": "Juan", "cliente_cedula": "123", "moto_vin": "9FL25AF31VDB95058", "plan": "P52S"}
    with patch("agents.contador.handlers.facturacion.validate_write_permission"):
        with patch("agents.contador.handlers.facturacion.publish_event", new_callable=AsyncMock) as mock_pub:
            result = await handle_crear_factura_venta_moto(tool_input, mock_alegra, mock_db, mock_db, "u1")
            assert result["success"] is True
            # Contador no longer writes to inventario/loanbook — only publishes events
            mock_db.inventario_motos.update_one.assert_not_called()
            mock_db.loanbook.insert_one.assert_not_called()
            mock_pub.assert_called_once()
            assert mock_pub.call_args.kwargs["event_type"] == "factura.venta.creada"
            datos = mock_pub.call_args.kwargs["datos"]
            assert datos["factura_id"] == "777"
            assert datos["vin"] == "9FL25AF31VDB95058"
            assert datos["motor"] == "BF3AT18C2356"
            assert datos["modelo"] == "TVS Raider 125"
            assert datos["color"] == "Negro Nebulosa"
            assert datos["plan"] == "P52S"


@pytest.mark.asyncio
async def test_anular_factura_reverses_cascade(mock_alegra, mock_db):
    from agents.contador.handlers.facturacion import handle_anular_factura
    tool_input = {"invoice_id": 777, "motivo": "Error en datos"}
    with patch("agents.contador.handlers.facturacion.validate_write_permission"):
        with patch("agents.contador.handlers.facturacion.publish_event", new_callable=AsyncMock) as mock_pub:
            result = await handle_anular_factura(tool_input, mock_alegra, mock_db, mock_db, "u1")
            assert result["success"] is True
            # Contador no longer writes to inventario/loanbook — only publishes events
            mock_db.inventario_motos.update_one.assert_not_called()
            mock_db.loanbook.update_one.assert_not_called()
            mock_pub.assert_called_once()
            assert mock_pub.call_args.kwargs["event_type"] == "factura.venta.anulada"
            datos = mock_pub.call_args.kwargs["datos"]
            assert datos["invoice_id"] == 777
            assert datos["motivo"] == "Error en datos"


@pytest.mark.asyncio
async def test_consultar_facturas_readonly(mock_alegra, mock_db):
    from agents.contador.handlers.facturacion import handle_consultar_facturas
    result = await handle_consultar_facturas({}, mock_alegra, mock_db, mock_db, "u1")
    assert result["success"] is True
    mock_alegra.get.assert_called()


@pytest.mark.asyncio
async def test_crear_nota_credito_publishes_event(mock_alegra, mock_db):
    from agents.contador.handlers.facturacion import handle_crear_nota_credito
    tool_input = {"invoice_id": 500, "motivo": "Devolucion parcial", "items": []}
    with patch("agents.contador.handlers.facturacion.validate_write_permission"):
        with patch("agents.contador.handlers.facturacion.publish_event", new_callable=AsyncMock) as mock_pub:
            result = await handle_crear_nota_credito(tool_input, mock_alegra, mock_db, mock_db, "u1")
            assert result["success"] is True
            assert mock_pub.call_args.kwargs["event_type"] == "nota_credito.creada"


def test_facturacion_mongodb_writes_only_allowed():
    """inventario_motos and loanbook writes are ALLOWED. No other MongoDB writes."""
    import pathlib
    path = pathlib.Path("backend/agents/contador/handlers/facturacion.py")
    if path.exists():
        content = path.read_text(encoding="utf-8")
        lines_with_writes = []
        for i, line in enumerate(content.split("\n"), 1):
            for op in ["insert_one", "update_one", "insert_many", "replace_one"]:
                if op in line and "inventario_motos" not in line and "loanbook" not in line and "roddos_events" not in line:
                    lines_with_writes.append(f"L{i}: {line.strip()}")
        assert len(lines_with_writes) == 0, f"Forbidden MongoDB writes: {lines_with_writes}"
