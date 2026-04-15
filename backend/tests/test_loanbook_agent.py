"""
Sprint 7 — Agente Loanbook: 11 Tools + Router + Permissions.

TDD: Tests written FIRST, expect RED until implementation.

Tests cover:
1. All 11 tools return correct data with mocks
2. Router dispatches credit queries to loanbook, not contador
3. Router dispatches expense queries to contador, not loanbook
4. WRITE_PERMISSIONS blocks unauthorized writes
5. registrar_pago_cuota publishes cuota.pagada event
6. Read-only vs write tool classification
7. LoanToolDispatcher wiring
"""
import pytest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

# ═══════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════

PLAN_P52S = {
    "codigo": "P52S",
    "nombre": "Plan 52 Semanas",
    "cuotas_base": 52,
    "anzi_pct": 0.02,
    "cuotas_modelo": {"Sport 100": 160_000, "Raider 125": 179_900},
}

SAMPLE_LOANBOOK = {
    "loanbook_id": "lb-001",
    "vin": "VIN001",
    "cliente": {"nombre": "Juan Perez", "cedula": "1234567890", "telefono": "573001234567"},
    "plan_codigo": "P52S",
    "modelo": "Sport 100",
    "modalidad": "semanal",
    "estado": "activo",
    "cuota_monto": 160_000,
    "num_cuotas": 52,
    "saldo_capital": 8_000_000,
    "total_pagado": 320_000,
    "total_mora_pagada": 0,
    "total_anzi_pagado": 6_400,
    "anzi_pct": 0.02,
    "fecha_entrega": "2026-03-01",
    "fecha_primer_pago": None,
    "fecha_creacion": "2026-03-01",
    "fecha_activacion": "2026-03-01T00:00:00+00:00",
    "fecha_primera_cuota": "2026-03-11",
    "fecha_ultima_cuota": "2027-03-03",
    "cuotas": [
        {"numero": 1, "monto": 160_000, "estado": "pagada", "fecha": "2026-03-11", "fecha_pago": "2026-03-11", "mora_acumulada": 0},
        {"numero": 2, "monto": 160_000, "estado": "pagada", "fecha": "2026-03-18", "fecha_pago": "2026-03-18", "mora_acumulada": 0},
        {"numero": 3, "monto": 160_000, "estado": "pendiente", "fecha": "2026-03-25", "fecha_pago": None, "mora_acumulada": 0},
        {"numero": 4, "monto": 160_000, "estado": "pendiente", "fecha": "2026-04-01", "fecha_pago": None, "mora_acumulada": 0},
        {"numero": 5, "monto": 160_000, "estado": "pendiente", "fecha": "2026-04-08", "fecha_pago": None, "mora_acumulada": 0},
        {"numero": 6, "monto": 160_000, "estado": "pendiente", "fecha": "2026-04-15", "fecha_pago": None, "mora_acumulada": 0},
        {"numero": 7, "monto": 160_000, "estado": "pendiente", "fecha": "2026-04-22", "fecha_pago": None, "mora_acumulada": 0},
        {"numero": 8, "monto": 160_000, "estado": "pendiente", "fecha": "2026-04-29", "fecha_pago": None, "mora_acumulada": 0},
        {"numero": 9, "monto": 160_000, "estado": "pendiente", "fecha": "2026-05-06", "fecha_pago": None, "mora_acumulada": 0},
    ],
}

SAMPLE_MOTO = {
    "vin": "VIN-DISP-001",
    "modelo": "Sport 100",
    "color": "Rojo",
    "estado": "disponible",
    "precio_venta": 8_500_000,
}

SAMPLE_CLIENTE = {
    "cedula": "1234567890",
    "nombre": "Juan Perez",
    "telefono": "573001234567",
    "email": "juan@test.com",
    "estado": "activo",
    "loanbooks": ["lb-001"],
    "score": None,
    "notas": "",
}


