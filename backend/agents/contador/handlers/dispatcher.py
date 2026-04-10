"""
ToolDispatcher — routes tool_name from LLM to the correct handler function.

All handler functions are imported lazily per-wave as they are implemented.
Wave 1: stub handlers that raise NotImplementedError (replaced by Waves 2-6).
"""
from motor.motor_asyncio import AsyncIOMotorDatabase
from services.alegra.client import AlegraClient
from core.events import publish_event

# Read-only tools execute immediately without ExecutionCard confirmation
READ_ONLY_TOOLS = frozenset({
    "consultar_plan_cuentas",
    "consultar_journals",
    "consultar_balance",
    "consultar_estado_resultados",
    "consultar_pagos",
    "consultar_contactos",
    "consultar_items",
    "consultar_movimiento_cuenta",
    "consultar_cxc_socios",
    "consultar_facturas",
    "consultar_cartera",
    "consultar_obligaciones_tributarias",
    "calcular_retenciones",
    "consultar_catalogo_roddos",
})

# Conciliation tools — now implemented in Phase 3
CONCILIATION_TOOLS = frozenset({
    "conciliar_extracto_bancario",
    "clasificar_movimiento",
    "enviar_movimiento_backlog",
    "causar_desde_backlog",
    "consultar_movimientos_pendientes",
})


def is_read_only_tool(tool_name: str) -> bool:
    return tool_name in READ_ONLY_TOOLS


def is_conciliation_tool(tool_name: str) -> bool:
    return tool_name in CONCILIATION_TOOLS


# ---------------------------------------------------------------------------
# Wave 1 stub handlers — replaced by Waves 2-6 implementations
# ---------------------------------------------------------------------------

async def _stub_handler(tool_name: str, **kwargs) -> dict:
    """Placeholder handler — will be replaced by the corresponding wave implementation."""
    raise NotImplementedError(f"Handler '{tool_name}' pendiente de implementación en Wave 2-6.")


async def _stub_crear_causacion(**kwargs) -> dict:
    raise NotImplementedError("crear_causacion: implementado en Wave 3 (egresos)")

async def _stub_registrar_gasto(**kwargs) -> dict:
    raise NotImplementedError("registrar_gasto: implementado en Wave 3 (egresos)")

async def _stub_registrar_gasto_recurrente(**kwargs) -> dict:
    raise NotImplementedError("registrar_gasto_recurrente: implementado en Wave 3 (egresos)")

async def _stub_anular_causacion(**kwargs) -> dict:
    raise NotImplementedError("anular_causacion: implementado en Wave 3 (egresos)")

async def _stub_causar_movimiento_bancario(**kwargs) -> dict:
    raise NotImplementedError("causar_movimiento_bancario: implementado en Wave 3 (egresos)")

async def _stub_registrar_ajuste_contable(**kwargs) -> dict:
    raise NotImplementedError("registrar_ajuste_contable: implementado en Wave 3 (egresos)")

async def _stub_registrar_depreciacion(**kwargs) -> dict:
    raise NotImplementedError("registrar_depreciacion: implementado en Wave 3 (egresos)")

async def _stub_registrar_pago_cuota(**kwargs) -> dict:
    raise NotImplementedError("registrar_pago_cuota: implementado en Wave 4 (ingresos)")

async def _stub_registrar_ingreso_no_operacional(**kwargs) -> dict:
    raise NotImplementedError("registrar_ingreso_no_operacional: implementado en Wave 4 (ingresos)")

async def _stub_registrar_cxc_socio(**kwargs) -> dict:
    raise NotImplementedError("registrar_cxc_socio: implementado en Wave 4 (ingresos)")

async def _stub_consultar_cxc_socios(**kwargs) -> dict:
    raise NotImplementedError("consultar_cxc_socios: implementado en Wave 4 (ingresos)")

async def _stub_crear_factura_venta_moto(**kwargs) -> dict:
    raise NotImplementedError("crear_factura_venta_moto: implementado en Wave 5 (facturacion)")

async def _stub_consultar_facturas(**kwargs) -> dict:
    raise NotImplementedError("consultar_facturas: implementado en Wave 5 (facturacion)")

async def _stub_anular_factura(**kwargs) -> dict:
    raise NotImplementedError("anular_factura: implementado en Wave 5 (facturacion)")

async def _stub_crear_nota_credito(**kwargs) -> dict:
    raise NotImplementedError("crear_nota_credito: implementado en Wave 5 (facturacion)")

async def _stub_consultar_plan_cuentas(**kwargs) -> dict:
    raise NotImplementedError("consultar_plan_cuentas: implementado en Wave 2 (consultas)")

async def _stub_consultar_journals(**kwargs) -> dict:
    raise NotImplementedError("consultar_journals: implementado en Wave 2 (consultas)")

