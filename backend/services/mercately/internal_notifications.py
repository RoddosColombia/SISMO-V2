"""
services/mercately/internal_notifications.py — Notificaciones WhatsApp internas
para el equipo RODDOS (Andres CEO, Ivan CFO/Operaciones, Fabian Contador).

Contexto:
  El Contador (y otros agentes) necesitan notificar al equipo cuando ocurren
  eventos operativos relevantes (gasto creado, factura aprobada, obligacion
  tributaria por vencer, conciliacion bancaria pendiente, etc.).

  Mercately permite mandar WhatsApp a numeros internos como cualquier cliente
  pero con consideraciones extra:
    1. Anti-spam: max 10 mensajes/dia por persona (evita ahogar al equipo).
    2. Dedupe 1h: si el mismo mensaje (hash persona+nivel+texto[:200]) ya se
       envio en la ultima hora, no lo reenvia (idempotencia ante reintentos).
    3. Niveles: info / alerta / task — el caller decide la severidad.

Resolucion de telefono:
  Por env vars (Render dashboard):
    INTERNAL_WA_ANDRES = 573001234567
    INTERNAL_WA_IVAN   = 573001234568
    INTERNAL_WA_FABIAN = 573001234569

Ventana 24h:
  WhatsApp Business obliga a usar template fuera de ventana 24h despues de la
  ultima respuesta del cliente. Para internos, asumimos que el equipo responde
  con frecuencia → intentamos send_text. Si falla por ventana, fallback a
  template MERCATELY_TEMPLATE_INTERNO_ID si esta configurado.

Audit:
  Coleccion whatsapp_internal_audit (append-only):
    {
      fecha:      datetime,
      persona:    "andres" | "ivan" | "fabian",
      nivel:      "info" | "alerta" | "task",
      mensaje:    str (max 1024),
      hash:       sha256 truncado para dedupe,
      contexto:   dict opcional (origen, alegra_id, etc.),
      enviado:    bool,
      message_id: str | "",
      via:        "send_text" | "template" | "skip" | "error",
      skip_motivo: str opcional ("max_diario", "duplicado_1h", "no_telefono")
    }

Sprint S3 (2026-04-28) — Cierra brecha #6 del informe REVISION_INTEGRAL.
"""
from __future__ import annotations
import hashlib
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Literal

from motor.motor_asyncio import AsyncIOMotorDatabase

from services.mercately.client import get_mercately_client

logger = logging.getLogger("mercately.internal")


PERSONAS = ("andres", "ivan", "fabian")
NIVELES = ("info", "alerta", "task")

MAX_POR_DIA_PERSONA = int(os.getenv("INTERNAL_WA_MAX_DIARIO", "10"))
DEDUPE_VENTANA_MIN = int(os.getenv("INTERNAL_WA_DEDUPE_MIN", "60"))


