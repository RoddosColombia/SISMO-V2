"""
RadarToolDispatcher — routes tool_name del agente RADAR a su handler.

Patron identico al ToolDispatcher del Contador. ROG-4b: solo escribe
en crm_clientes (gestiones, notas) y publica eventos en roddos_events.
NO escribe en Alegra. NO escribe en loanbook.

Sprint S2 (Ejecucion 2).
"""
from __future__ import annotations
import logging
import os
import traceback as _tb
from datetime import datetime, timezone, timedelta, date

from motor.motor_asyncio import AsyncIOMotorDatabase

from core.events import publish_event
from core.datetime_utils import now_bogota, today_bogota
from core.permissions import validate_write_permission

logger = logging.getLogger("dispatcher.radar")


READ_ONLY_TOOLS = frozenset({
    "generar_cola_cobranza",
    "consultar_estado_cliente",
})


def is_read_only_tool(tool_name: str) -> bool:
    return tool_name in READ_ONLY_TOOLS


# ─────────────────────────────────────────────────────────────────────────────
# Templates Mercately T1-T5 (configurables via env vars)
# ─────────────────────────────────────────────────────────────────────────────

# T1 — recordatorio amable -2d (martes para miercoles)
# T2 — cobro hoy (miercoles)
# T3 — mora <3d (jueves)
# T4 — mora 7-15d
# T5 — ultimo aviso pre-juridico (>30d)
TEMPLATE_IDS = {
    "T1": os.getenv("MERCATELY_TEMPLATE_T1_RECORDATORIO_ID", os.getenv("MERCATELY_TEMPLATE_COBRO_ID", "")),
    "T2": os.getenv("MERCATELY_TEMPLATE_T2_COBRO_HOY_ID",   os.getenv("MERCATELY_TEMPLATE_COBRO_ID", "")),
    "T3": os.getenv("MERCATELY_TEMPLATE_T3_MORA_CORTA_ID",  os.getenv("MERCATELY_TEMPLATE_MORA_ID", "")),
    "T4": os.getenv("MERCATELY_TEMPLATE_T4_MORA_MEDIA_ID",  os.getenv("MERCATELY_TEMPLATE_MORA_ID", "")),
    "T5": os.getenv("MERCATELY_TEMPLATE_T5_ULTIMO_AVISO_ID", os.getenv("MERCATELY_TEMPLATE_MORA_ID", "")),
}


# ─────────────────────────────────────────────────────────────────────────────
# Ley 2300/2023 — max 1 contacto por dia, L-V 7AM-7PM, Sab 8AM-3PM
# ─────────────────────────────────────────────────────────────────────────────

def _within_ley_2300_window(dt: datetime) -> bool:
    """Devuelve True si dt cae dentro del horario permitido por Ley 2300."""
    weekday = dt.weekday()  # 0=Mon ... 6=Sun
    hour = dt.hour
    if weekday < 5:  # Lun-Vie
        return 7 <= hour < 19
    if weekday == 5:  # Sabado
        return 8 <= hour < 15
    return False  # Domingo prohibido


async def _was_contacted_today(db, cedula: str) -> bool:
    """Devuelve True si crm_clientes ya tiene una gestion hoy con tipo whatsapp_*."""
    today_iso = today_bogota().isoformat()
    cliente = await db.crm_clientes.find_one(
        {"cedula": cedula},
        {"gestiones": 1, "_id": 0},
    )
    if not cliente:
        return False
    gestiones = cliente.get("gestiones") or []
    for g in gestiones:
        fecha = (g.get("fecha") or "")[:10]
        tipo = g.get("tipo", "")
        if fecha == today_iso and tipo.startswith("whatsapp"):
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Score / DPD helpers
# ─────────────────────────────────────────────────────────────────────────────

def _calcular_dpd(cuotas: list[dict], hoy: date) -> int:
    """Devuelve el DPD maximo entre las cuotas no pagadas con fecha <= hoy."""
    max_dpd = 0
    for c in cuotas or []:
        if c.get("estado") == "pagada":
            continue
        fecha_str = c.get("fecha")
        if not fecha_str:
            continue
        try:
            f = date.fromisoformat(fecha_str[:10])
        except Exception:
            continue
        if f < hoy:
            d = (hoy - f).days
            if d > max_dpd:
                max_dpd = d
    return max_dpd


