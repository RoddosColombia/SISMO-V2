"""
Tests V2 — Firecrawl Agent flows para Contador.

Cubre:
  - crear_factura_venta_agente (factura venta)
  - crear_lote_motos_agente (compra lote motos)
  - crear_lote_repuestos_agente (compra repuestos con bodega)
  - handle_crear_factura_venta_alegra_agente (handler completo)
  - dispatcher.dispatch — captura traceback en tool.error
  - heurística de éxito: NUNCA success=True sin id numérico real

Mocks: firecrawl.Firecrawl con MagicMock. Las pruebas NO contactan ni Alegra
ni MongoDB real (db es AsyncMock).

Diagnóstico: .planning/DIAGNOSTICO_CONTADOR_FIRECRAWL.md
"""
from __future__ import annotations
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers / fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _firecrawl_env(monkeypatch):
    """Defaults sanos para que _validar_credenciales_alegra no falle."""
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test-key")
    monkeypatch.setenv("ALEGRA_EMAIL", "test@roddos.com")
    monkeypatch.setenv("ALEGRA_PASSWORD", "ui-password-test")
    monkeypatch.setenv("ALEGRA_TOKEN", "api-key-test")


def _mock_fc_factory(agent_response):
    """Crea un mock de la fábrica _get_fc() con .agent() que devuelve `agent_response`."""
    fake_fc = MagicMock()
    fake_fc.agent = MagicMock(return_value=agent_response)
    return fake_fc


# ─────────────────────────────────────────────────────────────────────────────
# A. crear_factura_venta_agente — éxito
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crear_factura_venta_agente_extrae_id_numerico_real():
    """Debe devolver el id numérico real, no la cadena 'firecrawl'."""
    # Recargar módulo para que tome las env vars del fixture
    import importlib
    from services.firecrawl import alegra_browser
    importlib.reload(alegra_browser)

    fake_response = {
        "factura_creada":     True,
        "alegra_invoice_id":  "12345",
        "alegra_url":         "https://app.alegra.com/invoice/12345",
        "factura_total":      8_543_000,
    }
    with patch.object(alegra_browser, "_get_fc", return_value=_mock_fc_factory(fake_response)):
        result = await alegra_browser.crear_factura_venta_agente({
            "cliente_nombre":  "Juan Pérez",
            "cliente_cedula":  "1234567",
            "moto_vin":        "MD2A4CY3XRW123456",
            "moto_motor":      "CY3RW123456",
            "moto_modelo":     "TVS Raider 125",
            "plan":            "P52S",
            "modo_pago":       "semanal",
            "cuota_inicial":   500_000,
        })

    assert result["success"] is True
    assert result["alegra_id"] == "12345"
    assert result["alegra_id"] != "firecrawl"
    assert result["alegra_url"] == "https://app.alegra.com/invoice/12345"
    assert result["stage"] == "completed"


@pytest.mark.asyncio
async def test_crear_factura_venta_agente_extrae_id_de_url_si_falta():
    """Si el agente reporta success pero olvida alegra_invoice_id, lo extraemos del URL."""
    import importlib
    from services.firecrawl import alegra_browser
    importlib.reload(alegra_browser)

    fake_response = {
        "factura_creada":  True,
        # alegra_invoice_id intencionalmente ausente
        "alegra_url":      "https://app.alegra.com/sales/invoices/98765",
        "factura_total":   1_000_000,
    }
    with patch.object(alegra_browser, "_get_fc", return_value=_mock_fc_factory(fake_response)):
        result = await alegra_browser.crear_factura_venta_agente({
            "cliente_nombre":  "Ana López",
            "cliente_cedula":  "9876543",
            "moto_vin":        "VIN999",
            "moto_motor":      "MOTOR999",
            "moto_modelo":     "TVS Sport 100",
            "plan":            "P26S",
            "modo_pago":       "semanal",
        })

    assert result["success"] is True
    assert result["alegra_id"] == "98765"


