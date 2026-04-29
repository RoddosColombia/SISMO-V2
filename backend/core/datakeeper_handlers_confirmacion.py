"""
core/datakeeper_handlers_confirmacion.py — Confirmación WhatsApp al cliente
después de un pago auto procesado vía OCR (B11).

Cuando el handler comprobante (B9) procesa exitosamente un pago via WhatsApp,
publica `cuota.pagada` con `via=ocr_whatsapp_auto`. Este handler escucha ese
evento y envía un mensaje de confirmación al cliente con el saldo restante y
la próxima cuota.

Sprint B11 (2026-04-28).
"""
from __future__ import annotations
import logging
from datetime import date

from motor.motor_asyncio import AsyncIOMotorDatabase

from core.event_handlers import on_event
from services.mercately.client import get_mercately_client

logger = logging.getLogger("datakeeper.confirmacion_pago")


def _formatear_cop(monto: float | int) -> str:
    """Formatea $1.234.567 estilo colombiano."""
    return f"${int(monto):,}".replace(",", ".")


@on_event("cuota.pagada", critical=False)
async def handle_enviar_confirmacion_whatsapp(event: dict, db: AsyncIOMotorDatabase) -> None:
    """Envía confirmación WhatsApp al cliente tras pago auto via OCR.

    Solo se dispara cuando el evento viene del flujo OCR
    (`via=ocr_whatsapp_auto`). Para pagos via chat agente o admin manual,
    el saludo lo da el agente conversacional directamente.
    """
    datos = event.get("datos") or {}
    via = datos.get("via", "")
    if via != "ocr_whatsapp_auto":
        # Solo confirma los pagos del flujo OCR — el resto los maneja el agente
        return

    loanbook_id = datos.get("loanbook_id", "")
    monto = datos.get("monto_total_pagado", 0)
    cliente_nombre = datos.get("cliente_nombre", "") or "estimado cliente"
    cuota_numero = datos.get("cuota_numero")
    referencia = datos.get("referencia", "")

    # Lookup loanbook para sacar telefono + saldo restante + proxima cuota
    lb = await db.loanbook.find_one({"loanbook_id": loanbook_id})
    if not lb:
        logger.warning("confirmacion: loanbook %s no existe", loanbook_id)
        return

    cliente_block = lb.get("cliente") or {}
    telefono = cliente_block.get("telefono") or lb.get("cliente_telefono", "")
    if not telefono:
        logger.warning("confirmacion: loanbook %s sin telefono cliente", loanbook_id)
        return

    saldo_pendiente = lb.get("saldo_pendiente", 0) or 0
    estado = lb.get("estado", "")

    # Encontrar próxima cuota pendiente
    proxima_cuota = None
    for c in (lb.get("cuotas") or []):
        if c.get("estado") in ("pendiente", "vencida"):
            proxima_cuota = c
            break

    # Solo nombre primero para mensaje cordial
    nombre_corto = cliente_nombre.split()[0].title() if cliente_nombre else "estimado"

    # Construir mensaje
    lineas = [f"✅ Hola {nombre_corto}, recibimos tu pago de {_formatear_cop(monto)}."]

    if cuota_numero:
        lineas.append(f"Cuota #{cuota_numero} aplicada correctamente.")

    if estado == "Pagado" or estado == "saldado":
        lineas.append("\n🎉 ¡Tu crédito quedó SALDADO! Te enviaremos el paz y salvo.")
    elif proxima_cuota:
        proxima_fecha = proxima_cuota.get("fecha", "")
        proxima_monto = proxima_cuota.get("monto") or lb.get("cuota_periodica", 0)
        if proxima_fecha:
            try:
                fdt = date.fromisoformat(proxima_fecha[:10])
                fecha_str = fdt.strftime("%d/%m")
            except Exception:
                fecha_str = proxima_fecha
            lineas.append(
                f"\n📅 Próxima cuota: {_formatear_cop(proxima_monto)} el {fecha_str}"
            )
        lineas.append(f"💼 Saldo restante: {_formatear_cop(saldo_pendiente)}")

    if referencia:
        lineas.append(f"\nReferencia: {referencia}")

    lineas.append("\n— RODDOS S.A.S.")
    mensaje = "\n".join(lineas)

    # Enviar via Mercately (send_text — ventana 24h abierta porque acaba de
    # mandar el comprobante hace segundos/minutos)
    client = get_mercately_client()
    if not client.api_key:
        logger.warning("confirmacion: MERCATELY_API_KEY no configurada — skip")
        return

    res = await client.send_text(telefono, mensaje)
    if res.get("success"):
        logger.info(
            "confirmacion enviada loanbook=%s phone=%s monto=%s msg_id=%s",
            loanbook_id, telefono, monto, res.get("message_id"),
        )
        # Audit
        await db.mercately_internal_audit.insert_one({
            "tipo":           "confirmacion_pago_auto",
            "loanbook_id":    loanbook_id,
            "phone":          telefono,
            "monto":          monto,
            "mensaje":        mensaje,
            "message_id":     res.get("message_id"),
            "fecha":          datos.get("fecha_pago"),
            "via":            "ocr_whatsapp_auto",
        })
    else:
        logger.error(
            "confirmacion fallo loanbook=%s phone=%s error=%s",
            loanbook_id, telefono, res.get("error"),
        )
