"""
services/mercately/client.py — Cliente HTTP para la API de Mercately WhatsApp.

Envía mensajes de plantilla (templates) via:
  POST https://app.mercately.com/retailers/api/v1/whatsapp/send_notification_by_id

Auth: header api-key con MERCATELY_API_KEY.

Función pura de limpieza de teléfonos incluida (_limpiar_telefono).
Si MERCATELY_API_KEY no está configurada, loguea warning y retorna
success=False silenciosamente para no romper arranque ni tests.
"""

from __future__ import annotations

import logging
import os
import re

import httpx

logger = logging.getLogger("mercately")

_BASE_URL = "https://app.mercately.com/retailers/api/v1"
_ENDPOINT  = "/whatsapp/send_notification_by_id"


def _limpiar_telefono(raw: str) -> str:
    """Normaliza un número de teléfono al formato internacional colombiano sin +.

    Reglas (en orden):
    1. Remover espacios, guiones, paréntesis, puntos.
    2. Remover el + inicial si existe.
    3. Si empieza con 0, reemplazar con 57.
    4. Si tiene exactamente 10 dígitos (celular colombiano sin código), agregar 57.
    5. Retornar tal cual (ya tiene código de país u otro formato).

    Ejemplos:
      "+57 300 123-4567" → "573001234567"
      "3001234567"        → "573001234567"
      "573001234567"      → "573001234567"
      "0573001234567"     → "57573001234567"  (no es caso colombiano)
    """
    # 1. Strip whitespace, dashes, parens, dots
    numero = re.sub(r"[\s\-\(\)\.]", "", raw)
    # 2. Remove leading +
    if numero.startswith("+"):
        numero = numero[1:]
    # 3. Replace leading 0 with country code 57
    if numero.startswith("0"):
        numero = "57" + numero[1:]
    # 4. Bare 10-digit Colombian mobile (starts with 3)
    if len(numero) == 10 and numero.startswith("3"):
        numero = "57" + numero
    return numero


class MercatelyClient:
    """Cliente liviano para Mercately WhatsApp API."""

    def __init__(self) -> None:
        self.api_key  = os.getenv("MERCATELY_API_KEY", "")
        self.base_url = _BASE_URL

    async def send_template(
        self,
        phone_number: str,
        template_id: str,
        template_params: list[str],
    ) -> dict:
        """Envía un mensaje de plantilla via Mercately.

        Args:
            phone_number:    Número en cualquier formato — se limpia internamente.
            template_id:     UUID de la plantilla en Mercately (internal_id).
            template_params: Lista de strings con las variables de la plantilla.

        Returns:
            {"success": True,  "message_id": "...", "raw": {...}}
          | {"success": False, "error": "...", "raw": {...}}

        Si MERCATELY_API_KEY no está configurada, retorna success=False
        silenciosamente sin lanzar excepción.
        """
        if not self.api_key:
            logger.warning(
                "MercatelyClient: MERCATELY_API_KEY no configurada — "
                "mensaje a %s omitido silenciosamente", phone_number
            )
            return {"success": False, "error": "MERCATELY_API_KEY no configurada"}

        phone_clean = _limpiar_telefono(phone_number)
        payload = {
            "phone_number": phone_clean,
            "internal_id": template_id,
            "template_params": template_params,
        }
        headers = {
            "Content-Type": "application/json",
            "api-key": self.api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.base_url}{_ENDPOINT}",
                    json=payload,
                    headers=headers,
                )

            raw = {}
            try:
                raw = resp.json()
            except Exception:
                raw = {"body": resp.text}

            if resp.status_code in (200, 201):
                message_id = (
                    raw.get("id")
                    or raw.get("message_id")
                    or raw.get("uid")
                    or ""
                )
                logger.info(
                    "Mercately OK — phone=%s template=%s message_id=%s",
                    phone_clean, template_id, message_id,
                )
                return {"success": True, "message_id": str(message_id), "raw": raw}
            else:
                logger.warning(
                    "Mercately HTTP %d — phone=%s template=%s body=%s",
                    resp.status_code, phone_clean, template_id, raw,
                )
                return {
                    "success": False,
                    "error": f"HTTP {resp.status_code}",
                    "raw": raw,
                }

        except Exception as exc:
            logger.error(
                "Mercately excepción — phone=%s template=%s: %s",
                phone_clean, template_id, exc,
            )
            return {"success": False, "error": str(exc), "raw": {}}
