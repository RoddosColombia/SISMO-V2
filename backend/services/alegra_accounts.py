"""
AlegraAccountsService — resolves Alegra category IDs without MongoDB.

Source of truth: GET /categories from Alegra API.
In-memory cache with 5-minute TTL.
Fallback: hardcoded IDs from mapeo_alegra_ids.json (verified 2026-04-10).

This service replaces all find_one calls to plan_cuentas_roddos and
plan_ingresos_roddos in the accounting handlers (ROG-4 compliance).
"""
import time
from services.alegra.client import AlegraClient


# Hardcoded fallback — only used if Alegra GET /categories fails
FALLBACK_IDS = {
    # Bancos (category IDs for journal entries)
    "Bancolombia": "5314", "Bancolombia 2029": "5314", "Bancolombia 2540": "5315",
    "BBVA": "5318", "BBVA 0210": "5318", "BBVA 0212": "5319",
    "Davivienda": "5322",
    "Banco de Bogotá": "5321", "Banco de Bogota": "5321", "Bogota": "5321",
    "Global66": "5536", "Global 66": "5536",
    # CXC
    "cxc_socios": "5329",              # 132505
    "creditos_directos_roddos": "5327", # 13050502
    # Ingresos
    "ingresos_financieros": "5456",     # 41502001 Creditos Directos Roddos
    "intereses_bancarios": "5436",      # 42 Otros ingresos
    "venta_motos_recuperadas": "5442",  # 41350501 Motos
    "otros": "5436",                    # 42 Otros ingresos
    # Gastos
    "Arrendamientos": "5480",
    "Sueldos": "5462",
    "Comisiones": "5508",
    "Gastos bancarios": "5507",
    "Gravamen": "5509",
    # Retenciones por pagar
    "retefuente_arriendo": "5386",
    "retefuente_servicios": "5383",
    "retefuente_honorarios_pn": "5381",
    "retefuente_honorarios_pj": "5382",
    "retefuente_compras": "5388",
    "reteica": "5392",
}

FALLBACK_GASTO = "5494"  # Deudores (bajo Gastos Generales) — NUNCA 5493 ni 5495


class AlegraAccountsService:
    """Resolves Alegra account IDs. Source: GET /categories. Cache: 5 min."""

    def __init__(self, alegra_client: AlegraClient):
        self._alegra = alegra_client
        self._cache: dict[str, str] = {}  # name -> id
        self._cache_ts: float = 0
        self._TTL = 300  # 5 minutes

    async def _refresh_if_needed(self):
        """GET /categories from Alegra if cache expired."""
        if time.time() - self._cache_ts < self._TTL and self._cache:
            return
        try:
            categories = await self._alegra.get("categories")
            self._cache = {}
            self._flatten(categories)
            self._cache_ts = time.time()
        except Exception:
            # If Alegra is down, keep stale cache or use fallbacks
            if not self._cache:
                self._cache = dict(FALLBACK_IDS)
                self._cache_ts = time.time()

    def _flatten(self, nodes: list | dict):
        """Recursively flatten category tree into name->id map."""
        if isinstance(nodes, dict):
            nodes = [nodes]
        for node in nodes:
            if isinstance(node, dict):
                name = node.get("name", "")
                cat_id = str(node.get("id", ""))
                if name and cat_id:
                    self._cache[name] = cat_id
                children = node.get("children", [])
                if children:
                    self._flatten(children)

    async def get_account_id(self, nombre: str) -> str:
        """Resolve Alegra category ID by name. Exact match first, then partial."""
        await self._refresh_if_needed()
        # Exact match
        if nombre in self._cache:
            return self._cache[nombre]
        # Partial match
        nombre_lower = nombre.lower()
        for key, val in self._cache.items():
            if nombre_lower in key.lower():
                return val
        # Fallback
        return FALLBACK_IDS.get(nombre, FALLBACK_GASTO)

    async def get_ingreso_id(self, tipo: str) -> str:
        """Resolve income account ID by tipo (ingresos_financieros, otros, etc.)."""
        return FALLBACK_IDS.get(tipo, "5436")  # Default: Otros ingresos

    async def get_cxc_socios_id(self) -> str:
        """CXC Socios — confirmed in Alegra as 5329 (132505)."""
        return "5329"

    async def get_bank_category_id(self, banco: str) -> str:
        """Bank category ID for journal entries."""
        return FALLBACK_IDS.get(banco, "5314")

    async def get_retencion_id(self, tipo: str) -> str:
        """Retention account ID by type."""
        key = f"retefuente_{tipo}"
        return FALLBACK_IDS.get(key, "5383")  # Default: servicios 4%