def _sugerir_template(dpd: int, contexto: str) -> str:
    """Decide T1-T5 segun DPD y contexto de la jornada."""
    if contexto == "martes_recordatorio":
        return "T1"
    if contexto == "miercoles":
        return "T2" if dpd <= 0 else "T3"
    if contexto == "jueves_mora":
        if dpd >= 30:
            return "T5"
        if dpd >= 7:
            return "T4"
        return "T3"
    # ad_hoc
    if dpd >= 30:
        return "T5"
    if dpd >= 7:
        return "T4"
    if dpd >= 1:
        return "T3"
    return "T1"


# ─────────────────────────────────────────────────────────────────────────────
# Dispatcher
# ─────────────────────────────────────────────────────────────────────────────

class RadarToolDispatcher:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def dispatch(self, tool_name: str, tool_input: dict, user_id: str) -> dict:
        try:
            handler = getattr(self, f"_handle_{tool_name}", None)
            if not handler:
                logger.warning("RADAR dispatch — tool no registrada: %s", tool_name)
                return {"success": False, "error": f"Tool no encontrada: {tool_name}"}
            return await handler(tool_input, user_id)
        except PermissionError as e:
            logger.warning("RADAR dispatch — permiso denegado tool=%s: %s", tool_name, e)
            return {"success": False, "error": f"Sin permiso: {str(e)}"}
        except Exception as e:
            logger.exception("RADAR dispatch — excepcion ejecutando tool=%s", tool_name)
            tb_str = _tb.format_exc()
            try:
                await publish_event(
                    db=self.db,
                    event_type="tool.error",
                    source="agente_radar",
                    datos={
                        "tool_name": tool_name, "tool_input": tool_input,
                        "exception": f"{type(e).__name__}: {e}",
                        "traceback": tb_str[-2000:], "user_id": user_id,
                    },
                    accion_ejecutada=f"FALLO RADAR {tool_name}: {type(e).__name__}",
                )
            except Exception:
                pass
            return {
                "success": False,
                "error": f"Error ejecutando {tool_name}: {type(e).__name__}: {e}",
                "exception_type": type(e).__name__,
            }

    # ── Tool 1: generar_cola_cobranza ──────────────────────────────────

    async def _handle_generar_cola_cobranza(self, tool_input: dict, user_id: str) -> dict:
        dpd_min   = int(tool_input.get("dpd_min", 0))
        limite    = int(tool_input.get("limite", 50))
        contexto  = tool_input.get("modalidad_cobro", "miercoles")
        hoy       = today_bogota()

        # Loanbooks activos (no saldados, no castigados)
        cursor = self.db.loanbook.find(
            {"estado": {"$nin": ["saldado", "castigado", "pendiente_entrega"]}}
        ).limit(limite * 3)  # over-fetch para luego filtrar

        cola = []
        async for lb in cursor:
            cuotas = lb.get("cuotas") or []
            dpd = _calcular_dpd(cuotas, hoy)
            if dpd < dpd_min:
                continue

            cliente = lb.get("cliente") or {}
            cedula = cliente.get("cedula", "")
            telefono = cliente.get("telefono", "")
            nombre = cliente.get("nombre", "")

            # Saltear contactados hoy
            if await _was_contacted_today(self.db, cedula):
                continue

            # Score del CRM
            crm = await self.db.crm_clientes.find_one(
                {"cedula": cedula}, {"score": 1, "tags": 1, "gestiones": 1, "_id": 0}
            ) or {}
            score = crm.get("score") or 0
            ultima_gestion = (crm.get("gestiones") or [])[-1:]

            # Monto mora total
            monto_mora = sum(
                (c.get("monto") or c.get("monto_total") or 0)
                for c in cuotas if c.get("estado") != "pagada"
                   and c.get("fecha") and c["fecha"][:10] < hoy.isoformat()
            )

            cola.append({
                "cedula": cedula,
                "nombre": nombre,
                "telefono": telefono,
                "vin": lb.get("vin"),
                "loanbook_id": lb.get("loanbook_id"),
                "dpd": dpd,
                "monto_mora": monto_mora,
                "score": score,
                "ultima_gestion": ultima_gestion[0] if ultima_gestion else None,
                "template_sugerido": _sugerir_template(dpd, contexto),
                "prioridad": dpd * 10 + max(0, 100 - score),  # mas alto = mas urgente
            })

        # Ordenar por prioridad descendente
        cola.sort(key=lambda x: x["prioridad"], reverse=True)
        return {
            "success": True,
            "contexto": contexto,
            "fecha": hoy.isoformat(),
            "total": len(cola),
            "cola": cola[:limite],
        }

    # ── Tool 2: registrar_gestion ──────────────────────────────────────

    async def _handle_registrar_gestion(self, tool_input: dict, user_id: str) -> dict:
        validate_write_permission("radar", "crm_clientes", "mongodb")
        cedula = tool_input["cedula"]
        tipo = tool_input["tipo"]
        resultado = tool_input["resultado"]
        observacion = (tool_input.get("observacion") or "")[:500]
        vin = tool_input.get("vin", "")

        gestion = {
            "tipo": tipo,
            "resultado": resultado,
            "observacion": observacion,
            "vin": vin,
            "fecha": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
        }
        result = await self.db.crm_clientes.update_one(
            {"cedula": cedula},
            {"$push": {"gestiones": gestion},
             "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}},
        )
        if result.matched_count == 0:
            return {"success": False, "error": f"Cliente cedula {cedula} no encontrado en CRM"}

        await publish_event(
            db=self.db, event_type="crm.gestion.creada",
            source="agente_radar",
            datos={"cedula": cedula, "tipo": tipo, "resultado": resultado, "vin": vin},
            alegra_id=None,
            accion_ejecutada=f"Gestion {tipo} a {cedula}",
        )
        return {"success": True, "message": f"Gestion {tipo} registrada para {cedula}"}

    # ── Tool 3: registrar_promesa_pago ─────────────────────────────────

    async def _handle_registrar_promesa_pago(self, tool_input: dict, user_id: str) -> dict:
        validate_write_permission("radar", "crm_clientes", "mongodb")
        cedula = tool_input["cedula"]
        fecha_pactada_str = tool_input["fecha_pactada"]
        monto = float(tool_input["monto_pactado"])
        vin = tool_input.get("vin", "")
        canal = tool_input.get("canal", "whatsapp")
        nota = tool_input.get("nota", "")

        try:
            fecha_pactada = date.fromisoformat(fecha_pactada_str)
        except Exception:
            return {"success": False, "error": f"fecha_pactada invalida: {fecha_pactada_str}"}
        if fecha_pactada < today_bogota():
            return {"success": False, "error": "fecha_pactada debe ser >= hoy"}

        ptp = {
            "fecha_pactada": fecha_pactada.isoformat(),
            "monto_pactado": monto,
            "canal": canal,
            "vin": vin,
            "nota": nota[:500],
            "fecha_creacion": datetime.now(timezone.utc).isoformat(),
            "estado": "vigente",
            "user_id": user_id,
        }
        result = await self.db.crm_clientes.update_one(
            {"cedula": cedula},
            {"$push": {"promesas_pago": ptp},
             "$addToSet": {"tags": "ptp_vigente"}},
        )
        if result.matched_count == 0:
            return {"success": False, "error": f"Cliente cedula {cedula} no encontrado"}

        await publish_event(
            db=self.db, event_type="crm.ptp.creada",
            source="agente_radar",
            datos={"cedula": cedula, "fecha_pactada": fecha_pactada.isoformat(),
                   "monto_pactado": monto, "vin": vin},
            alegra_id=None,
            accion_ejecutada=f"PTP {cedula} ${monto:,.0f} para {fecha_pactada.isoformat()}",
        )
        return {
            "success": True,
            "message": f"PTP registrada: ${monto:,.0f} para {fecha_pactada.isoformat()}"
        }

    # ── Tool 4: enviar_whatsapp_template ───────────────────────────────

    async def _handle_enviar_whatsapp_template(self, tool_input: dict, user_id: str) -> dict:
        cedula = tool_input["cedula"]
        template = tool_input["template"].upper()
        vin = tool_input.get("vin", "")
        params_extra = tool_input.get("params_extra") or {}

        if template not in TEMPLATE_IDS:
            return {"success": False, "error": f"Template {template} invalido. Use T1-T5"}
        template_id = TEMPLATE_IDS[template]
        if not template_id:
            return {"success": False, "error": f"Template {template} no configurado en env vars MERCATELY_TEMPLATE_*"}

        # Ley 2300: ventana horaria
        ahora = now_bogota()
        if not _within_ley_2300_window(ahora):
            return {"success": False, "error": f"Fuera de ventana Ley 2300 (ahora: {ahora.strftime('%a %H:%M')}). L-V 7AM-7PM, Sab 8AM-3PM."}

        # Ley 2300: max 1 contacto/dia
        if await _was_contacted_today(self.db, cedula):
            return {"success": False, "error": f"Cliente {cedula} ya fue contactado hoy (Ley 2300)"}

        # Lookup cliente CRM
        cliente = await self.db.crm_clientes.find_one({"cedula": cedula})
        if not cliente:
            return {"success": False, "error": f"Cliente cedula {cedula} no en CRM"}
        telefono = cliente.get("mercately_phone") or cliente.get("telefono", "")
        if not telefono:
            return {"success": False, "error": f"Cliente {cedula} sin telefono"}

        # Resolver datos del loanbook si viene VIN
        nombre_corto = (cliente.get("nombre") or "").split(" ")[0] or "Cliente"
        monto_str = ""
        fecha_str = ""
        if vin:
            lb = await self.db.loanbook.find_one({"vin": vin})
            if lb:
                cuotas = lb.get("cuotas") or []
                hoy = today_bogota()
                # primera cuota pendiente
                pendiente = next(
                    (c for c in cuotas if c.get("estado") != "pagada" and c.get("fecha")),
                    None,
                )
                if pendiente:
                    monto_str = f"${(pendiente.get('monto') or pendiente.get('monto_total') or 0):,.0f}"
                    fecha_str = pendiente.get("fecha", "")[:10]

        # Params del template (los 3 estandares para todos los T1-T5)
        params = [
            params_extra.get("nombre", nombre_corto),
            params_extra.get("monto", monto_str or "$0"),
            params_extra.get("fecha", fecha_str or hoy.isoformat() if 'hoy' in dir() else today_bogota().isoformat()),
        ]

        from services.mercately.client import get_mercately_client
        client = get_mercately_client()
        result = await client.send_template(
            phone_number=telefono,
            template_id=template_id,
            template_params=params,
        )

        # Audit en radar_alertas (mantenemos la coleccion existente)
        await self.db.radar_alertas.insert_one({
            "cedula": cedula,
            "telefono": telefono,
            "template": template,
            "template_id": template_id,
            "params": params,
            "vin": vin,
            "estado": "enviado" if result.get("success") else "error",
            "raw_result": result,
            "user_id": user_id,
            "fecha": datetime.now(timezone.utc).isoformat(),
        })

        if result.get("success"):
            # Append gestion al timeline CRM
            await self.db.crm_clientes.update_one(
                {"cedula": cedula},
                {"$push": {"gestiones": {
                    "tipo": f"whatsapp_{template.lower()}",
                    "fecha": datetime.now(timezone.utc).isoformat(),
                    "resultado": "enviado",
                    "template": template,
                    "vin": vin,
                    "user_id": user_id,
                }}},
            )
            return {"success": True, "template": template, "message_id": result.get("message_id"),
                    "message": f"WhatsApp {template} enviado a {cedula}"}
        return {"success": False, "error": result.get("error", "Mercately fallo"), "raw": result.get("raw")}

    # ── Tool 5: consultar_estado_cliente ───────────────────────────────

    async def _handle_consultar_estado_cliente(self, tool_input: dict, user_id: str) -> dict:
        cedula = tool_input["cedula"]
        vin_filter = tool_input.get("vin")

        cliente = await self.db.crm_clientes.find_one({"cedula": cedula})
        if not cliente:
            return {"success": False, "error": f"Cliente {cedula} no encontrado en CRM"}

        # Loanbooks del cliente
        query = {"cliente.cedula": cedula}
        if vin_filter:
            query["vin"] = vin_filter
        lbs = []
        cursor = self.db.loanbook.find(query)
        hoy = today_bogota()
        async for lb in cursor:
            cuotas = lb.get("cuotas") or []
            dpd = _calcular_dpd(cuotas, hoy)
            cuotas_pagadas = sum(1 for c in cuotas if c.get("estado") == "pagada")
            monto_mora = sum(
                (c.get("monto") or c.get("monto_total") or 0)
                for c in cuotas if c.get("estado") != "pagada"
                   and c.get("fecha") and c["fecha"][:10] < hoy.isoformat()
            )
            lbs.append({
                "loanbook_id": lb.get("loanbook_id"),
                "vin": lb.get("vin"),
                "modelo": lb.get("modelo"),
                "modalidad": lb.get("modalidad"),
                "estado": lb.get("estado"),
                "dpd": dpd,
                "cuotas_pagadas": cuotas_pagadas,
                "num_cuotas": lb.get("num_cuotas", len(cuotas)),
                "monto_mora": monto_mora,
            })

        # Limpiar _id de cliente
        cliente.pop("_id", None)
        # Limitar gestiones a las ultimas 10
        gestiones = cliente.get("gestiones") or []
        cliente["gestiones"] = gestiones[-10:]
        # Promesas vigentes
        promesas = cliente.get("promesas_pago") or []
        promesas_vigentes = [p for p in promesas if p.get("estado") == "vigente"]

        return {
            "success": True,
            "cliente": cliente,
            "loanbooks": lbs,
            "promesas_vigentes": promesas_vigentes,
            "ultima_gestion": gestiones[-1] if gestiones else None,
            "contactado_hoy": await _was_contacted_today(self.db, cedula),
        }