def _mock_db():
    """Create mock DB with all collections needed by loanbook agent."""
    db = AsyncMock()

    # loanbook collection
    db.loanbook = AsyncMock()
    db.loanbook.find_one = AsyncMock(return_value=SAMPLE_LOANBOOK.copy())

    # Make find() return a mock cursor
    cursor = AsyncMock()
    cursor.sort = MagicMock(return_value=cursor)
    cursor.to_list = AsyncMock(return_value=[SAMPLE_LOANBOOK.copy()])
    db.loanbook.find = MagicMock(return_value=cursor)
    db.loanbook.insert_one = AsyncMock()
    db.loanbook.update_one = AsyncMock()

    # inventario_motos
    db.inventario_motos = AsyncMock()
    inv_cursor = AsyncMock()
    inv_cursor.to_list = AsyncMock(return_value=[SAMPLE_MOTO.copy()])
    db.inventario_motos.find = MagicMock(return_value=inv_cursor)
    db.inventario_motos.find_one = AsyncMock(return_value=SAMPLE_MOTO.copy())
    db.inventario_motos.update_one = AsyncMock()

    # catalogo_planes
    db.catalogo_planes = AsyncMock()
    db.catalogo_planes.find_one = AsyncMock(return_value=PLAN_P52S.copy())

    # crm_clientes
    db.crm_clientes = AsyncMock()
    db.crm_clientes.find_one = AsyncMock(return_value=SAMPLE_CLIENTE.copy())

    # apartados
    db.apartados = AsyncMock()
    db.apartados.insert_one = AsyncMock()
    db.apartados.find_one = AsyncMock(return_value=None)
    db.apartados.update_one = AsyncMock()

    # roddos_events (event bus)
    db.roddos_events = AsyncMock()
    db.roddos_events.insert_one = AsyncMock()

    return db


# ═══════════════════════════════════════════
# Test Group 1: Router keywords dispatch
# ═══════════════════════════════════════════

class TestRouterLoanbook:
    """Test that router dispatches credit queries to loanbook agent."""

    def test_credito_juan_routes_to_loanbook(self):
        from core.router import route_intent
        result = route_intent("¿cómo va el crédito de Juan?")
        assert result.agent == "loanbook", f"Expected loanbook, got {result.agent}"
        assert result.confidence >= 0.70

    def test_registra_gasto_routes_to_contador(self):
        from core.router import route_intent
        result = route_intent("registra este gasto de arriendo por 3 millones")
        assert result.agent == "contador", f"Expected contador, got {result.agent}"
        assert result.confidence >= 0.70

    def test_mora_routes_to_loanbook(self):
        """'mora' keyword should route to loanbook when combined with credit context."""
        from core.router import route_intent
        result = route_intent("¿cuántos créditos están en mora?")
        assert result.agent == "loanbook"

    def test_apartar_moto_routes_to_loanbook(self):
        from core.router import route_intent
        result = route_intent("quiero apartar una moto, crédito semanal para el cliente")
        assert result.agent == "loanbook"

    def test_liquidar_credito_routes_to_loanbook(self):
        from core.router import route_intent
        result = route_intent("¿cuánto falta para liquidar el crédito de VIN ABC123?")
        assert result.agent == "loanbook"

    def test_pago_cuota_routes_to_loanbook(self):
        from core.router import route_intent
        result = route_intent("registrar pago de cuota del crédito lb-001")
        assert result.agent == "loanbook"

    def test_entrega_moto_routes_to_loanbook(self):
        from core.router import route_intent
        result = route_intent("la moto fue entregada hoy, registrar entrega")
        assert result.agent == "loanbook"

    def test_inventario_disponible_routes_to_loanbook(self):
        from core.router import route_intent
        result = route_intent("¿qué motos hay disponibles en inventario?")
        assert result.agent == "loanbook"

    def test_resumen_cartera_routes_to_loanbook(self):
        from core.router import route_intent
        result = route_intent("dame el resumen de cartera de créditos")
        assert result.agent == "loanbook"


# ═══════════════════════════════════════════
# Test Group 2: Permissions
# ═══════════════════════════════════════════

