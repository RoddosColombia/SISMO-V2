"""
Sprint 3 — 3 Momentos del Crédito: DataKeeper handlers for loanbook lifecycle.

Momento 1: apartado.completo → create loanbook + mark moto apartada
Momento 2: entrega.realizada → activate loanbook (pendiente_entrega → activo)
Momento 3: pago.cuota.recibido → apply waterfall, update cuotas, recalc estado

These handlers use pure domain logic from loanbook_model.py and write to MongoDB
via the DataKeeper event processor. Tests mock the database.
"""
import pytest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid


# ═══════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════


PLAN_P52S = {
    "codigo": "P52S",
    "nombre": "Plan 52 Semanas",
    "cuotas_base": 52,
    "anzi_pct": 0.02,
    "cuotas_modelo": {"Sport 100": 160_000, "Raider 125": 179_900},
}


def _make_event(event_type: str, datos: dict) -> dict:
    """Build a fake event matching roddos_events schema."""
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


def _mock_db():
    """Create a mock AsyncIOMotorDatabase with needed collections."""
    db = AsyncMock()

    # catalogo_planes — returns plan on find_one
    db.catalogo_planes = AsyncMock()
    db.catalogo_planes.find_one = AsyncMock(return_value=PLAN_P52S)

    # loanbook — insert_one, find_one, update_one
    db.loanbook = AsyncMock()
    db.loanbook.insert_one = AsyncMock()
    db.loanbook.find_one = AsyncMock(return_value=None)
    db.loanbook.update_one = AsyncMock()

    # inventario_motos — update_one
    db.inventario_motos = AsyncMock()
    db.inventario_motos.update_one = AsyncMock()

    return db


# ═══════════════════════════════════════════
# Momento 1: apartado.completo
# ═══════════════════════════════════════════


class TestMomento1ApartadoCompleto:
    """apartado.completo → create loanbook + mark moto apartada."""

    @pytest.mark.asyncio
    async def test_creates_loanbook_in_mongodb(self):
        from core.loanbook_handlers import handle_apartado_completo

        db = _mock_db()
        event = _make_event("apartado.completo", {
            "vin": "VIN001",
            "cliente": {"nombre": "Juan Perez", "cedula": "123456"},
            "plan_codigo": "P52S",
            "modelo": "Sport 100",
            "modalidad": "semanal",
            "fecha_entrega": "2026-04-14",
        })

        await handle_apartado_completo(event, db)

        db.loanbook.insert_one.assert_called_once()
        lb = db.loanbook.insert_one.call_args[0][0]
        assert lb["vin"] == "VIN001"
        assert lb["plan_codigo"] == "P52S"
        assert lb["modalidad"] == "semanal"
        assert lb["estado"] == "pendiente_entrega"
        assert lb["num_cuotas"] == 52
        assert lb["cuota_monto"] == 160_000

    @pytest.mark.asyncio
    async def test_marks_moto_apartada(self):
        from core.loanbook_handlers import handle_apartado_completo

        db = _mock_db()
        event = _make_event("apartado.completo", {
            "vin": "VIN001",
            "cliente": {"nombre": "Juan", "cedula": "123"},
            "plan_codigo": "P52S",
            "modelo": "Sport 100",
            "modalidad": "semanal",
            "fecha_entrega": "2026-04-14",
        })

        await handle_apartado_completo(event, db)

        db.inventario_motos.update_one.assert_called_once()
        call_args = db.inventario_motos.update_one.call_args
        assert call_args[0][0] == {"vin": "VIN001"}
        assert call_args[0][1]["$set"]["estado"] == "apartada"

    @pytest.mark.asyncio
    async def test_fetches_plan_from_catalogo(self):
        from core.loanbook_handlers import handle_apartado_completo

        db = _mock_db()
        event = _make_event("apartado.completo", {
            "vin": "VIN001",
            "cliente": {"nombre": "Juan", "cedula": "123"},
            "plan_codigo": "P52S",
            "modelo": "Sport 100",
            "modalidad": "semanal",
            "fecha_entrega": "2026-04-14",
        })

        await handle_apartado_completo(event, db)

        db.catalogo_planes.find_one.assert_called_once_with({"codigo": "P52S"})

    @pytest.mark.asyncio
    async def test_raises_if_plan_not_found(self):
        from core.loanbook_handlers import handle_apartado_completo

        db = _mock_db()
        db.catalogo_planes.find_one = AsyncMock(return_value=None)

        event = _make_event("apartado.completo", {
            "vin": "VIN001",
            "cliente": {"nombre": "Juan", "cedula": "123"},
            "plan_codigo": "INEXISTENTE",
            "modelo": "Sport 100",
            "modalidad": "semanal",
            "fecha_entrega": "2026-04-14",
        })

        with pytest.raises(ValueError, match="[Pp]lan"):
            await handle_apartado_completo(event, db)

    @pytest.mark.asyncio
    async def test_quincenal_with_fecha_primer_pago(self):
        from core.loanbook_handlers import handle_apartado_completo

        db = _mock_db()
        event = _make_event("apartado.completo", {
            "vin": "VIN002",
            "cliente": {"nombre": "Maria", "cedula": "456"},
            "plan_codigo": "P52S",
            "modelo": "Sport 100",
            "modalidad": "quincenal",
            "fecha_entrega": "2026-04-14",
            "fecha_primer_pago": "2026-04-22",  # Wednesday
        })

        await handle_apartado_completo(event, db)

        lb = db.loanbook.insert_one.call_args[0][0]
        assert lb["modalidad"] == "quincenal"
        assert lb["num_cuotas"] == 26
        assert lb["cuota_monto"] == 352_000
        assert lb["fecha_primer_pago"] == "2026-04-22"

    @pytest.mark.asyncio
    async def test_contado_raises_no_loanbook(self):
        from core.loanbook_handlers import handle_apartado_completo

        db = _mock_db()
        event = _make_event("apartado.completo", {
            "vin": "VIN003",
            "cliente": {"nombre": "Pedro", "cedula": "789"},
            "plan_codigo": "P52S",
            "modelo": "Sport 100",
            "modalidad": "contado",
            "fecha_entrega": "2026-04-14",
        })

        with pytest.raises(ValueError, match="[Cc]ontado"):
            await handle_apartado_completo(event, db)

        # No MongoDB writes on contado
        db.loanbook.insert_one.assert_not_called()


