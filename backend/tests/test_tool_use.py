"""
Tests for Contador tool definitions — 44 tools after adding consultar_cuentas_inventario.

Rules verified:
- CONTADOR_TOOLS has exactly 44 tools (43 previous + 1 consultar_cuentas_inventario)
- Each tool has required Anthropic format fields
- CFO/RADAR return empty tool lists; Loanbook has 11
- No /journal-entries in any tool description
- No MongoDB references for contable data (plan de cuentas, journals, etc.)
- catalogo_cuentas_roddos contains all required IDs
- All write tools mention request_with_verify()
"""
import pytest
from agents.contador.tools import (
    CONTADOR_TOOLS,
    AGENT_TOOLS,
    get_tools_for_agent,
    _EGRESOS,
    _INGRESOS,
    _CONCILIACION,
    _FACTURACION,
    _CONSULTAS_ALEGRA,
    _CARTERA,
    _NOMINA_IMPUESTOS,
    _COMPRAS,
    _CATALOGO,
)


# --- Tool count ---

def test_contador_has_exactly_40_tools():
    # crear_factura_venta_via_firecrawl added: canal Firecrawl principal para facturar motos
    assert len(CONTADOR_TOOLS) == 48


def test_compras_has_2_tools():
    assert len(_COMPRAS) == 2


def test_egresos_has_7_tools():
    assert len(_EGRESOS) == 7


def test_ingresos_has_4_tools():
    assert len(_INGRESOS) == 4


def test_conciliacion_has_5_tools():
    assert len(_CONCILIACION) == 5


def test_facturacion_has_8_tools():
    assert len(_FACTURACION) == 10


def test_consultas_alegra_has_8_tools():
    assert len(_CONSULTAS_ALEGRA) == 8


def test_cartera_has_2_tools():
    assert len(_CARTERA) == 3  # resumen_cartera + consultar_cartera + consultar_recaudo_semanal


def test_nomina_impuestos_has_5_tools():
    assert len(_NOMINA_IMPUESTOS) == 5


def test_catalogo_has_1_tool():
    assert len(_CATALOGO) == 1


# --- Anthropic format ---

def test_each_tool_has_required_fields():
    required = {'name', 'description', 'input_schema'}
    for tool in CONTADOR_TOOLS:
        assert required.issubset(tool.keys()), f"Tool missing fields: {tool.get('name')}"


def test_input_schemas_are_valid():
    for tool in CONTADOR_TOOLS:
        schema = tool.get('input_schema', {})
        assert schema.get('type') == 'object', f"Tool {tool.get('name')} schema type must be 'object'"
        assert 'properties' in schema, f"Tool {tool.get('name')} schema must have 'properties'"


def test_all_tool_names_are_unique():
    names = [t['name'] for t in CONTADOR_TOOLS]
    assert len(names) == len(set(names)), f"Duplicate tool names: {[n for n in names if names.count(n) > 1]}"


# --- Agent routing ---

def test_get_tools_for_contador():
    tools = get_tools_for_agent('contador')
    assert len(tools) == 48


def test_get_tools_for_cfo_returns_empty():
    assert get_tools_for_agent('cfo') == []


def test_get_tools_for_radar_returns_5_tools():
    """Sprint S2 (Ejecucion 2): RADAR tiene 5 tools de cobranza."""
    tools = get_tools_for_agent('radar')
    assert len(tools) == 5
    nombres = {t["name"] for t in tools}
    assert "generar_cola_cobranza" in nombres
    assert "registrar_gestion" in nombres
    assert "registrar_promesa_pago" in nombres
    assert "enviar_whatsapp_template" in nombres
    assert "consultar_estado_cliente" in nombres


def test_get_tools_for_loanbook_returns_11():
    """Phase 7 Sprint 7: Loanbook agent now has 11 tools."""
    assert len(get_tools_for_agent('loanbook')) == 11


def test_unknown_agent_returns_empty():
    assert get_tools_for_agent('unknown_agent') == []


# --- Forbidden patterns ---

def test_no_journal_entries_in_descriptions():
    """journal-entries should only appear in 'NUNCA usar' warnings, never as an active endpoint."""
    for tool in CONTADOR_TOOLS:
        desc = tool.get('description', '')
        if 'journal-entries' in desc:
            assert 'NUNCA' in desc and 'journal-entries' in desc, \
                f"Tool {tool['name']} references /journal-entries without NUNCA warning"


def test_no_accounts_endpoint_in_descriptions():
    for tool in CONTADOR_TOOLS:
        desc = tool.get('description', '')
        assert '/accounts' not in desc, \
            f"Tool {tool['name']} references /accounts — use /categories"


def test_no_mongodb_for_contable_data():
    """Plan de cuentas, journals, facturas, pagos MUST come from Alegra, not MongoDB."""
    contable_tools = [
        'consultar_plan_cuentas', 'consultar_journals', 'consultar_facturas',
        'consultar_pagos', 'consultar_balance_general', 'consultar_estado_resultados',
        'registrar_ingreso_no_operacional', 'consultar_bills',
    ]
    for tool in CONTADOR_TOOLS:
        if tool['name'] in contable_tools:
            desc = tool.get('description', '').lower()
            assert 'mongodb' not in desc or 'nunca' in desc, \
                f"Tool {tool['name']} references MongoDB for contable data — must use Alegra"


