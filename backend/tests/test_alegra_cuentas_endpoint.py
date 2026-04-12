"""Tests for GET /api/alegra/cuentas endpoint."""
import pytest
from routers.alegra import _flatten_categories


def test_flatten_categories_extracts_movement_accounts():
    """Only 'movement' accounts are returned, not accumulative."""
    categories = [
        {
            "id": "5308", "name": "Bancos", "use": "accumulative", "code": "11",
            "children": [
                {"id": "5314", "name": "Bancolombia 2029", "use": "movement", "code": "11100501", "children": []},
                {"id": "5315", "name": "Bancolombia 2540", "use": "movement", "code": "11100502", "children": []},
            ],
        },
        {"id": "5493", "name": "Gastos Generales", "use": "accumulative", "code": "5195", "children": [
            {"id": "5494", "name": "Deudores", "use": "movement", "code": "51991001", "children": []},
        ]},
    ]
    result = []
    _flatten_categories(categories, result)
    ids = {a["id"] for a in result}
    # Movement accounts included
    assert "5314" in ids
    assert "5315" in ids
    assert "5494" in ids
    # Accumulative excluded
    assert "5308" not in ids
    assert "5493" not in ids


def test_5494_label_not_fallback():
    """Account 5494 should NOT have 'FALLBACK' in its name."""
    categories = [
        {"id": "5494", "name": "Deudores", "use": "movement", "code": "51991001", "children": []},
    ]
    result = []
    _flatten_categories(categories, result)
    assert len(result) == 1
    assert "FALLBACK" not in result[0]["nombre"]
    assert result[0]["nombre"] == "Deudores"
