"""services/mercately/client.py - Cliente HTTP para Mercately WhatsApp API.

Auth: header api-key (lowercase). Probado 2026-04-28.
Base URL: https://app.mercately.com/retailers/api/v1
"""
from __future__ import annotations
import logging
import os
import re

import httpx

logger = logging.getLogger("mercately")

_BASE_URL = "https://app.mercately.com/retailers/api/v1"


def _limpiar_telefono(raw: str) -> str:
    """Normaliza phone a 12 digitos (57XXXXXXXXXX) sin +."""
    numero = re.sub(r"[\s\-\(\)\.]", "", raw or "")
    if numero.startswith("+"):
        numero = numero[1:]
    if numero.startswith("0"):
        numero = "57" + numero[1:]
    if len(numero) == 10 and numero.startswith("3"):
        numero = "57" + numero
    return numero


class MercatelyClient:
    """Cliente liviano para Mercately WhatsApp API."""

    def __init__(self) -> None:
        self.api_key = os.getenv("MERCATELY_API_KEY", "")
        self.base_url = _BASE_URL

    def _headers(self, content_type: bool = False) -> dict:
        h = {"api-key": self.api_key}
        if content_type:
            h["Content-Type"] = "application/json"
        return h

    async def send_template(self, phone_number: str, template_id: str,
                            template_params: list) -> dict:
        """POST /whatsapp/send_notification_by_id - envia plantilla aprobada."""
        if not self.api_key:
            logger.warning("MercatelyClient: API_KEY no configurada, skip phone=%s",
                           phone_number)
            return {"success": False, "error": "MERCATELY_API_KEY no configurada"}

        phone_clean = _limpiar_telefono(phone_number)
        payload = {"phone_number": phone_clean, "internal_id": template_id,
                   "template_params": template_params}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.base_url}/whatsapp/send_notification_by_id",
                    json=payload, headers=self._headers(content_type=True),
                )
            raw = {}
            try:
                raw = resp.json()
            except Exception:
                raw = {"body": resp.text[:500]}
            if resp.status_code in (200, 201):
                msg_id = raw.get("id") or raw.get("message_id") or raw.get("uid") or ""
                logger.info("Mercately OK phone=%s template=%s msg_id=%s",
                            phone_clean, template_id, msg_id)
                return {"success": True, "message_id": str(msg_id), "raw": raw}
            logger.warning("Mercately HTTP %d phone=%s template=%s body=%s",
                           resp.status_code, phone_clean, template_id, raw)
            return {"success": False, "error": f"HTTP {resp.status_code}", "raw": raw}
        except Exception as exc:
            logger.error("Mercately send_template phone=%s exc=%s", phone_clean, exc)
            return {"success": False, "error": str(exc), "raw": {}}

    async def get_customer_by_phone(self, phone_number: str) -> dict:
        """GET /customers/{phone} - path-style. Probado 2026-04-28."""
        if not self.api_key:
            return {"success": False, "found": False, "customer": None,
                    "error": "MERCATELY_API_KEY no configurada"}

        phone = _limpiar_telefono(phone_number)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{self.base_url}/customers/{phone}",
                                        headers=self._headers())
            if resp.status_code == 200:
                raw = resp.json()
                customer = raw.get("customer") if isinstance(raw, dict) else None
                if customer:
                    return {"success": True, "found": True, "customer": customer, "raw": raw}
                if isinstance(raw, dict) and raw.get("customers"):
                    return {"success": True, "found": True,
                            "customer": raw["customers"][0], "raw": raw}
                return {"success": True, "found": False, "customer": None, "raw": raw}
            if resp.status_code == 404:
                return {"success": True, "found": False, "customer": None,
                        "raw": {"http": 404}}
            return {"success": False, "found": False, "customer": None,
                    "error": f"HTTP {resp.status_code}", "raw": resp.text[:500]}
        except Exception as exc:
            logger.error("Mercately get_customer_by_phone %s: %s", phone, exc)
            return {"success": False, "found": False, "customer": None, "error": str(exc)}

    async def create_customer(self, phone_number: str, first_name: str,
                              last_name: str = "", email: str = "",
                              id_number: str = "", tags=None) -> dict:
        """POST /customers - crea contacto."""
        if not self.api_key:
            return {"success": False, "error": "MERCATELY_API_KEY no configurada"}
        phone = _limpiar_telefono(phone_number)
        payload = {"phone_number": phone, "first_name": first_name,
                   "last_name": last_name, "email": email, "id_number": id_number}
        if tags:
            payload["tags"] = tags
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(f"{self.base_url}/customers",
                                         json=payload,
                                         headers=self._headers(content_type=True))
            raw = resp.json() if resp.headers.get("content-type", "").startswith(
                "application/json") else {"body": resp.text}
            if resp.status_code in (200, 201):
                return {"success": True, "customer": raw, "raw": raw}
            return {"success": False, "error": f"HTTP {resp.status_code}", "raw": raw}
        except Exception as exc:
            logger.error("Mercately create_customer %s: %s", phone, exc)
            return {"success": False, "error": str(exc)}

    async def update_customer_tags(self, phone_number: str,
                                   add_tags=None, remove_tags=None) -> dict:
        """PATCH /customers/by_phone/{phone}/tags - actualiza tags idempotente."""
        if not self.api_key:
            return {"success": False, "error": "MERCATELY_API_KEY no configurada"}
        phone = _limpiar_telefono(phone_number)
        body = {}
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
                    json=body, headers=self._headers(content_type=True))
            if resp.status_code in (200, 204):
                return {"success": True, "tags_added": add_tags or [],
                        "tags_removed": remove_tags or []}
            return {"success": False, "error": f"HTTP {resp.status_code}",
                    "raw": resp.text[:500]}
        except Exception as exc:
            logger.error("Mercately update_customer_tags %s: %s", phone, exc)
            return {"success": False, "error": str(exc)}

    async def list_whatsapp_conversations(self, page: int = 1,
                                          results_per_page: int = 100) -> dict:
        """DEPRECATED 2026-04-28: endpoint global devuelve HTTP 500 (bug Mercately).
        Mantenido por compatibilidad. Usar get_whatsapp_conversations_by_phone."""
        if not self.api_key:
            return {"success": False, "conversations": [],
                    "error": "MERCATELY_API_KEY no configurada"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.base_url}/whatsapp_conversations",
                    params={"page": page, "results_per_page": results_per_page},
                    headers=self._headers())
            if resp.status_code == 200:
                raw = resp.json()
                return {"success": True,
                        "conversations": raw.get("whatsapp_conversations", []),
                        "total_pages": raw.get("total_pages", 1),
                        "results": raw.get("results", 0), "raw": raw}
            return {"success": False, "conversations": [],
                    "error": f"HTTP {resp.status_code}", "raw": resp.text[:500]}
        except Exception as exc:
            logger.error("Mercately list_whatsapp_conversations: %s", exc)
            return {"success": False, "conversations": [], "error": str(exc)}

    async def get_customer_messages(self, customer_id: str, page: int = 1) -> dict:
        """GET /customers/{id_or_phone}/whatsapp_conversations - mensajes."""
        if not self.api_key:
            return {"success": False, "messages": [],
                    "error": "MERCATELY_API_KEY no configurada"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.base_url}/customers/{customer_id}/whatsapp_conversations",
                    params={"page": page}, headers=self._headers())
            if resp.status_code == 200:
                raw = resp.json()
                return {"success": True,
                        "messages": raw.get("whatsapp_conversations", []),
                        "total_pages": raw.get("total_pages", 1), "raw": raw}
            return {"success": False, "messages": [],
                    "error": f"HTTP {resp.status_code}", "raw": resp.text[:500]}
        except Exception as exc:
            logger.error("Mercately get_customer_messages %s: %s", customer_id, exc)
            return {"success": False, "messages": [], "error": str(exc)}

    async def get_whatsapp_conversations_by_phone(self, phone_number: str,
                                                   page: int = 1) -> dict:
        """Helper semantico: GET /customers/{phone}/whatsapp_conversations."""
        phone = _limpiar_telefono(phone_number)
        return await self.get_customer_messages(phone, page=page)

    async def send_text(self, phone_number: str, message: str) -> dict:
        """POST /whatsapp/send_message - texto libre dentro de ventana 24h."""
        if not self.api_key:
            return {"success": False, "error": "MERCATELY_API_KEY no configurada"}
        phone = _limpiar_telefono(phone_number)
        payload = {"phone_number": phone, "message": message[:1024]}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.base_url}/whatsapp/send_message",
                    json=payload, headers=self._headers(content_type=True))
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


# Singleton
_mercately_client = None


def get_mercately_client() -> MercatelyClient:
    global _mercately_client
    if _mercately_client is None:
        _mercately_client = MercatelyClient()
    return _mercately_client
