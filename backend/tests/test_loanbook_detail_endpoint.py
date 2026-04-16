"""
Tests for GET /api/loanbook/{identifier} — accepts both VIN and loanbook_id.

Loanbooks of tipo_producto in {comparendo, licencia} have no VIN, so the
detail endpoint MUST also resolve by loanbook_id (e.g. "LB-2026-0026").
"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from routers.loanbook import get_loanbook


def _sample_doc(vin=None, lb_id="LB-2026-0099", tipo="moto"):
    return {
        "_id": "mongoobjectid",
        "loanbook_id": lb_id,
        "tipo_producto": tipo,
        "vin": vin,
        "cliente": {"nombre": "Test", "cedula": "123"},
        "modelo": "RAIDER 125" if tipo == "moto" else "LICENCIA",
        "estado": "activo",
        "cuotas": [
            {"numero": 1, "monto": 100_000, "estado": "pagada",
             "fecha": "2026-01-07", "fecha_pago": "2026-01-07", "mora_acumulada": 0},
            {"numero": 2, "monto": 100_000, "estado": "pendiente",
             "fecha": date.today().isoformat(), "fecha_pago": None, "mora_acumulada": 0},
        ],
    }


@pytest.mark.asyncio
async def test_lookup_by_vin_for_moto():
    """GET /api/loanbook/<VIN> resolves a moto loanbook."""
    db = MagicMock()
    db.loanbook = MagicMock()
    db.loanbook.find_one = AsyncMock(return_value=_sample_doc(vin="ABC123", lb_id="LB-2026-0001"))
    result = await get_loanbook(identifier="ABC123", db=db)
    assert result["loanbook_id"] == "LB-2026-0001"
    assert "_id" not in result  # _clean_doc pops it
    # Called at least once (VIN lookup path)
    db.loanbook.find_one.assert_called()


@pytest.mark.asyncio
async def test_lookup_by_loanbook_id_for_licencia():
    """GET /api/loanbook/LB-2026-0026 resolves a licencia loanbook with no VIN."""
    db = MagicMock()
    db.loanbook = MagicMock()
    doc = _sample_doc(vin=None, lb_id="LB-2026-0026", tipo="licencia")
    db.loanbook.find_one = AsyncMock(return_value=doc)
    result = await get_loanbook(identifier="LB-2026-0026", db=db)
    assert result["loanbook_id"] == "LB-2026-0026"
    assert result.get("tipo_producto") == "licencia"


@pytest.mark.asyncio
async def test_lookup_not_found_raises_404():
    """Unknown identifier returns HTTP 404."""
    db = MagicMock()
    db.loanbook = MagicMock()
    db.loanbook.find_one = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await get_loanbook(identifier="DOESNOTEXIST", db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_response_includes_computed_fields():
    """Response must include dpd, cuotas_pagadas, proxima_cuota, timeline_status."""
    db = MagicMock()
    db.loanbook = MagicMock()
    db.loanbook.find_one = AsyncMock(return_value=_sample_doc(vin="VIN123"))
    result = await get_loanbook(identifier="VIN123", db=db)
    assert "dpd" in result
    assert "cuotas_pagadas" in result
    assert result["cuotas_pagadas"] == 1  # 1 pagada de 2
    assert result["cuotas_total"] == 2
    # timeline_status assigned to each cuota
    for c in result["cuotas"]:
        assert "timeline_status" in c