# ═══════════════════════════════════════════
# Momento 2: entrega.realizada
# ═══════════════════════════════════════════


class TestMomento2EntregaRealizada:
    """entrega.realizada → activate loanbook + mark moto vendida."""

    def _lb_pendiente(self, vin="VIN001"):
        """Loanbook in pendiente_entrega state."""
        return {
            "loanbook_id": str(uuid.uuid4()),
            "vin": vin,
            "estado": "pendiente_entrega",
            "modalidad": "semanal",
            "num_cuotas": 1,
            "fecha_entrega": "2026-04-14",
            "fecha_primer_pago": None,
            "cuotas": [{"numero": 1, "monto": 160_000, "estado": "pendiente", "fecha": None, "fecha_pago": None, "mora_acumulada": 0}],
        }

    @pytest.mark.asyncio
    async def test_transitions_to_activo(self):
        from core.loanbook_handlers import handle_entrega_realizada

        db = _mock_db()
        db.loanbook.find_one = AsyncMock(return_value=self._lb_pendiente())

        event = _make_event("entrega.realizada", {"vin": "VIN001"})
        await handle_entrega_realizada(event, db)

        db.loanbook.update_one.assert_called_once()
        call_args = db.loanbook.update_one.call_args
        assert call_args[0][0] == {"vin": "VIN001"}
        update_set = call_args[0][1]["$set"]
        assert update_set["estado"] == "activo"

    @pytest.mark.asyncio
    async def test_marks_moto_vendida(self):
        from core.loanbook_handlers import handle_entrega_realizada

        db = _mock_db()
        db.loanbook.find_one = AsyncMock(return_value=self._lb_pendiente())

        event = _make_event("entrega.realizada", {"vin": "VIN001"})
        await handle_entrega_realizada(event, db)

        db.inventario_motos.update_one.assert_called_once()
        call_args = db.inventario_motos.update_one.call_args
        assert call_args[0][0] == {"vin": "VIN001"}
        assert call_args[0][1]["$set"]["estado"] == "vendida"

    @pytest.mark.asyncio
    async def test_raises_if_no_loanbook(self):
        from core.loanbook_handlers import handle_entrega_realizada

        db = _mock_db()
        db.loanbook.find_one = AsyncMock(return_value=None)

        event = _make_event("entrega.realizada", {"vin": "VIN_NOEXISTE"})
        with pytest.raises(ValueError, match="[Ll]oanbook|VIN"):
            await handle_entrega_realizada(event, db)

    @pytest.mark.asyncio
    async def test_raises_if_invalid_transition(self):
        from core.loanbook_handlers import handle_entrega_realizada

        db = _mock_db()
        lb = self._lb_pendiente()
        lb["estado"] = "saldado"  # Can't go from saldado → activo
        db.loanbook.find_one = AsyncMock(return_value=lb)

        event = _make_event("entrega.realizada", {"vin": "VIN001"})
        with pytest.raises(ValueError, match="[Tt]ransici|transition|estado"):
            await handle_entrega_realizada(event, db)


