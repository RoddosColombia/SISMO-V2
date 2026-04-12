"""
Wave 1 tests — Bank parsers + anti-duplicados.
Tests use inline mock data, no real files needed.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.anti_duplicados import (
    hash_extracto,
    hash_movimiento,
    check_extracto_duplicado,
    check_movimiento_duplicado,
    registrar_extracto_procesado,
    registrar_movimiento_procesado,
)
from services.bank_parsers import detect_bank, _parse_monto, _parse_date


# ═══════════════════════════════════════════════════════
# PARSER UTILITY TESTS
# ═══════════════════════════════════════════════════════

def test_parse_monto_negative():
    monto, tipo = _parse_monto("$-2,919.54")
    assert monto == 2919.54
    assert tipo == "debito"


def test_parse_monto_positive():
    monto, tipo = _parse_monto("$250,000.00")
    assert monto == 250000.0
    assert tipo == "credito"


def test_parse_monto_negative_large():
    monto, tipo = _parse_monto("$-729,886.00")
    assert monto == 729886.0
    assert tipo == "debito"


def test_parse_monto_numeric():
    monto, tipo = _parse_monto(-3361.30)
    assert monto == 3361.30
    assert tipo == "debito"


def test_parse_monto_positive_numeric():
    monto, tipo = _parse_monto(478574.00)
    assert monto == 478574.0
    assert tipo == "credito"


def test_parse_date_dd_mm_yyyy():
    assert _parse_date("31/03/2026", "%d/%m/%Y") == "2026-03-31"


def test_parse_date_dd_mm_yyyy_bbva():
    assert _parse_date("15-03-2026", "%d-%m-%Y") == "2026-03-15"


# ═══════════════════════════════════════════════════════
# DETECT BANK TESTS
# ═══════════════════════════════════════════════════════

def test_detect_bank_pdf_is_nequi():
    assert detect_bank("extracto_marzo.pdf") == "nequi"


def test_detect_bank_unsupported_extension():
    with pytest.raises(ValueError, match="no soportado"):
        detect_bank("extracto.csv")


# ═══════════════════════════════════════════════════════
# ANTI-DUPLICADOS TESTS
# ═══════════════════════════════════════════════════════

def test_hash_extracto_consistent():
    content = b"same content here"
    h1 = hash_extracto(content)
    h2 = hash_extracto(content)
    assert h1 == h2
    assert len(h1) == 32  # MD5 hex digest


def test_hash_extracto_different():
    h1 = hash_extracto(b"content A")
    h2 = hash_extracto(b"content B")
    assert h1 != h2


def test_hash_movimiento_consistent():
    h1 = hash_movimiento("2026-03-15", "PAGO ARRIENDO", 3614953.0)
    h2 = hash_movimiento("2026-03-15", "PAGO ARRIENDO", 3614953.0)
    assert h1 == h2


def test_hash_movimiento_different():
    h1 = hash_movimiento("2026-03-15", "PAGO ARRIENDO", 3614953.0)
    h2 = hash_movimiento("2026-03-15", "PAGO ARRIENDO", 3614954.0)
    assert h1 != h2


@pytest.mark.asyncio
async def test_check_extracto_duplicado_false():
    db = MagicMock()
    db.conciliacion_extractos_procesados = MagicMock()
    db.conciliacion_extractos_procesados.find_one = AsyncMock(return_value=None)
    result = await check_extracto_duplicado(db, "abc123")
    assert result is False


@pytest.mark.asyncio
async def test_check_extracto_duplicado_true():
    db = MagicMock()
    db.conciliacion_extractos_procesados = MagicMock()
    db.conciliacion_extractos_procesados.find_one = AsyncMock(return_value={"hash": "abc123"})
    result = await check_extracto_duplicado(db, "abc123")
    assert result is True


@pytest.mark.asyncio
async def test_check_movimiento_duplicado_false():
    db = MagicMock()
    db.conciliacion_movimientos_procesados = MagicMock()
    db.conciliacion_movimientos_procesados.find_one = AsyncMock(return_value=None)
    result = await check_movimiento_duplicado(db, "xyz789")
    assert result is False


@pytest.mark.asyncio
async def test_registrar_extracto_procesado():
    db = MagicMock()
    db.conciliacion_extractos_procesados = MagicMock()
    db.conciliacion_extractos_procesados.insert_one = AsyncMock()
    await registrar_extracto_procesado(db, "hash123", "Bancolombia", 50)
    db.conciliacion_extractos_procesados.insert_one.assert_called_once()


@pytest.mark.asyncio
async def test_registrar_movimiento_procesado():
    db = MagicMock()
    db.conciliacion_movimientos_procesados = MagicMock()
    db.conciliacion_movimientos_procesados.insert_one = AsyncMock()
    await registrar_movimiento_procesado(db, "hash456", "12345")
    db.conciliacion_movimientos_procesados.insert_one.assert_called_once()


# ═══════════════════════════════════════════════════════
# STATIC ANALYSIS
# ═══════════════════════════════════════════════════════

def test_pdfplumber_in_bank_parsers():
    import pathlib
    path = pathlib.Path("services/bank_parsers.py")
    content = path.read_text(encoding="utf-8")
    assert "import pdfplumber" in content


def test_pdfplumber_in_pyproject():
    import pathlib
    path = pathlib.Path("pyproject.toml")
    content = path.read_text(encoding="utf-8")
    assert "pdfplumber" in content
