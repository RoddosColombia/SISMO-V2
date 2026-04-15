"""
Sprint 5 — CRM Clientes: endpoints + DataKeeper handler sync.

Tests cover:
1. CRUD endpoints (create, read, update, list with filters)
2. Stats endpoint
3. Handler loanbook.creado → sync CRM
4. Duplicate cédula handling
"""
import pytest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid


# ═══════════════════════════════════════════
# CRM data model validation
# ═══════════════════════════════════════════


class TestCRMModel:
    """Validate CRM client data structure."""

    def test_crear_cliente_doc(self):
        from core.crm_model import crear_cliente_doc

        doc = crear_cliente_doc(
            cedula="123456",
            nombre="Juan Perez",
            telefono="573001234567",
        )
        assert doc["cedula"] == "123456"
        assert doc["nombre"] == "Juan Perez"
        assert doc["telefono"] == "573001234567"
        assert doc["estado"] == "activo"
        assert doc["score"] is None  # Set by Phase 8 RADAR
        assert doc["loanbooks"] == []
        assert doc["notas"] == ""

    def test_crear_cliente_doc_optional_fields(self):
        from core.crm_model import crear_cliente_doc

        doc = crear_cliente_doc(
            cedula="123456",
            nombre="Juan Perez",
            telefono="573001234567",
            email="juan@email.com",
            direccion="Calle 123",
        )
        assert doc["email"] == "juan@email.com"
        assert doc["direccion"] == "Calle 123"

    def test_crear_cliente_doc_has_timestamps(self):
        from core.crm_model import crear_cliente_doc

        doc = crear_cliente_doc(
            cedula="123456",
            nombre="Juan",
            telefono="573001234567",
        )
        assert "created_at" in doc
        assert "updated_at" in doc
        assert "fecha_registro" in doc

    def test_telefono_format_validation(self):
        from core.crm_model import validar_telefono

        assert validar_telefono("573001234567") is True
        assert validar_telefono("3001234567") is False  # Missing country code
        assert validar_telefono("123") is False

    def test_estados_validos(self):
        from core.crm_model import ESTADOS_CRM

        assert "activo" in ESTADOS_CRM
        assert "inactivo" in ESTADOS_CRM
        assert "mora" in ESTADOS_CRM
        assert "saldado" in ESTADOS_CRM


# ═══════════════════════════════════════════
# CRM Router — CRUD operations
# ═══════════════════════════════════════════


class TestCRMRouter:
    """Test CRM endpoints with mocked DB."""

    @pytest.mark.asyncio
    async def test_crear_cliente_success(self):
        from routers.crm import _crear_cliente

        db = AsyncMock()
        db.crm_clientes.find_one = AsyncMock(return_value=None)  # No duplicate
        db.crm_clientes.insert_one = AsyncMock()

        result = await _crear_cliente(db, {
            "cedula": "123456",
            "nombre": "Juan Perez",
            "telefono": "573001234567",
        })
        assert result["cedula"] == "123456"
        db.crm_clientes.insert_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_crear_cliente_duplicado_raises(self):
        from routers.crm import _crear_cliente

        db = AsyncMock()
        db.crm_clientes.find_one = AsyncMock(return_value={"cedula": "123456"})

        with pytest.raises(ValueError, match="[Dd]uplic|existe"):
            await _crear_cliente(db, {
                "cedula": "123456",
                "nombre": "Juan Perez",
                "telefono": "573001234567",
            })

    @pytest.mark.asyncio
    async def test_get_cliente_por_cedula(self):
        from routers.crm import _get_cliente

        db = AsyncMock()
        db.crm_clientes.find_one = AsyncMock(return_value={
            "cedula": "123456",
            "nombre": "Juan Perez",
            "loanbooks": ["lb-001"],
            "_id": "fake",
        })

        result = await _get_cliente(db, "123456")
        assert result["cedula"] == "123456"
        assert result["loanbooks"] == ["lb-001"]
        assert "_id" not in result  # MongoDB _id stripped

    @pytest.mark.asyncio
    async def test_get_cliente_not_found(self):
        from routers.crm import _get_cliente

        db = AsyncMock()
        db.crm_clientes.find_one = AsyncMock(return_value=None)

        result = await _get_cliente(db, "999999")
        assert result is None

    @pytest.mark.asyncio
    async def test_actualizar_cliente(self):
        from routers.crm import _actualizar_cliente

        db = AsyncMock()
        db.crm_clientes.find_one = AsyncMock(return_value={"cedula": "123456"})
        db.crm_clientes.update_one = AsyncMock()

        result = await _actualizar_cliente(db, "123456", {
            "telefono": "573009999999",
            "notas": "Cliente preferencial",
        })
        assert result is True
        db.crm_clientes.update_one.assert_called_once()
        call_args = db.crm_clientes.update_one.call_args
        update_set = call_args[0][1]["$set"]
        assert update_set["telefono"] == "573009999999"
        assert update_set["notas"] == "Cliente preferencial"
        assert "updated_at" in update_set

    @pytest.mark.asyncio
    async def test_listar_clientes_con_filtro_estado(self):
        from routers.crm import _listar_clientes

        # Mock cursor chain: find().sort().to_list()
        mock_cursor = AsyncMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=[
            {"cedula": "111", "nombre": "Ana", "estado": "activo", "_id": "x"},
            {"cedula": "222", "nombre": "Luis", "estado": "activo", "_id": "y"},
        ])
        db = AsyncMock()
        db.crm_clientes.find = MagicMock(return_value=mock_cursor)

        result = await _listar_clientes(db, estado="activo")
        assert len(result) == 2
        # Verify filter was passed
        db.crm_clientes.find.assert_called_once()
        filter_arg = db.crm_clientes.find.call_args[0][0]
        assert filter_arg["estado"] == "activo"

    @pytest.mark.asyncio
    async def test_listar_clientes_sin_filtro(self):
        from routers.crm import _listar_clientes

        mock_cursor = AsyncMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=[])
        db = AsyncMock()
        db.crm_clientes.find = MagicMock(return_value=mock_cursor)

        result = await _listar_clientes(db, estado=None)
        filter_arg = db.crm_clientes.find.call_args[0][0]
        assert filter_arg == {}  # No filter

    @pytest.mark.asyncio
    async def test_stats_returns_counts(self):
        from routers.crm import _get_stats

        db = AsyncMock()
        # Order: total, then ESTADOS_CRM = [activo, inactivo, mora, saldado]
        db.crm_clientes.count_documents = AsyncMock(side_effect=[
            23,  # total
            15,  # activo
            0,   # inactivo
            3,   # mora
            5,   # saldado
        ])

        result = await _get_stats(db)
        assert result["total"] == 23
        assert result["por_estado"]["activo"] == 15
        assert result["por_estado"]["inactivo"] == 0
        assert result["por_estado"]["mora"] == 3
        assert result["por_estado"]["saldado"] == 5