# ═══════════════════════════════════════════
# Momento 3: pago.cuota.recibido
# ═══════════════════════════════════════════


class TestMomento3PagoCuota:
    """pago.cuota.recibido → apply waterfall, update cuotas."""

    def _lb_activo(self, vin="VIN001"):
        """Loanbook in activo state with 3 cuotas."""
        return {
            "loanbook_id": str(uuid.uuid4()),
            "vin": vin,
            "estado": "activo",
            "anzi_pct": 0.02,
            "cuota_monto": 160_000,
            "num_cuotas": 52,
            "saldo_capital": 52 * 160_000,
            "total_pagado": 0,
            "total_mora_pagada": 0,
            "total_anzi_pagado": 0,
            "cuotas": [
                {"numero": 1, "monto": 160_000, "estado": "pendiente",
                 "fecha": "2026-04-16", "fecha_pago": None, "mora_acumulada": 0},
                {"numero": 2, "monto": 160_000, "estado": "pendiente",
                 "fecha": "2026-04-23", "fecha_pago": None, "mora_acumulada": 0},
                {"numero": 3, "monto": 160_000, "estado": "pendiente",
                 "fecha": "2026-04-30", "fecha_pago": None, "mora_acumulada": 0},
            ],
        }

    @pytest.mark.asyncio
    async def test_pays_first_cuota_on_time(self):
        from core.loanbook_handlers import handle_pago_cuota

        db = _mock_db()
        db.loanbook.find_one = AsyncMock(return_value=self._lb_activo())

        # Must pay enough to cover cuota (160k) PLUS ANZI (2%).
        # 164k → ANZI 3,280 → remaining 160,720 → covers cuota 160k
        event = _make_event("pago.cuota.recibido", {
            "vin": "VIN001",
            "monto_pago": 164_000,
            "fecha_pago": "2026-04-16",
        })

        await handle_pago_cuota(event, db)

        db.loanbook.update_one.assert_called_once()
        call_args = db.loanbook.update_one.call_args
        update_set = call_args[0][1]["$set"]

        # First cuota should be marked pagada
        cuotas = update_set["cuotas"]
        assert cuotas[0]["estado"] == "pagada"
        assert cuotas[0]["fecha_pago"] == "2026-04-16"
        # Others remain pendiente
        assert cuotas[1]["estado"] == "pendiente"
        assert cuotas[2]["estado"] == "pendiente"

    @pytest.mark.asyncio
    async def test_waterfall_anzi_deducted(self):
        from core.loanbook_handlers import handle_pago_cuota

        db = _mock_db()
        db.loanbook.find_one = AsyncMock(return_value=self._lb_activo())

        event = _make_event("pago.cuota.recibido", {
            "vin": "VIN001",
            "monto_pago": 164_000,
            "fecha_pago": "2026-04-16",
        })

        await handle_pago_cuota(event, db)

        call_args = db.loanbook.update_one.call_args
        update_set = call_args[0][1]["$set"]
        # ANZI = 2% of 164,000 = 3,280
        assert update_set["total_anzi_pagado"] == 3_280

    @pytest.mark.asyncio
    async def test_waterfall_with_mora(self):
        from core.loanbook_handlers import handle_pago_cuota

        db = _mock_db()
        lb = self._lb_activo()
        # Cuota 1 is overdue with mora
        lb["cuotas"][0]["mora_acumulada"] = 10_000
        db.loanbook.find_one = AsyncMock(return_value=lb)

        event = _make_event("pago.cuota.recibido", {
            "vin": "VIN001",
            "monto_pago": 170_000,
            "fecha_pago": "2026-04-21",  # 5 days late
        })

        await handle_pago_cuota(event, db)

        call_args = db.loanbook.update_one.call_args
        update_set = call_args[0][1]["$set"]
        assert update_set["total_mora_pagada"] == 10_000

    @pytest.mark.asyncio
    async def test_saldo_capital_reduced(self):
        from core.loanbook_handlers import handle_pago_cuota

        db = _mock_db()
        lb = self._lb_activo()
        db.loanbook.find_one = AsyncMock(return_value=lb)

        event = _make_event("pago.cuota.recibido", {
            "vin": "VIN001",
            "monto_pago": 164_000,
            "fecha_pago": "2026-04-16",
        })

        await handle_pago_cuota(event, db)

        call_args = db.loanbook.update_one.call_args
        update_set = call_args[0][1]["$set"]
        # Pago: 160k. ANZI: 3,200. Cuota corriente covers 156,800.
        # saldo_capital reduced by cuota amount covered via corriente
        original_saldo = 52 * 160_000
        assert update_set["saldo_capital"] < original_saldo

    @pytest.mark.asyncio
    async def test_estado_updates_from_dpd(self):
        from core.loanbook_handlers import handle_pago_cuota

        db = _mock_db()
        lb = self._lb_activo()
        db.loanbook.find_one = AsyncMock(return_value=lb)

        event = _make_event("pago.cuota.recibido", {
            "vin": "VIN001",
            "monto_pago": 164_000,
            "fecha_pago": "2026-04-16",
        })

        await handle_pago_cuota(event, db)

        call_args = db.loanbook.update_one.call_args
        update_set = call_args[0][1]["$set"]
        # After paying on time, DPD should be 0 → al_dia
        assert update_set["estado"] == "al_dia"

    @pytest.mark.asyncio
    async def test_raises_if_no_loanbook(self):
        from core.loanbook_handlers import handle_pago_cuota

        db = _mock_db()
        db.loanbook.find_one = AsyncMock(return_value=None)

        event = _make_event("pago.cuota.recibido", {
            "vin": "VIN_NOEXISTE",
            "monto_pago": 160_000,
            "fecha_pago": "2026-04-16",
        })

        with pytest.raises(ValueError, match="[Ll]oanbook|VIN"):
            await handle_pago_cuota(event, db)

    @pytest.mark.asyncio
    async def test_total_pagado_accumulates(self):
        from core.loanbook_handlers import handle_pago_cuota

        db = _mock_db()
        lb = self._lb_activo()
        lb["total_pagado"] = 160_000  # Already paid once
        db.loanbook.find_one = AsyncMock(return_value=lb)

        event = _make_event("pago.cuota.recibido", {
            "vin": "VIN001",
            "monto_pago": 160_000,
            "fecha_pago": "2026-04-23",
        })

        await handle_pago_cuota(event, db)

        call_args = db.loanbook.update_one.call_args
        update_set = call_args[0][1]["$set"]
        assert update_set["total_pagado"] == 320_000


# ═══════════════════════════════════════════
# Handler registration
# ═══════════════════════════════════════════


class TestHandlerRegistration:
    """Verify handlers are properly decorated for DataKeeper."""

    def test_handlers_registered_as_critical(self):
        from core.loanbook_handlers import (
            handle_apartado_completo,
            handle_entrega_realizada,
            handle_pago_cuota,
        )
        from core.event_handlers import get_registry

        registry = get_registry()

        # All 3 moments should be registered
        assert "apartado.completo" in registry
        assert "entrega.realizada" in registry
        assert "pago.cuota.recibido" in registry

        # All should be critical (loanbook writes are critical path)
        for event_type in ["apartado.completo", "entrega.realizada", "pago.cuota.recibido"]:
            handlers = registry[event_type]
            critical_handlers = [h for h in handlers if h["critical"]]
            assert len(critical_handlers) >= 1, f"{event_type} should have at least 1 critical handler"
