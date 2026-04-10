"""
Phase 3 integration tests — full conciliation flow.
"""
import pathlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.bank_parsers import _parse_monto, _parse_date, detect_bank
from services.anti_duplicados import hash_extracto, hash_movimiento
from agents.contador.handlers.conciliacion import _classify_movement, CONFIDENCE_THRESHOLD


# T1: parse_bancolombia structure (inline mock - can't create real xlsx in test)
def test_t1_parse_monto_bancolombia_format():
    """Bancolombia uses numeric values — negative=egreso."""
    monto, tipo = _parse_monto(-3361.30)
    assert monto == 3361.30
    assert tipo == "debito"


# T2: parse_nequi value handling
def test_t2_nequi_negative_positive():
    """Nequi: $-2,919.54 = egreso, $250,000.00 = ingreso."""
    m1, t1 = _parse_monto("$-2,919.54")
    assert m1 == 2919.54
    assert t1 == "debito"
    m2, t2 = _parse_monto("$250,000.00")
    assert m2 == 250000.0
    assert t2 == "credito"


# T3: detect_bank returns correct banco
def test_t3_detect_bank_pdf_nequi():
    assert detect_bank("extracto.pdf") == "nequi"


def test_t3b_detect_bank_csv_rejected():
    with pytest.raises(ValueError):
        detect_bank("extracto.csv")


# T4: hash_extracto consistent
def test_t4_hash_extracto_consistent():
    h1 = hash_extracto(b"same content")
    h2 = hash_extracto(b"same content")
    assert h1 == h2


# T5: hash_movimiento consistent
def test_t5_hash_movimiento_consistent():
    h1 = hash_movimiento("2026-03-15", "ARRIENDO", 3614953.0)
    h2 = hash_movimiento("2026-03-15", "ARRIENDO", 3614953.0)
    assert h1 == h2
    h3 = hash_movimiento("2026-03-15", "ARRIENDO", 3614954.0)
    assert h1 != h3


# T6: Classification >= 0.70 auto-cause
def test_t6_high_confidence_auto_cause():
    r = _classify_movement("PAGO ARRIENDO BODEGA ENERO", 3614953)
    assert r["confianza"] >= CONFIDENCE_THRESHOLD
    assert r["cuenta_id"] == 5480


# T7: Classification < 0.70 → backlog
def test_t7_low_confidence_backlog():
    r = _classify_movement("TRANSFERENCIA DESCONOCIDA REF12345", 500000)
    assert r["confianza"] < CONFIDENCE_THRESHOLD


# T8: Anti-dup Capa 1 — same extract hash
def test_t8_antidup_capa1():
    h1 = hash_extracto(b"file content ABC")
    h2 = hash_extracto(b"file content ABC")
    assert h1 == h2, "Same file should produce same hash"


# T9: Anti-dup Capa 2 — same movement hash
def test_t9_antidup_capa2():
    h1 = hash_movimiento("2026-01-15", "PAGO SERVICIOS ETB", 150000.0)
    h2 = hash_movimiento("2026-01-15", "PAGO SERVICIOS ETB", 150000.0)
    assert h1 == h2, "Same movement should produce same hash"


# T10: causar_desde_backlog flow
@pytest.mark.asyncio
async def test_t10_causar_desde_backlog():
    from agents.contador.handlers.conciliacion import handle_causar_desde_backlog
    mock_alegra = AsyncMock()
    mock_alegra.request_with_verify = AsyncMock(return_value={"id": 999, "_alegra_id": "999"})
    mock_db = MagicMock()
    mock_db.roddos_events = MagicMock()
    mock_db.roddos_events.insert_one = AsyncMock()
    mock_db.backlog_movimientos = MagicMock()
    mock_db.backlog_movimientos.find_one = AsyncMock(return_value={
        "_id": "fake_id", "fecha": "2026-03-15", "descripcion": "PAGO TEST",
        "monto": 500000, "tipo": "debito", "banco": "BBVA",
    })
    mock_db.backlog_movimientos.update_one = AsyncMock()

    with patch("agents.contador.handlers.conciliacion.validate_write_permission"):
        with patch("agents.contador.handlers.conciliacion.publish_event", new_callable=AsyncMock):
            with patch("bson.ObjectId", return_value="fake_id"):
                result = await handle_causar_desde_backlog(
                    {"backlog_id": "fake_id", "cuenta_id": 5484},
                    mock_alegra, mock_db, mock_db, "u1",
                )
                assert result["success"] is True
                assert result["alegra_id"] == "999"


# T11: STATIC — no contable MongoDB writes in conciliacion.py
def test_t11_static_no_contable_writes():
    path = pathlib.Path("backend/agents/contador/handlers/conciliacion.py")
    if not path.exists():
        pytest.skip("conciliacion.py not found")
    content = path.read_text(encoding="utf-8")
    allowed = {"backlog_movimientos", "conciliacion_jobs", "conciliacion_extractos_procesados",
                "conciliacion_movimientos_procesados", "roddos_events"}
    violations = []
    for i, line in enumerate(content.split("\n"), 1):
        for op in ["insert_one", "update_one"]:
            if op in line and not any(col in line for col in allowed):
                violations.append(f"L{i}: {line.strip()}")
    assert len(violations) == 0, f"Forbidden writes: {violations}"


# T12: Socio classification → CXC 1.0
def test_t12_socio_classification():
    r = _classify_movement("ENVIO CON BRE-B A: ANDRES 80075452", 620000)
    assert r["tipo"] == "cxc_socio"
    assert r["confianza"] == 1.0
    assert r["socio_cc"] == "80075452"