# ═══════════════════════════════════════════
# Handler: loanbook.creado → sync CRM
# ═══════════════════════════════════════════


def _make_event(event_type, datos):
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "source": "test",
        "correlation_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "datos": datos,
        "alegra_id": None,
        "accion_ejecutada": "test",
    }


class TestCRMSyncHandler:
    """loanbook.creado event → upsert CRM client."""

    @pytest.mark.asyncio
    async def test_creates_new_client_if_not_exists(self):
        from core.crm_handlers import handle_loanbook_creado

        db = AsyncMock()
        db.crm_clientes.find_one = AsyncMock(return_value=None)
        db.crm_clientes.insert_one = AsyncMock()
        db.crm_clientes.update_one = AsyncMock()

        event = _make_event("loanbook.creado", {
            "loanbook_id": "lb-001",
            "cliente": {
                "nombre": "Juan Perez",
                "cedula": "123456",
                "telefono": "573001234567",
            },
        })

        await handle_loanbook_creado(event, db)

        # Should insert new client
        db.crm_clientes.insert_one.assert_called_once()
        doc = db.crm_clientes.insert_one.call_args[0][0]
        assert doc["cedula"] == "123456"
        assert doc["nombre"] == "Juan Perez"
        assert "lb-001" in doc["loanbooks"]

    @pytest.mark.asyncio
    async def test_adds_loanbook_to_existing_client(self):
        from core.crm_handlers import handle_loanbook_creado

        db = AsyncMock()
        db.crm_clientes.find_one = AsyncMock(return_value={
            "cedula": "123456",
            "nombre": "Juan Perez",
            "loanbooks": ["lb-000"],
        })
        db.crm_clientes.update_one = AsyncMock()

        event = _make_event("loanbook.creado", {
            "loanbook_id": "lb-001",
            "cliente": {
                "nombre": "Juan Perez",
                "cedula": "123456",
                "telefono": "573001234567",
            },
        })

        await handle_loanbook_creado(event, db)

        # Should update existing, not insert
        db.crm_clientes.update_one.assert_called_once()
        call_args = db.crm_clientes.update_one.call_args
        assert call_args[0][0] == {"cedula": "123456"}
        add_to_set = call_args[0][1].get("$addToSet", {})
        assert add_to_set["loanbooks"] == "lb-001"

    @pytest.mark.asyncio
    async def test_handler_registered_in_event_system(self):
        from core.crm_handlers import handle_loanbook_creado
        from core.event_handlers import get_registry

        registry = get_registry()
        assert "loanbook.creado" in registry


# ═══════════════════════════════════════════
# Integration: apartado publishes loanbook.creado
# ═══════════════════════════════════════════


class TestApartadoPublishesLoanbookCreado:
    """handle_apartado_completo should publish loanbook.creado event."""

    @pytest.mark.asyncio
    async def test_apartado_publishes_loanbook_creado(self):
        from core.loanbook_handlers import handle_apartado_completo

        db = AsyncMock()
        db.catalogo_planes.find_one = AsyncMock(return_value={
            "codigo": "P52S",
            "cuotas_base": 52,
            "anzi_pct": 0.02,
            "cuotas_modelo": {"Sport 100": 160_000},
        })
        db.loanbook.insert_one = AsyncMock()
        db.inventario_motos.update_one = AsyncMock()
        db.roddos_events.insert_one = AsyncMock()

        event = _make_event("apartado.completo", {
            "vin": "VIN001",
            "cliente": {"nombre": "Juan", "cedula": "123", "telefono": "573001234567"},
            "plan_codigo": "P52S",
            "modelo": "Sport 100",
            "modalidad": "semanal",
            "fecha_entrega": "2026-04-14",
        })

        await handle_apartado_completo(event, db)

        # Should publish loanbook.creado event
        db.roddos_events.insert_one.assert_called_once()
        published = db.roddos_events.insert_one.call_args[0][0]
        assert published["event_type"] == "loanbook.creado"
        assert published["datos"]["cliente"]["cedula"] == "123"
        assert "loanbook_id" in published["datos"]
