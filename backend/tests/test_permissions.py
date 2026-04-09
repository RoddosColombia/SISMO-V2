import pytest
from core.permissions import validate_write_permission, WRITE_PERMISSIONS


def test_contador_can_write_cartera_pagos():
    assert validate_write_permission('contador', 'cartera_pagos', 'mongodb') is True


def test_contador_can_post_journals():
    assert validate_write_permission('contador', 'POST /journals', 'alegra') is True


def test_cfo_cannot_post_journals():
    with pytest.raises(PermissionError) as exc:
        validate_write_permission('cfo', 'POST /journals', 'alegra')
    assert 'cfo' in str(exc.value).lower()
    assert 'alegra' in str(exc.value).lower()


def test_radar_cannot_write_cartera_pagos():
    with pytest.raises(PermissionError):
        validate_write_permission('radar', 'cartera_pagos', 'mongodb')


def test_loanbook_can_write_inventario():
    assert validate_write_permission('loanbook', 'inventario_motos', 'mongodb') is True


def test_unknown_agent_raises():
    with pytest.raises(PermissionError):
        validate_write_permission('ghost', 'anything', 'mongodb')


def test_all_agents_can_append_events():
    for agent in ['contador', 'cfo', 'radar', 'loanbook']:
        assert validate_write_permission(agent, 'roddos_events', 'mongodb') is True
