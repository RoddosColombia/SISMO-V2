"""
Router keyword expansion for moto sales (B7-UX BUG 3).

Contador now recognizes venta de moto phrases (factura / vende / venta /
VIN / sport / raider / apache / Pxx S). Regression tests ensure cfo and
radar routing still work.
"""
from core.router import CONFIDENCE_THRESHOLD, route_intent


def test_factura_sport_100_routes_to_contador():
    r = route_intent("Factura una Sport 100 a Juan, CC 123")
    assert r.agent == "contador", f"Expected contador, got {r.agent} ({r.confidence})"
    assert r.confidence >= CONFIDENCE_THRESHOLD


def test_vende_raider_vin_routes_to_contador():
    r = route_intent("Vende la Raider VIN 9FL25AF31VDB95057 al cliente Maria")
    assert r.agent == "contador", f"Expected contador, got {r.agent} ({r.confidence})"
    assert r.confidence >= CONFIDENCE_THRESHOLD


def test_registrar_venta_apache_routes_to_contador():
    r = route_intent("Registrar venta de moto Apache 160 con plan P52S")
    assert r.agent == "contador", f"Expected contador, got {r.agent} ({r.confidence})"
    assert r.confidence >= CONFIDENCE_THRESHOLD


# ── Regression: existing intents still route correctly ────────────────


def test_pl_still_routes_to_cfo():
    r = route_intent("¿Cuál es el P&L de marzo?")
    assert r.agent == "cfo", f"Expected cfo, got {r.agent} ({r.confidence})"
    assert r.confidence >= CONFIDENCE_THRESHOLD


def test_gasto_arriendo_still_routes_to_contador():
    r = route_intent("Causa este gasto de arriendo $3.600.000")
    assert r.agent == "contador", f"Expected contador, got {r.agent} ({r.confidence})"
    assert r.confidence >= CONFIDENCE_THRESHOLD


def test_cobranza_mora_still_routes_to_radar():
    # Use radar-specific terms that were already supported pre-B7
    r = route_intent("Quien esta en mora con cuota vencida — gestion de cobro")
    assert r.agent == "radar", f"Expected radar, got {r.agent} ({r.confidence})"
    assert r.confidence >= CONFIDENCE_THRESHOLD
