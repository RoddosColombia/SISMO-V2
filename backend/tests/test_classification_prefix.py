"""
Tests for classification prefix [XX] in journal observations.

Verifies that every handler prepends the correct prefix to observations
before POSTing to Alegra.

Prefixes:
  [AC]  — Ajuste contable / gastos operativos
  [NO]  — Nomina / prestaciones
  [RDX] — Recaudo cuota
  [CI]  — Cuota inicial (not yet implemented)
  [ING] — Ingresos no operacionales
  [D]   — Depreciaciones
  [TR]  — Transferencias entre cuentas propias
  [CXC] — CXC socios
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ───────────────────────────────────────────────
# Helper: _prefix_obs (shared across handlers)
# ───────────────────────────────────────────────

class TestPrefixObs:
    """Test the _prefix_obs utility function."""

    def test_adds_prefix(self):
        from agents.contador.handlers.egresos import _prefix_obs
        assert _prefix_obs("AC", "Pago arriendo") == "[AC] Pago arriendo"

    def test_no_double_prefix(self):
        from agents.contador.handlers.egresos import _prefix_obs
        assert _prefix_obs("AC", "[AC] Pago arriendo") == "[AC] Pago arriendo"

    def test_different_prefix_not_stripped(self):
        from agents.contador.handlers.egresos import _prefix_obs
        # If obs already has a different prefix, it adds the new one
        result = _prefix_obs("NO", "[AC] Pago arriendo")
        assert result == "[NO] [AC] Pago arriendo"

    def test_empty_observations(self):
        from agents.contador.handlers.egresos import _prefix_obs
        assert _prefix_obs("D", "") == "[D] "


# ───────────────────────────────────────────────
# Mock setup for handler tests
# ───────────────────────────────────────────────

def _make_alegra_mock(alegra_id="999"):
    """Create an AlegraClient mock that captures payload."""
    mock = AsyncMock()
    mock.request_with_verify = AsyncMock(return_value={"_alegra_id": alegra_id})
    mock.get = AsyncMock(return_value=[])  # anti-dup returns empty
    return mock


def _make_db_mock():
    """Create a MongoDB mock."""
    db = MagicMock()
    db.loanbook = MagicMock()
    db.loanbook.find_one = AsyncMock(return_value={
        "loanbook_id": "LB001",
        "factura_alegra_id": "123",
    })
    db.backlog_movimientos = MagicMock()
    db.backlog_movimientos.insert_one = AsyncMock()
    db.backlog_movimientos.update_one = AsyncMock()
    db.roddos_events = MagicMock()
    db.roddos_events.insert_one = AsyncMock()
    return db


# ───────────────────────────────────────────────
# Egresos handler prefix tests
# ───────────────────────────────────────────────

class TestEgresosPrefix:
    @pytest.mark.asyncio
    async def test_crear_causacion_ac_prefix(self):
        from agents.contador.handlers.egresos import handle_crear_causacion
        alegra = _make_alegra_mock()
        db = _make_db_mock()

        tool_input = {
            "date": "2026-04-01",
            "observations": "Compra repuestos",
            "entries": [
                {"id": "5314", "debit": 100000, "credit": 0},
                {"id": "5494", "debit": 0, "credit": 100000},
            ],
        }
        await handle_crear_causacion(tool_input, alegra, db, db, "test")

        payload = alegra.request_with_verify.call_args[1].get("payload") or alegra.request_with_verify.call_args[0][2]
        assert payload["observations"].startswith("[AC]")

    @pytest.mark.asyncio
    async def test_registrar_gasto_ac_prefix(self):
        from agents.contador.handlers.egresos import handle_registrar_gasto
        alegra = _make_alegra_mock()
        db = _make_db_mock()

        tool_input = {
            "monto": 500000,
            "banco": "Bancolombia",
            "descripcion": "Compra de insumos",
            "fecha": "2026-04-01",
        }
        await handle_registrar_gasto(tool_input, alegra, db, db, "test")

        payload = alegra.request_with_verify.call_args[1].get("payload") or alegra.request_with_verify.call_args[0][2]
        assert payload["observations"].startswith("[AC]")

    @pytest.mark.asyncio
    async def test_registrar_gasto_socio_cxc_prefix(self):
        from agents.contador.handlers.egresos import handle_registrar_gasto
        alegra = _make_alegra_mock()
        db = _make_db_mock()

        tool_input = {
            "monto": 500000,
            "banco": "Bancolombia",
            "descripcion": "Retiro personal",
            "proveedor_nit": "80075452",
            "fecha": "2026-04-01",
        }
        await handle_registrar_gasto(tool_input, alegra, db, db, "test")

        payload = alegra.request_with_verify.call_args[1].get("payload") or alegra.request_with_verify.call_args[0][2]
        assert payload["observations"].startswith("[CXC]")

    @pytest.mark.asyncio
    async def test_registrar_depreciacion_d_prefix(self):
        from agents.contador.handlers.egresos import handle_registrar_depreciacion
        alegra = _make_alegra_mock()
        db = _make_db_mock()

        tool_input = {
            "activo": "MacBook Pro",
            "monto": 150000,
            "periodo": "2026-04",
            "fecha": "2026-04-30",
            "tipo_activo": "equipo_computo",
        }
        await handle_registrar_depreciacion(tool_input, alegra, db, db, "test")

        payload = alegra.request_with_verify.call_args[1].get("payload") or alegra.request_with_verify.call_args[0][2]
        assert payload["observations"].startswith("[D]")

    @pytest.mark.asyncio
    async def test_registrar_ajuste_ac_prefix(self):
        from agents.contador.handlers.egresos import handle_registrar_ajuste_contable
        alegra = _make_alegra_mock()
        db = _make_db_mock()

        tool_input = {
            "cuenta_origen_id": "5494",
            "cuenta_destino_id": "5480",
            "monto": 200000,
            "motivo": "Reclasificacion arriendo",
            "fecha": "2026-04-01",
        }
        await handle_registrar_ajuste_contable(tool_input, alegra, db, db, "test")

        payload = alegra.request_with_verify.call_args[1].get("payload") or alegra.request_with_verify.call_args[0][2]
        assert payload["observations"].startswith("[AC]")


# ───────────────────────────────────────────────
# Ingresos handler prefix tests
# ───────────────────────────────────────────────

class TestIngresosPrefix:
    @pytest.mark.asyncio
    async def test_ingreso_cuota_rdx_prefix(self):
        from agents.contador.handlers.ingresos import handle_registrar_ingreso_cuota
        alegra = _make_alegra_mock()
        db = _make_db_mock()

        tool_input = {
            "loanbook_id": "LB001",
            "monto": 800000,
            "banco": "Bancolombia",
            "numero_cuota": 3,
            "fecha": "2026-04-01",
        }
        await handle_registrar_ingreso_cuota(tool_input, alegra, db, db, "test")

        # Second call is the journal (first is payment)
        calls = alegra.request_with_verify.call_args_list
        journal_call = calls[1]  # journals is second
        payload = journal_call[1].get("payload") or journal_call[0][2]
        assert payload["observations"].startswith("[RDX]")

    @pytest.mark.asyncio
    async def test_ingreso_no_operacional_ing_prefix(self):
        from agents.contador.handlers.ingresos import handle_registrar_ingreso_no_operacional

        alegra = _make_alegra_mock()
        db = _make_db_mock()

        # Mock AlegraAccountsService — imported inline inside handler
        with patch("services.alegra_accounts.AlegraAccountsService") as MockAccounts:
            instance = MockAccounts.return_value
            instance.get_ingreso_id = AsyncMock(return_value="5456")

            tool_input = {
                "tipo": "intereses",
                "monto": 50000,
                "banco": "Bancolombia",
                "descripcion": "Intereses bancarios",
                "fecha": "2026-04-01",
            }
            await handle_registrar_ingreso_no_operacional(tool_input, alegra, db, db, "test")

        payload = alegra.request_with_verify.call_args[1].get("payload") or alegra.request_with_verify.call_args[0][2]
        assert payload["observations"].startswith("[ING]")

    @pytest.mark.asyncio
    async def test_cxc_socio_prefix(self):
        from agents.contador.handlers.ingresos import handle_registrar_cxc_socio

        alegra = _make_alegra_mock()
        db = _make_db_mock()

        with patch("services.alegra_accounts.AlegraAccountsService") as MockAccounts:
            instance = MockAccounts.return_value
            instance.get_cxc_socios_id = AsyncMock(return_value="5329")

            tool_input = {
                "socio_cedula": "80075452",
                "monto": 300000,
                "banco": "Bancolombia",
                "descripcion": "Retiro personal",
                "fecha": "2026-04-01",
            }
            await handle_registrar_cxc_socio(tool_input, alegra, db, db, "test")

        payload = alegra.request_with_verify.call_args[1].get("payload") or alegra.request_with_verify.call_args[0][2]
        assert payload["observations"].startswith("[CXC]")


# ───────────────────────────────────────────────
# Nomina handler prefix tests
# ───────────────────────────────────────────────

class TestNominaPrefix:
    @pytest.mark.asyncio
    async def test_nomina_no_prefix(self):
        from agents.contador.handlers.nomina import handle_registrar_nomina_mensual
        alegra = _make_alegra_mock()
        db = _make_db_mock()

        tool_input = {
            "mes": 4,
            "anio": 2026,
            "empleados": [{"nombre": "TestEmp", "salario": 2000000}],
            "banco": "Bancolombia",
            "incluir_sgsss": False,
        }
        await handle_registrar_nomina_mensual(tool_input, alegra, db, db, "test")

        payload = alegra.request_with_verify.call_args[1].get("payload") or alegra.request_with_verify.call_args[0][2]
        assert payload["observations"].startswith("[NO]")

    @pytest.mark.asyncio
    async def test_prestaciones_no_prefix(self):
        from agents.contador.handlers.nomina import handle_provisionar_prestaciones
        alegra = _make_alegra_mock()
        db = _make_db_mock()

        tool_input = {
            "mes": "2026-04",
            "empleados": [{"nombre": "TestEmp", "salario": 2000000}],
        }
        await handle_provisionar_prestaciones(tool_input, alegra, db, db, "test")

        payload = alegra.request_with_verify.call_args[1].get("payload") or alegra.request_with_verify.call_args[0][2]
        assert payload["observations"].startswith("[NO]")
