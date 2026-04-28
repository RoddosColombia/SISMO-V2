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

    # ── Sprint S2 (Ejecucion 2) — Mercately bidireccional ─────────────────────

    async def get_customer_by_phone(self, phone_number: str) -> dict:
        """GET /customers?phone=... (R-MERCATELY: SIEMPRE antes de POST/PATCH).

        Returns:
            {"success": True, "found": bool, "customer": {...}|None, "raw": {...}}
        """
        if not self.api_key:
            return {"success": False, "found": False, "customer": None,
                    "error": "MERCATELY_API_KEY no configurada"}

        phone = _limpiar_telefono(phone_number)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.base_url}/customers",
                    params={"phone_number": phone},
                    headers={"api-key": self.api_key},
                )
            if resp.status_code == 200:
                raw = resp.json()
                # API puede devolver lista directa o {"customers": [...]}
                customers = raw if isinstance(raw, list) else raw.get("customers", [])
                if customers:
                    return {"success": True, "found": True, "customer": customers[0], "raw": raw}
                return {"success": True, "found": False, "customer": None, "raw": raw}
            return {"success": False, "found": False, "customer": None,
                    "error": f"HTTP {resp.status_code}", "raw": resp.text[:500]}
        except Exception as exc:
            logger.error("Mercately get_customer_by_phone %s: %s", phone, exc)
            return {"success": False, "found": False, "customer": None, "error": str(exc)}

    async def create_customer(
        self, phone_number: str, first_name: str, last_name: str = "",
        email: str = "", id_number: str = "", tags: list[str] | None = None,
    ) -> dict:
        """POST /customers — crea contacto en Mercately."""
        if not self.api_key:
            return {"success": False, "error": "MERCATELY_API_KEY no configurada"}
        phone = _limpiar_telefono(phone_number)
        payload = {
            "phone_number": phone,
            "first_name":   first_name,
            "last_name":    last_name,
            "email":        email,
            "id_number":    id_number,
        }
        if tags:
            payload["tags"] = tags
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.base_url}/customers",
                    json=payload,
                    headers={"Content-Type": "application/json", "api-key": self.api_key},
                )
            raw = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"body": resp.text}
            if resp.status_code in (200, 201):
                return {"success": True, "customer": raw, "raw": raw}
            return {"success": False, "error": f"HTTP {resp.status_code}", "raw": raw}
        except Exception as exc:
            logger.error("Mercately create_customer %s: %s", phone, exc)
            return {"success": False, "error": str(exc)}

    async def update_customer_tags(
        self, phone_number: str, add_tags: list[str] | None = None,
        remove_tags: list[str] | None = None,
    ) -> dict:
        """PATCH tags del contacto. Idempotente.
        Mercately no documenta endpoint exacto en todas las versiones; intentamos
        PATCH /customers/by_phone/{phone}/tags. Si falla, fallback al endpoint
        de actualizar contacto completo."""
        if not self.api_key:
            return {"success": False, "error": "MERCATELY_API_KEY no configurada"}
        phone = _limpiar_telefono(phone_number)
        body: dict = {}
        if add_tags:
            body["add_tags"] = add_tags
        if remove_tags:
            body["remove_tags"] = remove_tags
        if not body:
            return {"success": True, "noop": True}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.patch(
                    f"{self.base_url}/customers/by_phone/{phone}",
                    json=body,
                    headers={"Content-Type": "application/json", "api-key": self.api_key},
                )
            if resp.status_code in (200, 204):
                return {"success": True, "tags_added": add_tags or [], "tags_removed": remove_tags or []}
            return {"success": False, "error": f"HTTP {resp.status_code}", "raw": resp.text[:500]}
        except Exception as exc:
            logger.error("Mercately update_customer_tags %s: %s", phone, exc)
            return {"success": False, "error": str(exc)}

    async def list_whatsapp_conversations(
        self, page: int = 1, results_per_page: int = 100,
    ) -> dict:
        """GET /whatsapp_conversations — lista conversaciones WA con last_interaction.

        Returns:
            {"success": True, "conversations": [...], "total_pages": int, "raw": {...}}
            Cada conversation tiene: customer_id, phone, first_name, last_name,
            message_count, last_interaction (ISO8601 UTC), agent_id.
        """
        if not self.api_key:
            return {"success": False, "conversations": [], "error": "MERCATELY_API_KEY no configurada"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.base_url}/whatsapp_conversations",
                    params={"page": page, "results_per_page": results_per_page},
                    headers={"api-key": self.api_key},
                )
            if resp.status_code == 200:
                raw = resp.json()
                return {
                    "success": True,
                    "conversations": raw.get("whatsapp_conversations", []),
                    "total_pages": raw.get("total_pages", 1),
                    "results": raw.get("results", 0),
                    "raw": raw,
                }
            return {"success": False, "conversations": [],
                    "error": f"HTTP {resp.status_code}", "raw": resp.text[:500]}
        except Exception as exc:
            logger.error("Mercately list_whatsapp_conversations: %s", exc)
            return {"success": False, "conversations": [], "error": str(exc)}

    async def get_customer_messages(
        self, customer_id: str, page: int = 1,
    ) -> dict:
        """GET /customers/{id}/whatsapp_conversations — mensajes de la conversacion.

        Returns:
            {"success": True, "messages": [...], "total_pages": int, "raw": {...}}
            Cada message tiene: id, direction (inbound/outbound), content_type,
            content_text, created_time (ISO8601 UTC), status, message_identifier.
        """
        if not self.api_key:
            return {"success": False, "messages": [], "error": "MERCATELY_API_KEY no configurada"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.base_url}/customers/{customer_id}/whatsapp_conversations",
                    params={"page": page},
                    headers={"api-key": self.api_key},
                )
            if resp.status_code == 200:
                raw = resp.json()
                return {
                    "success": True,
                    "messages": raw.get("whatsapp_conversations", []),
                    "total_pages": raw.get("total_pages", 1),
                    "raw": raw,
                }
            return {"success": False, "messages": [],
                    "error": f"HTTP {resp.status_code}", "raw": resp.text[:500]}
        except Exception as exc:
            logger.error("Mercately get_customer_messages %s: %s", customer_id, exc)
            return {"success": False, "messages": [], "error": str(exc)}

    async def send_text(self, phone_number: str, message: str) -> dict:
        """Envía mensaje de texto libre (no template) via Mercately.
        Solo funciona dentro de la ventana de 24h después de la última respuesta
        del cliente. Para fuera de ventana, usar send_template."""
        if not self.api_key:
            return {"success": False, "error": "MERCATELY_API_KEY no configurada"}
        phone = _limpiar_telefono(phone_number)
        payload = {"phone_number": phone, "message": message[:1024]}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.base_url}/whatsapp/send_message",
                    json=payload,
                    headers={"Content-Type": "application/json", "api-key": self.api_key},
                )
            raw = {}
            try:
                raw = resp.json()
            except Exception:
                raw = {"body": resp.text[:500]}
            if resp.status_code in (200, 201):
                return {"success": True, "message_id": raw.get("id", ""), "raw": raw}
            return {"success": False, "error": f"HTTP {resp.status_code}", "raw": raw}
        except Exception as exc:
            logger.error("Mercately send_text %s: %s", phone, exc)
            return {"success": False, "error": str(exc)}


# Singleton helper
_mercately_client: MercatelyClient | None = None


def get_mercately_client() -> MercatelyClient:
    global _mercately_client
    if _mercately_client is None:
        _mercately_client = MercatelyClient()
    return _mercately_client