async def _stub_consultar_balance(**kwargs) -> dict:
    raise NotImplementedError("consultar_balance: implementado en Wave 2 (consultas)")

async def _stub_consultar_estado_resultados(**kwargs) -> dict:
    raise NotImplementedError("consultar_estado_resultados: implementado en Wave 2 (consultas)")

async def _stub_consultar_pagos(**kwargs) -> dict:
    raise NotImplementedError("consultar_pagos: implementado en Wave 2 (consultas)")

async def _stub_consultar_contactos(**kwargs) -> dict:
    raise NotImplementedError("consultar_contactos: implementado en Wave 2 (consultas)")

async def _stub_consultar_items(**kwargs) -> dict:
    raise NotImplementedError("consultar_items: implementado en Wave 2 (consultas)")

async def _stub_consultar_movimiento_cuenta(**kwargs) -> dict:
    raise NotImplementedError("consultar_movimiento_cuenta: implementado en Wave 2 (consultas)")

async def _stub_consultar_cartera(**kwargs) -> dict:
    raise NotImplementedError("consultar_cartera: implementado en Wave 6 (cartera)")

async def _stub_registrar_nomina_mensual(**kwargs) -> dict:
    raise NotImplementedError("registrar_nomina_mensual: implementado en Wave 6 (nomina)")

async def _stub_consultar_obligaciones_tributarias(**kwargs) -> dict:
    raise NotImplementedError("consultar_obligaciones_tributarias: implementado en Wave 6 (nomina)")

async def _stub_calcular_retenciones(**kwargs) -> dict:
    raise NotImplementedError("calcular_retenciones: implementado en Wave 6 (nomina)")

async def _stub_consultar_catalogo_roddos(**kwargs) -> dict:
    raise NotImplementedError("consultar_catalogo_roddos: implementado en Wave 6 (catalogo)")


# Default stub registry (Wave 1) — Waves 2-6 override these via _build_handlers()
_DEFAULT_HANDLERS: dict = {
    "crear_causacion": _stub_crear_causacion,
    "registrar_gasto": _stub_registrar_gasto,
    "registrar_gasto_recurrente": _stub_registrar_gasto_recurrente,
    "anular_causacion": _stub_anular_causacion,
    "causar_movimiento_bancario": _stub_causar_movimiento_bancario,
    "registrar_ajuste_contable": _stub_registrar_ajuste_contable,
    "registrar_depreciacion": _stub_registrar_depreciacion,
    "registrar_pago_cuota": _stub_registrar_pago_cuota,
    "registrar_ingreso_no_operacional": _stub_registrar_ingreso_no_operacional,
    "registrar_cxc_socio": _stub_registrar_cxc_socio,
    "consultar_cxc_socios": _stub_consultar_cxc_socios,
    "crear_factura_venta_moto": _stub_crear_factura_venta_moto,
    "consultar_facturas": _stub_consultar_facturas,
    "anular_factura": _stub_anular_factura,
    "crear_nota_credito": _stub_crear_nota_credito,
    "consultar_plan_cuentas": _stub_consultar_plan_cuentas,
    "consultar_journals": _stub_consultar_journals,
    "consultar_balance": _stub_consultar_balance,
    "consultar_estado_resultados": _stub_consultar_estado_resultados,
    "consultar_pagos": _stub_consultar_pagos,
    "consultar_contactos": _stub_consultar_contactos,
    "consultar_items": _stub_consultar_items,
    "consultar_movimiento_cuenta": _stub_consultar_movimiento_cuenta,
    "consultar_cartera": _stub_consultar_cartera,
    "registrar_nomina_mensual": _stub_registrar_nomina_mensual,
    "consultar_obligaciones_tributarias": _stub_consultar_obligaciones_tributarias,
    "calcular_retenciones": _stub_calcular_retenciones,
    "consultar_catalogo_roddos": _stub_consultar_catalogo_roddos,
}


