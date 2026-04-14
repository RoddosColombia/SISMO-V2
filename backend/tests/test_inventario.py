"""Tests for inventario module — motos, apartados, repuestos, kits.

Adjusted for VIN-based flow:
- Motos registered manually in MongoDB with VIN
- Apartado keyed by VIN, not just item_id
- Anticipos account: 5370 (NIIF 2805)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

# ═══════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════

SAMPLE_MOTO_ITEM = {
    "id": "25",
    "name": "Moto nueva 100",
    "type": "product",
    "description": "MOTOCICLETA SPORT 100 ELS NEGRO",
    "reference": "60006459",
    "itemCategory": {"id": 1, "name": "Motos nuevas"},
    "inventory": {"availableQuantity": 23, "unitCost": 4157461, "unit": "unit"},
    "price": [{"price": 4831933}],
}

SAMPLE_MOTO_USADA = {
    "id": "31",
    "name": "Moto Usada 160",
    "type": "product",
    "description": "MOTO APACHE RTR 160",
    "reference": None,
    "itemCategory": {"id": 2, "name": "Motos usadas"},
    "inventory": {"availableQuantity": 2, "unitCost": 0, "unit": "unit"},
    "price": [{"price": 5500000}],
}

SAMPLE_SERVICE_ITEM = {
    "id": "1",
    "name": "Arriendo oficina",
    "type": "service",
    "description": None,
    "reference": None,
    "itemCategory": None,
    "inventory": {"unit": "service"},
    "price": [{"price": 700000}],
}

SAMPLE_REPUESTO_ITEM = {
    "id": "50",
    "name": "Filtro aceite Sport 100",
    "type": "product",
    "description": "Filtro de aceite para Sport 100",
    "reference": "FLT-001",
    "itemCategory": {"id": 5, "name": "Repuestos"},
    "inventory": {"availableQuantity": 15, "unit": "unit"},
    "price": [{"price": 12000}],
}


@pytest.fixture
def mock_alegra():
    client = AsyncMock()
    return client


@pytest.fixture
def mock_db():
    db = MagicMock()
    # Default: empty cursors
    db.apartados.find.return_value = _async_cursor([])
    db.apartados.find_one = AsyncMock(return_value=None)
    db.apartados.insert_one = AsyncMock()
    db.apartados.update_one = AsyncMock()
    db.roddos_events.insert_one = AsyncMock()
    db.kits_definiciones.find.return_value = _async_cursor([])
    db.kits_definiciones.update_one = AsyncMock()
    db.inventario_motos.find.return_value = _async_cursor([])
    db.inventario_motos.find_one = AsyncMock(return_value=None)
    db.inventario_motos.insert_one = AsyncMock()
    db.inventario_motos.update_one = AsyncMock()
    return db


def _async_cursor(items):
    """Create a mock async cursor that yields items."""
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=items)

    # Support async for
    async def _aiter():
        for item in items:
            yield item
    cursor.__aiter__ = _aiter
    return cursor


# ═══════════════════════════════════════════
# AlegraItemsService tests
# ═══════════════════════════════════════════


class TestAlegraItemsService:
    """Test that inventory reads come from Alegra, not MongoDB."""

    @pytest.mark.asyncio
    async def test_list_motos_reads_from_alegra(self, mock_alegra):
        from services.alegra_items import AlegraItemsService

        mock_alegra.get = AsyncMock(return_value=[
            SAMPLE_MOTO_ITEM, SAMPLE_MOTO_USADA, SAMPLE_SERVICE_ITEM
        ])

        service = AlegraItemsService(mock_alegra)
        motos = await service.list_motos()

        mock_alegra.get.assert_called()
        assert len(motos) == 2
        assert motos[0]["id_alegra"] == "25"
        assert motos[0]["nombre"] == "Moto nueva 100"
        assert motos[0]["stock"] == 23
        assert motos[1]["id_alegra"] == "31"

    @pytest.mark.asyncio
    async def test_list_motos_excludes_services(self, mock_alegra):
        from services.alegra_items import AlegraItemsService

        mock_alegra.get = AsyncMock(return_value=[SAMPLE_SERVICE_ITEM])
        service = AlegraItemsService(mock_alegra)
        motos = await service.list_motos()

        assert len(motos) == 0

    @pytest.mark.asyncio
    async def test_list_repuestos_reads_from_alegra(self, mock_alegra):
        from services.alegra_items import AlegraItemsService

        mock_alegra.get = AsyncMock(return_value=[
            SAMPLE_MOTO_ITEM, SAMPLE_REPUESTO_ITEM, SAMPLE_SERVICE_ITEM
        ])
        service = AlegraItemsService(mock_alegra)
        repuestos = await service.list_repuestos()

        assert len(repuestos) == 1
        assert repuestos[0]["id_alegra"] == "50"
        assert repuestos[0]["stock_actual"] == 15
        assert repuestos[0]["alerta_stock_bajo"] is False

    @pytest.mark.asyncio
    async def test_repuesto_low_stock_alert(self, mock_alegra):
        from services.alegra_items import AlegraItemsService

        low_stock = {**SAMPLE_REPUESTO_ITEM, "inventory": {"availableQuantity": 2, "unit": "unit"}}
        mock_alegra.get = AsyncMock(return_value=[low_stock])
        service = AlegraItemsService(mock_alegra)
        repuestos = await service.list_repuestos()

        assert repuestos[0]["alerta_stock_bajo"] is True

    @pytest.mark.asyncio
    async def test_get_item_stock(self, mock_alegra):
        from services.alegra_items import AlegraItemsService

        mock_alegra.get = AsyncMock(return_value=SAMPLE_MOTO_ITEM)
        service = AlegraItemsService(mock_alegra)
        stock = await service.get_item_stock("25")

        assert stock == 23
        mock_alegra.get.assert_called_with("items/25")


# ═══════════════════════════════════════════
# Registro manual VIN tests
# ═══════════════════════════════════════════


class TestRegistroManual:
    """Test manual VIN registration."""

    @pytest.mark.asyncio
    async def test_registrar_vin_success(self, mock_db):
        from routers.inventario import registrar_moto_manual, RegistroManualRequest

        body = RegistroManualRequest(
            vin="9C2JC4110RR100001",
            motor="JC41E-100001",
            modelo="Sport 100",
            color="Negro Nebulosa",
        )

        result = await registrar_moto_manual(body=body, db=mock_db)

        assert result["success"] is True
        assert result["vin"] == "9C2JC4110RR100001"
        mock_db.inventario_motos.insert_one.assert_called_once()
        doc = mock_db.inventario_motos.insert_one.call_args[0][0]
        assert doc["vin"] == "9C2JC4110RR100001"
        assert doc["estado"] == "disponible"

    @pytest.mark.asyncio
    async def test_registrar_vin_duplicado(self, mock_db):
        from routers.inventario import registrar_moto_manual, RegistroManualRequest

        mock_db.inventario_motos.find_one = AsyncMock(return_value={"vin": "DUPLICATE"})

        body = RegistroManualRequest(vin="DUPLICATE", modelo="Sport 100")

        with pytest.raises(Exception) as exc:
            await registrar_moto_manual(body=body, db=mock_db)
        assert exc.value.status_code == 409


# ═══════════════════════════════════════════
# Apartar tests (VIN-based)
# ═══════════════════════════════════════════


class TestApartar:
    """Test moto reservation workflow with VIN."""

    @pytest.mark.asyncio
    async def test_apartar_creates_journal_and_mongo(self, mock_alegra, mock_db):
        from routers.inventario import apartar_moto, ApartarRequest

        # VIN registered and available
        mock_db.inventario_motos.find_one = AsyncMock(return_value={
            "vin": "9C2JC4110RR100001", "estado": "disponible", "item_id_alegra": "25"
        })
        # Alegra returns item with stock
        mock_alegra.get = AsyncMock(return_value=SAMPLE_MOTO_ITEM)
        mock_alegra.request_with_verify = AsyncMock(return_value={"id": "700"})
        # No existing apartado
        mock_db.apartados.find_one = AsyncMock(return_value=None)

        body = ApartarRequest(
            vin="9C2JC4110RR100001",
            cliente_nombre="Juan Perez",
            cliente_cedula="123456789",
            cliente_telefono="3001234567",
            monto_pago=500000,
            cuota_inicial_total=2000000,
            banco_recibo="bancolombia_2029",
            plan_credito="36 cuotas",
        )

        result = await apartar_moto(
            item_id="25", body=body, alegra=mock_alegra, db=mock_db
        )

        # Verify Alegra journal with [CI] prefix and correct account
        mock_alegra.request_with_verify.assert_called_once()
        call_args = mock_alegra.request_with_verify.call_args
        payload = call_args[0][2]
        assert "[CI]" in payload["observations"]
        assert "VIN:9C2JC4110RR100001" in payload["observations"]
        assert payload["entries"][0]["id"] == "5314"  # Bancolombia 2029
        assert payload["entries"][0]["debit"] == 500000
        assert payload["entries"][1]["id"] == "5370"  # Anticipos recibidos (NIIF 2805)
        assert payload["entries"][1]["credit"] == 500000

        # Verify MongoDB apartado has VIN
        mock_db.apartados.insert_one.assert_called_once()
        apartado = mock_db.apartados.insert_one.call_args[0][0]
        assert apartado["vin"] == "9C2JC4110RR100001"
        assert apartado["item_id_alegra"] == "25"
        assert apartado["monto_acumulado"] == 500000
        assert apartado["monto_pendiente"] == 1500000
        assert apartado["estado"] == "activo"

        # Verify moto estado updated
        mock_db.inventario_motos.update_one.assert_called_once()

        # Verify response
        assert result["success"] is True
        assert result["alegra_journal_id"] == "700"

    @pytest.mark.asyncio
    async def test_apartar_fails_no_vin_registered(self, mock_alegra, mock_db):
        from routers.inventario import apartar_moto, ApartarRequest

        mock_db.inventario_motos.find_one = AsyncMock(return_value=None)

        body = ApartarRequest(
            vin="NOEXISTE",
            cliente_nombre="Test",
            cliente_cedula="111",
            monto_pago=100000,
            cuota_inicial_total=1000000,
            banco_recibo="bancolombia_2029",
        )

        with pytest.raises(Exception) as exc:
            await apartar_moto(item_id="25", body=body, alegra=mock_alegra, db=mock_db)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_apartar_fails_no_stock(self, mock_alegra, mock_db):
        from routers.inventario import apartar_moto, ApartarRequest

        mock_db.inventario_motos.find_one = AsyncMock(return_value={
            "vin": "VIN001", "estado": "disponible"
        })
        no_stock = {**SAMPLE_MOTO_ITEM, "inventory": {"availableQuantity": 0}}
        mock_alegra.get = AsyncMock(return_value=no_stock)
        mock_db.apartados.find_one = AsyncMock(return_value=None)

        body = ApartarRequest(
            vin="VIN001",
            cliente_nombre="Test",
            cliente_cedula="111",
            monto_pago=100000,
            cuota_inicial_total=1000000,
            banco_recibo="bancolombia_2029",
        )

        with pytest.raises(Exception) as exc:
            await apartar_moto(item_id="25", body=body, alegra=mock_alegra, db=mock_db)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_apartar_fails_duplicate_vin(self, mock_alegra, mock_db):
        from routers.inventario import apartar_moto, ApartarRequest

        mock_db.inventario_motos.find_one = AsyncMock(return_value={
            "vin": "VIN001", "estado": "disponible"
        })
        mock_alegra.get = AsyncMock(return_value=SAMPLE_MOTO_ITEM)
        mock_db.apartados.find_one = AsyncMock(return_value={
            "vin": "VIN001", "estado": "activo",
            "cliente": {"nombre": "Ya Apartada"},
        })

        body = ApartarRequest(
            vin="VIN001",
            cliente_nombre="Otro",
            cliente_cedula="222",
            monto_pago=100000,
            cuota_inicial_total=1000000,
            banco_recibo="bancolombia_2029",
        )

        with pytest.raises(Exception) as exc:
            await apartar_moto(item_id="25", body=body, alegra=mock_alegra, db=mock_db)
        assert exc.value.status_code == 409


# ═══════════════════════════════════════════
# Pago parcial tests
# ═══════════════════════════════════════════


class TestPagoParcial:
    """Test partial payment accumulation."""

    @pytest.mark.asyncio
    async def test_pago_parcial_acumula(self, mock_alegra, mock_db):
        from routers.inventario import pago_parcial, PagoParcialRequest

        mock_db.apartados.find_one = AsyncMock(return_value={
            "_id": "abc",
            "vin": "VIN001",
            "item_id_alegra": "25",
            "modelo": "Moto nueva 100",
            "cliente": {"nombre": "Juan"},
            "monto_acumulado": 500000,
            "cuota_inicial_total": 2000000,
            "estado": "activo",
        })
        mock_alegra.request_with_verify = AsyncMock(return_value={"id": "701"})

        body = PagoParcialRequest(monto_pago=300000, banco_recibo="nequi")

        result = await pago_parcial(
            item_id="VIN001", body=body, alegra=mock_alegra, db=mock_db
        )

        assert result["monto_acumulado"] == 800000
        assert result["monto_pendiente"] == 1200000
        assert result["cuota_completa"] is False

        # Verify journal has [CI] prefix and correct bank
        call_args = mock_alegra.request_with_verify.call_args
        payload = call_args[0][2]
        assert "[CI]" in payload["observations"]
        assert payload["entries"][0]["id"] == "5310"  # Nequi = Caja general
        assert payload["entries"][1]["id"] == "5370"  # Anticipos (NIIF 2805)

    @pytest.mark.asyncio
    async def test_pago_completa_cuota(self, mock_alegra, mock_db):
        from routers.inventario import pago_parcial, PagoParcialRequest

        mock_db.apartados.find_one = AsyncMock(return_value={
            "_id": "abc",
            "vin": "VIN001",
            "item_id_alegra": "25",
            "modelo": "Moto nueva 100",
            "cliente": {"nombre": "Juan"},
            "monto_acumulado": 1500000,
            "cuota_inicial_total": 2000000,
            "estado": "activo",
        })
        mock_alegra.request_with_verify = AsyncMock(return_value={"id": "702"})

        body = PagoParcialRequest(monto_pago=500000, banco_recibo="bancolombia_2029")

        result = await pago_parcial(
            item_id="VIN001", body=body, alegra=mock_alegra, db=mock_db
        )

        assert result["monto_acumulado"] == 2000000
        assert result["monto_pendiente"] == 0
        assert result["cuota_completa"] is True

        update_call = mock_db.apartados.update_one.call_args
        update_doc = update_call[0][1]
        assert update_doc["$set"]["estado"] == "completo"

    @pytest.mark.asyncio
    async def test_pago_parcial_no_apartado(self, mock_alegra, mock_db):
        from routers.inventario import pago_parcial, PagoParcialRequest

        mock_db.apartados.find_one = AsyncMock(return_value=None)

        body = PagoParcialRequest(monto_pago=100000, banco_recibo="nequi")

        with pytest.raises(Exception) as exc:
            await pago_parcial(item_id="99", body=body, alegra=mock_alegra, db=mock_db)
        assert exc.value.status_code == 404


# ═══════════════════════════════════════════
# Liberar tests
# ═══════════════════════════════════════════


class TestLiberar:
    """Test moto release — restores VIN to disponible."""

    @pytest.mark.asyncio
    async def test_liberar_cancels_apartado_and_restores_vin(self, mock_db):
        from routers.inventario import liberar_moto

        mock_db.apartados.find_one = AsyncMock(return_value={
            "_id": "abc",
            "vin": "VIN001",
            "item_id_alegra": "25",
            "modelo": "Moto nueva 100",
            "cliente": {"nombre": "Juan"},
            "estado": "activo",
        })

        result = await liberar_moto(item_id="VIN001", db=mock_db)

        assert result["success"] is True
        assert result["estado"] == "liberado"

        # Verify apartado updated
        apt_update = mock_db.apartados.update_one.call_args
        assert apt_update[0][1]["$set"]["estado"] == "liberado"

        # Verify moto restored to disponible
        moto_update = mock_db.inventario_motos.update_one.call_args
        assert moto_update[0][0] == {"vin": "VIN001"}
        assert moto_update[0][1] == {"$set": {"estado": "disponible"}}

        # Verify event published
        mock_db.roddos_events.insert_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_liberar_no_apartado(self, mock_db):
        from routers.inventario import liberar_moto

        mock_db.apartados.find_one = AsyncMock(return_value=None)

        with pytest.raises(Exception) as exc:
            await liberar_moto(item_id="99", db=mock_db)
        assert exc.value.status_code == 404


# ═══════════════════════════════════════════
# Kits tests
# ═══════════════════════════════════════════


class TestKits:
    """Test kit availability calculation."""

    @pytest.mark.asyncio
    async def test_kits_disponibles_min_calculation(self, mock_alegra, mock_db):
        from routers.inventario import list_kits
        from services.alegra_items import AlegraItemsService

        kit_def = {
            "nombre": "Kit Raider 125",
            "modelo": "Raider 125",
            "tipo": "mantenimiento",
            "componentes": [
                {"item_id_alegra": "50", "cantidad": 2},
                {"item_id_alegra": "51", "cantidad": 1},
            ],
            "precio_kit": 50000,
        }
        mock_db.kits_definiciones.find.return_value = _async_cursor([kit_def])

        async def mock_get(endpoint, **kwargs):
            if "50" in endpoint:
                return {"inventory": {"availableQuantity": 10}}
            elif "51" in endpoint:
                return {"inventory": {"availableQuantity": 3}}
            return {"inventory": {"availableQuantity": 0}}

        mock_alegra.get = AsyncMock(side_effect=mock_get)
        service = AlegraItemsService(mock_alegra)

        result = await list_kits(service=service, db=mock_db)

        assert result["count"] == 1
        kit = result["data"][0]
        assert kit["kits_disponibles"] == 3  # MIN(10/2, 3/1)
        assert kit["alerta"] is True
        assert kit["componente_limitante"]["item_id_alegra"] == "51"

    @pytest.mark.asyncio
    async def test_kits_zero_when_no_stock(self, mock_alegra, mock_db):
        from routers.inventario import list_kits
        from services.alegra_items import AlegraItemsService

        kit_def = {
            "nombre": "Kit Sport",
            "modelo": "Sport 100",
            "tipo": "basico",
            "componentes": [{"item_id_alegra": "60", "cantidad": 1}],
            "precio_kit": 30000,
        }
        mock_db.kits_definiciones.find.return_value = _async_cursor([kit_def])

        mock_alegra.get = AsyncMock(return_value={"inventory": {"availableQuantity": 0}})
        service = AlegraItemsService(mock_alegra)

        result = await list_kits(service=service, db=mock_db)

        assert result["data"][0]["kits_disponibles"] == 0
        assert result["data"][0]["alerta"] is True

    @pytest.mark.asyncio
    async def test_componente_limitante_identified(self, mock_alegra, mock_db):
        from routers.inventario import list_kits
        from services.alegra_items import AlegraItemsService

        kit_def = {
            "nombre": "Kit Full",
            "modelo": "X",
            "tipo": "full",
            "componentes": [
                {"item_id_alegra": "A", "cantidad": 1},
                {"item_id_alegra": "B", "cantidad": 3},
                {"item_id_alegra": "C", "cantidad": 1},
            ],
            "precio_kit": 100000,
        }
        mock_db.kits_definiciones.find.return_value = _async_cursor([kit_def])

        async def mock_get(endpoint, **kwargs):
            if "/A" in endpoint:
                return {"inventory": {"availableQuantity": 20}}
            elif "/B" in endpoint:
                return {"inventory": {"availableQuantity": 6}}
            elif "/C" in endpoint:
                return {"inventory": {"availableQuantity": 50}}
            return {"inventory": {"availableQuantity": 0}}

        mock_alegra.get = AsyncMock(side_effect=mock_get)
        service = AlegraItemsService(mock_alegra)

        result = await list_kits(service=service, db=mock_db)

        kit = result["data"][0]
        assert kit["kits_disponibles"] == 2  # MIN(20/1, 6/3, 50/1)
        assert kit["componente_limitante"]["item_id_alegra"] == "B"

    @pytest.mark.asyncio
    async def test_empty_kits_when_no_definitions(self, mock_alegra, mock_db):
        from routers.inventario import list_kits
        from services.alegra_items import AlegraItemsService

        mock_db.kits_definiciones.find.return_value = _async_cursor([])
        service = AlegraItemsService(mock_alegra)

        result = await list_kits(service=service, db=mock_db)

        assert result["count"] == 0
        assert result["data"] == []
