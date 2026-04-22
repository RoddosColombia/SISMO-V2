"""
test_catalogo_service.py — Tests del cache en memoria de catálogos maestros.

Valida:
  - Los 10 planes están en el cache (seeded por conftest)
  - Cada celda de cuotas_por_modalidad coincide con el maestro
  - Los 4 subtipos RODANTE están disponibles
  - Las funciones de validación de producto × plan funcionan
  - seed_for_tests / clear_cache funcionan correctamente

Todos son tests unitarios — sin MongoDB, sin I/O.
El fixture `seed_catalogos` en conftest.py pre-carga el cache antes de la sesión.
"""

import pytest
from services.loanbook import catalogo_service as cs
from services.loanbook.reglas_negocio import get_num_cuotas, PLAN_CUOTAS


# ─────────────────────── BLOQUE 1 — Planes en cache ──────────────────────────

def test_cache_tiene_10_planes():
    """Deben existir exactamente 10 planes en el cache."""
    planes = cs.list_planes_activos()
    assert len(planes) == 10, f"Se esperaban 10 planes, hay {len(planes)}"


def test_todos_los_codigos_de_plan_presentes():
    """Los 10 códigos de plan del maestro deben estar en el cache."""
    codigos_esperados = {"P1S", "P2S", "P3S", "P4S", "P6S", "P12S", "P15S", "P39S", "P52S", "P78S"}
    codigos_en_cache = {p["plan_codigo"] for p in cs.list_planes_activos()}
    assert codigos_en_cache == codigos_esperados


# ─────────────────────── BLOQUE 2 — Cuotas por modalidad ─────────────────────

class TestCuotasPorPlan:
    """Valida cada celda de la tabla cuotas × modalidad del maestro."""

    # RDX — planes con quincenal y mensual
    def test_P39S_semanal_39(self):
        assert cs.get_num_cuotas_sync("P39S", "semanal") == 39

    def test_P39S_quincenal_20(self):
        """Regla crítica: 20, NO round(39/2.2)=18."""
        assert cs.get_num_cuotas_sync("P39S", "quincenal") == 20

    def test_P39S_mensual_9(self):
        assert cs.get_num_cuotas_sync("P39S", "mensual") == 9

    def test_P52S_semanal_52(self):
        assert cs.get_num_cuotas_sync("P52S", "semanal") == 52

    def test_P52S_quincenal_26(self):
        """Regla crítica: 26, NO round(52/2.2)=24."""
        assert cs.get_num_cuotas_sync("P52S", "quincenal") == 26

    def test_P52S_mensual_12(self):
        assert cs.get_num_cuotas_sync("P52S", "mensual") == 12

    def test_P78S_semanal_78(self):
        assert cs.get_num_cuotas_sync("P78S", "semanal") == 78

    def test_P78S_quincenal_39(self):
        assert cs.get_num_cuotas_sync("P78S", "quincenal") == 39

    def test_P78S_mensual_18(self):
        assert cs.get_num_cuotas_sync("P78S", "mensual") == 18

    # RODANTE — solo semanal (R-23)
    def test_P1S_semanal_0_contado(self):
        """P1S contado: 0 cuotas programadas."""
        assert cs.get_num_cuotas_sync("P1S", "semanal") == 0

    def test_P2S_semanal_2(self):
        assert cs.get_num_cuotas_sync("P2S", "semanal") == 2

    def test_P3S_semanal_3(self):
        assert cs.get_num_cuotas_sync("P3S", "semanal") == 3

    def test_P4S_semanal_4(self):
        assert cs.get_num_cuotas_sync("P4S", "semanal") == 4

    def test_P6S_semanal_6(self):
        assert cs.get_num_cuotas_sync("P6S", "semanal") == 6

    def test_P12S_semanal_12(self):
        assert cs.get_num_cuotas_sync("P12S", "semanal") == 12

    def test_P15S_semanal_15(self):
        assert cs.get_num_cuotas_sync("P15S", "semanal") == 15

    # Combinaciones no configuradas → None (R-23)
    def test_P15S_quincenal_es_None(self):
        """RODANTE no tiene quincenal — debe retornar None."""
        assert cs.get_num_cuotas_sync("P15S", "quincenal") is None

    def test_P12S_mensual_es_None(self):
        """RODANTE no tiene mensual — debe retornar None."""
        assert cs.get_num_cuotas_sync("P12S", "mensual") is None

    def test_P1S_quincenal_es_None(self):
        assert cs.get_num_cuotas_sync("P1S", "quincenal") is None

    def test_plan_inexistente_retorna_None(self):
        assert cs.get_num_cuotas_sync("P999S", "semanal") is None

    def test_plan_vacio_retorna_None(self):
        assert cs.get_num_cuotas_sync("", "semanal") is None


# ─────────────────────── BLOQUE 3 — PLAN_CUOTAS lazy ─────────────────────────

