"""
services/email/sender.py — Wrapper Resend API para envío de emails HTML.

Resend (resend.com) es el servicio escogido por:
- API simple
- $20/mes plan que cubre 50K emails
- Buen deliverability para Colombia
- SDK Python oficial

Configuración (env vars Render):
  RESEND_API_KEY      = re_xxxxx
  EMAIL_FROM          = "Sismo RODDOS <reportes@sismo.roddos.com>"
  EMAIL_ANDRES        = andres@roddos.com
  EMAIL_IVAN          = ivan@roddos.com
  EMAIL_FABIAN        = fabian@roddos.com (contador)
"""
from __future__ import annotations
import logging
import os

import httpx

logger = logging.getLogger("services.email")

RESEND_API = "https://api.resend.com/emails"


async def enviar_email(
    to: str | list[str],
    subject: str,
    html: str,
    *,
    from_addr: str | None = None,
    reply_to: str | None = None,
    text_alt: str | None = None,
) -> dict:
    """Envia email HTML via Resend.

    Returns:
        {"success": True, "id": "<resend_id>"}  | {"success": False, "error": "..."}
    """
    api_key = os.getenv("RESEND_API_KEY", "")
    if not api_key:
        logger.warning("RESEND_API_KEY no configurada — skip envio email")
        return {"success": False, "error": "RESEND_API_KEY no configurada"}

    from_default = os.getenv("EMAIL_FROM", "Sismo RODDOS <onboarding@resend.dev>")

    if isinstance(to, str):
        to = [to]
    to = [a for a in to if a and "@" in a]
    if not to:
        return {"success": False, "error": "destinatarios vacios"}

    payload = {
        "from":    from_addr or from_default,
        "to":      to,
        "subject": subject,
        "html":    html,
    }
    if text_alt:
        payload["text"] = text_alt
    if reply_to:
        payload["reply_to"] = reply_to

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                RESEND_API,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if resp.status_code in (200, 201, 202):
            data = resp.json()
            logger.info("email enviado a %s subject=%r id=%s",
                        to, subject[:60], data.get("id"))
            return {"success": True, "id": data.get("id"), "raw": data}
        logger.error("Resend HTTP %d body=%s", resp.status_code, resp.text[:300])
        return {"success": False, "error": f"HTTP {resp.status_code}",
                "details": resp.text[:300]}
    except Exception as exc:
        logger.exception("Resend excepcion: %s", exc)
        return {"success": False, "error": str(exc)}


def emails_destinatarios_internos() -> list[str]:
    """Lee env vars EMAIL_ANDRES, EMAIL_IVAN, EMAIL_FABIAN. Filtra los vacios."""
    candidatos = [
        os.getenv("EMAIL_ANDRES", "").strip(),
        os.getenv("EMAIL_IVAN", "").strip(),
        os.getenv("EMAIL_FABIAN", "").strip(),
    ]
    return [c for c in candidatos if c and "@" in c]