class TestPermissions:
    """Test WRITE_PERMISSIONS for loanbook agent."""

    def test_loanbook_can_write_loanbook(self):
        from core.permissions import validate_write_permission
        assert validate_write_permission("loanbook", "loanbook", "mongodb") is True

    def test_loanbook_can_write_inventario(self):
        from core.permissions import validate_write_permission
        assert validate_write_permission("loanbook", "inventario_motos", "mongodb") is True

    def test_loanbook_can_write_events(self):
        from core.permissions import validate_write_permission
        assert validate_write_permission("loanbook", "roddos_events", "mongodb") is True

    def test_loanbook_can_write_apartados(self):
        from core.permissions import validate_write_permission
        assert validate_write_permission("loanbook", "apartados", "mongodb") is True

    def test_loanbook_can_write_crm(self):
        from core.permissions import validate_write_permission
        assert validate_write_permission("loanbook", "crm_clientes", "mongodb") is True

    def test_loanbook_cannot_write_cartera_pagos(self):
        from core.permissions import validate_write_permission
        with pytest.raises(PermissionError):
            validate_write_permission("loanbook", "cartera_pagos", "mongodb")

    def test_loanbook_cannot_write_alegra(self):
        from core.permissions import validate_write_permission
        with pytest.raises(PermissionError):
            validate_write_permission("loanbook", "POST /journals", "alegra")

    def test_loanbook_cannot_write_cfo(self):
        from core.permissions import validate_write_permission
        with pytest.raises(PermissionError):
            validate_write_permission("loanbook", "cfo_informes", "mongodb")


# ═══════════════════════════════════════════
# Test Group 3: Tool definitions
# ═══════════════════════════════════════════

class TestToolDefinitions:
    """Test that tool definitions are correct Anthropic format."""

    def test_loanbook_has_11_tools(self):
        from agents.contador.tools import get_tools_for_agent
        tools = get_tools_for_agent("loanbook")
        assert len(tools) == 11, f"Expected 11 tools, got {len(tools)}"

    def test_all_tools_have_required_fields(self):
        from agents.contador.tools import get_tools_for_agent
        tools = get_tools_for_agent("loanbook")
        for tool in tools:
            assert "name" in tool, f"Tool missing 'name': {tool}"
            assert "description" in tool, f"Tool {tool.get('name')} missing 'description'"
            assert "input_schema" in tool, f"Tool {tool.get('name')} missing 'input_schema'"

    def test_tool_names_match_expected(self):
        from agents.contador.tools import get_tools_for_agent
        tools = get_tools_for_agent("loanbook")
        names = {t["name"] for t in tools}
        expected = {
            "consultar_loanbook",
            "listar_loanbooks",
            "registrar_apartado",
            "registrar_pago_parcial",
            "registrar_entrega",
            "registrar_pago_cuota",
            "consultar_mora",
            "calcular_liquidacion",
            "consultar_inventario",
            "consultar_cliente",
            "resumen_cartera",
        }
        assert names == expected, f"Mismatch: missing={expected - names}, extra={names - expected}"


# ═══════════════════════════════════════════
# Test Group 4: Read-only vs write classification
# ═══════════════════════════════════════════

class TestReadOnlyClassification:
    """Test that read-only tools are correctly classified."""

    def test_read_only_tools(self):
        from agents.loanbook.handlers.dispatcher import is_read_only_tool
        read_only = [
            "consultar_loanbook",
            "listar_loanbooks",
            "consultar_mora",
            "calcular_liquidacion",
            "consultar_inventario",
            "consultar_cliente",
            "resumen_cartera",
        ]
        for name in read_only:
            assert is_read_only_tool(name), f"{name} should be read-only"

    def test_write_tools_not_read_only(self):
        from agents.loanbook.handlers.dispatcher import is_read_only_tool
        write_tools = [
            "registrar_apartado",
            "registrar_pago_parcial",
            "registrar_entrega",
            "registrar_pago_cuota",
        ]
        for name in write_tools:
            assert not is_read_only_tool(name), f"{name} should NOT be read-only"


