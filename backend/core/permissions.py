"""
WRITE_PERMISSIONS — Code-enforced write permissions per agent.
No agent can write outside its permitted set. PermissionError is raised
before any Alegra call or MongoDB write. The LLM cannot reason around this.
"""

WRITE_PERMISSIONS: dict[str, dict[str, list[str]]] = {
    'contador': {
        'mongodb': ['cartera_pagos', 'cxc_socios', 'cxc_clientes',
                    'plan_cuentas_roddos', 'inventario_motos', 'roddos_events'],
        'alegra': ['POST /journals', 'POST /invoices', 'POST /payments',
                   'POST /items', 'POST /bills',
                   'DELETE /journals', 'GET /categories', 'GET /journals',
                   'GET /items', 'GET /bills'],
    },
    'cfo': {
        'mongodb': ['cfo_informes', 'cfo_alertas', 'roddos_events'],
        'alegra': ['GET /journals', 'GET /invoices', 'GET /payments',
                   'GET /categories', 'GET /bills'],
    },
    'radar': {
        'mongodb': ['crm_clientes', 'gestiones_cobranza', 'roddos_events'],
        'alegra': [],
    },
    'loanbook': {
        'mongodb': ['inventario_motos', 'loanbook', 'roddos_events', 'apartados', 'crm_clientes'],
        'alegra': [],
    },
}


def validate_write_permission(
    agent_type: str,
    target: str,
    operation: str = 'mongodb',
) -> bool:
    """
    Validate that agent_type has write permission for target in the given operation.

    Args:
        agent_type: 'contador' | 'cfo' | 'radar' | 'loanbook'
        target: MongoDB collection name OR Alegra endpoint (e.g., 'POST /journals')
        operation: 'mongodb' | 'alegra'

    Returns:
        True if permission granted.

    Raises:
        PermissionError: If agent_type is unknown or target is not in allowed list.
    """
    if agent_type not in WRITE_PERMISSIONS:
        raise PermissionError(
            f"Agente desconocido: '{agent_type}'. "
            f"Agentes válidos: {list(WRITE_PERMISSIONS.keys())}"
        )

    allowed = WRITE_PERMISSIONS[agent_type].get(operation, [])
    if target not in allowed:
        raise PermissionError(
            f"Agente '{agent_type}' no tiene permiso de escritura en "
            f"{operation}:{target}. Permisos permitidos: {allowed}"
        )

    return True