# ─────────────────────────────────────────────────────────────────────────────
# B. crear_factura_venta_agente — fallos detectables
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crear_factura_falla_sin_password_ui(monkeypatch):
    """Bug F-1: ALEGRA_PASSWORD vacío debe ser detectado y reportado claramente."""
    monkeypatch.setenv("ALEGRA_PASSWORD", "")
    import importlib
    from services.firecrawl import alegra_browser
    importlib.reload(alegra_browser)

    result = await alegra_browser.crear_factura_venta_agente({
        "cliente_nombre":  "X", "cliente_cedula":  "1", "moto_vin":        "V",
        "moto_motor":      "M", "moto_modelo":     "TVS Raider 125",
        "plan":            "P52S", "modo_pago":       "semanal",
    })
    assert result["success"] is False
    assert result["stage"] == "credentials"
    assert "ALEGRA_PASSWORD" in result["error"]
    # El mensaje debe explicar que ALEGRA_TOKEN ≠ ALEGRA_PASSWORD
    assert "API key" in result["error"]


@pytest.mark.asyncio
async def test_crear_factura_falla_si_agente_reporta_no_creada():
    """Si fc.agent devuelve factura_creada=false, NO publicar evento."""
    import importlib
    from services.firecrawl import alegra_browser
    importlib.reload(alegra_browser)

    fake_response = {
        "factura_creada": False,
        "error":          "Cliente con CC 9999 no encontrado y no se pudo crear",
    }
    with patch.object(alegra_browser, "_get_fc", return_value=_mock_fc_factory(fake_response)):
        result = await alegra_browser.crear_factura_venta_agente({
            "cliente_nombre":  "X", "cliente_cedula":  "9999", "moto_vin":        "V",
            "moto_motor":      "M", "moto_modelo":     "TVS Raider 125",
            "plan":            "P52S", "modo_pago":       "semanal",
        })

    assert result["success"] is False
    assert result["stage"] == "verification"
    assert "Cliente" in result["error"]


@pytest.mark.asyncio
async def test_crear_factura_falla_si_id_no_numerico():
    """Bug F-4: éxito heurístico falso. 'firecrawl' NO es id válido."""
    import importlib
    from services.firecrawl import alegra_browser
    importlib.reload(alegra_browser)

    fake_response = {
        "factura_creada":     True,
        "alegra_invoice_id":  "firecrawl",  # ← falsificación detectable
        "alegra_url":         "https://app.alegra.com/income/invoices/add",
    }
    with patch.object(alegra_browser, "_get_fc", return_value=_mock_fc_factory(fake_response)):
        result = await alegra_browser.crear_factura_venta_agente({
            "cliente_nombre":  "X", "cliente_cedula":  "1", "moto_vin":        "V",
            "moto_motor":      "M", "moto_modelo":     "TVS Raider 125",
            "plan":            "P52S", "modo_pago":       "semanal",
        })

    assert result["success"] is False
    assert result["stage"] == "verification"


@pytest.mark.asyncio
async def test_crear_factura_falla_si_falta_vin_o_motor():
    import importlib
    from services.firecrawl import alegra_browser
    importlib.reload(alegra_browser)

    r1 = await alegra_browser.crear_factura_venta_agente({
        "cliente_nombre":  "X", "cliente_cedula":  "1",
        "moto_vin":        "", "moto_motor": "M", "moto_modelo": "TVS Raider 125",
        "plan":            "P52S", "modo_pago":       "semanal",
    })
    assert r1["success"] is False
    assert r1["stage"] == "validation"

    r2 = await alegra_browser.crear_factura_venta_agente({
        "cliente_nombre":  "X", "cliente_cedula":  "1",
        "moto_vin":        "V", "moto_motor": "", "moto_modelo": "TVS Raider 125",
        "plan":            "P52S", "modo_pago":       "semanal",
    })
    assert r2["success"] is False
    assert r2["stage"] == "validation"


@pytest.mark.asyncio
async def test_crear_factura_falla_si_sdk_no_expone_agent():
    """Si la SDK Firecrawl no expone .agent (versión incompatible), falla limpio."""
    import importlib
    from services.firecrawl import alegra_browser
    importlib.reload(alegra_browser)

    # Mock del fc cuyo .agent levanta AttributeError (simula SDK sin método)
    fake_fc = MagicMock()
    fake_fc.agent = MagicMock(side_effect=AttributeError("'Firecrawl' object has no attribute 'agent'"))
    with patch.object(alegra_browser, "_get_fc", return_value=fake_fc):
        result = await alegra_browser.crear_factura_venta_agente({
            "cliente_nombre":  "X", "cliente_cedula":  "1", "moto_vin": "V",
            "moto_motor":      "M", "moto_modelo": "TVS Raider 125",
            "plan":            "P52S", "modo_pago":       "semanal",
        })
    assert result["success"] is False
    assert result["stage"] == "sdk_incompatible"