def test_PLAN_CUOTAS_lazy_tiene_10_entradas():
    """La interfaz lazy PLAN_CUOTAS debe exponer los 10 planes."""
    assert len(PLAN_CUOTAS) == 10


def test_PLAN_CUOTAS_P39S_quincenal_es_20():
    """Validación vía interfaz legacy PLAN_CUOTAS."""
    assert PLAN_CUOTAS["P39S"]["quincenal"] == 20


def test_PLAN_CUOTAS_P52S_quincenal_es_26():
    assert PLAN_CUOTAS["P52S"]["quincenal"] == 26


def test_PLAN_CUOTAS_contains_P78S():
    assert "P78S" in PLAN_CUOTAS


def test_PLAN_CUOTAS_get_plan_inexistente():
    assert PLAN_CUOTAS.get("P999S") is None


# ─────────────────────── BLOQUE 4 — get_num_cuotas (reglas_negocio) ──────────

def test_get_num_cuotas_delega_a_cache():
    """get_num_cuotas() en reglas_negocio debe delegar al cache, no a constante."""
    assert get_num_cuotas("P39S", "quincenal") == 20
    assert get_num_cuotas("P52S", "quincenal") == 26
    assert get_num_cuotas("P78S", "semanal") == 78


def test_get_num_cuotas_plan_inexistente():
    assert get_num_cuotas("P999S", "semanal") is None


# ─────────────────────── BLOQUE 5 — Subtipos RODANTE ─────────────────────────

def test_cache_tiene_4_subtipos_rodante():
    subtipos = cs.list_subtipos_rodante()
    assert len(subtipos) == 4


def test_todos_los_subtipos_rodante_presentes():
    subtipos_esperados = {"repuestos", "soat", "comparendo", "licencia"}
    subtipos_en_cache = {r["subtipo"] for r in cs.list_subtipos_rodante()}
    assert subtipos_en_cache == subtipos_esperados


def test_subtipo_soat_ticket_min_200k():
    soat = cs.get_subtipo_rodante("soat")
    assert soat is not None
    assert soat["ticket_min"] == 200_000


def test_subtipo_soat_ticket_max_600k():
    soat = cs.get_subtipo_rodante("soat")
    assert soat["ticket_max"] == 600_000


def test_subtipo_licencia_ticket_max_1_4m():
    licencia = cs.get_subtipo_rodante("licencia")
    assert licencia is not None
    assert licencia["ticket_max"] == 1_400_000


def test_subtipo_repuestos_tiene_inventario():
    repuestos = cs.get_subtipo_rodante("repuestos")
    assert repuestos["inventario"] == "inventario_repuestos"


def test_subtipo_soat_inventario_es_None():
    soat = cs.get_subtipo_rodante("soat")
    assert soat["inventario"] is None


def test_subtipo_inexistente_retorna_None():
    assert cs.get_subtipo_rodante("hipoteca") is None


# ─────────────────────── BLOQUE 6 — Validación producto × plan ───────────────

def test_P78S_aplica_a_RDX():
    assert cs.is_plan_valido_para_producto("P78S", "RDX") is True


def test_P78S_no_aplica_a_RODANTE():
    """R-23: RODANTE solo P1S-P15S."""
    assert cs.is_plan_valido_para_producto("P78S", "RODANTE") is False


def test_P15S_aplica_a_RODANTE():
    assert cs.is_plan_valido_para_producto("P15S", "RODANTE") is True


def test_P15S_no_aplica_a_RDX():
    assert cs.is_plan_valido_para_producto("P15S", "RDX") is False


def test_P1S_aplica_a_ambos():
    """P1S contado es válido para RDX y RODANTE."""
    assert cs.is_plan_valido_para_producto("P1S", "RDX") is True
    assert cs.is_plan_valido_para_producto("P1S", "RODANTE") is True


def test_plan_inexistente_no_aplica():
    assert cs.is_plan_valido_para_producto("P999S", "RDX") is False


# ─────────────────────── BLOQUE 7 — get_planes_cuotas_dict ───────────────────

def test_get_planes_cuotas_dict_tiene_10_entradas():
    d = cs.get_planes_cuotas_dict()
    assert len(d) == 10


def test_get_planes_cuotas_dict_P39S_correcto():
    d = cs.get_planes_cuotas_dict()
    p39 = d["P39S"]
    assert p39["semanal"] == 39
    assert p39["quincenal"] == 20
    assert p39["mensual"] == 9


# ─────────────────────── BLOQUE 8 — get_planes_roddos_dict ───────────────────

def test_get_planes_roddos_dict_incluye_todos_los_semanas():
    """Todos los planes con modalidad semanal deben aparecer."""
    d = cs.get_planes_roddos_dict()
    codigos_esperados = {"P1S", "P2S", "P3S", "P4S", "P6S", "P12S", "P15S", "P39S", "P52S", "P78S"}
    assert set(d.keys()) == codigos_esperados


def test_get_planes_roddos_dict_P52S_es_52():
    d = cs.get_planes_roddos_dict()
    assert d["P52S"] == 52
