"""
DataKeeper handler registry — Sprint 1 handlers.

Handlers are registered via @on_event decorator. Sprint 1 provides
INFRASTRUCTURE-ONLY handlers that prove the bus works end-to-end.

Loanbook handlers (factura.venta.creada → moto vendida, pago.cuota.registrado,
moto.entregada) arrive in Sprint 3 and Sprint 8 when the Loanbook model exists.
"""
import logging
from typing import Callable, Awaitable
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger("datakeeper.handlers")

HandlerFn = Callable[[dict, AsyncIOMotorDatabase], Awaitable[None]]

_registry: dict[str, list[dict]] = {}


def on_event(event_type: str, critical: bool = False):
    """Decorator to register an event handler."""
    def decorator(fn: HandlerFn) -> HandlerFn:
        if event_type not in _registry:
            _registry[event_type] = []
        _registry[event_type].append({
            "fn": fn,
            "critical": critical,
            "name": fn.__name__,
        })
        return fn
    return decorator


def get_registry() -> dict[str, list[dict]]:
    """Return the global handler registry."""
    return _registry


def register_all_handlers(processor) -> None:
    """Wire all decorated handlers into the EventProcessor."""
    for event_type, handlers in _registry.items():
        for h in handlers:
            processor.register(event_type, h["fn"], critical=h["critical"])


# ═══════════════════════════════════════════
# Sprint 1 handlers — infrastructure only
# ═══════════════════════════════════════════


@on_event("gasto.causado", critical=False)
async def handle_gasto_cfo_cache(event: dict, db: AsyncIOMotorDatabase):
    """
    CFO cache invalidation placeholder.
    Real invalidation implemented when CFO dashboard cache exists.
    """
    logger.info(
        f"CFO cache invalidation for gasto {event.get('event_id', '?')}"
    )


@on_event("apartado.completo", critical=False)
async def handle_apartado_completo_log(event: dict, db: AsyncIOMotorDatabase):
    """
    Apartado completo log — facturacion trigger deferred to Sprint 7.
    When Loanbook exists, this will trigger factura creation.
    """
    vin = event.get("datos", {}).get("vin", "?")
    logger.info(
        f"Apartado completo: VIN {vin} — "
        f"facturacion trigger deferred to Sprint 7"
    )


@on_event("test.ping", critical=True)
async def handle_test_ping(event: dict, db: AsyncIOMotorDatabase):
    """
    Test handler — validates the full processing loop end-to-end.
    Critical=True so tests can verify the critical path.
    """
    logger.info(f"DataKeeper ping received: {event.get('event_id', '?')}")


# ═══════════════════════════════════════════
# Dashboard cache — Alegra stats sync
# ═══════════════════════════════════════════

@on_event("factura.venta.creada", critical=False)
async def handle_factura_creada_sync_dashboard(event: dict, db: AsyncIOMotorDatabase):
    """
    Cuando se crea una factura de venta, actualiza inmediatamente el cache
    de métricas de Alegra en MongoDB para que el dashboard refleje el dato.
    Non-critical: si falla no bloquea el flujo principal.
    """
    sep_id = event.get("datos", {}).get("separacion_id", "?")
    logger.info(f"Dashboard cache sync trigger — factura.venta.creada sep={sep_id}")
    try:
        from core.alegra_sync import sync_alegra_invoice_stats
        await sync_alegra_invoice_stats(db)
    except Exception as exc:
        logger.warning(f"Dashboard cache sync failed (non-critical): {exc}")