# ─────────────────────────────────────────────────────────────────────────────
# C. crear_lote_motos_agente
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crear_lote_motos_exitoso():
    import importlib
    from services.firecrawl import alegra_browser
    importlib.reload(alegra_browser)

    fake_response = {
        "items_creados": [
            {"vin": "VIN001", "alegra_id": "5001", "nombre": "TVS Raider 125 - VIN: VIN001 / Motor: M001"},
            {"vin": "VIN002", "alegra_id": "5002", "nombre": "TVS Raider 125 - VIN: VIN002 / Motor: M002"},
        ],
        "items_omitidos":  [],
        "bill_alegra_id":  "9000",
        "bill_alegra_url": "https://app.alegra.com/bill/9000",
        "errores":         [],
        "todo_ok":         True,
    }
    with patch.object(alegra_browser, "_get_fc", return_value=_mock_fc_factory(fake_response)):
        result = await alegra_browser.crear_lote_motos_agente(
            motos=[
                {"vin": "VIN001", "motor": "M001", "modelo": "TVS Raider 125"},
                {"vin": "VIN002", "motor": "M002", "modelo": "TVS Raider 125"},
            ],
            proveedor_nit="901249413",
            numero_factura="FV-2026-001",
            fecha="2026-04-28",
        )

    assert result["success"] is True
    assert result["creadas"] == 2
    assert result["bill_alegra_id"] == "9000"


@pytest.mark.asyncio
async def test_crear_lote_motos_rechaza_bill_id_no_numerico():
    """Si el agente reporta bill_alegra_id que no es numérico, fallo duro."""
    import importlib
    from services.firecrawl import alegra_browser
    importlib.reload(alegra_browser)

    fake_response = {
        "items_creados":   [{"vin": "VIN001", "alegra_id": "5001"}],
        "items_omitidos":  [],
        "bill_alegra_id":  "firecrawl",  # ← falso
        "bill_alegra_url": "https://app.alegra.com/bills/add",
        "errores":         [],
        "todo_ok":         True,
    }
    with patch.object(alegra_browser, "_get_fc", return_value=_mock_fc_factory(fake_response)):
        result = await alegra_browser.crear_lote_motos_agente(
            motos=[{"vin": "VIN001", "motor": "M001", "modelo": "TVS Raider 125"}],
            proveedor_nit="901249413",
            numero_factura="FV-2026-001",
            fecha="2026-04-28",
        )

    assert result["success"] is False
    assert result["bill_alegra_id"] is None


# ─────────────────────────────────────────────────────────────────────────────
# D. crear_lote_repuestos_agente — bodega Repuestos
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crear_lote_repuestos_con_bodega_existente():
    """La bodega Repuestos ya existe → bodega_repuestos_creada=False."""
    import importlib
    from services.firecrawl import alegra_browser
    importlib.reload(alegra_browser)

    fake_response = {
        "bodega_repuestos_existia": True,
        "bodega_repuestos_id":      "BOD-7",
        "bodega_repuestos_creada":  False,
        "items_creados": [
            {"referencia": "REP-001", "alegra_id": "30001", "nombre": "Filtro aire", "cantidad": 5},
        ],
        "items_omitidos":  [],
        "bill_alegra_id":  "8500",
        "bill_alegra_url": "https://app.alegra.com/bill/8500",
        "errores":         [],
        "todo_ok":         True,
    }
    with patch.object(alegra_browser, "_get_fc", return_value=_mock_fc_factory(fake_response)):
        result = await alegra_browser.crear_lote_repuestos_agente(
            items=[{"referencia": "REP-001", "nombre": "Filtro aire", "cantidad": 5, "precio_unit": 12_000}],
            proveedor_nit="860024781",
            numero_factura="FV-AUT-001",
            fecha="2026-04-28",
        )

    assert result["success"] is True
    assert result["bodega_repuestos_id"] == "BOD-7"
    assert result["bodega_repuestos_creada"] is False
    assert result["bill_alegra_id"] == "8500"


