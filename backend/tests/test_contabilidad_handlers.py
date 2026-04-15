"""
Sprint 8 — Integration Loanbook↔Contador via Event Bus.

TDD: Tests written FIRST, expect RED until implementation.

Tests cover:
1. cuota.pagada → journal created in Alegra with correct accounts
2. Observations has [RDX] prefix with client data
3. ANZI > 0 → separate entry in journal
4. Mora > 0 → separate entry in journal
5. request_with_verify mock confirms POST + GET
6. Alegra failure → handler raises (DLQ handles retry)
7. loanbook.saldado → CRM updated to saldado
8. Handlers registered as critical in DataKeeper
"""
import pytest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid


# ═══════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════

def _make_cuota_pagada_event(
    monto_total=163_265,
    cuota_corriente=160_000,
    anzi=3_265,
    mora=0,
    vencidas=0,
    capital_extra=0,
    banco="5314",
    cuota_numero=3,
):
    """Build a cuota.pagada event matching the enriched payload from Sprint 7."""
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "cuota.pagada",
        "source": "agent.loanbook",
        "correlation_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "datos": {
            "loanbook_id": "lb-2026-0042",
            "vin": "VIN-TEST-001",
            "cliente_nombre": "Chenier Quintero",
            "cliente_cedula": "1234567890",
            "cuota_numero": cuota_numero,
            "monto_total_pagado": monto_total,
            "desglose": {
                "cuota_corriente": cuota_corriente,
                "vencidas": vencidas,
                "anzi": anzi,
                "mora": mora,
                "capital_extra": capital_extra,
            },
            "banco_recibo": banco,
            "fecha_pago": "2026-04-16",
            "modelo_moto": "Sport 100",
            "plan_codigo": "P52S",
            "modalidad": "semanal",
            "nuevo_estado": "al_dia",
            "dpd": 0,
        },
        "alegra_id": None,
        "accion_ejecutada": "Pago $163,265 en VIN VIN-TEST-001",
    }


def _make_saldado_event():
    """Build a loanbook.saldado event."""
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "loanbook.saldado",
        "source": "agent.loanbook",
        "correlation_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "datos": {
            "loanbook_id": "lb-2026-0042",
            "vin": "VIN-TEST-001",
            "cliente_nombre": "Chenier Quintero",
            "cliente_cedula": "1234567890",
        },
        "alegra_id": None,
        "accion_ejecutada": "Credito saldado VIN VIN-TEST-001",
    }


def _mock_db():
    """Create mock DB."""
    db = AsyncMock()
    db.roddos_events = AsyncMock()
    db.roddos_events.insert_one = AsyncMock()
    db.crm_clientes = AsyncMock()
    db.crm_clientes.update_one = AsyncMock()
    db.loanbook = AsyncMock()
    db.loanbook.update_one = AsyncMock()
    return db


def _mock_alegra():
    """Create mock AlegraClient that returns a successful journal."""
    alegra = AsyncMock()
    alegra.request_with_verify = AsyncMock(return_value={
        "id": 99001,
        "_alegra_id": "99001",
        "date": "2026-04-16",
        "observations": "test",
    })
    return alegra


# ═══════════════════════════════════════════
# Test Group 1: cuota.pagada → Alegra journal
# ═══════════════════════════════════════════

