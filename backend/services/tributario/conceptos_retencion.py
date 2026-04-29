"""
services/tributario/conceptos_retencion.py — Catálogo conceptos retefuente + ReICA.

Tarifas vigentes 2026 para RODDOS S.A.S. (régimen ordinario, agente retenedor).

Las cuentas Alegra ya están en CLAUDE.md (sección "Retenciones por pagar"):
  Honorarios 10% → ID 5381
  Honorarios 11% → ID 5382
  Servicios 4%   → ID 5383
  Arriendo 3.5%  → ID 5386
  Compras 2.5%   → ID 5388
  RteIca         → ID 5392

REGLA CLAUDE.md: Auteco NIT 860024781 = autoretenedor → NUNCA aplicar ReteFuente.
"""
from __future__ import annotations
from typing import TypedDict


class ConceptoRetencion(TypedDict):
    codigo: str
    descripcion: str
    tarifa_pct: float        # ej 0.10 = 10%
    base_minima_uvt: float   # base mínima en UVT (0 = sin base mínima)
    cuenta_alegra_id: str    # ID Alegra para journal entry
    aplica_a: str            # "compras" | "servicios" | "honorarios" | "arriendos"


# UVT 2026: $49.799 (resolución DIAN 000193 de 2025, ajustar cuando salga 2026)
UVT_2026 = 49799


# ─────────────────────────────────────────────────────────────────────────────
# RETEFUENTE — conceptos comunes RODDOS
# ─────────────────────────────────────────────────────────────────────────────

CONCEPTOS_RETEFUENTE: dict[str, ConceptoRetencion] = {
    "honorarios_10": {
        "codigo": "honorarios_10",
        "descripcion": "Honorarios profesionales (persona natural)",
        "tarifa_pct": 0.10,
        "base_minima_uvt": 0,  # sin base mínima
        "cuenta_alegra_id": "5381",
        "aplica_a": "honorarios",
    },
    "honorarios_11": {
        "codigo": "honorarios_11",
        "descripcion": "Honorarios profesionales (persona jurídica)",
        "tarifa_pct": 0.11,
        "base_minima_uvt": 0,
        "cuenta_alegra_id": "5382",
        "aplica_a": "honorarios",
    },
    "servicios_4": {
        "codigo": "servicios_4",
        "descripcion": "Servicios en general (persona jurídica)",
        "tarifa_pct": 0.04,
        "base_minima_uvt": 4,  # 4 UVT base mínima ($199.196 en 2026)
        "cuenta_alegra_id": "5383",
        "aplica_a": "servicios",
    },
    "arriendo_35": {
        "codigo": "arriendo_35",
        "descripcion": "Arrendamiento bienes inmuebles",
        "tarifa_pct": 0.035,
        "base_minima_uvt": 27,  # 27 UVT
        "cuenta_alegra_id": "5386",
        "aplica_a": "arriendos",
    },
    "compras_25": {
        "codigo": "compras_25",
        "descripcion": "Compra de bienes (declarantes)",
        "tarifa_pct": 0.025,
        "base_minima_uvt": 27,
        "cuenta_alegra_id": "5388",
        "aplica_a": "compras",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# ReteIVA — agentes retenedores grandes contribuyentes (15% sobre el IVA)
# RODDOS ES agente retenedor IVA según info usuario
# ─────────────────────────────────────────────────────────────────────────────

RETEIVA_TARIFA = 0.15  # 15% del IVA generado en compras a régimen común
RETEIVA_BASE_MINIMA_UVT_SERVICIOS = 4   # base mínima servicios
RETEIVA_BASE_MINIMA_UVT_COMPRAS = 27    # base mínima compras


# ─────────────────────────────────────────────────────────────────────────────
# ReICA Bogotá — comercial general
# Tarifa: 4‰ (4 por mil) según info usuario
# ─────────────────────────────────────────────────────────────────────────────

REICA_BOGOTA_TARIFA_COMERCIAL = 0.004  # 4 por mil
REICA_BOGOTA_AGENTE_RETENEDOR = True   # RODDOS retiene a sus proveedores


# ─────────────────────────────────────────────────────────────────────────────
# IVA — tarifas
# ─────────────────────────────────────────────────────────────────────────────

IVA_GENERAL = 0.19              # 19% general (motos, repuestos, accesorios)
IVA_EXENTO_CONCEPTOS = {        # operaciones exentas o no gravadas
    "soat", "matricula",        # SOAT y matrícula son exentos (CLAUDE.md)
}


def aplica_retefuente(
    monto_base: float,
    concepto: str,
    nit_proveedor: str = "",
) -> tuple[float, ConceptoRetencion | None]:
    """
    Calcula la retención fuente para un pago.

    Returns:
        (monto_retenido, concepto_dict) si aplica
        (0.0, None) si no aplica (autoretenedor, base inferior, concepto desconocido)
    """
    # Auteco autoretenedor — nunca aplicar
    if nit_proveedor == "860024781":
        return 0.0, None

    if concepto not in CONCEPTOS_RETEFUENTE:
        return 0.0, None

    c = CONCEPTOS_RETEFUENTE[concepto]
    base_min = c["base_minima_uvt"] * UVT_2026
    if monto_base < base_min:
        return 0.0, None

    retencion = round(monto_base * c["tarifa_pct"])
    return retencion, c


def aplica_reteiva(
    iva_base: float,
    monto_compra: float,
    es_servicio: bool,
    proveedor_regimen: str = "comun",
) -> float:
    """
    Calcula ReteIVA al 15% sobre el IVA generado.

    Solo aplica si:
    - Proveedor es régimen común
    - Monto excede la base mínima (4 UVT servicios, 27 UVT compras)
    """
    if proveedor_regimen != "comun":
        return 0.0
    base_min_uvt = RETEIVA_BASE_MINIMA_UVT_SERVICIOS if es_servicio else RETEIVA_BASE_MINIMA_UVT_COMPRAS
    base_min = base_min_uvt * UVT_2026
    if monto_compra < base_min:
        return 0.0
    return round(iva_base * RETEIVA_TARIFA)


def aplica_reica_bogota(monto_base: float) -> float:
    """ReICA Bogotá — 4 por mil sobre el monto bruto."""
    return round(monto_base * REICA_BOGOTA_TARIFA_COMERCIAL)