@pytest.mark.asyncio
async def test_crear_lote_repuestos_crea_bodega_si_falta():
    """Bug crítico negocio: la bodega Repuestos NO existía → la creamos."""
    import importlib
    from services.firecrawl import alegra_browser
    importlib.reload(alegra_browser)

    fake_response = {
        "bodega_repuestos_existia": False,
        "bodega_repuestos_id":      "BOD-99",
        "bodega_repuestos_creada":  True,
        "items_creados": [
            {"referencia": "REP-007", "alegra_id": "30007", "nombre": "Pastillas de freno", "cantidad": 10},
        ],
        "items_omitidos":  [],
        "bill_alegra_id":  "8501",
        "bill_alegra_url": "https://app.alegra.com/bill/8501",
        "errores":         [],
        "todo_ok":         True,
    }
    with patch.object(alegra_browser, "_get_fc", return_value=_mock_fc_factory(fake_response)):
        result = await alegra_browser.crear_lote_repuestos_agente(
            items=[{"referencia": "REP-007", "nombre": "Pastillas freno", "cantidad": 10, "precio_unit": 35_000}],
            proveedor_nit="860024781",
            numero_factura="FV-AUT-002",
            fecha="2026-04-28",
        )

    assert result["success"] is True
    assert result["bodega_repuestos_creada"] is True
    assert result["bodega_repuestos_id"] == "BOD-99"


# ─────────────────────────────────────────────────────────────────────────────
# E. Handler completo + publicación de evento
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handler_factura_publica_evento_solo_si_id_real():
    """El handler NO debe publicar factura.venta.creada si alegra_id es bogus."""
    import importlib
    from services.firecrawl import alegra_browser
    importlib.reload(alegra_browser)

    from agents.contador.handlers import facturacion as fact_mod
    importlib.reload(fact_mod)

    db = MagicMock()
    db.system_health = MagicMock()
    alegra_client = MagicMock()
    publish_calls: list[str] = []

    async def _fake_publish(**kwargs):
        publish_calls.append(kwargs.get("event_type"))
        return None

    # Caso 1: agente devuelve id falso → handler no publica
    fake_response_bad = {"factura_creada": True, "alegra_invoice_id": "firecrawl",
                         "alegra_url": "https://app.alegra.com/income/invoices/add"}
    with patch.object(alegra_browser, "_get_fc", return_value=_mock_fc_factory(fake_response_bad)), \
         patch.object(fact_mod, "publish_event", side_effect=_fake_publish), \
         patch.object(fact_mod, "validate_write_permission", return_value=None):
        result = await fact_mod.handle_crear_factura_venta_alegra_agente(
            tool_input={
                "cliente_nombre": "X", "cliente_cedula": "1",
                "moto_vin": "V", "moto_motor": "M",
                "moto_modelo": "TVS Raider 125",
                "plan": "P52S", "modo_pago": "semanal",
            },
            alegra=alegra_client, db=db, event_bus=None, user_id="u1",
        )
    assert result["success"] is False
    assert publish_calls == []  # no se publicó nada

    # Caso 2: agente devuelve id válido → handler publica
    fake_response_ok = {"factura_creada": True, "alegra_invoice_id": "123",
                        "alegra_url": "https://app.alegra.com/invoice/123",
                        "factura_total": 1_000_000}
    with patch.object(alegra_browser, "_get_fc", return_value=_mock_fc_factory(fake_response_ok)), \
         patch.object(fact_mod, "publish_event", side_effect=_fake_publish), \
         patch.object(fact_mod, "validate_write_permission", return_value=None):
        result = await fact_mod.handle_crear_factura_venta_alegra_agente(
            tool_input={
                "cliente_nombre": "X", "cliente_cedula": "1",
                "moto_vin": "V", "moto_motor": "M",
                "moto_modelo": "TVS Raider 125",
                "plan": "P52S", "modo_pago": "semanal",
            },
            alegra=alegra_client, db=db, event_bus=None, user_id="u1",
        )
    assert result["success"] is True
    assert result["alegra_id"] == "123"
    assert publish_calls == ["factura.venta.creada"]


# ─────────────────────────────────────────────────────────────────────────────
# F. Dispatcher captura traceback en tool.error
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dispatcher_publica_tool_error_con_traceback():
    """Bug F-11: antes solo capturaba str(e). Ahora debe persistir traceback."""
    import importlib
    from agents.contador.handlers import dispatcher as disp_mod
    importlib.reload(disp_mod)

    db = MagicMock()
    alegra_client = MagicMock()
    captured: list[dict] = []

    async def _capture(**kw):
        captured.append(kw)

    d = disp_mod.ToolDispatcher(alegra=alegra_client, db=db, event_bus=None)

    async def _explode(**kw):
        raise ValueError("bug intencional para test")

    d._handlers["tool_explosivo"] = _explode

    with patch.object(disp_mod, "publish_event", side_effect=_capture):
        out = await d.dispatch("tool_explosivo", {"x": 1}, user_id="u1")

    assert out["success"] is False
    assert "ValueError" in out["error"]
    assert out["exception_type"] == "ValueError"
    # publish_event fue llamado con tool.error y traceback
    assert any(c.get("event_type") == "tool.error" for c in captured)
    err_call = next(c for c in captured if c.get("event_type") == "tool.error")
    assert "ValueError" in err_call["datos"]["exception"]
    assert "Traceback" in err_call["datos"]["traceback"] or "test" in err_call["datos"]["traceback"]