class TestCuotaPagadaContabilidad:
    """Handler: cuota.pagada → create ingreso journal in Alegra."""

    @pytest.mark.asyncio
    async def test_creates_journal_with_correct_accounts(self):
        """cuota.pagada → POST /journals with D:Banco C:Ingreso C:ANZI."""
        from core.contabilidad_handlers import handle_cuota_pagada_contabilidad

        db = _mock_db()
        alegra = _mock_alegra()
        event = _make_cuota_pagada_event(
            monto_total=163_265,
            cuota_corriente=160_000,
            anzi=3_265,
            mora=0,
        )

        await handle_cuota_pagada_contabilidad(event, db, alegra)

        # Verify request_with_verify was called
        alegra.request_with_verify.assert_called_once()
        call_args = alegra.request_with_verify.call_args
        assert call_args[1]["endpoint"] == "journals" or call_args[0][0] == "journals"

        # Extract the payload
        if call_args[1].get("payload"):
            payload = call_args[1]["payload"]
        else:
            payload = call_args[0][2] if len(call_args[0]) > 2 else call_args[1].get("payload")

        entries = payload["entries"]

        # D: Banco 5314 for full amount
        debit_entries = [e for e in entries if e.get("debit", 0) > 0]
        assert any(e["id"] == "5314" and e["debit"] == 163_265 for e in debit_entries), \
            f"Missing banco debit entry. Entries: {entries}"

        # C: Ingreso financiacion 5456 for cuota amount
        credit_entries = [e for e in entries if e.get("credit", 0) > 0]
        assert any(e["id"] == "5456" and e["credit"] == 160_000 for e in credit_entries), \
            f"Missing ingreso credit entry. Entries: {entries}"

    @pytest.mark.asyncio
    async def test_observations_has_rdx_prefix(self):
        """Observations must start with [RDX] and include client/cuota info."""
        from core.contabilidad_handlers import handle_cuota_pagada_contabilidad

        db = _mock_db()
        alegra = _mock_alegra()
        event = _make_cuota_pagada_event()

        await handle_cuota_pagada_contabilidad(event, db, alegra)

        call_args = alegra.request_with_verify.call_args
        payload = call_args[1].get("payload") or call_args[0][2]
        obs = payload["observations"]

        assert obs.startswith("[RDX]"), f"Observations should start with [RDX], got: {obs}"
        assert "Chenier Quintero" in obs
        assert "Cuota #3" in obs or "cuota #3" in obs.lower() or "#3" in obs

    @pytest.mark.asyncio
    async def test_anzi_greater_than_zero_creates_separate_entry(self):
        """ANZI > 0 → separate credit entry in journal."""
        from core.contabilidad_handlers import handle_cuota_pagada_contabilidad, CUENTA_ANZI

        db = _mock_db()
        alegra = _mock_alegra()
        event = _make_cuota_pagada_event(anzi=3_265)

        await handle_cuota_pagada_contabilidad(event, db, alegra)

        call_args = alegra.request_with_verify.call_args
        payload = call_args[1].get("payload") or call_args[0][2]
        entries = payload["entries"]

        # Must have ANZI credit entry
        anzi_entries = [e for e in entries if e.get("credit", 0) == 3_265]
        assert len(anzi_entries) >= 1, f"No ANZI entry for $3,265. Entries: {entries}"
        assert anzi_entries[0]["id"] == CUENTA_ANZI

    @pytest.mark.asyncio
    async def test_mora_greater_than_zero_creates_separate_entry(self):
        """Mora > 0 → separate credit entry in journal."""
        from core.contabilidad_handlers import handle_cuota_pagada_contabilidad, CUENTA_MORA

        db = _mock_db()
        alegra = _mock_alegra()
        event = _make_cuota_pagada_event(
            monto_total=175_265,
            cuota_corriente=160_000,
            anzi=3_265,
            mora=12_000,
        )

        await handle_cuota_pagada_contabilidad(event, db, alegra)

        call_args = alegra.request_with_verify.call_args
        payload = call_args[1].get("payload") or call_args[0][2]
        entries = payload["entries"]

        # Must have mora credit entry
        mora_entries = [e for e in entries if e.get("credit", 0) == 12_000]
        assert len(mora_entries) >= 1, f"No mora entry for $12,000. Entries: {entries}"
        assert mora_entries[0]["id"] == CUENTA_MORA

    @pytest.mark.asyncio
    async def test_vencidas_included_in_ingreso(self):
        """Cuotas vencidas paid → included in ingreso financiacion credit."""
        from core.contabilidad_handlers import handle_cuota_pagada_contabilidad

        db = _mock_db()
        alegra = _mock_alegra()
        event = _make_cuota_pagada_event(
            monto_total=326_530,
            cuota_corriente=160_000,
            vencidas=160_000,
            anzi=6_530,
            mora=0,
        )

        await handle_cuota_pagada_contabilidad(event, db, alegra)

        call_args = alegra.request_with_verify.call_args
        payload = call_args[1].get("payload") or call_args[0][2]
        entries = payload["entries"]

        # Ingreso 5456 should be cuota_corriente + vencidas = 320,000
        ingreso_entries = [e for e in entries if e.get("id") == "5456" and e.get("credit", 0) > 0]
        assert len(ingreso_entries) == 1
        assert ingreso_entries[0]["credit"] == 320_000

    @pytest.mark.asyncio
    async def test_capital_extra_included_in_ingreso(self):
        """Capital extra (abono a capital) → also goes to ingreso financiacion."""
        from core.contabilidad_handlers import handle_cuota_pagada_contabilidad

        db = _mock_db()
        alegra = _mock_alegra()
        event = _make_cuota_pagada_event(
            monto_total=213_265,
            cuota_corriente=160_000,
            anzi=3_265,
            mora=0,
            capital_extra=50_000,
        )

        await handle_cuota_pagada_contabilidad(event, db, alegra)

        call_args = alegra.request_with_verify.call_args
        payload = call_args[1].get("payload") or call_args[0][2]
        entries = payload["entries"]

        # Ingreso 5456 = cuota + capital = 210,000
        ingreso_entries = [e for e in entries if e.get("id") == "5456" and e.get("credit", 0) > 0]
        assert ingreso_entries[0]["credit"] == 210_000

    @pytest.mark.asyncio
    async def test_different_banco(self):
        """Different banco → uses that banco ID in debit entry."""
        from core.contabilidad_handlers import handle_cuota_pagada_contabilidad

        db = _mock_db()
        alegra = _mock_alegra()
        event = _make_cuota_pagada_event(banco="5318")  # BBVA

        await handle_cuota_pagada_contabilidad(event, db, alegra)

        call_args = alegra.request_with_verify.call_args
        payload = call_args[1].get("payload") or call_args[0][2]
        entries = payload["entries"]

        debit_entries = [e for e in entries if e.get("debit", 0) > 0]
        assert debit_entries[0]["id"] == "5318"

    @pytest.mark.asyncio
    async def test_fecha_from_event(self):
        """Journal date must come from event datos.fecha_pago."""
        from core.contabilidad_handlers import handle_cuota_pagada_contabilidad

        db = _mock_db()
        alegra = _mock_alegra()
        event = _make_cuota_pagada_event()

        await handle_cuota_pagada_contabilidad(event, db, alegra)

        call_args = alegra.request_with_verify.call_args
        payload = call_args[1].get("payload") or call_args[0][2]
        assert payload["date"] == "2026-04-16"

    @pytest.mark.asyncio
    async def test_publishes_ingreso_registrado_event(self):
        """After Alegra journal, must publish ingreso.cuota.registrado event."""
        from core.contabilidad_handlers import handle_cuota_pagada_contabilidad

        db = _mock_db()
        alegra = _mock_alegra()
        event = _make_cuota_pagada_event()

        await handle_cuota_pagada_contabilidad(event, db, alegra)

        # Should publish event to roddos_events
        db.roddos_events.insert_one.assert_called()
        published = db.roddos_events.insert_one.call_args[0][0]
        assert published["event_type"] == "ingreso.cuota.registrado"
        assert published["alegra_id"] == "99001"

    @pytest.mark.asyncio
    async def test_alegra_failure_raises(self):
        """If Alegra fails, handler should raise so DLQ can retry."""
        from core.contabilidad_handlers import handle_cuota_pagada_contabilidad
        from services.alegra.client import AlegraError

        db = _mock_db()
        alegra = _mock_alegra()
        alegra.request_with_verify = AsyncMock(side_effect=AlegraError("Error Alegra", 500))
        event = _make_cuota_pagada_event()

        with pytest.raises(AlegraError):
            await handle_cuota_pagada_contabilidad(event, db, alegra)

    @pytest.mark.asyncio
    async def test_journal_entries_balance(self):
        """Sum of debits must equal sum of credits (partida doble)."""
        from core.contabilidad_handlers import handle_cuota_pagada_contabilidad

        db = _mock_db()
        alegra = _mock_alegra()
        event = _make_cuota_pagada_event(
            monto_total=175_265,
            cuota_corriente=160_000,
            anzi=3_265,
            mora=12_000,
        )

        await handle_cuota_pagada_contabilidad(event, db, alegra)

        call_args = alegra.request_with_verify.call_args
        payload = call_args[1].get("payload") or call_args[0][2]
        entries = payload["entries"]

        total_debit = sum(e.get("debit", 0) for e in entries)
        total_credit = sum(e.get("credit", 0) for e in entries)
        assert total_debit == total_credit, \
            f"Entries don't balance: debit={total_debit}, credit={total_credit}"


