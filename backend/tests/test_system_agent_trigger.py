"""
tests/test_system_agent_trigger.py — Tests del loop agéntico automático.

Verifica:
  1. process_system_event() ejecuta tools vía ToolDispatcher cuando auto_approve=True
  2. detect_and_sync_new_invoices() llama process_system_event por factura nueva sin loanbook
  3. detect_and_sync_new_invoices() NO llama process_system_event si loanbook ya existe
  4. Facturas en estado draft no se procesan
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.datetime_utils import today_bogota


# ── 1. process_system_event ejecuta tool ──────────────────────────────────────

@pytest.mark.asyncio
async def test_process_system_event_ejecuta_tool():
    """Claude devuelve tool_use → dispatcher.dispatch se llama con los parámetros correctos."""
    # Mock del bloque tool_use que devuelve la API
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "registrar_gasto"
    tool_block.input = {"monto": 100_000, "descripcion": "test automatico"}

    mock_response = MagicMock()
    mock_response.content = [tool_block]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    mock_dispatcher = AsyncMock()
    mock_dispatcher.dispatch = AsyncMock(return_value={"success": True, "alegra_id": "TEST-1"})

    db = MagicMock()

    with patch("anthropic.AsyncAnthropic", return_value=mock_client), \
         patch("agents.chat.ToolDispatcher", return_value=mock_dispatcher):
        from agents.chat import process_system_event
        result = await process_system_event(
            message="Registrar un gasto de prueba",
            db=db,
            agent_type="contador",
            auto_approve=True,
        )

    assert len(result["results"]) == 1
    assert result["results"][0]["tool"] == "registrar_gasto"
    assert result["results"][0]["result"]["success"] is True
    mock_dispatcher.dispatch.assert_called_once()
    call_args = mock_dispatcher.dispatch.call_args[0]
    assert call_args[0] == "registrar_gasto"
    assert call_args[1] == {"monto": 100_000, "descripcion": "test automatico"}


# ── 2. detect_new_invoice_sin_loanbook ────────────────────────────────────────

@pytest.mark.asyncio
async def test_detect_new_invoice_sin_loanbook():
    """Factura nueva sin loanbook existente → process_system_event se llama una vez."""
    mes_prefix = today_bogota().strftime("%Y-%m")

    mock_invoices = [{
        "id": "999",
        "date": f"{mes_prefix}-15",
        "status": "open",
        "numberTemplate": {"number": "FE999"},
        "client": {
            "name": "Test Cliente",
            "identification": "12345678",
            "mobile": "3001234567",
        },
        "items": [{"name": "Raider 125"}],
        "total": 7_800_000,
        "observations": "Plan P52S semanal",
    }]

    mock_alegra = AsyncMock()
    mock_alegra.get = AsyncMock(return_value=mock_invoices)

    db = MagicMock()
    db.loanbook.find_one = AsyncMock(return_value=None)

    with patch("services.alegra.client.AlegraClient", return_value=mock_alegra), \
         patch("agents.chat.process_system_event", new_callable=AsyncMock) as mock_pse:
        from core.alegra_sync import detect_and_sync_new_invoices
        await detect_and_sync_new_invoices(db)

    mock_pse.assert_called_once()
    _, kwargs = mock_pse.call_args
    assert kwargs.get("agent_type") == "loanbook"
    assert kwargs.get("auto_approve") is True
    assert kwargs.get("correlation_id") == "alegra-sync-999"


# ── 3. detect_new_invoice_ya_existe ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_detect_new_invoice_ya_existe():
    """Factura con loanbook ya registrado → process_system_event NO se llama."""
    mes_prefix = today_bogota().strftime("%Y-%m")

    mock_invoices = [{
        "id": "888",
        "date": f"{mes_prefix}-10",
        "status": "open",
        "numberTemplate": {"number": "FE888"},
        "client": {"name": "Cliente Existente", "identification": "99999999"},
        "items": [],
        "total": 5_000_000,
    }]

    mock_alegra = AsyncMock()
    mock_alegra.get = AsyncMock(return_value=mock_invoices)

    db = MagicMock()
    db.loanbook.find_one = AsyncMock(
        return_value={"loanbook_id": "LB-2026-0001", "factura_alegra_id": "FE888"}
    )

    with patch("services.alegra.client.AlegraClient", return_value=mock_alegra), \
         patch("agents.chat.process_system_event", new_callable=AsyncMock) as mock_pse:
        from core.alegra_sync import detect_and_sync_new_invoices
        await detect_and_sync_new_invoices(db)

    mock_pse.assert_not_called()


# ── 4. detect_invoice_draft_skip ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_detect_invoice_draft_skip():
    """Facturas en estado draft no se procesan — process_system_event NO se llama."""
    mes_prefix = today_bogota().strftime("%Y-%m")

    mock_invoices = [{
        "id": "777",
        "date": f"{mes_prefix}-05",
        "status": "draft",
        "numberTemplate": {"number": "FE777"},
        "client": {"name": "Cliente Draft"},
        "items": [],
        "total": 3_000_000,
    }]

    mock_alegra = AsyncMock()
    mock_alegra.get = AsyncMock(return_value=mock_invoices)

    db = MagicMock()
    db.loanbook.find_one = AsyncMock(return_value=None)

    with patch("services.alegra.client.AlegraClient", return_value=mock_alegra), \
         patch("agents.chat.process_system_event", new_callable=AsyncMock) as mock_pse:
        from core.alegra_sync import detect_and_sync_new_invoices
        await detect_and_sync_new_invoices(db)

    mock_pse.assert_not_called()
