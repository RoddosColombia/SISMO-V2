"""
Tests for GET /api/loanbook/stats — activos count.

Rule (BUG 1 fix):
  "activos" = cartera viva = total - (saldado + castigado).
  pendiente_entrega IS counted as active credit.
  Only excludes saldado and castigado.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from routers.loanbook import loanbook_stats


def _mock_db_with_estados(estados: list[str]):
    """Build a mock db whose loanbook.find() returns docs with given estados."""
    docs = []
    for e in estados:
        docs.append({
            "estado": e,
            "modalidad": "semanal",
            "cuota_monto": 100_000,
            "saldo_capital": 1_000_000,
            "cuotas": [],
        })

    # Motor's find().to_list(length=N) — mock the async chain
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=docs)
    db = MagicMock()
    db.loanbook = MagicMock()
    db.loanbook.find = MagicMock(return_value=cursor)
    return db


@pytest.mark.asyncio
async def test_stats_counts_pendiente_entrega_as_active():
    """pendiente_entrega should be included in 'activos'."""
    db = _mock_db_with_estados(
        ["activo"] * 20 + ["mora"] * 3 + ["pendiente_entrega"] * 2 + ["saldado"]
    )
    stats = await loanbook_stats(db=db)
    assert stats["total"] == 26
    # 20 activo + 3 mora + 2 pendiente_entrega = 25
    assert stats["activos"] == 25, f"Expected 25 active credits, got {stats['activos']}"
    assert stats["saldados"] == 1
    assert stats["pendiente_entrega"] == 2


@pytest.mark.asyncio
async def test_stats_excludes_only_saldado_and_castigado():
    """Castigado + saldado must not count as active. Everything else does."""
    db = _mock_db_with_estados([
        "activo", "al_dia", "en_riesgo", "mora", "mora_grave",
        "reestructurado", "pendiente_entrega",
        "saldado", "castigado",
    ])
    stats = await loanbook_stats(db=db)
    # 7 activos varios, 2 excluidos
    assert stats["total"] == 9
    assert stats["activos"] == 7
    assert stats["saldados"] == 2


@pytest.mark.asyncio
async def test_stats_pendiente_entrega_does_not_contribute_to_recaudo():
    """pendiente_entrega counts as active but shouldn't add to weekly recaudo."""
    db = _mock_db_with_estados(["activo", "pendiente_entrega"])
    stats = await loanbook_stats(db=db)
    # Only the activo contributes (100_000 semanal)
    assert stats["recaudo_semanal"] == 100_000
    assert stats["activos"] == 2


@pytest.mark.asyncio
async def test_stats_cartera_total_sums_saldo_capital():
    """cartera_total suma saldo_capital de todos los no-saldados."""
    db = _mock_db_with_estados(["activo", "activo", "mora", "saldado"])
    stats = await loanbook_stats(db=db)
    # 3 activos × 1_000_000 = 3_000_000
    assert stats["cartera_total"] == 3_000_000