# ═══════════════════════════════════════════
# Test Group 2: loanbook.saldado → CRM update
# ═══════════════════════════════════════════

class TestLoanbookSaldado:
    """Handler: loanbook.saldado → update CRM client to saldado."""

    @pytest.mark.asyncio
    async def test_updates_crm_to_saldado(self):
        from core.contabilidad_handlers import handle_loanbook_saldado

        db = _mock_db()
        event = _make_saldado_event()

        await handle_loanbook_saldado(event, db)

        db.crm_clientes.update_one.assert_called_once()
        call_args = db.crm_clientes.update_one.call_args[0]
        # Filter by cedula
        assert call_args[0] == {"cedula": "1234567890"}
        # Set estado to saldado
        update = call_args[1]
        assert update["$set"]["estado"] == "saldado"

    @pytest.mark.asyncio
    async def test_publishes_credito_cerrado_event(self):
        from core.contabilidad_handlers import handle_loanbook_saldado

        db = _mock_db()
        event = _make_saldado_event()

        await handle_loanbook_saldado(event, db)

        db.roddos_events.insert_one.assert_called()
        published = db.roddos_events.insert_one.call_args[0][0]
        assert published["event_type"] == "credito.cerrado"


# ═══════════════════════════════════════════
# Test Group 3: Handler registration
# ═══════════════════════════════════════════

class TestHandlerRegistration:
    """Handlers must be registered as critical in the DataKeeper."""

    def test_cuota_pagada_registered(self):
        # Import the module to trigger @on_event decorators
        import core.contabilidad_handlers  # noqa: F401
        from core.event_handlers import get_registry
        registry = get_registry()
        assert "cuota.pagada" in registry
        handlers = registry["cuota.pagada"]
        contab_handler = [h for h in handlers if h["name"] == "handle_cuota_pagada_contabilidad"]
        assert len(contab_handler) == 1
        assert contab_handler[0]["critical"] is True

    def test_loanbook_saldado_registered(self):
        import core.contabilidad_handlers  # noqa: F401
        from core.event_handlers import get_registry
        registry = get_registry()
        assert "loanbook.saldado" in registry
        handlers = registry["loanbook.saldado"]
        saldado_handler = [h for h in handlers if h["name"] == "handle_loanbook_saldado"]
        assert len(saldado_handler) == 1
        assert saldado_handler[0]["critical"] is True
