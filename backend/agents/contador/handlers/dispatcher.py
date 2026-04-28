"""
ToolDispatcher — routes tool_name from LLM to the correct handler function.

CRITICAL: Tool names here MUST match the "name" field in tools.py exactly.
Claude emits tool names from tools.py; if the dispatcher key differs, the tool won't execute.
"""
import logging
import traceback as _tb
from motor.motor_asyncio import AsyncIOMotorDatabase
from services.alegra.client import AlegraClient
from core.events import publish_event

logger = logging.getLogger("dispatcher.contador")

# Read-only tools execute immediately without ExecutionCard confirmation
# Names must match tools.py "name" fields exactly
READ_ONLY_TOOLS = frozenset({
    "consultar_plan_cuentas",
    "consultar_journals",
    "consultar_balance_general",
    "consultar_estado_resultados",
    "consultar_pagos",
    "consultar_proveedores",
    "consultar_saldo_cxc",
    "consultar_facturas",
    "consultar_cartera",
    "resumen_cartera",
    "consultar_iva_cuatrimestral",
    "consultar_recaudo_semanal",
    "consultar_inventario",
    "consultar_inventario_alegra",
    "consultar_bills",
    "catalogo_cuentas_roddos",
    "consultar_calendario_tributario",
    "consultar_cuentas_inventario",
})

# Conciliation tools — implemented in Phase 3
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
        self._handlers: dict = {}
        self._build_handlers()

    def _build_handlers(self):
        """Import handlers lazily. Keys MUST match tools.py 'name' fields."""

        # Wave 2: consultas (read-only)
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
                "consultar_balance_general": handle_consultar_balance,
                "consultar_estado_resultados": handle_consultar_estado_resultados,
                "consultar_pagos": handle_consultar_pagos,
                "consultar_proveedores": handle_consultar_contactos,
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
                "consultar_saldo_cxc": handle_consultar_cxc_socios,
            })
        except ImportError:
            pass

        # Wave 5: facturacion
        try:
            from agents.contador.handlers.facturacion import (
                handle_registrar_compra_motos,
                handle_crear_item_inventario,
                handle_crear_factura_venta_moto,
                handle_crear_factura_venta_via_firecrawl,
                handle_consultar_facturas,
                handle_anular_factura,
                handle_crear_nota_credito,
                handle_consultar_cuentas_inventario,
            )
            self._handlers.update({
                "registrar_compra_motos": handle_registrar_compra_motos,
                "crear_item_inventario": handle_crear_item_inventario,
                "crear_factura_venta": handle_crear_factura_venta_moto,
                "crear_factura_venta_via_firecrawl": handle_crear_factura_venta_via_firecrawl,
                "consultar_facturas": handle_consultar_facturas,
                "anular_factura": handle_anular_factura,
                "crear_nota_credito": handle_crear_nota_credito,
                "consultar_cuentas_inventario": handle_consultar_cuentas_inventario,
            })
        except ImportError:
            pass

        # Wave 6: nomina + cartera + catalogo
        try:
            from agents.contador.handlers.nomina import (
                handle_registrar_nomina_mensual,
                handle_consultar_obligaciones_tributarias,
                handle_calcular_retenciones,
                handle_provisionar_prestaciones,
                handle_consultar_calendario_tributario,
            )
            from agents.contador.handlers.cartera import (
                handle_consultar_cartera,
                handle_resumen_cartera,
                handle_consultar_catalogo_roddos,
            )
            self._handlers.update({
                "registrar_nomina": handle_registrar_nomina_mensual,
                "consultar_iva_cuatrimestral": handle_consultar_obligaciones_tributarias,
                "provisionar_prestaciones": handle_provisionar_prestaciones,
                "consultar_cartera": handle_consultar_cartera,
                "resumen_cartera": handle_resumen_cartera,
                "catalogo_cuentas_roddos": handle_consultar_catalogo_roddos,
                "consultar_calendario_tributario": handle_consultar_calendario_tributario,
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

        # Phase 8: compras a proveedores (bills + inventario Alegra)
        try:
            from agents.contador.handlers.compras import (
                handle_registrar_compra_proveedor,
                handle_consultar_inventario_alegra,
            )
            self._handlers.update({
                "registrar_compra_proveedor": handle_registrar_compra_proveedor,
                "consultar_inventario_alegra": handle_consultar_inventario_alegra,
            })
        except ImportError:
            pass

        # Phase 9 (2026-04-27): Tools V2 vía Firecrawl Agent — reemplazo robusto
        # de los flujos rotos de scrape+interact. Diagnóstico:
        # .planning/DIAGNOSTICO_CONTADOR_FIRECRAWL.md
        try:
            from agents.contador.handlers.facturacion import (
                handle_crear_factura_venta_alegra_agente,
                handle_registrar_compra_motos_agente,
            )
            from agents.contador.handlers.compras import (
                handle_registrar_compra_repuestos_agente,
            )
            self._handlers.update({
                "crear_factura_venta_alegra_agente":   handle_crear_factura_venta_alegra_agente,
                "registrar_compra_motos_agente":        handle_registrar_compra_motos_agente,
                "registrar_compra_repuestos_agente":    handle_registrar_compra_repuestos_agente,
            })
        except ImportError as _imp_err:
            logger.error("Phase 9 V2 handlers no se pudieron importar: %s", _imp_err)

        # Sprint S3 (2026-04-28): Notificaciones internas WhatsApp al equipo
        try:
            from agents.contador.handlers.notificaciones import (
                handle_notificar_equipo,
            )
            self._handlers.update({
                "notificar_equipo": handle_notificar_equipo,
            })
        except ImportError as _imp_err:
            logger.error("Sprint S3 notificaciones handler no se pudo importar: %s", _imp_err)

    async def dispatch(self, tool_name: str, tool_input: dict, user_id: str) -> dict:
        handler = self._handlers.get(tool_name)
        if not handler:
            logger.warning("dispatch — handler no registrado: %s", tool_name)
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
            logger.warning("dispatch — permiso denegado tool=%s: %s", tool_name, e)
            return {"success": False, "error": f"Sin permiso: {str(e)}"}
        except Exception as e:
            # logger.exception captura traceback completo (P0 fix — antes solo era str(e))
            logger.exception("dispatch — excepción ejecutando tool=%s", tool_name)
            tb_str = _tb.format_exc()
            # Persistir tool.error en roddos_events para auditoría / debugging
            try:
                await publish_event(
                    db=self.db,
                    event_type="tool.error",
                    source="agente_contador",
                    datos={
                        "tool_name":  tool_name,
                        "tool_input": tool_input,
                        "exception":  f"{type(e).__name__}: {e}",
                        "traceback":  tb_str[-2000:],  # tail por si es enorme
                        "user_id":    user_id,
                    },
                    accion_ejecutada=f"FALLO {tool_name}: {type(e).__name__}",
                )
            except Exception:
                pass  # publicar evento no debe enmascarar el error original
            return {
                "success": False,
                "error": f"Error ejecutando {tool_name}: {type(e).__name__}: {str(e)}",
                "exception_type": type(e).__name__,
            }
