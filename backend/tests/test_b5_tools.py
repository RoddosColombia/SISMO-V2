"""
test_b5_tools.py — Tests para tool_handlers.py

Cubre los 7 handlers read-only + 2 write-handlers con mocks de MongoDB.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import date
from bson import ObjectId


# ─────────────────────── Fixtures ─────────────────────────────────────────────

def make_lb(**overrides):
    base = {
        "_id": ObjectId(),
        "loanbook_id": "LB-0001",
        "vin": "VIN001",
        "estado": "activo",
        "dpd": 0,
        "saldo_capital": 2_000_000,
        "saldo_pendiente": 2_000_000,
        "mora_acumulada_cop": 0,
        "sub_bucket_semanal": "Current",
        "cliente": {"nombre": "Ana Torres", "cedula": "12345678", "telefono": "3001234567"},
        "modalidad": "semanal",
        "cuota_monto": 80_000,
        "tasa_ea": 0.39,
        "cuotas": [
            {"numero": 1, "estado": "pendiente", "fecha_programada": "2026-04-23",
             "fecha": "2026-04-23", "monto": 80_000, "monto_total": 80_000},
        ],
    }
    base.update(overrides)
    return base


def make_db_with_lbs(lbs=None, inventario=None, clientes=None):
    db = MagicMock()
    lb_list = lbs or [make_lb()]
    db.loanbook.find_one = AsyncMock(return_value=lb_list[0] if lb_list else None)
    # cursor mock
    cursor = MagicMock()
    cursor.skip = MagicMock(return_value=cursor)
    cursor.limit = MagicMock(return_value=cursor)
    cursor.to_list = AsyncMock(return_value=lb_list)
    db.loanbook.find = MagicMock(return_value=cursor)
    db.loanbook.count_documents = AsyncMock(return_value=len(lb_list))
    # inventario
    inv_cursor = MagicMock()
    inv_cursor.limit = MagicMock(return_value=inv_cursor)
    inv_cursor.to_list = AsyncMock(return_value=inventario or [])
    db.inventario_motos.find = MagicMock(return_value=inv_cursor)
    db.inventario_motos.find_one = AsyncMock(return_value=None)
    # crm
    db.crm_clientes.find_one = AsyncMock(return_value=clientes[0] if clientes else None)
    # events
    db.roddos_events.insert_one = AsyncMock(return_value=MagicMock())
    db.loanbook.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    return db


# ─────────────────────── Read-only handlers ────────────────────────────────────

class TestConsultarLoanbook:

    @pytest.mark.asyncio
    async def test_consultar_loanbook_existente(self):
        from services.loanbook.tool_handlers import handle_consultar_loanbook
        db = make_db_with_lbs()

        result = await handle_consultar_loanbook(db, "LB-0001")

        assert result["codigo"] == "LB-0001"
        assert result["cliente"] == "Ana Torres"
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_consultar_loanbook_inexistente(self):
        from services.loanbook.tool_handlers import handle_consultar_loanbook
        db = make_db_with_lbs(lbs=[])
        db.loanbook.find_one = AsyncMock(return_value=None)

        result = await handle_consultar_loanbook(db, "LB-XXXX")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_consultar_loanbook_incluye_proxima_cuota(self):
        from services.loanbook.tool_handlers import handle_consultar_loanbook
        db = make_db_with_lbs()

        result = await handle_consultar_loanbook(db, "LB-0001")

        assert "proxima_cuota" in result
        assert result["proxima_cuota"]["numero"] == 1


class TestListarLoanbooks:

    @pytest.mark.asyncio
    async def test_listar_loanbooks_sin_filtros(self):
        from services.loanbook.tool_handlers import handle_listar_loanbooks
        lbs = [make_lb(loanbook_id=f"LB-{i:04}") for i in range(3)]
        db = make_db_with_lbs(lbs)

        result = await handle_listar_loanbooks(db)

        assert result["total"] == 3
        assert len(result["loanbooks"]) == 3

    @pytest.mark.asyncio
    async def test_listar_loanbooks_filtro_estado(self):
        from services.loanbook.tool_handlers import handle_listar_loanbooks
        lbs = [make_lb(estado="mora")]
        db = make_db_with_lbs(lbs)

        result = await handle_listar_loanbooks(db, estado="mora")

        # Query debe incluir estado
        call_args = db.loanbook.find.call_args[0][0]
        assert call_args.get("estado") == "mora"

    @pytest.mark.asyncio
    async def test_listar_loanbooks_paginacion(self):
        from services.loanbook.tool_handlers import handle_listar_loanbooks
        db = make_db_with_lbs()

        result = await handle_listar_loanbooks(db, page=2)

        cursor = db.loanbook.find.return_value
        cursor.skip.assert_called_with(20)


class TestConsultarMora:

    @pytest.mark.asyncio
    async def test_consultar_mora_global(self):
        from services.loanbook.tool_handlers import handle_consultar_mora
        lbs = [make_lb(dpd=7, saldo_capital=500_000, mora_acumulada_cop=14_000)]
        db = make_db_with_lbs(lbs)
        # cursor to_list para mora query
        mora_cursor = MagicMock()
        mora_cursor.to_list = AsyncMock(return_value=lbs)
        db.loanbook.find = MagicMock(return_value=mora_cursor)

        result = await handle_consultar_mora(db)

        assert result["en_mora"] == 1
        assert result["mora_acumulada_total_cop"] == 14_000

    @pytest.mark.asyncio
    async def test_consultar_mora_cartera_sin_mora(self):
        from services.loanbook.tool_handlers import handle_consultar_mora
        db = make_db_with_lbs([])
        mora_cursor = MagicMock()
        mora_cursor.to_list = AsyncMock(return_value=[])
        db.loanbook.find = MagicMock(return_value=mora_cursor)

        result = await handle_consultar_mora(db)

        assert result["en_mora"] == 0
        assert result["valor_cartera_mora_cop"] == 0


class TestResumenCartera:

    @pytest.mark.asyncio
    async def test_resumen_cartera(self):
        from services.loanbook.tool_handlers import handle_resumen_cartera
        lbs = [
            make_lb(estado="activo", saldo_capital=1_000_000, saldo_pendiente=1_000_000, cuota_monto=80_000),
            make_lb(loanbook_id="LB-0002", estado="mora", saldo_capital=500_000, saldo_pendiente=500_000, dpd=7),
        ]
        db = make_db_with_lbs(lbs)
        all_cursor = MagicMock()
        all_cursor.to_list = AsyncMock(return_value=lbs)
        db.loanbook.find = MagicMock(return_value=all_cursor)

        result = await handle_resumen_cartera(db)

        assert result["total_creditos"] == 2
        assert result["cartera_total_cop"] == 1_500_000
        assert "por_estado" in result


class TestConsultarInventario:

    @pytest.mark.asyncio
    async def test_consultar_inventario_sin_filtro(self):
        from services.loanbook.tool_handlers import handle_consultar_inventario
        motos = [{"vin": "VIN001", "modelo": "Sport 100", "estado": "disponible", "_id": None}]
        db = make_db_with_lbs(inventario=motos)

        result = await handle_consultar_inventario(db)

        assert result["disponibles"] == 1

    @pytest.mark.asyncio
    async def test_consultar_inventario_vacio(self):
        from services.loanbook.tool_handlers import handle_consultar_inventario
        db = make_db_with_lbs(inventario=[])

        result = await handle_consultar_inventario(db)

        assert result["disponibles"] == 0


class TestCalcularLiquidacion:

    @pytest.mark.asyncio
    async def test_calcular_liquidacion_ok(self):
        from services.loanbook.tool_handlers import handle_calcular_liquidacion
        lb = make_lb(saldo_capital=2_000_000, dpd=0, mora_acumulada_cop=0)
        db = make_db_with_lbs([lb])

        result = await handle_calcular_liquidacion(db, vin="VIN001", fecha_liquidacion="2026-04-22")

        # calcular_liquidacion_anticipada retorna un dict con total_pagar
        assert isinstance(result, dict)
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_calcular_liquidacion_inexistente(self):
        from services.loanbook.tool_handlers import handle_calcular_liquidacion
        db = make_db_with_lbs([])
        db.loanbook.find_one = AsyncMock(return_value=None)

        result = await handle_calcular_liquidacion(db, vin="VIN999")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_calcular_liquidacion_sin_identificador(self):
        from services.loanbook.tool_handlers import handle_calcular_liquidacion
        db = make_db_with_lbs()

        result = await handle_calcular_liquidacion(db)

        assert "error" in result


# ─────────────────────── Write handlers ────────────────────────────────────────

class TestRegistrarPagoCuota:

    @pytest.mark.asyncio
    async def test_registrar_pago_fecha_futura_rechazada(self):
        from services.loanbook.tool_handlers import handle_registrar_pago_cuota
        lb = make_lb()
        db = make_db_with_lbs([lb])

        result = await handle_registrar_pago_cuota(
            db, vin="VIN001", monto=80_000, fecha_pago="2099-01-01", banco="Bancolombia"
        )

        assert "error" in result
        assert "futura" in result["error"]

    @pytest.mark.asyncio
    async def test_registrar_pago_loanbook_inexistente(self):
        from services.loanbook.tool_handlers import handle_registrar_pago_cuota
        db = make_db_with_lbs([])
        db.loanbook.find_one = AsyncMock(return_value=None)

        result = await handle_registrar_pago_cuota(
            db, vin="VIN_GHOST", monto=80_000, fecha_pago="2026-04-22", banco="BBVA"
        )

        assert "error" in result
