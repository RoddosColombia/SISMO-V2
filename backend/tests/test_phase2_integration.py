"""
Wave 7 — Phase 2 integration tests + smoke test + static analysis.

12 tests verifying end-to-end flows across all Wave 3-6 handlers.
T12 is static analysis: no contable MongoDB writes in handlers/.
"""
import pathlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.retenciones import calcular_retenciones


@pytest.fixture
def mock_alegra():
    client = AsyncMock()
    client.request_with_verify = AsyncMock(return_value={"id": 555, "_alegra_id": "555"})
    client.get = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.roddos_events = MagicMock()
    db.roddos_events.insert_one = AsyncMock()
    db.loanbook = MagicMock()
    db.loanbook.find_one = AsyncMock(return_value={"loanbook_id": "LB-001", "factura_alegra_id": "500"})
    db.loanbook.insert_one = AsyncMock()
    db.loanbook.update_one = AsyncMock()
    db.inventario_motos = MagicMock()
    db.inventario_motos.find_one = AsyncMock(return_value={
        "vin": "TEST123", "motor": "M456", "modelo": "TVS Sport", "color": "Rojo", "estado": "disponible", "precio": 7000000,
    })
    db.inventario_motos.update_one = AsyncMock()
    db.plan_ingresos_roddos = MagicMock()
    db.plan_ingresos_roddos.find_one = AsyncMock(return_value={"tipo": "ingresos_financieros", "alegra_id": 4100})
    db.plan_cuentas_roddos = MagicMock()
    db.plan_cuentas_roddos.find_one = AsyncMock(return_value={"tipo": "cxc_socios", "alegra_id": 1305})
    return db


# T1: User describes gasto → dispatcher → handler → journal → event
@pytest.mark.asyncio
async def test_t1_gasto_end_to_end(mock_alegra, mock_db):
    from agents.contador.handlers.egresos import handle_registrar_gasto
    tool_input = {"descripcion": "pago arriendo bodega enero", "monto": 3614953, "banco": "BBVA"}
    with patch("agents.contador.handlers.egresos.validate_write_permission"):
        with patch("agents.contador.handlers.egresos.publish_event", new_callable=AsyncMock) as mock_pub:
            result = await handle_registrar_gasto(tool_input, mock_alegra, mock_db, mock_db, "user1")
            assert result["success"] is True
            assert result["alegra_id"] == "555"
            mock_pub.assert_called_once()


# T2: Gasto with ReteFuente 3.5% — entries balance
def test_t2_arriendo_retenciones_balance():
    r = calcular_retenciones("arriendo", 3_614_953)
    total = r["retefuente_monto"] + r["reteica_monto"] + r["neto_a_pagar"]
    assert round(total, 2) == 3_614_953.0


# T3: Gasto de socio → CXC, not gasto operativo
@pytest.mark.asyncio
async def test_t3_socio_routes_cxc(mock_alegra, mock_db):
    from agents.contador.handlers.egresos import handle_registrar_gasto
    tool_input = {"descripcion": "retiro personal 80075452 Andres", "monto": 500000, "banco": "Bancolombia"}
    with patch("agents.contador.handlers.egresos.validate_write_permission"):
        with patch("agents.contador.handlers.egresos.publish_event", new_callable=AsyncMock) as mock_pub:
            result = await handle_registrar_gasto(tool_input, mock_alegra, mock_db, mock_db, "user1")
            assert result["success"] is True
            event_type = mock_pub.call_args.kwargs.get("event_type", "")
            assert "cxc" in event_type.lower()


# T4: Factura venta moto sin VIN → BLOQUEO
@pytest.mark.asyncio
async def test_t4_factura_sin_vin_bloqueada(mock_alegra, mock_db):
    from agents.contador.handlers.facturacion import handle_crear_factura_venta_moto
    tool_input = {"cliente_nombre": "Juan", "cliente_cedula": "123", "moto_vin": "", "plan": "P52S"}
    with patch("agents.contador.handlers.facturacion.validate_write_permission"):
        result = await handle_crear_factura_venta_moto(tool_input, mock_alegra, mock_db, mock_db, "u1")
        assert result["success"] is False
        assert "VIN" in result["error"]


# T5: Factura venta moto con VIN → event published (no direct MongoDB writes)
@pytest.mark.asyncio
async def test_t5_factura_con_vin_cascade(mock_alegra, mock_db):
    from agents.contador.handlers.facturacion import handle_crear_factura_venta_moto
    tool_input = {"cliente_nombre": "Juan", "cliente_cedula": "123", "moto_vin": "TEST123", "plan": "P52S"}
    with patch("agents.contador.handlers.facturacion.validate_write_permission"):
        with patch("agents.contador.handlers.facturacion.publish_event", new_callable=AsyncMock) as mock_pub:
            result = await handle_crear_factura_venta_moto(tool_input, mock_alegra, mock_db, mock_db, "u1")
            assert result["success"] is True
            mock_pub.assert_called_once()
            call_kwargs = mock_pub.call_args.kwargs
            assert call_kwargs["event_type"] == "factura.venta.creada"
            datos = call_kwargs["datos"]
            assert datos["factura_id"] == "555"
            assert datos["cliente_nombre"] == "Juan"
            assert datos["cliente_cedula"] == "123"
            assert datos["vin"] == "TEST123"
            assert datos["motor"] == "M456"
            assert datos["modelo"] == "TVS Sport"
            assert datos["color"] == "Rojo"
            assert datos["plan"] == "P52S"
            assert "fecha" in datos


