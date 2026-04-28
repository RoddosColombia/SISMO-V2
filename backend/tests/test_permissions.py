import pytest
from core.permissions import validate_write_permission, WRITE_PERMISSIONS


def test_contador_cannot_write_cartera_pagos():
    """ROG-4 reformulada (2026-04-28): cartera_pagos es del Loanbook.
    El Contador antes tenia permiso latente que nunca usaba en produccion.
    Ahora cerrado para evitar drift futuro."""
    with pytest.raises(PermissionError):
        validate_write_permission('contador', 'cartera_pagos', 'mongodb')


def test_contador_cannot_write_inventario_motos():
    """ROG-4 reformulada: inventario_motos tiene mutex en Loanbook.
    El Contador puede LEER (Mongo no valida lecturas) pero no escribir."""
    with pytest.raises(PermissionError):
        validate_write_permission('contador', 'inventario_motos', 'mongodb')


def test_contador_cannot_write_plan_cuentas_roddos():
    """ROG-4: plan_cuentas_roddos deprecada en Phase 5.5.
    AlegraAccountsService es la fuente de IDs de cuenta."""
    with pytest.raises(PermissionError):
        validate_write_permission('contador', 'plan_cuentas_roddos', 'mongodb')


def test_contador_can_post_journals():
    assert validate_write_permission('contador', 'POST /journals', 'alegra') is True


def test_contador_can_append_events():
    assert validate_write_permission('contador', 'roddos_events', 'mongodb') is True


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