# ─────────────────────────────────────────────────────────────────────────────
# G. Tools registradas en CONTADOR_TOOLS
# ─────────────────────────────────────────────────────────────────────────────

def test_tools_v2_registradas():
    from agents.contador.tools import CONTADOR_TOOLS
    nombres = {t["name"] for t in CONTADOR_TOOLS}
    assert "crear_factura_venta_alegra_agente" in nombres
    assert "registrar_compra_motos_agente" in nombres
    assert "registrar_compra_repuestos_agente" in nombres


def test_dispatcher_resuelve_tools_v2():
    from agents.contador.handlers.dispatcher import ToolDispatcher
    d = ToolDispatcher(alegra=MagicMock(), db=MagicMock(), event_bus=None)
    assert "crear_factura_venta_alegra_agente" in d._handlers
    assert "registrar_compra_motos_agente" in d._handlers
    assert "registrar_compra_repuestos_agente" in d._handlers


# ─────────────────────────────────────────────────────────────────────────────
# H. Fix NIIF → ID interno Alegra (2026-04-28)
# Antes mandábamos código NIIF (41350501/...) en payload de items y Alegra
# rechazaba con "No se encontró la cuenta contable asociada al ítem".
# Mapeo verificado en .planning/mapeo_alegra_ids.json.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_consultar_cuentas_inventario_motos_devuelve_ids_internos():
    """consultar_cuentas_inventario debe devolver ID interno Alegra (5442/5348/5520),
    no el código NIIF (41350501/14350101/61350501). Fix 2026-04-28."""
    from agents.contador.handlers.facturacion import handle_consultar_cuentas_inventario

    result = await handle_consultar_cuentas_inventario(tool_input={"tipo_item": "motos"})
    assert result["payload_alegra"]["account"]["id"] == "5442",  f"esperado 5442 (Ingresos motos), got {result['payload_alegra']['account']['id']}"
    assert result["payload_alegra"]["inventoryAccount"]["id"] == "5348", f"esperado 5348 (Inventario motos)"
    assert result["payload_alegra"]["costsAccount"]["id"] == "5520",     f"esperado 5520 (Costo motos)"
    # NIIF debe quedar como referencia documental
    assert result["cuentas"]["account"]["niif"] == "41350501"


@pytest.mark.asyncio
async def test_consultar_cuentas_inventario_repuestos_devuelve_ids_internos():
    from agents.contador.handlers.facturacion import handle_consultar_cuentas_inventario

    result = await handle_consultar_cuentas_inventario(tool_input={"tipo_item": "repuestos"})
    assert result["payload_alegra"]["account"]["id"] == "5444",  f"esperado 5444 (Ingresos repuestos)"
    assert result["payload_alegra"]["inventoryAccount"]["id"] == "5349", f"esperado 5349 (Inventario repuestos)"
    assert result["payload_alegra"]["costsAccount"]["id"] == "5522",     f"esperado 5522 (Costo repuestos)"
    assert result["cuentas"]["account"]["niif"] == "41350601"


def test_payload_compra_motos_usa_ids_internos():
    """Verifica que el payload de registrar_compra_motos use IDs internos."""
    import inspect
    from agents.contador.handlers import facturacion
    src = inspect.getsource(facturacion.handle_registrar_compra_motos)
    # Debe contener los IDs internos
    assert '"5442"' in src, "Falta ID 5442 (Ingresos ventas motos)"
    assert '"5348"' in src, "Falta ID 5348 (Inventario motos)"
    assert '"5520"' in src, "Falta ID 5520 (Costo ventas motos)"


def test_payload_crear_item_inventario_usa_ids_internos():
    """Verifica que crear_item_inventario use IDs internos para motos y repuestos."""
    import inspect
    from agents.contador.handlers import facturacion
    src = inspect.getsource(facturacion.handle_crear_item_inventario)
    # Motos
    assert '"5442"' in src, "Falta ID 5442 (Ingresos motos)"
    