import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from main import app

pytest_asyncio.mode = "auto"

# ─────────────────────── Seed de catálogos para tests unitarios ───────────────
#
# Los tests de reglas_negocio, state_calculator, auditor, reparador y excel_export
# son tests unitarios (sin I/O). Usan funciones síncronas que leen del cache en
# memoria de catalogo_service.
#
# Este fixture inyecta los mismos datos que scripts/poblar_catalogos.py antes de
# que corran los tests, sin tocar MongoDB.
#
# Scope "session" → se ejecuta una vez por sesión de tests, no una vez por test.

_PLANES_TEST = [
    {
        "plan_codigo": "P1S",
        "descripcion": "Contado (pago único)",
        "aplica_a": ["RDX", "RODANTE"],
        "cuotas_por_modalidad": {"semanal": 0},
        "multiplicador_precio": {"semanal": 1.0},
        "activo": True,
    },
    {
        "plan_codigo": "P2S",
        "descripcion": "2 semanas",
        "aplica_a": ["RODANTE"],
        "cuotas_por_modalidad": {"semanal": 2},
        "multiplicador_precio": {"semanal": 1.0},
        "activo": True,
    },
    {
        "plan_codigo": "P3S",
        "descripcion": "3 semanas",
        "aplica_a": ["RODANTE"],
        "cuotas_por_modalidad": {"semanal": 3},
        "multiplicador_precio": {"semanal": 1.0},
        "activo": True,
    },
    {
        "plan_codigo": "P4S",
        "descripcion": "4 semanas",
        "aplica_a": ["RODANTE"],
        "cuotas_por_modalidad": {"semanal": 4},
        "multiplicador_precio": {"semanal": 1.0},
        "activo": True,
    },
    {
        "plan_codigo": "P6S",
        "descripcion": "6 semanas",
        "aplica_a": ["RODANTE"],
        "cuotas_por_modalidad": {"semanal": 6},
        "multiplicador_precio": {"semanal": 1.0},
        "activo": True,
    },
    {
        "plan_codigo": "P12S",
        "descripcion": "12 semanas",
        "aplica_a": ["RODANTE"],
        "cuotas_por_modalidad": {"semanal": 12},
        "multiplicador_precio": {"semanal": 1.0},
        "activo": True,
    },
    {
        "plan_codigo": "P15S",
        "descripcion": "15 semanas",
        "aplica_a": ["RODANTE"],
        "cuotas_por_modalidad": {"semanal": 15},
        "multiplicador_precio": {"semanal": 1.0},
        "activo": True,
    },
    {
        "plan_codigo": "P39S",
        "descripcion": "39 semanas / 9 meses",
        "aplica_a": ["RDX"],
        "cuotas_por_modalidad": {"semanal": 39, "quincenal": 20, "mensual": 9},
        "multiplicador_precio": {"semanal": 1.0, "quincenal": 2.2, "mensual": 4.4},
        "activo": True,
    },
    {
        "plan_codigo": "P52S",
        "descripcion": "52 semanas / 12 meses",
        "aplica_a": ["RDX"],
        "cuotas_por_modalidad": {"semanal": 52, "quincenal": 26, "mensual": 12},
        "multiplicador_precio": {"semanal": 1.0, "quincenal": 2.2, "mensual": 4.4},
        "activo": True,
    },
    {
        "plan_codigo": "P78S",
        "descripcion": "78 semanas / 18 meses",
        "aplica_a": ["RDX"],
        "cuotas_por_modalidad": {"semanal": 78, "quincenal": 39, "mensual": 18},
        "multiplicador_precio": {"semanal": 1.0, "quincenal": 2.2, "mensual": 4.4},
        "activo": True,
    },
]

_RODANTE_TEST = [
    {
        "subtipo": "repuestos",
        "descripcion": "Microcrédito para repuestos de moto",
        "ticket_min": 50_000,
        "ticket_max": 500_000,
        "planes_validos": ["P1S", "P2S", "P3S", "P4S", "P6S", "P12S", "P15S"],
        "required_fields": [
            "referencia_sku", "cantidad", "valor_unitario",
            "descripcion_repuesto", "inventario_origen_id",
        ],
        "inventario": "inventario_repuestos",
        "activo": True,
    },
    {
        "subtipo": "soat",
        "descripcion": "Financiación SOAT",
        "ticket_min": 200_000,
        "ticket_max": 600_000,
        "planes_validos": ["P1S", "P2S", "P3S", "P4S", "P6S", "P12S", "P15S"],
        "required_fields": [
            "poliza_numero", "aseguradora", "cilindraje_moto",
            "vigencia_desde", "vigencia_hasta", "valor_soat", "placa_cubierta",
        ],
        "inventario": None,
        "activo": True,
    },
    {
        "subtipo": "comparendo",
        "descripcion": "Financiación comparendos",
        "ticket_min": 100_000,
        "ticket_max": 5_000_000,
        "planes_validos": ["P1S", "P2S", "P3S", "P4S", "P6S", "P12S", "P15S"],
        "required_fields": [
            "comparendo_numero", "entidad_emisora", "fecha_infraccion",
            "valor_comparendo", "codigo_infraccion",
        ],
        "inventario": None,
        "activo": True,
    },
    {
        "subtipo": "licencia",
        "descripcion": "Financiación licencia de conducción",
        "ticket_min": 200_000,
        "ticket_max": 1_400_000,
        "planes_validos": ["P1S", "P2S", "P3S", "P4S", "P6S", "P12S", "P15S"],
        "required_fields": [
            "categoria_licencia", "centro_ensenanza_nombre", "centro_ensenanza_nit",
            "fecha_inicio_curso", "valor_curso",
        ],
        "inventario": None,
        "activo": True,
    },
]


@pytest.fixture(scope="session", autouse=True)
def seed_catalogos():
    """Pre-carga el cache de catalogo_service con los datos del maestro.

    autouse=True → se ejecuta automáticamente antes de TODOS los tests de la sesión.
    Esto garantiza que get_num_cuotas(), PLAN_CUOTAS, PLANES_RODDOS funcionen sin MongoDB.
    """
    from services.loanbook import catalogo_service
    from services.loanbook.reglas_negocio import PLAN_CUOTAS
    from services.loanbook.state_calculator import PLANES_RODDOS

    catalogo_service.seed_for_tests(_PLANES_TEST, _RODANTE_TEST)

    # Forzar recarga de los lazy dicts ahora que el cache está sembrado
    if hasattr(PLAN_CUOTAS, "_invalidate"):
        PLAN_CUOTAS._invalidate()
    if hasattr(PLANES_RODDOS, "_invalidate"):
        PLANES_RODDOS._invalidate()

    yield

    # Teardown: dejar el cache limpio para no contaminar sesiones posteriores
    catalogo_service.clear_cache()


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