def _resolver_telefono(persona: str) -> str:
    """Devuelve telefono normalizado (12 digitos) desde env, o '' si no esta."""
    key = f"INTERNAL_WA_{persona.upper()}"
    raw = os.getenv(key, "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 10 and digits.startswith("3"):
        digits = "57" + digits
    if len(digits) == 12 and digits.startswith("57"):
        return digits
    return ""


def _hash_mensaje(persona: str, nivel: str, mensaje: str) -> str:
    """Hash sha256 truncado para dedupe (persona + nivel + primeros 200 chars)."""
    base = f"{persona}|{nivel}|{mensaje[:200]}".encode("utf-8")
    return hashlib.sha256(base).hexdigest()[:24]


def _formatear_mensaje(nivel: str, mensaje: str, contexto: dict | None) -> str:
    """Formato consistente con prefijo de nivel y contexto opcional."""
    prefijos = {
        "info":   "[INFO]",
        "alerta": "[ALERTA]",
        "task":   "[TAREA]",
    }
    prefijo = prefijos.get(nivel, "[INFO]")
    txt = f"{prefijo} {mensaje}"
    if contexto:
        # Aplanar contexto a "k1=v1, k2=v2"
        ctx_str = ", ".join(f"{k}={v}" for k, v in contexto.items() if v not in (None, ""))
        if ctx_str:
            txt += f"\n\n_{ctx_str}_"
    # WhatsApp text limit ~1024 chars, dejamos margen
    return txt[:1000]


async def _contador_envios_hoy(
    db: AsyncIOMotorDatabase, persona: str,
) -> int:
    """Cuenta envios exitosos hoy a esa persona (zona Bogota implicita por UTC -5)."""
    inicio_hoy = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    return await db.whatsapp_internal_audit.count_documents({
        "persona": persona,
        "enviado": True,
        "fecha":   {"$gte": inicio_hoy},
    })


async def _es_duplicado_reciente(
    db: AsyncIOMotorDatabase, hash_msg: str,
) -> bool:
    """True si existe un envio identico en los ultimos DEDUPE_VENTANA_MIN minutos."""
    desde = datetime.now(timezone.utc) - timedelta(minutes=DEDUPE_VENTANA_MIN)
    existe = await db.whatsapp_internal_audit.find_one({
        "hash":  hash_msg,
        "fecha": {"$gte": desde},
        "enviado": True,
    })
    return existe is not None


async def _audit(
    db: AsyncIOMotorDatabase, persona: str, nivel: str, mensaje: str,
    hash_msg: str, contexto: dict | None, enviado: bool, message_id: str,
    via: str, skip_motivo: str = "", error: str = "",
) -> None:
    """Append a whatsapp_internal_audit (append-only)."""
    await db.whatsapp_internal_audit.insert_one({
        "fecha":       datetime.now(timezone.utc),
        "persona":     persona,
        "nivel":       nivel,
        "mensaje":     mensaje[:1024],
        "hash":        hash_msg,
        "contexto":    contexto or {},
        "enviado":     enviado,
        "message_id":  message_id,
        "via":         via,
        "skip_motivo": skip_motivo,
        "error":       error,
    })


async def notificar_interno(
    db: AsyncIOMotorDatabase,
    persona: Literal["andres", "ivan", "fabian"],
    nivel: Literal["info", "alerta", "task"],
    mensaje: str,
    *,
    contexto: dict | None = None,
) -> dict:
    """Envia WhatsApp interno via Mercately con anti-spam y dedupe.

    Args:
        db:       motor DB
        persona:  destinatario (andres, ivan, fabian)
        nivel:    info / alerta / task — afecta solo el prefijo del mensaje
        mensaje:  texto del mensaje (max 1000 chars utiles)
        contexto: dict opcional para enriquecer audit (origen, alegra_id, etc.)

    Returns (todos los caminos auditados):
        {"success": True, "via": "send_text"|"template", "message_id": "...",
         "persona": ..., "nivel": ..., "telefono": "573..."}
        {"success": False, "skip": "max_diario_alcanzado"|"duplicado_1h"|"no_telefono"}
        {"success": False, "error": "..."}
    """
    persona = (persona or "").lower().strip()
    nivel = (nivel or "info").lower().strip()
    mensaje = (mensaje or "").strip()

    if persona not in PERSONAS:
        return {"success": False, "error": f"persona invalida: {persona}. Validas: {PERSONAS}"}
    if nivel not in NIVELES:
        return {"success": False, "error": f"nivel invalido: {nivel}. Validos: {NIVELES}"}
    if not mensaje:
        return {"success": False, "error": "mensaje vacio"}

    telefono = _resolver_telefono(persona)
    if not telefono:
        await _audit(db, persona, nivel, mensaje, "", contexto, False, "",
                     "skip", skip_motivo="no_telefono")
        return {"success": False, "skip": "no_telefono",
                "hint": f"Configurar env var INTERNAL_WA_{persona.upper()}=57..."}

    hash_msg = _hash_mensaje(persona, nivel, mensaje)
    texto_final = _formatear_mensaje(nivel, mensaje, contexto)

    # 1. Anti-spam diario
    enviados_hoy = await _contador_envios_hoy(db, persona)
    if enviados_hoy >= MAX_POR_DIA_PERSONA:
        await _audit(db, persona, nivel, mensaje, hash_msg, contexto, False, "",
                     "skip", skip_motivo="max_diario_alcanzado")
        logger.warning(
            "notificar_interno skip — persona=%s ya recibio %d/%d hoy",
            persona, enviados_hoy, MAX_POR_DIA_PERSONA,
        )
        return {"success": False, "skip": "max_diario_alcanzado",
                "enviados_hoy": enviados_hoy, "max": MAX_POR_DIA_PERSONA}

    # 2. Dedupe 1h
    if await _es_duplicado_reciente(db, hash_msg):
        await _audit(db, persona, nivel, mensaje, hash_msg, contexto, False, "",
                     "skip", skip_motivo="duplicado_1h")
        logger.info(
            "notificar_interno skip — duplicado en ultimos %dmin persona=%s hash=%s",
            DEDUPE_VENTANA_MIN, persona, hash_msg,
        )
        return {"success": False, "skip": "duplicado_1h"}

    # 3. Enviar via Mercately send_text (texto libre, requiere ventana 24h abierta)
    client = get_mercately_client()
    res = await client.send_text(telefono, texto_final)

    if res.get("success"):
        message_id = res.get("message_id", "")
        await _audit(db, persona, nivel, mensaje, hash_msg, contexto, True,
                     message_id, "send_text")
        logger.info(
            "notificar_interno OK — persona=%s nivel=%s message_id=%s",
            persona, nivel, message_id,
        )
        return {
            "success":    True,
            "via":        "send_text",
            "message_id": message_id,
            "persona":    persona,
            "nivel":      nivel,
            "telefono":   telefono,
        }

    # 4. Fallback a template interno si esta configurado y send_text fallo
    template_id = os.getenv("MERCATELY_TEMPLATE_INTERNO_ID", "").strip()
    if template_id:
        # Template debe tener 2 params: {{1}}=nivel, {{2}}=mensaje (truncado)
        params = [nivel.upper(), mensaje[:200]]
        tres = await client.send_template(telefono, template_id, params)
        if tres.get("success"):
            message_id = tres.get("message_id", "")
            await _audit(db, persona, nivel, mensaje, hash_msg, contexto, True,
                         message_id, "template")
            return {
                "success":    True,
                "via":        "template",
                "message_id": message_id,
                "persona":    persona,
                "nivel":      nivel,
                "telefono":   telefono,
            }
        # Tambien fallo template
        await _audit(db, persona, nivel, mensaje, hash_msg, contexto, False, "",
                     "error", error=f"send_text:{res.get('error')} template:{tres.get('error')}")
        return {"success": False,
                "error": f"Fallaron send_text y template — {tres.get('error')}"}

    # Sin template configurado y send_text fallo
    await _audit(db, persona, nivel, mensaje, hash_msg, contexto, False, "",
                 "error", error=str(res.get("error", "")))
    logger.warning(
        "notificar_interno FALLO — persona=%s error=%s (sin template fallback)",
        persona, res.get("error"),
    )
    return {"success": False, "error": str(res.get("error", "send_text fallo"))}