# T6: Consulta P&L → retorna datos sin error
@pytest.mark.asyncio
async def test_t6_consulta_pl(mock_alegra, mock_db):
    from agents.contador.handlers.consultas import handle_consultar_estado_resultados
    mock_alegra.get = AsyncMock(return_value={"revenue": 1000000, "expenses": 500000})
    result = await handle_consultar_estado_resultados({}, mock_alegra, mock_db, mock_db, "u1")
    assert result["success"] is True


# T7: Pago cuota → evento publicado
@pytest.mark.asyncio
async def test_t7_pago_cuota_event(mock_alegra, mock_db):
    from agents.contador.handlers.cartera import handle_registrar_pago_cuota
    tool_input = {"loanbook_id": "LB-001", "monto": 175000, "banco": "Bancolombia", "numero_cuota": 5}
    with patch("agents.contador.handlers.cartera.validate_write_permission"):
        with patch("agents.contador.handlers.cartera.publish_event", new_callable=AsyncMock) as mock_pub:
            result = await handle_registrar_pago_cuota(tool_input, mock_alegra, mock_db, mock_db, "u1")
            assert result["success"] is True
            mock_pub.assert_called_once()
            assert mock_pub.call_args.kwargs["event_type"] == "pago.cuota.registrado"


# T8: Nomina duplicada → anti-dup bloquea
@pytest.mark.asyncio
async def test_t8_nomina_antidup(mock_alegra, mock_db):
    from agents.contador.handlers.nomina import handle_registrar_nomina_mensual
    mock_alegra.get = AsyncMock(return_value=[{"observations": "Nómina Alexa 2/2026", "id": 1}])
    tool_input = {"mes": 2, "anio": 2026, "empleados": [{"nombre": "Alexa", "salario": 4500000}]}
    with patch("agents.contador.handlers.nomina.validate_write_permission"):
        with patch("agents.contador.handlers.nomina.publish_event", new_callable=AsyncMock):
            result = await handle_registrar_nomina_mensual(tool_input, mock_alegra, mock_db, mock_db, "u1")
            assert result["resultados"][0]["status"] == "duplicado"


# T9: Anular journal → DELETE verificado
@pytest.mark.asyncio
async def test_t10_anular_journal(mock_alegra, mock_db):
    from agents.contador.handlers.egresos import handle_anular_causacion
    mock_alegra.get = AsyncMock(side_effect=[{"id": 100}, Exception("404")])
    mock_alegra.request_with_verify = AsyncMock(return_value={"deleted": True})
    tool_input = {"journal_id": 100, "motivo": "duplicado"}
    with patch("agents.contador.handlers.egresos.validate_write_permission"):
        with patch("agents.contador.handlers.egresos.publish_event", new_callable=AsyncMock):
            result = await handle_anular_causacion(tool_input, mock_alegra, mock_db, mock_db, "u1")
            assert result["success"] is True


# T11: Auteco → sin ReteFuente
def test_t11_auteco_sin_retefuente():
    r = calcular_retenciones("compras", 10_000_000, "860024781")
    assert r["retefuente_monto"] == 0.0
    assert r["reteica_monto"] > 0  # ReteICA still applies


# T12: STATIC ANALYSIS — no contable MongoDB writes in handlers/
def test_t12_static_no_contable_mongodb_writes():
    """grep insert_one/update_one in handlers/ excluding allowed collections → MUST be 0."""
    handlers_dir = pathlib.Path("agents/contador/handlers")
    if not handlers_dir.exists():
        pytest.skip("handlers/ directory not found")

    allowed_collections = {"roddos_events", "conciliacion_jobs", "inventario_motos", "loanbook",
                           "backlog_movimientos", "conciliacion_extractos_procesados",
                           "conciliacion_movimientos_procesados"}
    violations = []

    for py_file in handlers_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        content = py_file.read_text(encoding="utf-8")
        for i, line in enumerate(content.split("\n"), 1):
            for op in ["insert_one", "insert_many", "update_one", "replace_one"]:
                if op in line:
                    # Check if the line references an allowed collection
                    if not any(col in line for col in allowed_collections):
                        violations.append(f"{py_file.name}:L{i}: {line.strip()}")

    assert len(violations) == 0, f"Contable MongoDB writes found in handlers:\n" + "\n".join(violations)
