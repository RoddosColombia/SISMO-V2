"""
agents/contador/handlers/notificaciones.py — Handler de la tool notificar_equipo.

Sprint S3 (2026-04-28). Wraps services/mercately/internal_notifications.

Responsabilidades:
  1. Validar entrada (persona, nivel, mensaje).
  2. Llamar notificar_interno() del servicio.
  3. Publicar evento auditable (notificacion.interna.enviada o ...skip).
  4. Devolver resultado normalizado para el ToolDispatcher.

NO escribe directamente en MongoDB ni en Alegra. ROG-4 OK:
  - Solo escribe roddos_events (via publish_event)
  - El servicio escribe whatsapp_internal_audit (no es coleccion de dominio agente)
"""
from __future__ import annotations
import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from core.events import publish_event
from services.mercately.internal_notifications import notificar_interno

logger = logging.getLogger("handlers.contador.notificaciones")


async def handle_notificar_equipo(
    *,
    tool_input: dict,
    alegra: Any = None,
    db: AsyncIOMotorDatabase,
    event_bus: Any = None,
    user_id: str = "",
) -> dict:
    """Handler de la tool notificar_equipo.

    Args:
        tool_input: dict con persona, nivel, mensaje, contexto opcional.
        db:         motor DB.
        otros:      no usados (firma estandar del dispatcher).

    Returns:
        Resultado normalizado del servicio:
            {success: True, via, message_id, persona, nivel, telefono}
          | {success: False, skip: <motivo>, ...}
          | {success: False, error: <texto>}
    """
    persona = (tool_input.get("persona") or "").strip().lower()
    nivel = (tool_input.get("nivel") or "info").strip().lower()
    mensaje = (tool_input.get("mensaje") or "").strip()
    contexto = tool_input.get("contexto") or {}

    if not persona or not mensaje:
        return {
            "success": False,
            "error": "Parametros requeridos: persona, nivel, mensaje.",
        }

    # Llamar servicio (incluye anti-spam + dedupe + audit)
    res = await notificar_interno(
        db=db,
        persona=persona,
        nivel=nivel,
        mensaje=mensaje,
        contexto=contexto,
    )

    # Publicar evento auditable
    event_type = (
        "notificacion.interna.enviada" if res.get("success")
        else "notificacion.interna.skip" if res.get("skip")
        else "notificacion.interna.error"
    )

    try:
        await publish_event(
            db=db,
            event_type=event_type,
            source="contador.tool.notificar_equipo",
            datos={
                "persona":   persona,
                "nivel":     nivel,
                "mensaje":   mensaje[:200],
                "contexto":  contexto,
                "via":       res.get("via", ""),
                "message_id": res.get("message_id", ""),
                "skip":      res.get("skip", ""),
                "error":     res.get("error", ""),
                "user_id":   user_id,
            },
            alegra_id=None,
            accion_ejecutada=(
                f"notificar_equipo persona={persona} nivel={nivel} "
                f"resultado={'OK' if res.get('success') else (res.get('skip') or 'ERROR')}"
            ),
        )
    except Exception as exc:
        logger.warning("notificar_equipo: publish_event fallo (no critico): %s", exc)

    logger.info(
        "notificar_equipo persona=%s nivel=%s success=%s via=%s skip=%s",
        persona, nivel, res.get("success"), res.get("via", ""), res.get("skip", ""),
    )
    return res
