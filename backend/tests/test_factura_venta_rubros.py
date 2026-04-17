"""
Tests for factura venta moto CON rubros adicionales + listener factura.venta.creada.

- Tool accepts rubros_adicionales + modo_promocion
- Handler builds multi-line invoice (moto + SOAT + matrícula + GPS)
- Invoice sent with status=open (no draft)
- Listener factura.venta.creada creates loanbook in pendiente_entrega
- CRM upsert happens via chained loanbook.creado event
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ═══════════════════════════════════════════
# Tool handler — multi-item with rubros
# ═══════════════════════════════════════════


@pytest.fixture
def mock_alegra():
    client = AsyncMock()
    client.request_with_verify = AsyncMock(return_value={
        "id": "39",
        "_alegra_id": "39",
        "numberTemplate": {"fullNumber": "FE470"},
    })
    client.get = AsyncMock(return_value=[])  # contact not found → will create
    return client


@pytest.fixture
def mock_db_no_moto_in_mongo():
    """Para ventas donde Alegra es inventario canónico — no hay registro en Mongo."""
    db = MagicMock()
    db.roddos_events = MagicMock()
    db.roddos_events.insert_one = AsyncMock()
    db.inventario_motos = MagicMock()
    db.inventario_motos.find_one = AsyncMock(return_value=None)
    db.loanbook = MagicMock()
    db.loanbook.insert_one = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_factura_con_rubros_4_items(mock_alegra, mock_db_no_moto_in_mongo):
    """Envía SOAT + matrícula + GPS → el payload POST /invoices tiene 4 líneas."""
    from agents.contador.handlers.facturacion import (
        handle_crear_factura_venta_moto,
        ALEGRA_ITEM_SOAT, ALEGRA_ITEM_MATRICULA, ALEGRA_ITEM_GPS,
    )
    tool_input = {
        "cliente_nombre": "Toribio Rodriguez Salcedo",
        "cliente_cedula": "19594484",
        "cliente_telefono": "573214383749",
        "moto_vin": "9FLT81001VDB62264",
        "moto_motor": "RF5AT1XA5588",
        "moto_modelo": "TVS Sport 100",
        "plan": "P39S",
        "modo_pago": "semanal",
        "cuota_valor": 204000,
        "num_cuotas": 39,
        "cuota_inicial": 0,
        "modo_promocion": True,
        "precio_moto": 5_750_000,
        "rubros_adicionales": {
            "soat": 296000,
            "matricula": 284000,
            "gps": 82000,
        },
    }
    with patch("agents.contador.handlers.facturacion.validate_write_permission"):
        with patch("agents.contador.handlers.facturacion.publish_event",
                   new_callable=AsyncMock) as mock_pub:
            result = await handle_crear_factura_venta_moto(
                tool_input, mock_alegra, mock_db_no_moto_in_mongo,
                mock_db_no_moto_in_mongo, "u1",
            )
    assert result["success"] is True

    # The POST /invoices call — extract the invoice payload
    # request_with_verify might be called twice: once for resolve_contact, once for invoice.
    calls = mock_alegra.request_with_verify.call_args_list
    invoice_call = next(
        (c for c in calls if c.kwargs.get("endpoint") == "invoices"
         or (len(c.args) > 0 and c.args[0] == "invoices")),
        None,
    )
    assert invoice_call is not None, "POST /invoices never called"
    payload = invoice_call.kwargs.get("payload") or (invoice_call.args[2] if len(invoice_call.args) > 2 else {})

    # 4 líneas: moto + SOAT + matrícula + GPS
    assert len(payload["items"]) == 4
    # status=open (no draft)
    assert payload["status"] == "open"
    assert payload["paymentForm"] == "CREDIT"

    # IDs de rubros corresponden a los items Alegra reales
    ids_in_payload = [it.get("id") for it in payload["items"] if "id" in it]
    assert ALEGRA_ITEM_SOAT in ids_in_payload
    assert ALEGRA_ITEM_MATRICULA in ids_in_payload
    assert ALEGRA_ITEM_GPS in ids_in_payload

    # El evento factura.venta.creada se publica CON los rubros
    mock_pub.assert_called_once()
    datos = mock_pub.call_args.kwargs["datos"]
    assert datos["modo_promocion"] is True
    assert datos["rubros"]["soat"] == 296000
    assert datos["rubros"]["matricula"] == 284000
    assert datos["rubros"]["gps"] == 82000
    assert datos["cuota_inicial"] == 0
    assert datos["cuota_monto"] == 204000
    assert datos["num_cuotas"] == 39


@pytest.mark.asyncio
async def test_factura_sin_moto_en_mongo_falla_sin_motor(mock_alegra, mock_db_no_moto_in_mongo):
    """Si la moto no está en inventario_motos y no se envía moto_motor → error."""
    from agents.contador.handlers.facturacion import handle_crear_factura_venta_moto
    tool_input = {
        "cliente_nombre": "X", "cliente_cedula": "1",
        "moto_vin": "UNKNOWN", "plan": "P39S",
    }
    with patch("agents.contador.handlers.facturacion.validate_write_permission"):
        result = await handle_crear_factura_venta_moto(
            tool_input, mock_alegra, mock_db_no_moto_in_mongo,
            mock_db_no_moto_in_mongo, "u1",
        )
    assert result["success"] is False
    assert "moto_motor" in result["error"] or "motor" in result["error"].lower()


# ═══════════════════════════════════════════
# Listener: factura.venta.creada → loanbook
# ═══════════════════════════════════════════


def _fake_event(alegra_id="39", vin="9FLT81001VDB62264") -> dict:
    return {
        "event_id": "evt-1",
        "event_type": "factura.venta.creada",
        "source": "agente_contador",
        "correlation_id": "corr-1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "alegra_id": alegra_id,
        "datos": {
            "factura_id": alegra_id,
            "alegra_invoice_number": "FE470",
            "cliente_nombre": "Toribio Rodriguez Salcedo",
            "cliente_cedula": "19594484",
            "cliente_telefono": "573214383749",
            "vin": vin,
            "motor": "RF5AT1XA5588",
            "modelo": "TVS Sport 100",
            "plan": "P39S",
            "modalidad": "semanal",
            "cuota_monto": 204000,
            "num_cuotas": 39,
            "cuota_inicial": 0,
            "modo_promocion": True,
            "precio_moto": 5_750_000,
            "rubros": {"soat": 296000, "matricula": 284000, "gps": 82000},
            "valor_factura": 6_412_000,
        },
    }


@pytest.mark.asyncio
async def test_listener_factura_crea_loanbook_pendiente_entrega():
    """El handler reactivo crea loanbook pendiente_entrega + publica loanbook.creado."""
    from core.loanbook_handlers import handle_factura_venta_creada

    db = MagicMock()
    db.loanbook = MagicMock()
    db.loanbook.find_one = AsyncMock(return_value=None)  # no existe ni por VIN ni numeración
    # cursor del _next_loanbook_id
    cur = MagicMock()
    cur.sort = MagicMock(return_value=cur)
    cur.limit = MagicMock(return_value=cur)
    cur.to_list = AsyncMock(return_value=[])
    db.loanbook.find = MagicMock(return_value=cur)
    db.loanbook.insert_one = AsyncMock()
    db.roddos_events = MagicMock()
    db.roddos_events.insert_one = AsyncMock()

    with patch("core.loanbook_handlers.publish_event", new_callable=AsyncMock) as mock_pub:
        await handle_factura_venta_creada(_fake_event(), db)

    # Loanbook insertado
    db.loanbook.insert_one.assert_called_once()
    lb_doc = db.loanbook.insert_one.call_args.args[0]
    assert lb_doc["estado"] == "pendiente_entrega"
    assert lb_doc["cuotas"] == []  # Vacío hasta entrega
    assert lb_doc["vin"] == "9FLT81001VDB62264"
    assert lb_doc["plan_codigo"] == "P39S"
    assert lb_doc["cuota_monto"] == 204000
    assert lb_doc["num_cuotas"] == 39
    assert lb_doc["modo_promocion"] is True
    assert lb_doc["rubros_adicionales"]["soat"] == 296000

    # Publica loanbook.creado para que el CRM listener cree el cliente
    mock_pub.assert_called_once()
    assert mock_pub.call_args.kwargs["event_type"] == "loanbook.creado"
    datos = mock_pub.call_args.kwargs["datos"]
    assert datos["vin"] == "9FLT81001VDB62264"
    assert datos["cliente"]["cedula"] == "19594484"
    assert datos["cliente"]["nombre"] == "Toribio Rodriguez Salcedo"


@pytest.mark.asyncio
async def test_listener_idempotente_por_vin():
    """Si el loanbook para VIN ya existe, el listener NO duplica."""
    from core.loanbook_handlers import handle_factura_venta_creada

    db = MagicMock()
    db.loanbook = MagicMock()
    db.loanbook.find_one = AsyncMock(return_value={"loanbook_id": "LB-2026-0029", "vin": "9FLT81001VDB62264"})
    db.loanbook.insert_one = AsyncMock()
    db.roddos_events = MagicMock()
    db.roddos_events.insert_one = AsyncMock()

    with patch("core.loanbook_handlers.publish_event", new_callable=AsyncMock) as mock_pub:
        await handle_factura_venta_creada(_fake_event(), db)

    db.loanbook.insert_one.assert_not_called()
    mock_pub.assert_not_called()


@pytest.mark.asyncio
async def test_listener_skip_si_evento_sin_vin():
    """Evento sin VIN → listener no hace nada (log warning)."""
    from core.loanbook_handlers import handle_factura_venta_creada

    evt = _fake_event()
    evt["datos"]["vin"] = ""

    db = MagicMock()
    db.loanbook = MagicMock()
    db.loanbook.insert_one = AsyncMock()
    db.loanbook.find_one = AsyncMock(return_value=None)
    db.roddos_events = MagicMock()
    db.roddos_events.insert_one = AsyncMock()

    with patch("core.loanbook_handlers.publish_event", new_callable=AsyncMock) as mock_pub:
        await handle_factura_venta_creada(evt, db)

    db.loanbook.insert_one.assert_not_called()
    mock_pub.assert_not_called()


# ═══════════════════════════════════════════
# ROG-4: handler NO escribe en crm_clientes o inventario_motos
# ═══════════════════════════════════════════


@pytest.mark.asyncio
async def test_rog4_handler_no_escribe_loanbook_directo(mock_alegra, mock_db_no_moto_in_mongo):
    """El handler Contador debe publicar evento, NO escribir loanbook/crm directamente."""
    from agents.contador.handlers.facturacion import handle_crear_factura_venta_moto
    tool_input = {
        "cliente_nombre": "X", "cliente_cedula": "1",
        "moto_vin": "V1", "moto_motor": "M1", "plan": "P52S",
        "cuota_valor": 100000, "num_cuotas": 52, "modo_promocion": True,
        "precio_moto": 5_000_000,
    }
    mock_db_no_moto_in_mongo.crm_clientes = MagicMock()
    mock_db_no_moto_in_mongo.crm_clientes.insert_one = AsyncMock()
    mock_db_no_moto_in_mongo.crm_clientes.update_one = AsyncMock()

    with patch("agents.contador.handlers.facturacion.validate_write_permission"):
        with patch("agents.contador.handlers.facturacion.publish_event", new_callable=AsyncMock):
            await handle_crear_factura_venta_moto(
                tool_input, mock_alegra, mock_db_no_moto_in_mongo,
                mock_db_no_moto_in_mongo, "u1",
            )

    # ROG-4: ni loanbook, ni crm_clientes, ni inventario_motos deben ser escritos directo
    mock_db_no_moto_in_mongo.loanbook.insert_one.assert_not_called()
    mock_db_no_moto_in_mongo.crm_clientes.insert_one.assert_not_called()
    mock_db_no_moto_in_mongo.crm_clientes.update_one.assert_not_called()