# ═══════════════════════════════════════════
# Test Group 5: Handler implementations (11 tools)
# ═══════════════════════════════════════════

class TestConsultarLoanbook:
    """Tool 1: consultar_loanbook — search by VIN or client name."""

    @pytest.mark.asyncio
    async def test_search_by_vin(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "consultar_loanbook",
            {"busqueda": "VIN001"},
            user_id="test",
        )
        assert result["success"] is True
        assert result["loanbook"]["vin"] == "VIN001"

    @pytest.mark.asyncio
    async def test_search_by_name(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        # find_one by VIN returns None, find by client name returns list
        db.loanbook.find_one = AsyncMock(return_value=None)
        cursor = AsyncMock()
        cursor.to_list = AsyncMock(return_value=[SAMPLE_LOANBOOK.copy()])
        db.loanbook.find = MagicMock(return_value=cursor)

        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "consultar_loanbook",
            {"busqueda": "Juan"},
            user_id="test",
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_not_found(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        db.loanbook.find_one = AsyncMock(return_value=None)
        cursor = AsyncMock()
        cursor.to_list = AsyncMock(return_value=[])
        db.loanbook.find = MagicMock(return_value=cursor)

        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "consultar_loanbook",
            {"busqueda": "INEXISTENTE"},
            user_id="test",
        )
        assert result["success"] is False


class TestListarLoanbooks:
    """Tool 2: listar_loanbooks — list/filter by estado."""

    @pytest.mark.asyncio
    async def test_list_all(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "listar_loanbooks",
            {},
            user_id="test",
        )
        assert result["success"] is True
        assert "loanbooks" in result
        assert len(result["loanbooks"]) >= 1

    @pytest.mark.asyncio
    async def test_filter_by_estado(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "listar_loanbooks",
            {"estado": "activo"},
            user_id="test",
        )
        assert result["success"] is True


class TestRegistrarApartado:
    """Tool 3: registrar_apartado — create apartado + loanbook."""

    @pytest.mark.asyncio
    async def test_creates_apartado_and_publishes_event(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        # Moto must be disponible
        db.inventario_motos.find_one = AsyncMock(return_value={
            "vin": "VIN-DISP-001", "modelo": "Sport 100", "estado": "disponible"
        })

        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "registrar_apartado",
            {
                "vin": "VIN-DISP-001",
                "cliente": {"nombre": "Maria Lopez", "cedula": "9876543210", "telefono": "573009876543"},
                "plan_codigo": "P52S",
                "modelo": "Sport 100",
                "modalidad": "semanal",
                "fecha_entrega": "2026-04-15",
            },
            user_id="test",
        )
        assert result["success"] is True
        assert "loanbook_id" in result
        # Must publish event to roddos_events
        db.roddos_events.insert_one.assert_called()

    @pytest.mark.asyncio
    async def test_rejects_moto_not_disponible(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        db.inventario_motos.find_one = AsyncMock(return_value={
            "vin": "VIN-SOLD", "modelo": "Sport 100", "estado": "vendida"
        })

        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "registrar_apartado",
            {
                "vin": "VIN-SOLD",
                "cliente": {"nombre": "Test", "cedula": "111", "telefono": "573001111111"},
                "plan_codigo": "P52S",
                "modelo": "Sport 100",
                "modalidad": "semanal",
                "fecha_entrega": "2026-04-15",
            },
            user_id="test",
        )
        assert result["success"] is False
        assert "disponible" in result["error"].lower() or "no está" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_rejects_moto_not_found(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        db.inventario_motos.find_one = AsyncMock(return_value=None)

        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "registrar_apartado",
            {
                "vin": "VIN-GHOST",
                "cliente": {"nombre": "Test", "cedula": "111", "telefono": "573001111111"},
                "plan_codigo": "P52S",
                "modelo": "Sport 100",
                "modalidad": "semanal",
                "fecha_entrega": "2026-04-15",
            },
            user_id="test",
        )
        assert result["success"] is False


class TestRegistrarPagoParcial:
    """Tool 4: registrar_pago_parcial — add partial payment to apartado."""

    @pytest.mark.asyncio
    async def test_adds_payment_to_apartado(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        db.apartados.find_one = AsyncMock(return_value={
            "vin": "VIN001",
            "estado": "pendiente",
            "monto_total": 500_000,
            "pagos": [],
            "total_pagado": 0,
        })

        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "registrar_pago_parcial",
            {"vin": "VIN001", "monto": 200_000, "referencia": "TRX-001"},
            user_id="test",
        )
        assert result["success"] is True
        db.apartados.update_one.assert_called()


class TestRegistrarEntrega:
    """Tool 5: registrar_entrega — activate loanbook with cronograma."""

    @pytest.mark.asyncio
    async def test_activates_loanbook(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        # Loanbook in pendiente_entrega state
        lb = SAMPLE_LOANBOOK.copy()
        lb["estado"] = "pendiente_entrega"
        lb["cuotas"] = [
            {"numero": i, "monto": 160_000, "estado": "pendiente", "fecha": None, "fecha_pago": None, "mora_acumulada": 0}
            for i in range(1, 53)
        ]
        db.loanbook.find_one = AsyncMock(return_value=lb)

        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "registrar_entrega",
            {"vin": "VIN001", "fecha_entrega": "2026-04-14"},
            user_id="test",
        )
        assert result["success"] is True
        db.loanbook.update_one.assert_called()
        # Must publish event
        db.roddos_events.insert_one.assert_called()

    @pytest.mark.asyncio
    async def test_rejects_already_active(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        # Loanbook already active
        lb = SAMPLE_LOANBOOK.copy()
        lb["estado"] = "activo"
        db.loanbook.find_one = AsyncMock(return_value=lb)

        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "registrar_entrega",
            {"vin": "VIN001", "fecha_entrega": "2026-04-14"},
            user_id="test",
        )
        assert result["success"] is False


class TestRegistrarPagoCuota:
    """Tool 6: registrar_pago_cuota — apply waterfall, publish cuota.pagada."""

    @pytest.mark.asyncio
    async def test_applies_payment_and_publishes_event(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        # Active loanbook with pending cuota
        lb = SAMPLE_LOANBOOK.copy()
        lb["cuotas"] = [
            {"numero": 1, "monto": 160_000, "estado": "pagada", "fecha": "2026-03-11", "fecha_pago": "2026-03-11", "mora_acumulada": 0},
            {"numero": 2, "monto": 160_000, "estado": "pendiente", "fecha": "2026-03-18", "fecha_pago": None, "mora_acumulada": 0},
            {"numero": 3, "monto": 160_000, "estado": "pendiente", "fecha": "2026-03-25", "fecha_pago": None, "mora_acumulada": 0},
        ]
        lb["saldo_capital"] = 320_000
        db.loanbook.find_one = AsyncMock(return_value=lb)

        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "registrar_pago_cuota",
            {"vin": "VIN001", "monto": 164_000, "fecha_pago": "2026-03-18"},
            user_id="test",
        )
        assert result["success"] is True
        assert "waterfall" in result
        # Must publish cuota.pagada event
        db.roddos_events.insert_one.assert_called()
        event_call = db.roddos_events.insert_one.call_args[0][0]
        assert event_call["event_type"] == "cuota.pagada"

    @pytest.mark.asyncio
    async def test_rejects_no_loanbook(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        db.loanbook.find_one = AsyncMock(return_value=None)

        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "registrar_pago_cuota",
            {"vin": "VIN-GHOST", "monto": 160_000, "fecha_pago": "2026-03-18"},
            user_id="test",
        )
        assert result["success"] is False


class TestConsultarMora:
    """Tool 7: consultar_mora — mora summary."""

    @pytest.mark.asyncio
    async def test_mora_for_vin(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "consultar_mora",
            {"vin": "VIN001"},
            user_id="test",
        )
        assert result["success"] is True
        assert "dpd" in result

    @pytest.mark.asyncio
    async def test_mora_all(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "consultar_mora",
            {},
            user_id="test",
        )
        assert result["success"] is True


class TestCalcularLiquidacion:
    """Tool 8: calcular_liquidacion — payoff calculation."""

    @pytest.mark.asyncio
    async def test_calculates_payoff(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "calcular_liquidacion",
            {"vin": "VIN001"},
            user_id="test",
        )
        assert result["success"] is True
        assert "saldo_capital" in result
        assert "mora_acumulada" in result
        assert "total_liquidacion" in result


class TestConsultarInventario:
    """Tool 9: consultar_inventario — available motos."""

    @pytest.mark.asyncio
    async def test_returns_available_motos(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "consultar_inventario",
            {},
            user_id="test",
        )
        assert result["success"] is True
        assert "motos" in result
        assert len(result["motos"]) >= 1

    @pytest.mark.asyncio
    async def test_filter_by_modelo(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "consultar_inventario",
            {"modelo": "Sport 100"},
            user_id="test",
        )
        assert result["success"] is True


class TestConsultarCliente:
    """Tool 10: consultar_cliente — CRM lookup."""

    @pytest.mark.asyncio
    async def test_find_by_cedula(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "consultar_cliente",
            {"busqueda": "1234567890"},
            user_id="test",
        )
        assert result["success"] is True
        assert result["cliente"]["cedula"] == "1234567890"

    @pytest.mark.asyncio
    async def test_not_found(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        db.crm_clientes.find_one = AsyncMock(return_value=None)
        cursor = AsyncMock()
        cursor.to_list = AsyncMock(return_value=[])
        db.crm_clientes.find = MagicMock(return_value=cursor)

        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "consultar_cliente",
            {"busqueda": "INEXISTENTE"},
            user_id="test",
        )
        assert result["success"] is False


class TestResumenCartera:
    """Tool 11: resumen_cartera — executive portfolio summary."""

    @pytest.mark.asyncio
    async def test_returns_portfolio_summary(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "resumen_cartera",
            {},
            user_id="test",
        )
        assert result["success"] is True
        assert "total_creditos" in result
        assert "activos" in result
        assert "cartera_total" in result
        assert "en_mora" in result


# ═══════════════════════════════════════════
# Test Group 6: Dispatcher integration
# ═══════════════════════════════════════════

class TestLoanToolDispatcher:
    """Test dispatcher routes to correct handlers."""

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        dispatcher = LoanToolDispatcher(db=db)
        result = await dispatcher.dispatch(
            "tool_inexistente",
            {},
            user_id="test",
        )
        assert result["success"] is False
        assert "no encontrado" in result["error"].lower() or "Handler" in result["error"]

    @pytest.mark.asyncio
    async def test_all_11_tools_have_handlers(self):
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        db = _mock_db()
        dispatcher = LoanToolDispatcher(db=db)
        expected_tools = [
            "consultar_loanbook", "listar_loanbooks", "registrar_apartado",
            "registrar_pago_parcial", "registrar_entrega", "registrar_pago_cuota",
            "consultar_mora", "calcular_liquidacion", "consultar_inventario",
            "consultar_cliente", "resumen_cartera",
        ]
        for tool_name in expected_tools:
            assert tool_name in dispatcher._handlers, f"Missing handler for {tool_name}"


# ═══════════════════════════════════════════
# Test Group 7: chat.py integration
# ═══════════════════════════════════════════

class TestChatIntegration:
    """Test that chat.py correctly wires loanbook tools and dispatcher."""

    def test_get_tools_returns_11_for_loanbook(self):
        from agents.contador.tools import get_tools_for_agent
        tools = get_tools_for_agent("loanbook")
        assert len(tools) == 11

    def test_system_prompt_loanbook_has_tools_section(self):
        from agents.prompts import SYSTEM_PROMPT_LOANBOOK
        assert "HERRAMIENTAS" in SYSTEM_PROMPT_LOANBOOK
        assert "consultar_loanbook" in SYSTEM_PROMPT_LOANBOOK or "Loanbook" in SYSTEM_PROMPT_LOANBOOK
