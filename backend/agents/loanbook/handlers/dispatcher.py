"""
LoanToolDispatcher — routes tool_name to handler functions for the Loanbook agent.

CRITICAL: Tool names here MUST match the "name" field in agents/loanbook/tools.py exactly.

Read-only tools execute immediately without ExecutionCard confirmation.
Write tools require user confirmation via ExecutionCard SSE event.
"""
import logging
import uuid
from datetime import date, datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.loanbook_model import (
    crear_loanbook,
    is_valid_transition,
    aplicar_waterfall,
    calcular_dpd,
    estado_from_dpd,
    calcular_mora,
    calcular_cronograma,
    asignar_cronograma,
    MORA_TASA_DIARIA,
)

logger = logging.getLogger("agent.loanbook")

# Read-only tools — execute immediately, no ExecutionCard
READ_ONLY_TOOLS = frozenset({
    "consultar_loanbook",
    "listar_loanbooks",
    "consultar_mora",
    "calcular_liquidacion",
    "consultar_inventario",
    "consultar_cliente",
    "resumen_cartera",
})


def is_read_only_tool(tool_name: str) -> bool:
    return tool_name in READ_ONLY_TOOLS


def _clean_doc(doc: dict) -> dict:
    """Remove MongoDB _id for JSON serialization."""
    if doc:
        doc.pop("_id", None)
    return doc


