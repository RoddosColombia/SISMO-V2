"""
WRITE_PERMISSIONS - Code-enforced write permissions per agent.
No agent can write outside its permitted set. PermissionError is raised
before any Alegra call or MongoDB write. The LLM cannot reason around this.

ROG-4 (reformulada 2026-04-28) - SEPARACION DE DOMINIO:
  Cada coleccion operativa tiene UN solo agente dueno de escritura.
  - Contador: roddos_events + operaciones Alegra
  - Loanbook: inventario_motos, loanbook, apartados, crm_clientes (sync)
  - RADAR:    crm_clientes (gestiones), gestiones_cobranza
  - CFO:      cfo_informes, cfo_alertas (read-only sobre Alegra)

  Los datos contables (journals, invoices, payments, bills, items)
  viven SOLO en Alegra. AlegraAccountsService cachea IDs de cuentas
  desde GET /categories - nunca se persisten en MongoDB.

Cambios 2026-04-28 (cierre violacion latente):
  - Removidas de Contador: 'inventario_motos' (mutex Loanbook),
    'plan_cuentas_roddos' (deprecada Phase 5.5),
    'cartera_pagos' (mutex Loanbook),
    'cxc_socios', 'cxc_clientes' (no se mutaban en produccion real).
  - Contador ahora solo escribe en 'roddos_events'.
  - Test estatico tests/test_rog4_dominios.py bloquea CI si algun
    handler intenta mutar coleccion fuera de su dominio.
"""

WRITE_PERMISSIONS: dict[str, dict[str, list[str]]] = {
    'contador': {
        'mongodb': ['roddos_events', 'obligaciones_tributarias'],
        'alegra': ['POST /journals', 'POST /invoices', 'POST /payments',
                   'POST /items', 'POST /bills',
                   'DELETE /journals', 'GET /categories', 'GET /journals',
                   'GET /items', 'GET /bills'],
    },
    'cfo': {
        'mongodb': ['cfo_informes', 'cfo_alertas', 'roddos_events',
                    'tributario_recomendaciones'],
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
            f"Agentes validos: {list(WRITE_PERMISSIONS.keys())}"
        )

    allowed = WRITE_PERMISSIONS[agent_type].get(operation, [])
    if target not in allowed:
        raise PermissionError(
            f"Agente '{agent_type}' no tiene permiso de escritura en "
            f"{operation}:{target}. Permisos permitidos: {allowed}"
        )

    return True
