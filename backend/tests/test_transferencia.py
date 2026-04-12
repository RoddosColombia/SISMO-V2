"""Tests for transferencia entre cuentas feature."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from routers.alegra import _flatten_categories


# --- Fixtures ---

@pytest.fixture
def mock_db():
    db = MagicMock()
    db.backlog_movimientos = MagicMock()
    db.backlog_movimientos.find_one = AsyncMock()
    db.backlog_movimientos.update_one = AsyncMock()
    db.roddos_events = MagicMock()
    db.roddos_events.insert_one = AsyncMock()
    return db


@pytest.fixture
def sample_mov():
    return {
        "_id": ObjectId("665a1b2c3d4e5f6a7b8c9d00"),
        "fecha": "2026-04-10",
        "banco": "Bancolombia",
        "descripcion": "Transferencia a Davivienda",
        "monto": 5000000,
        "estado": "pendiente",
    }


# --- Test 1: causar_transferencia creates journal with correct debit/credit ---

@pytest.mark.asyncio
async def test_causar_transferencia_creates_journal(mock_db, sample_mov):
    """Transfer creates journal with DEBIT destino / CREDIT origen."""
    from routers.backlog import causar_transferencia, TransferCausarRequest

    mock_db.backlog_movimientos.find_one = AsyncMock(return_value=sample_mov)

    mock_alegra = MagicMock()
    mock_alegra.request_with_verify = AsyncMock(return_value={"_alegra_id": "9999"})

    request = TransferCausarRequest(cuenta_origen="5314", cuenta_destino="5322")

    with patch("services.alegra.client.AlegraClient", return_value=mock_alegra):
        result = await causar_transferencia(
            backlog_id="665a1b2c3d4e5f6a7b8c9d00",
            request=request,
            db=mock_db,
        )

    assert result["success"] is True
    assert result["alegra_id"] == "9999"

    # Verify journal payload
    call_args = mock_alegra.request_with_verify.call_args
    payload = call_args[1].get("payload") or call_args[0][2] if len(call_args[0]) > 2 else call_args[1].get("payload")
    # The call is request_with_verify("journals", "POST", payload=payload)
    assert call_args[0][0] == "journals"
    assert call_args[0][1] == "POST"
    entries = payload["entries"]
    # First entry: DEBIT destino
    assert entries[0]["id"] == "5322"
    assert entries[0]["debit"] == 5000000
    assert entries[0]["credit"] == 0
    # Second entry: CREDIT origen
    assert entries[1]["id"] == "5314"
    assert entries[1]["debit"] == 0
    assert entries[1]["credit"] == 5000000

    # Verify movement marked as causado
    mock_db.backlog_movimientos.update_one.assert_called_once()
    update_call = mock_db.backlog_movimientos.update_one.call_args
    assert update_call[0][1]["$set"]["estado"] == "causado"
    assert update_call[0][1]["$set"]["alegra_id"] == "9999"

    # Verify event published to roddos_events
    mock_db.roddos_events.insert_one.assert_called_once()


# --- Test 2: existing gasto flow still works (no regression) ---

@pytest.mark.asyncio
async def test_causar_gasto_still_works(mock_db, sample_mov):
    """The existing /{backlog_id}/causar endpoint still functions correctly."""
    from routers.backlog import causar_desde_backlog

    mock_handler_result = {"success": True, "alegra_id": "1234"}

    with patch("agents.contador.handlers.conciliacion.handle_causar_desde_backlog", new_callable=AsyncMock, return_value=mock_handler_result) as mock_handler, \
         patch("services.alegra.client.AlegraClient") as mock_alegra_cls:
        mock_alegra_cls.return_value = MagicMock()
        result = await causar_desde_backlog(
            backlog_id="665a1b2c3d4e5f6a7b8c9d00",
            cuenta_id="5494",
            retefuente=0,
            reteica=0,
            db=mock_db,
        )

    assert result["success"] is True
    assert result["alegra_id"] == "1234"
    mock_handler.assert_called_once()
    call_kwargs = mock_handler.call_args[1]
    assert call_kwargs["tool_input"]["cuenta_id"] == "5494"
    assert call_kwargs["tool_input"]["retenciones"]["retefuente"] == 0
    assert call_kwargs["tool_input"]["retenciones"]["reteica"] == 0


# --- Test 3: _flatten_categories adds es_banco for bank codes ---

def test_cuentas_endpoint_has_es_banco_flag():
    """Bank accounts (code 1105/1110/1120) get es_banco=True, others False."""
    categories = [
        {
            "id": "5308", "name": "Bancos", "use": "accumulative", "code": "11",
            "children": [
                {"id": "5314", "name": "Bancolombia 2029", "use": "movement", "code": "11100501", "children": []},
                {"id": "5318", "name": "BBVA", "use": "movement", "code": "11100601", "children": []},
                {"id": "5400", "name": "Caja general", "use": "movement", "code": "11050101", "children": []},
            ],
        },
        {
            "id": "5493", "name": "Gastos Generales", "use": "accumulative", "code": "5195",
            "children": [
                {"id": "5494", "name": "Deudores", "use": "movement", "code": "51991001", "children": []},
            ],
        },
        {
            "id": "9999", "name": "Savings", "use": "movement", "code": "11200101",
            "categoryRule": {"key": "BANK_ACCOUNTS"},
            "children": [],
        },
    ]
    result = []
    _flatten_categories(categories, result)

    by_id = {a["id"]: a for a in result}

    # Bank accounts by code prefix
    assert by_id["5314"]["es_banco"] is True   # code starts with 1110
    assert by_id["5318"]["es_banco"] is True   # code starts with 1110
    assert by_id["5400"]["es_banco"] is True   # code starts with 1105

    # Bank account by categoryRule
    assert by_id["9999"]["es_banco"] is True

    # Non-bank account
    assert by_id["5494"]["es_banco"] is False