class LoanToolDispatcher:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self._handlers: dict = {}
        self._build_handlers()

    def _build_handlers(self):
        """Register all 11 tool handlers. Keys MUST match tools.py 'name' fields."""
        self._handlers = {
            # Read-only (7)
            "consultar_loanbook": self._handle_consultar_loanbook,
            "listar_loanbooks": self._handle_listar_loanbooks,
            "consultar_mora": self._handle_consultar_mora,
            "calcular_liquidacion": self._handle_calcular_liquidacion,
            "consultar_inventario": self._handle_consultar_inventario,
            "consultar_cliente": self._handle_consultar_cliente,
            "resumen_cartera": self._handle_resumen_cartera,
            # Write (4)
            "registrar_apartado": self._handle_registrar_apartado,
            "registrar_pago_parcial": self._handle_registrar_pago_parcial,
            "registrar_entrega": self._handle_registrar_entrega,
            "registrar_pago_cuota": self._handle_registrar_pago_cuota,
        }

    async def dispatch(self, tool_name: str, tool_input: dict, user_id: str) -> dict:
        handler = self._handlers.get(tool_name)
        if not handler:
            return {"success": False, "error": f"Handler no encontrado: {tool_name}"}

        try:
            return await handler(tool_input, user_id)
        except Exception as e:
            return {"success": False, "error": f"Error ejecutando {tool_name}: {str(e)}"}

    # ═══════════════════════════════════════════
    # Tool 1: consultar_loanbook
    # ═══════════════════════════════════════════

    async def _handle_consultar_loanbook(self, tool_input: dict, user_id: str) -> dict:
        """Search by VIN first, then by client name."""
        busqueda = tool_input["busqueda"]

        # Try exact VIN match first
        lb = await self.db.loanbook.find_one({"vin": busqueda})
        if lb:
            _clean_doc(lb)
            today = date.today()
            cuotas = lb.get("cuotas", [])
            lb["dpd"] = calcular_dpd(cuotas, today)
            lb["cuotas_pagadas"] = sum(1 for c in cuotas if c.get("estado") == "pagada")
            return {"success": True, "loanbook": lb}

        # Try client name search (case-insensitive partial)
        cursor = self.db.loanbook.find(
            {"cliente.nombre": {"$regex": busqueda, "$options": "i"}}
        )
        results = await cursor.to_list(length=20)
        if results:
            for r in results:
                _clean_doc(r)
            return {"success": True, "loanbooks": results, "count": len(results)}

        return {"success": False, "error": f"No se encontro loanbook para '{busqueda}'."}

    # ═══════════════════════════════════════════
    # Tool 2: listar_loanbooks
    # ═══════════════════════════════════════════

    async def _handle_listar_loanbooks(self, tool_input: dict, user_id: str) -> dict:
        """List all loanbooks, optionally filtered by estado."""
        filtro = {}
        estado = tool_input.get("estado")
        if estado:
            filtro["estado"] = estado

        cursor = self.db.loanbook.find(filtro).sort("fecha_creacion", -1)
        items = await cursor.to_list(length=500)
        today = date.today()

        result = []
        for lb in items:
            _clean_doc(lb)
            cuotas = lb.get("cuotas", [])
            lb["dpd"] = calcular_dpd(cuotas, today)
            lb["cuotas_pagadas"] = sum(1 for c in cuotas if c.get("estado") == "pagada")
            lb.pop("cuotas", None)  # Strip full cuotas from list view
            result.append(lb)

        return {"success": True, "loanbooks": result, "count": len(result)}

    # ═══════════════════════════════════════════
    # Tool 3: registrar_apartado
    # ═══════════════════════════════════════════

    async def _handle_registrar_apartado(self, tool_input: dict, user_id: str) -> dict:
        """Create apartado + loanbook, mark moto as apartada."""
        vin = tool_input["vin"]
        cliente = tool_input["cliente"]
        plan_codigo = tool_input["plan_codigo"]
        modelo = tool_input["modelo"]
        modalidad = tool_input["modalidad"]
        fecha_entrega = date.fromisoformat(tool_input["fecha_entrega"])
        fecha_primer_pago_str = tool_input.get("fecha_primer_pago")
        fecha_primer_pago = date.fromisoformat(fecha_primer_pago_str) if fecha_primer_pago_str else None

        # Verify moto exists and is disponible
        moto = await self.db.inventario_motos.find_one({"vin": vin})
        if not moto:
            return {"success": False, "error": f"Moto VIN {vin} no encontrada en inventario."}
        if moto.get("estado") != "disponible":
            return {
                "success": False,
                "error": f"Moto VIN {vin} no esta disponible (estado actual: {moto.get('estado')}).",
            }

        # Fetch plan
        plan = await self.db.catalogo_planes.find_one({"codigo": plan_codigo})
        if not plan:
            return {"success": False, "error": f"Plan '{plan_codigo}' no encontrado en catalogo."}

        # Create loanbook via domain logic
        try:
            lb = crear_loanbook(
                vin=vin,
                cliente=cliente,
                plan=plan,
                modelo=modelo,
                modalidad=modalidad,
                fecha_entrega=fecha_entrega,
                fecha_primer_pago=fecha_primer_pago,
            )
        except ValueError as e:
            return {"success": False, "error": str(e)}

        # Persist loanbook
        await self.db.loanbook.insert_one(lb)

        # Mark moto as apartada
        await self.db.inventario_motos.update_one(
            {"vin": vin},
            {"$set": {"estado": "apartada"}},
        )

        # Publish event
        await self.db.roddos_events.insert_one({
            "event_id": str(uuid.uuid4()),
            "event_type": "apartado.completo",
            "source": "agent.loanbook",
            "correlation_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "datos": {
                "loanbook_id": lb["loanbook_id"],
                "vin": vin,
                "cliente": cliente,
                "plan_codigo": plan_codigo,
                "modelo": modelo,
                "modalidad": modalidad,
            },
            "alegra_id": None,
            "accion_ejecutada": f"Apartado VIN {vin} para {cliente.get('nombre', '')}",
        })

        logger.info(f"Apartado creado: VIN {vin}, plan {plan_codigo}, modalidad {modalidad}")
        return {
            "success": True,
            "loanbook_id": lb["loanbook_id"],
            "vin": vin,
            "cuota_monto": lb["cuota_monto"],
            "num_cuotas": lb["num_cuotas"],
            "mensaje": f"Moto {vin} apartada para {cliente.get('nombre', '')}. Loanbook creado.",
        }

    # ═══════════════════════════════════════════
    # Tool 4: registrar_pago_parcial
    # ═══════════════════════════════════════════

    async def _handle_registrar_pago_parcial(self, tool_input: dict, user_id: str) -> dict:
        """Add partial payment to apartado."""
        vin = tool_input["vin"]
        monto = tool_input["monto"]
        referencia = tool_input["referencia"]

        apartado = await self.db.apartados.find_one({"vin": vin})
        if not apartado:
            return {"success": False, "error": f"No existe apartado para VIN {vin}."}

        pago = {
            "monto": monto,
            "referencia": referencia,
            "fecha": date.today().isoformat(),
        }

        await self.db.apartados.update_one(
            {"vin": vin},
            {
                "$push": {"pagos": pago},
                "$inc": {"total_pagado": monto},
            },
        )

        nuevo_total = apartado.get("total_pagado", 0) + monto
        logger.info(f"Pago parcial ${monto:,.0f} para apartado VIN {vin}. Total: ${nuevo_total:,.0f}")
        return {
            "success": True,
            "vin": vin,
            "pago": monto,
            "total_pagado": nuevo_total,
            "mensaje": f"Pago de ${monto:,.0f} registrado. Total pagado: ${nuevo_total:,.0f}.",
        }

    # ═══════════════════════════════════════════
    # Tool 5: registrar_entrega
    # ═══════════════════════════════════════════

    async def _handle_registrar_entrega(self, tool_input: dict, user_id: str) -> dict:
        """Activate loanbook with cronograma on delivery."""
        vin = tool_input["vin"]
        fecha_entrega = date.fromisoformat(tool_input["fecha_entrega"])
        fecha_primer_pago_str = tool_input.get("fecha_primer_pago")
        fecha_primer_pago = date.fromisoformat(fecha_primer_pago_str) if fecha_primer_pago_str else None

        lb = await self.db.loanbook.find_one({"vin": vin})
        if not lb:
            return {"success": False, "error": f"No existe loanbook para VIN {vin}."}

        if lb["estado"] != "pendiente_entrega":
            return {
                "success": False,
                "error": f"Loanbook VIN {vin} no esta en pendiente_entrega (estado: {lb['estado']}).",
            }

        modalidad = lb["modalidad"]
        num_cuotas = lb["num_cuotas"]
        # Use provided fecha_primer_pago or the one from loanbook creation
        if not fecha_primer_pago:
            fpp_str = lb.get("fecha_primer_pago")
            fecha_primer_pago = date.fromisoformat(fpp_str) if fpp_str else None

        try:
            cronograma = calcular_cronograma(
                fecha_entrega=fecha_entrega,
                modalidad=modalidad,
                num_cuotas=num_cuotas,
                fecha_primer_pago=fecha_primer_pago,
            )
            resultado = asignar_cronograma(lb["cuotas"], cronograma)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        now = datetime.now(timezone.utc).isoformat()

        # Update loanbook
        await self.db.loanbook.update_one(
            {"vin": vin},
            {"$set": {
                "estado": "activo",
                "fecha_entrega": fecha_entrega.isoformat(),
                "fecha_activacion": now,
                "cuotas": resultado["cuotas"],
                "fecha_primera_cuota": resultado["fecha_primera_cuota"],
                "fecha_ultima_cuota": resultado["fecha_ultima_cuota"],
            }},
        )

        # Mark moto as vendida
        await self.db.inventario_motos.update_one(
            {"vin": vin},
            {"$set": {"estado": "vendida", "fecha_venta": now}},
        )

        # Publish event
        await self.db.roddos_events.insert_one({
            "event_id": str(uuid.uuid4()),
            "event_type": "entrega.realizada",
            "source": "agent.loanbook",
            "correlation_id": str(uuid.uuid4()),
            "timestamp": now,
            "datos": {
                "vin": vin,
                "fecha_entrega": fecha_entrega.isoformat(),
                "primera_cuota": resultado["fecha_primera_cuota"],
                "ultima_cuota": resultado["fecha_ultima_cuota"],
            },
            "alegra_id": None,
            "accion_ejecutada": f"Entrega VIN {vin} — cronograma {resultado['fecha_primera_cuota']} a {resultado['fecha_ultima_cuota']}",
        })

        logger.info(f"Entrega registrada: VIN {vin}, cronograma generado")
        return {
            "success": True,
            "vin": vin,
            "fecha_primera_cuota": resultado["fecha_primera_cuota"],
            "fecha_ultima_cuota": resultado["fecha_ultima_cuota"],
            "mensaje": f"Moto {vin} entregada. Credito activo. Primera cuota: {resultado['fecha_primera_cuota']}.",
        }

    # ═══════════════════════════════════════════
    # Tool 6: registrar_pago_cuota
    # ═══════════════════════════════════════════

    async def _handle_registrar_pago_cuota(self, tool_input: dict, user_id: str) -> dict:
        """Apply waterfall payment, publish cuota.pagada event."""
        vin = tool_input["vin"]
        monto_pago = tool_input["monto"]
        fecha_pago = date.fromisoformat(tool_input["fecha_pago"])

        lb = await self.db.loanbook.find_one({"vin": vin})
        if not lb:
            return {"success": False, "error": f"No existe loanbook para VIN {vin}."}

        cuotas = lb["cuotas"]
        anzi_pct = lb.get("anzi_pct", 0.02)

        # Calculate mora for overdue unpaid cuotas
        mora_pendiente = 0
        for cuota in cuotas:
            if cuota["estado"] == "pagada":
                continue
            if cuota.get("fecha"):
                fecha_cuota = date.fromisoformat(cuota["fecha"])
                mora = calcular_mora(fecha_cuota, fecha_pago)
                cuota["mora_acumulada"] = mora
                mora_pendiente += mora

        # Identify vencidas
        cuotas_vencidas_total = 0
        for cuota in cuotas:
            if cuota["estado"] == "pagada":
                continue
            if cuota.get("fecha"):
                fecha_cuota = date.fromisoformat(cuota["fecha"])
                if fecha_cuota < fecha_pago:
                    cuotas_vencidas_total += cuota["monto"]

        # Current cuota
        cuota_corriente_monto = 0
        for cuota in cuotas:
            if cuota["estado"] != "pagada":
                if cuota.get("fecha"):
                    fecha_cuota = date.fromisoformat(cuota["fecha"])
                    if fecha_cuota >= fecha_pago:
                        cuota_corriente_monto = cuota["monto"]
                        break

        saldo_capital = lb["saldo_capital"]

        # Apply waterfall
        allocation = aplicar_waterfall(
            monto_pago=monto_pago,
            anzi_pct=anzi_pct,
            mora_pendiente=mora_pendiente,
            cuotas_vencidas_total=cuotas_vencidas_total,
            cuota_corriente=cuota_corriente_monto,
            saldo_capital=saldo_capital,
        )

        # Mark cuotas as paid
        remaining_for_vencidas = allocation["vencidas"]
        remaining_for_corriente = allocation["corriente"]
        fecha_pago_str = fecha_pago.isoformat()

        for cuota in cuotas:
            if cuota["estado"] == "pagada":
                continue
            if cuota.get("fecha"):
                fecha_cuota = date.fromisoformat(cuota["fecha"])
                if fecha_cuota < fecha_pago and remaining_for_vencidas >= cuota["monto"]:
                    cuota["estado"] = "pagada"
                    cuota["fecha_pago"] = fecha_pago_str
                    cuota["mora_acumulada"] = 0
                    remaining_for_vencidas -= cuota["monto"]
                    continue
                if fecha_cuota >= fecha_pago and remaining_for_corriente >= cuota["monto"]:
                    cuota["estado"] = "pagada"
                    cuota["fecha_pago"] = fecha_pago_str
                    cuota["mora_acumulada"] = 0
                    remaining_for_corriente -= cuota["monto"]
                    break

        # Update totals
        new_saldo = saldo_capital - allocation["corriente"] - allocation["vencidas"] - allocation["capital"]
        new_total_pagado = lb["total_pagado"] + monto_pago
        dpd = calcular_dpd(cuotas, fecha_pago)
        new_estado = estado_from_dpd(dpd)

        # Persist
        await self.db.loanbook.update_one(
            {"vin": vin},
            {"$set": {
                "cuotas": cuotas,
                "saldo_capital": max(new_saldo, 0),
                "total_pagado": new_total_pagado,
                "total_mora_pagada": lb["total_mora_pagada"] + allocation["mora"],
                "total_anzi_pagado": lb["total_anzi_pagado"] + allocation["anzi"],
                "estado": new_estado,
            }},
        )

        # Identify which cuota number was paid (first pagada with this fecha_pago)
        cuota_numero = None
        for c in cuotas:
            if c.get("fecha_pago") == fecha_pago_str and c["estado"] == "pagada":
                cuota_numero = c["numero"]
                break

        # Publish cuota.pagada event — enriched payload for contabilidad handler
        banco_recibo = tool_input.get("banco", "5314")  # default Bancolombia 2029
        await self.db.roddos_events.insert_one({
            "event_id": str(uuid.uuid4()),
            "event_type": "cuota.pagada",
            "source": "agent.loanbook",
            "correlation_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "datos": {
                "loanbook_id": lb.get("loanbook_id", ""),
                "vin": vin,
                "cliente_nombre": lb.get("cliente", {}).get("nombre", ""),
                "cliente_cedula": lb.get("cliente", {}).get("cedula", ""),
                "cuota_numero": cuota_numero,
                "monto_total_pagado": monto_pago,
                "desglose": {
                    "cuota_corriente": allocation["corriente"],
                    "vencidas": allocation["vencidas"],
                    "anzi": allocation["anzi"],
                    "mora": allocation["mora"],
                    "capital_extra": allocation["capital"],
                },
                "banco_recibo": banco_recibo,
                "fecha_pago": fecha_pago_str,
                "modelo_moto": lb.get("modelo", ""),
                "plan_codigo": lb.get("plan_codigo", ""),
                "modalidad": lb.get("modalidad", ""),
                "nuevo_estado": new_estado,
                "dpd": dpd,
            },
            "alegra_id": None,
            "accion_ejecutada": f"Pago ${monto_pago:,.0f} en VIN {vin}",
        })

        # If all cuotas are paid → publish loanbook.saldado
        cuotas_pendientes = sum(1 for c in cuotas if c["estado"] != "pagada")
        if cuotas_pendientes == 0 and max(new_saldo, 0) == 0:
            await self.db.roddos_events.insert_one({
                "event_id": str(uuid.uuid4()),
                "event_type": "loanbook.saldado",
                "source": "agent.loanbook",
                "correlation_id": str(uuid.uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "datos": {
                    "loanbook_id": lb.get("loanbook_id", ""),
                    "vin": vin,
                    "cliente_nombre": lb.get("cliente", {}).get("nombre", ""),
                    "cliente_cedula": lb.get("cliente", {}).get("cedula", ""),
                },
                "alegra_id": None,
                "accion_ejecutada": f"Credito saldado VIN {vin}",
            })
            # Update loanbook state to saldado
            await self.db.loanbook.update_one(
                {"vin": vin},
                {"$set": {"estado": "saldado"}},
            )

        logger.info(f"Pago cuota ${monto_pago:,.0f} VIN {vin}: {allocation}")
        return {
            "success": True,
            "vin": vin,
            "waterfall": allocation,
            "nuevo_estado": new_estado,
            "dpd": dpd,
            "saldo_capital": max(new_saldo, 0),
            "mensaje": f"Pago ${monto_pago:,.0f} aplicado. Estado: {new_estado}.",
        }

    # ═══════════════════════════════════════════
    # Tool 7: consultar_mora
    # ═══════════════════════════════════════════

    async def _handle_consultar_mora(self, tool_input: dict, user_id: str) -> dict:
        """Mora summary for one VIN or entire portfolio."""
        vin = tool_input.get("vin")
        today = date.today()

        if vin:
            lb = await self.db.loanbook.find_one({"vin": vin})
            if not lb:
                return {"success": False, "error": f"No existe loanbook para VIN {vin}."}
            _clean_doc(lb)
            cuotas = lb.get("cuotas", [])
            dpd = calcular_dpd(cuotas, today)
            mora_total = sum(
                calcular_mora(date.fromisoformat(c["fecha"]), today)
                for c in cuotas
                if c["estado"] != "pagada" and c.get("fecha")
            )
            cuotas_vencidas = sum(
                1 for c in cuotas
                if c["estado"] != "pagada" and c.get("fecha")
                and date.fromisoformat(c["fecha"]) < today
            )
            return {
                "success": True,
                "vin": vin,
                "dpd": dpd,
                "mora_total": mora_total,
                "cuotas_vencidas": cuotas_vencidas,
                "estado": estado_from_dpd(dpd),
            }

        # All portfolio
        cursor = self.db.loanbook.find({"estado": {"$nin": ["saldado", "castigado", "pendiente_entrega"]}})
        all_lbs = await cursor.to_list(length=1000)
        en_mora = []
        for lb in all_lbs:
            _clean_doc(lb)
            cuotas = lb.get("cuotas", [])
            dpd = calcular_dpd(cuotas, today)
            if dpd > 0:
                en_mora.append({
                    "vin": lb["vin"],
                    "cliente": lb.get("cliente", {}).get("nombre", ""),
                    "dpd": dpd,
                    "estado": estado_from_dpd(dpd),
                })

        en_mora.sort(key=lambda x: x["dpd"], reverse=True)
        return {
            "success": True,
            "total_en_mora": len(en_mora),
            "creditos_en_mora": en_mora,
        }

    # ═══════════════════════════════════════════
    # Tool 8: calcular_liquidacion
    # ═══════════════════════════════════════════

    async def _handle_calcular_liquidacion(self, tool_input: dict, user_id: str) -> dict:
        """Calculate payoff amount for today."""
        vin = tool_input["vin"]
        today = date.today()

        lb = await self.db.loanbook.find_one({"vin": vin})
        if not lb:
            return {"success": False, "error": f"No existe loanbook para VIN {vin}."}

        _clean_doc(lb)
        cuotas = lb.get("cuotas", [])
        saldo_capital = lb.get("saldo_capital", 0)

        # Calculate total mora
        mora_acumulada = sum(
            calcular_mora(date.fromisoformat(c["fecha"]), today)
            for c in cuotas
            if c["estado"] != "pagada" and c.get("fecha")
        )

        total_liquidacion = saldo_capital + mora_acumulada

        return {
            "success": True,
            "vin": vin,
            "saldo_capital": saldo_capital,
            "mora_acumulada": mora_acumulada,
            "total_liquidacion": total_liquidacion,
            "fecha_calculo": today.isoformat(),
            "mensaje": f"Para liquidar VIN {vin} hoy: ${total_liquidacion:,.0f} (capital ${saldo_capital:,.0f} + mora ${mora_acumulada:,.0f}).",
        }

    # ═══════════════════════════════════════════
    # Tool 9: consultar_inventario
    # ═══════════════════════════════════════════

    async def _handle_consultar_inventario(self, tool_input: dict, user_id: str) -> dict:
        """List available motos, optionally filtered by modelo."""
        filtro = {"estado": "disponible"}
        modelo = tool_input.get("modelo")
        if modelo:
            filtro["modelo"] = modelo

        cursor = self.db.inventario_motos.find(filtro)
        motos = await cursor.to_list(length=200)
        for m in motos:
            _clean_doc(m)

        return {
            "success": True,
            "motos": motos,
            "count": len(motos),
        }

    # ═══════════════════════════════════════════
    # Tool 10: consultar_cliente
    # ═══════════════════════════════════════════

    async def _handle_consultar_cliente(self, tool_input: dict, user_id: str) -> dict:
        """CRM lookup by cedula or name."""
        busqueda = tool_input["busqueda"]

        # Try exact cedula match first
        cliente = await self.db.crm_clientes.find_one({"cedula": busqueda})
        if cliente:
            _clean_doc(cliente)
            return {"success": True, "cliente": cliente}

        # Try name search
        cursor = self.db.crm_clientes.find(
            {"nombre": {"$regex": busqueda, "$options": "i"}}
        )
        results = await cursor.to_list(length=20)
        if results:
            for r in results:
                _clean_doc(r)
            return {"success": True, "clientes": results, "count": len(results)}

        return {"success": False, "error": f"Cliente '{busqueda}' no encontrado."}

    # ═══════════════════════════════════════════
    # Tool 11: resumen_cartera
    # ═══════════════════════════════════════════

    async def _handle_resumen_cartera(self, tool_input: dict, user_id: str) -> dict:
        """Executive portfolio summary."""
        today = date.today()

        cursor = self.db.loanbook.find({})
        all_lbs = await cursor.to_list(length=1000)

        total = len(all_lbs)
        activos = 0
        cartera_total = 0
        en_mora = 0
        por_estado = {}

        for lb in all_lbs:
            estado = lb.get("estado", "")
            por_estado[estado] = por_estado.get(estado, 0) + 1

            if estado not in ("saldado", "castigado", "pendiente_entrega"):
                activos += 1
                cartera_total += lb.get("saldo_capital", 0)

                cuotas = lb.get("cuotas", [])
                dpd = calcular_dpd(cuotas, today)
                if dpd > 0:
                    en_mora += 1

        return {
            "success": True,
            "total_creditos": total,
            "activos": activos,
            "cartera_total": round(cartera_total),
            "en_mora": en_mora,
            "por_estado": por_estado,
        }