class ToolDispatcher:
    def __init__(
        self,
        alegra: AlegraClient,
        db: AsyncIOMotorDatabase,
        event_bus,
    ):
        self.alegra = alegra
        self.db = db
        self.event_bus = event_bus
        # Start with stub handlers — waves override as modules become available
        self._handlers: dict = dict(_DEFAULT_HANDLERS)
        self._build_handlers()

    def _build_handlers(self):
        """Import handlers lazily so missing modules don't block Wave 1."""
        # Wave 2: consultas
        try:
            from agents.contador.handlers.consultas import (
                handle_consultar_plan_cuentas,
                handle_consultar_journals,
                handle_consultar_balance,
                handle_consultar_estado_resultados,
                handle_consultar_pagos,
                handle_consultar_contactos,
                handle_consultar_items,
                handle_consultar_movimiento_cuenta,
            )
            self._handlers.update({
                "consultar_plan_cuentas": handle_consultar_plan_cuentas,
                "consultar_journals": handle_consultar_journals,
                "consultar_balance": handle_consultar_balance,
                "consultar_estado_resultados": handle_consultar_estado_resultados,
                "consultar_pagos": handle_consultar_pagos,
                "consultar_contactos": handle_consultar_contactos,
                "consultar_items": handle_consultar_items,
                "consultar_movimiento_cuenta": handle_consultar_movimiento_cuenta,
            })
        except ImportError:
            pass

        # Wave 3: egresos
        try:
            from agents.contador.handlers.egresos import (
                handle_crear_causacion,
                handle_registrar_gasto,
                handle_registrar_gasto_recurrente,
                handle_anular_causacion,
                handle_causar_movimiento_bancario,
                handle_registrar_ajuste_contable,
                handle_registrar_depreciacion,
            )
            self._handlers.update({
                "crear_causacion": handle_crear_causacion,
                "registrar_gasto": handle_registrar_gasto,
                "registrar_gasto_recurrente": handle_registrar_gasto_recurrente,
                "anular_causacion": handle_anular_causacion,
                "causar_movimiento_bancario": handle_causar_movimiento_bancario,
                "registrar_ajuste_contable": handle_registrar_ajuste_contable,
                "registrar_depreciacion": handle_registrar_depreciacion,
            })
        except ImportError:
            pass

        # Wave 4: ingresos + CXC
        try:
            from agents.contador.handlers.ingresos import (
                handle_registrar_ingreso_cuota,
                handle_registrar_ingreso_no_operacional,
                handle_registrar_cxc_socio,
                handle_consultar_cxc_socios,
            )
            self._handlers.update({
                "registrar_pago_cuota": handle_registrar_ingreso_cuota,
                "registrar_ingreso_no_operacional": handle_registrar_ingreso_no_operacional,
                "registrar_cxc_socio": handle_registrar_cxc_socio,
                "consultar_cxc_socios": handle_consultar_cxc_socios,
            })
        except ImportError:
            pass

        # Wave 5: facturacion
        try:
            from agents.contador.handlers.facturacion import (
                handle_crear_factura_venta_moto,
                handle_consultar_facturas,
                handle_anular_factura,
                handle_crear_nota_credito,
            )
            self._handlers.update({
                "crear_factura_venta_moto": handle_crear_factura_venta_moto,
                "consultar_facturas": handle_consultar_facturas,
                "anular_factura": handle_anular_factura,
                "crear_nota_credito": handle_crear_nota_credito,
            })
        except ImportError:
            pass

        # Wave 6: nomina + cartera + catalogo
        try:
            from agents.contador.handlers.nomina import (
                handle_registrar_nomina_mensual,
                handle_consultar_obligaciones_tributarias,
                handle_calcular_retenciones,
            )
            from agents.contador.handlers.cartera import (
                handle_consultar_cartera,
                handle_consultar_catalogo_roddos,
            )
            self._handlers.update({
                "registrar_nomina_mensual": handle_registrar_nomina_mensual,
                "consultar_obligaciones_tributarias": handle_consultar_obligaciones_tributarias,
                "calcular_retenciones": handle_calcular_retenciones,
                # registrar_pago_cuota mapped in Wave 4 to ingresos dual-op handler
                "consultar_cartera": handle_consultar_cartera,
                "consultar_catalogo_roddos": handle_consultar_catalogo_roddos,
            })
        except ImportError:
            pass

        # Phase 3: conciliacion bancaria
        try:
            from agents.contador.handlers.conciliacion import (
                handle_conciliar_extracto_bancario,
                handle_clasificar_movimiento,
                handle_enviar_movimiento_backlog,
                handle_causar_desde_backlog,
                handle_consultar_movimientos_pendientes,
            )
            self._handlers.update({
                "conciliar_extracto_bancario": handle_conciliar_extracto_bancario,
                "clasificar_movimiento": handle_clasificar_movimiento,
                "enviar_movimiento_backlog": handle_enviar_movimiento_backlog,
                "causar_desde_backlog": handle_causar_desde_backlog,
                "consultar_movimientos_pendientes": handle_consultar_movimientos_pendientes,
            })
        except ImportError:
            pass

    async def dispatch(self, tool_name: str, tool_input: dict, user_id: str) -> dict:
        handler = self._handlers.get(tool_name)
        if not handler:
            return {"success": False, "error": f"Handler no encontrado: {tool_name}"}

        try:
            return await handler(
                tool_input=tool_input,
                alegra=self.alegra,
                db=self.db,
                event_bus=self.event_bus,
                user_id=user_id,
            )
        except PermissionError as e:
            return {"success": False, "error": f"Sin permiso: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": f"Error ejecutando {tool_name}: {str(e)}"}