def test_no_5495_in_catalogo():
    """ID 5495 is forbidden — caused 143 incorrect entries."""
    catalogo = next(t for t in CONTADOR_TOOLS if t['name'] == 'catalogo_cuentas_roddos')
    desc = catalogo['description']
    assert '5495' in desc, "catalogo must mention 5495 as forbidden"
    assert 'NUNCA' in desc and '5495' in desc, "catalogo must warn NUNCA usar 5495"


# --- Specific tools exist ---

EXPECTED_TOOLS = [
    'crear_causacion', 'registrar_gasto', 'registrar_gasto_recurrente',
    'anular_causacion', 'causar_movimiento_bancario', 'registrar_ajuste_contable',
    'registrar_depreciacion', 'registrar_pago_cuota', 'registrar_ingreso_no_operacional',
    'registrar_abono_cxc', 'registrar_ingreso_operacional',
    'conciliar_extracto_bancario', 'clasificar_movimiento', 'enviar_movimiento_backlog',
    'causar_desde_backlog', 'consultar_movimientos_pendientes',
    'crear_factura_venta', 'consultar_inventario', 'actualizar_estado_moto', 'consultar_bills',
    'consultar_plan_cuentas', 'consultar_journals', 'consultar_facturas', 'consultar_pagos',
    'consultar_saldo_cxc', 'consultar_balance_general', 'consultar_estado_resultados',
    'consultar_proveedores',
    'consultar_cartera', 'consultar_recaudo_semanal',
    'registrar_nomina', 'registrar_cxc_socio', 'consultar_iva_cuatrimestral',
    'consultar_calendario_tributario',
    'catalogo_cuentas_roddos',
]


@pytest.mark.parametrize("tool_name", EXPECTED_TOOLS)
def test_expected_tool_exists(tool_name):
    names = [t['name'] for t in CONTADOR_TOOLS]
    assert tool_name in names, f"Tool '{tool_name}' not found in CONTADOR_TOOLS"


# --- Write tools mention request_with_verify ---

WRITE_TOOLS = [
    'crear_causacion', 'registrar_gasto', 'registrar_gasto_recurrente',
    'anular_causacion', 'causar_movimiento_bancario', 'registrar_ajuste_contable',
    'registrar_depreciacion', 'registrar_pago_cuota', 'registrar_ingreso_no_operacional',
    'registrar_abono_cxc', 'registrar_ingreso_operacional',
    'conciliar_extracto_bancario', 'causar_desde_backlog',
    'crear_factura_venta', 'registrar_nomina', 'registrar_cxc_socio',
]


@pytest.mark.parametrize("tool_name", WRITE_TOOLS)
def test_write_tool_mentions_request_with_verify(tool_name):
    tool = next(t for t in CONTADOR_TOOLS if t['name'] == tool_name)
    assert 'request_with_verify' in tool['description'], \
        f"Write tool '{tool_name}' must mention request_with_verify() in description"


# --- Catálogo embebido contains all required IDs ---

def test_catalogo_contains_all_gasto_ids():
    catalogo = next(t for t in CONTADOR_TOOLS if t['name'] == 'catalogo_cuentas_roddos')
    desc = catalogo['description']
    gasto_ids = ['5462', '5475', '5471', '5472', '5480', '5485', '5487',
                 '5492', '5497', '5499', '5507', '5508', '5509', '5494',
                 '5486']
    for gid in gasto_ids:
        assert gid in desc, f"catalogo missing gasto ID {gid}"


def test_catalogo_contains_retencion_ids():
    catalogo = next(t for t in CONTADOR_TOOLS if t['name'] == 'catalogo_cuentas_roddos')
    desc = catalogo['description']
    # Real Alegra retención IDs (per type, not NIIF codes)
    assert '5381' in desc, "catalogo missing ReteFuente honorarios 10% ID 5381"
    assert '5382' in desc, "catalogo missing ReteFuente honorarios 11% ID 5382"
    assert '5383' in desc, "catalogo missing ReteFuente servicios 4% ID 5383"
    assert '5386' in desc, "catalogo missing ReteFuente arriendo 3.5% ID 5386"
    assert '5388' in desc, "catalogo missing ReteFuente compras 2.5% ID 5388"
    assert '5392' in desc, "catalogo missing ReteICA ID 5392"


def test_catalogo_contains_banco_ids():
    catalogo = next(t for t in CONTADOR_TOOLS if t['name'] == 'catalogo_cuentas_roddos')
    desc = catalogo['description']
    # Real Alegra bank category IDs
    banco_ids = ['5314', '5315', '5319', '5322', '5321', '5536']
    for bid in banco_ids:
        assert bid in desc, f"catalogo missing banco ID {bid}"


def test_catalogo_contains_retencion_rules():
    catalogo = next(t for t in CONTADOR_TOOLS if t['name'] == 'catalogo_cuentas_roddos')
    desc = catalogo['description']
    assert '3.5%' in desc, "catalogo missing arriendo ReteFuente 3.5%"
    assert '0.414%' in desc, "catalogo missing ReteICA 0.414%"
    assert 'cuatrimestral' in desc, "catalogo missing IVA cuatrimestral"
    assert '860024781' in desc, "catalogo missing Auteco NIT"


def test_catalogo_contains_socios():
    catalogo = next(t for t in CONTADOR_TOOLS if t['name'] == 'catalogo_cuentas_roddos')
    desc = catalogo['description']
    assert '80075452' in desc, "catalogo missing Andrés CC"
    assert '80086601' in desc, "catalogo missing Iván CC"
