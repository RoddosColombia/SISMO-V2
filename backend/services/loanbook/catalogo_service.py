"""
services/loanbook/catalogo_service.py — Cache en memoria de los catálogos maestros.

En producción:
  - `warm_catalogo(db)` se llama una vez al inicio (lifespan) y carga los datos
    de las colecciones `catalogo_planes` y `catalogo_rodante` de MongoDB.
  - Las funciones sync (get_plan, get_num_cuotas_sync, etc.) leen del cache —
    sin await, sin I/O — seguras para usar en funciones puras.

En tests unitarios:
  - `seed_for_tests(planes, rodante)` inyecta los datos directamente.
  - conftest.py llama a seed_for_tests antes de que corran los tests.

Regla R-06: PLAN_CUOTAS NUNCA hardcoded en Python. Este módulo es la única
fuente de verdad del catálogo de planes en tiempo de ejecución.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

# ─────────────────────── Estado del cache ─────────────────────────────────────

_cache: dict[str, list[dict]] = {
    "planes":  [],   # lista de documentos catalogo_planes
    "rodante": [],   # lista de documentos catalogo_rodante
}


# ─────────────────────── Calentamiento async ──────────────────────────────────

async def warm_catalogo(db: "AsyncIOMotorDatabase") -> None:
    """Carga catalogo_planes y catalogo_rodante desde MongoDB al cache.

    Se llama una vez al inicio del proceso (lifespan de FastAPI).
    Si alguna colección está vacía, registra un warning pero no lanza excepción.

    Args:
        db: instancia de AsyncIOMotorDatabase ya inicializada
    """
    planes_docs = await db.catalogo_planes.find({"activo": True}).to_list(length=100)
    rodante_docs = await db.catalogo_rodante.find({"activo": True}).to_list(length=20)

    _cache["planes"]  = [{k: v for k, v in d.items() if k != "_id"} for d in planes_docs]
    _cache["rodante"] = [{k: v for k, v in d.items() if k != "_id"} for d in rodante_docs]

    logger.info(
        "catalogo_service: %d planes, %d subtipos RODANTE cargados",
        len(_cache["planes"]),
        len(_cache["rodante"]),
    )

    if not _cache["planes"]:
        logger.warning(
            "catalogo_planes está vacío. Ejecuta scripts/poblar_catalogos.py"
        )
    if not _cache["rodante"]:
        logger.warning(
            "catalogo_rodante está vacío. Ejecuta scripts/poblar_catalogos.py"
        )


# ─────────────────────── Lectura sync (sin I/O) ───────────────────────────────

def get_plan(plan_codigo: str) -> dict | None:
    """Documento completo de un plan por su código.

    Args:
        plan_codigo: "P1S", "P2S", ..., "P78S"

    Returns:
        dict con todos los campos del catálogo, o None si no existe.
    """
    for p in _cache["planes"]:
        if p.get("plan_codigo") == plan_codigo:
            return p
    return None


def get_num_cuotas_sync(plan_codigo: str, modalidad: str) -> int | None:
    """Número canónico de cuotas para plan × modalidad (sync, sin I/O).

    Args:
        plan_codigo: "P39S", "P52S", etc.
        modalidad:   "semanal", "quincenal" o "mensual"

    Returns:
        int  — número de cuotas según tabla maestra
        None — plan no existe o combinación no configurada
    """
    plan = get_plan(plan_codigo)
    if plan is None:
        return None
    return plan.get("cuotas_por_modalidad", {}).get(modalidad)


def get_planes_cuotas_dict() -> dict[str, dict[str, int | None]]:
    """Construye el dict equivalente a la antigua constante PLAN_CUOTAS.

    Formato de salida:
        {
            "P39S": {"semanal": 39, "quincenal": 20, "mensual": 9},
            ...
        }

    Retorna un dict vacío si el cache no está calentado aún.
    Solo se usa en funciones legacy que necesitan iterar todos los planes.
    """
    result: dict[str, dict[str, int | None]] = {}
    for p in _cache["planes"]:
        codigo = p.get("plan_codigo", "")
        cuotas = p.get("cuotas_por_modalidad", {})
        result[codigo] = {
            "semanal":   cuotas.get("semanal"),
            "quincenal": cuotas.get("quincenal"),
            "mensual":   cuotas.get("mensual"),
        }
    return result


def get_planes_roddos_dict() -> dict[str, int]:
    """Dict plan_codigo → num_cuotas_semanal para los planes con modalidad semanal.

    Equivale a la antigua constante PLANES_RODDOS de state_calculator.py.
    """
    return {
        p["plan_codigo"]: p["cuotas_por_modalidad"]["semanal"]
        for p in _cache["planes"]
        if "semanal" in p.get("cuotas_por_modalidad", {})
    }


def get_subtipo_rodante(subtipo: str) -> dict | None:
    """Documento de catálogo para un subtipo RODANTE.

    Args:
        subtipo: "repuestos", "soat", "comparendo" o "licencia"

    Returns:
        dict con campos del catálogo, o None si no existe.
    """
    for r in _cache["rodante"]:
        if r.get("subtipo") == subtipo:
            return r
    return None


def list_planes_activos() -> list[dict]:
    """Lista completa de planes activos tal como están en el cache."""
    return list(_cache["planes"])


def list_subtipos_rodante() -> list[dict]:
    """Lista completa de subtipos RODANTE tal como están en el cache."""
    return list(_cache["rodante"])


def is_plan_valido_para_producto(plan_codigo: str, producto: str) -> bool:
    """Verifica si un plan es válido para un producto (RDX o RODANTE).

    Args:
        plan_codigo: código del plan a verificar
        producto:    "RDX" o "RODANTE"

    Returns:
        True si el plan existe y acepta el producto dado.
    """
    plan = get_plan(plan_codigo)
    if plan is None:
        return False
    return producto in plan.get("aplica_a", [])


# ─────────────────────── Inyección para tests ─────────────────────────────────

def seed_for_tests(
    planes: list[dict],
    rodante: list[dict],
) -> None:
    """Inyecta datos directamente en el cache sin tocar MongoDB.

    SOLO para tests unitarios. conftest.py debe llamar esta función antes
    de que corran los tests que usen funciones de reglas_negocio o catalogo_service.

    Args:
        planes:  lista de documentos con el mismo formato que catalogo_planes
        rodante: lista de documentos con el mismo formato que catalogo_rodante
    """
    _cache["planes"]  = list(planes)
    _cache["rodante"] = list(rodante)


def clear_cache() -> None:
    """Vacía el cache. Solo para tests que necesiten aislar estado."""
    _cache["planes"]  = []
    _cache["rodante"] = []
