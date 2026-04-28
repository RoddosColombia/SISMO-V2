"""
services/mercately/inbound_poller.py — Polling de mensajes WhatsApp entrantes.

Mercately NO expone webhooks (verificado en API redocly + soporte 2026-04-28).
Este modulo simula el webhook via polling al endpoint REST.

Estrategia 2-niveles:
  1. Cada 60s: GET /whatsapp_conversations  -> listado con last_interaction
  2. Filtrar conversaciones con last_interaction > last_global_check
  3. Para cada una: GET /customers/{id}/whatsapp_conversations -> mensajes
  4. Filtrar mensajes con direction='inbound' y created_time > last_seen
  5. Por cada mensaje nuevo: ejecutar handler de inbound (mismo que webhook)
  6. Persistir last_seen_msg_id por customer en mercately_polling_state

Beneficio:
  - 1 request global por ciclo (no N por cliente)
  - Solo se profundiza en conversaciones con actividad nueva
  - Replica exactamente el comportamiento del webhook que no existe

Coleccion de estado:
  mercately_polling_state (singleton "global"):
    {
      "_id": "global",
      "last_global_check_iso": "2026-04-28T13:24:00Z",
      "actualizado_en": datetime
    }

  mercately_polling_state (per-customer):
    {
      "_id": "customer:{customer_id}",
      "customer_id": int,
      "phone": "573...",
      "last_seen_msg_id": "...",
      "last_seen_iso": "2026-04-28T13:23:45Z",
      "actualizado_en": datetime
    }

Coleccion de audit:
  mercately_inbound_audit (append-only):
    {
      "fecha": datetime,
      "customer_id": int,
      "phone": "573...",
      "msg_id": "...",
      "direction": "inbound",
      "content_text": "...",
      "evento_publicado": True,
      "cliente_crm_encontrado": True,
      "cedula": "..."
    }

Sprint S2.5 (2026-04-28) — Cierre del bucle bidirecccional via polling.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from core.events import publish_event
from services.mercately.client import get_mercately_client

logger = logging.getLogger("mercately.inbound_poller")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _iso_to_dt(iso: str) -> datetime | None:
    """Parse ISO8601 (Z o +00:00). Devuelve aware UTC o None."""
    if not iso:
        return None
    try:
        # Mercately envia formato '2022-09-23T00:34:13.097Z'
        s = iso.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _normalize_phone(raw: str) -> str:
    """Normaliza a 12 digitos con prefijo 57 colombiano."""
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if len(digits) == 10 and digits.startswith("3"):
        digits = "57" + digits
    return digits


# ─────────────────────────────────────────────────────────────────────────────
# Estado del poller
# ─────────────────────────────────────────────────────────────────────────────

async def _get_global_state(db: AsyncIOMotorDatabase) -> datetime:
    """Devuelve last_global_check_iso como datetime UTC. Default: hace 5min."""
    doc = await db.mercately_polling_state.find_one({"_id": "global"})
    if doc and doc.get("last_global_check_iso"):
        dt = _iso_to_dt(doc["last_global_check_iso"])
        if dt:
            return dt
    # Default: hace 5min para arranque suave
    return datetime.now(timezone.utc) - timedelta(minutes=5)


async def _set_global_state(db: AsyncIOMotorDatabase, when: datetime) -> None:
    await db.mercately_polling_state.update_one(
        {"_id": "global"},
        {"$set": {
            "last_global_check_iso": when.isoformat(),
            "actualizado_en": datetime.now(timezone.utc),
        }},
        upsert=True,
    )


async def _get_customer_state(
    db: AsyncIOMotorDatabase, customer_id: Any,
) -> tuple[str, datetime | None]:
    """Devuelve (last_seen_msg_id, last_seen_dt) para customer."""
    doc = await db.mercately_polling_state.find_one(
        {"_id": f"customer:{customer_id}"}
    )
    if not doc:
        return "", None
    return doc.get("last_seen_msg_id", ""), _iso_to_dt(doc.get("last_seen_iso", ""))


async def _set_customer_state(
    db: AsyncIOMotorDatabase, customer_id: Any, phone: str,
    msg_id: str, when_iso: str,
) -> None:
    await db.mercately_polling_state.update_one(
        {"_id": f"customer:{customer_id}"},
        {"$set": {
            "customer_id": customer_id,
            "phone": phone,
            "last_seen_msg_id": msg_id,
            "last_seen_iso": when_iso,
            "actualizado_en": datetime.now(timezone.utc),
        }},
        upsert=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Procesamiento de mensaje individual (replica el webhook handler)
# ─────────────────────────────────────────────────────────────────────────────

async def _process_inbound_message(
    db: AsyncIOMotorDatabase,
    customer_id: Any,
    phone_raw: str,
    msg: dict,
) -> dict:
    """Replica logica de routers/webhooks.py:mercately_inbound_webhook.

    1. Append gestion en crm_clientes (si cliente existe)
    2. Publish event cliente.respondio.whatsapp para que RADAR decida.
    3. Audit en mercately_inbound_audit.
    """
    msg_id = str(msg.get("id", "") or msg.get("message_identifier", ""))
    content_text = (msg.get("content_text") or "").strip()
    content_type = msg.get("content_type", "text")
    created_time_iso = msg.get("created_time", "")
    phone = _normalize_phone(phone_raw)

    # Buscar cliente CRM
    cliente = None
    if phone:
        cliente = await db.crm_clientes.find_one({"mercately_phone": phone})
        if not cliente:
            cliente = await db.crm_clientes.find_one(
                {"telefono": {"$regex": phone[-10:]}}
            ) if len(phone) >= 10 else None

    cedula = (cliente or {}).get("cedula", "")

    # Append gestion
    if cliente:
        await db.crm_clientes.update_one(
            {"_id": cliente["_id"]},
            {"$push": {
                "gestiones": {
                    "tipo": "whatsapp_inbound",
                    "fecha": datetime.now(timezone.utc).isoformat(),
                    "mensaje": content_text[:1024],
                    "msg_type": content_type,
                    "msg_id": msg_id,
                    "phone": phone,
                    "via": "polling",
                    "nota": f"Cliente respondio por WhatsApp (polling): '{content_text[:200]}'",
                }
            }},
        )

    # Publish event
    await publish_event(
        db=db,
        event_type="cliente.respondio.whatsapp",
        source="polling.mercately",
        datos={
            "phone":         phone,
            "cedula":        cedula,
            "mensaje":       content_text[:1024],
            "msg_type":      content_type,
            "msg_id":        msg_id,
            "customer_id":   customer_id,
            "via":           "polling",
            "created_time":  created_time_iso,
        },
        alegra_id=None,
        accion_ejecutada=f"Respuesta WhatsApp (poll) de {cedula or phone}",
    )

    # Audit
    await db.mercately_inbound_audit.insert_one({
        "fecha":                  datetime.now(timezone.utc),
        "customer_id":            customer_id,
        "phone":                  phone,
        "msg_id":                 msg_id,
        "direction":              msg.get("direction", "inbound"),
        "content_type":           content_type,
        "content_text":           content_text[:1024],
        "created_time_iso":       created_time_iso,
        "evento_publicado":       True,
        "cliente_crm_encontrado": bool(cliente),
        "cedula":                 cedula,
        "via":                    "polling",
    })

    logger.info(
        "polling inbound — customer=%s phone=%s cedula=%s msg='%s'",
        customer_id, phone, cedula, content_text[:80],
    )

    return {
        "msg_id":            msg_id,
        "phone":             phone,
        "cedula":            cedula,
        "cliente_encontrado": bool(cliente),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Loop principal de un ciclo
# ─────────────────────────────────────────────────────────────────────────────

async def poll_once(db: AsyncIOMotorDatabase) -> dict:
    """Ejecuta UN ciclo de polling. Devuelve resumen.

    Pasos:
      1. Lee global last_check
      2. GET /whatsapp_conversations (paginado)
      3. Filtra conversaciones con last_interaction > last_check
      4. Para cada una: GET messages, filtra inbound nuevos, procesa
      5. Actualiza estado global y per-customer
    """
    client = get_mercately_client()
    if not client.api_key:
        return {"ok": False, "skip": "no_api_key"}

    last_global = await _get_global_state(db)
    nuevo_global = datetime.now(timezone.utc)

    # 1. Listar conversaciones con actividad
    page = 1
    total_pages = 1
    candidatas: list[dict] = []
    while page <= total_pages and page <= 5:  # safety: max 5 paginas (500 convs)
        res = await client.list_whatsapp_conversations(page=page, results_per_page=100)
        if not res.get("success"):
            logger.warning("polling list conversations falló: %s", res.get("error"))
            break
        for conv in res.get("conversations", []):
            li = _iso_to_dt(conv.get("last_interaction", ""))
            if li and li > last_global:
                candidatas.append(conv)
        total_pages = res.get("total_pages", 1)
        page += 1

    # 2. Para cada conversacion candidata, traer mensajes
    procesados = 0
    nuevos_mensajes_total = 0
    for conv in candidatas:
        customer_id = conv.get("customer_id")
        if not customer_id:
            continue
        phone_raw = conv.get("phone", "")

        last_msg_id, last_seen_dt = await _get_customer_state(db, customer_id)

        msg_res = await client.get_customer_messages(str(customer_id), page=1)
        if not msg_res.get("success"):
            continue

        nuevos: list[dict] = []
        for m in msg_res.get("messages", []):
            if (m.get("direction") or "").lower() != "inbound":
                continue
            mid = str(m.get("id", "") or m.get("message_identifier", ""))
            ct = _iso_to_dt(m.get("created_time", ""))
            # Filtros: id distinto del ultimo visto, y/o timestamp posterior
            if last_seen_dt and ct and ct <= last_seen_dt:
                continue
            if mid and mid == last_msg_id:
                continue
            nuevos.append(m)

        # Ordenar mas viejo primero para procesar en orden cronologico
        nuevos.sort(key=lambda x: x.get("created_time", ""))

        for m in nuevos:
            try:
                await _process_inbound_message(db, customer_id, phone_raw, m)
                nuevos_mensajes_total += 1
                # Actualizar estado per-customer al ultimo procesado
                await _set_customer_state(
                    db,
                    customer_id=customer_id,
                    phone=_normalize_phone(phone_raw),
                    msg_id=str(m.get("id", "") or m.get("message_identifier", "")),
                    when_iso=m.get("created_time", ""),
                )
            except Exception as exc:
                logger.exception("polling proceso msg fallo customer=%s: %s", customer_id, exc)
        procesados += 1

    # 3. Actualizar last_global solo si terminamos OK (sin excepcion)
    await _set_global_state(db, nuevo_global)

    return {
        "ok":                    True,
        "candidatas":            len(candidatas),
        "conversaciones":        procesados,
        "mensajes_procesados":   nuevos_mensajes_total,
        "last_global_iso":       nuevo_global.isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Loop forever (scheduler)
# ─────────────────────────────────────────────────────────────────────────────

async def run_inbound_poller_loop(
    db_factory, interval_s: int = 60,
) -> None:
    """Loop infinito; ejecuta poll_once() cada `interval_s` segundos.

    db_factory: callable async que devuelve la DB (para reusar conexion del lifespan).
    """
    logger.info("Mercately inbound poller arrancado (interval=%ds)", interval_s)
    while True:
        try:
            db = db_factory()
            res = await poll_once(db)
            if res.get("mensajes_procesados", 0) > 0:
                logger.info(
                    "inbound poll ok — convs=%s msgs=%s",
                    res.get("conversaciones"), res.get("mensajes_procesados"),
                )
        except asyncio.CancelledError:
            logger.info("Mercately inbound poller cancelado (shutdown)")
            raise
        except Exception as exc:
            logger.exception("Mercately inbound poller error en ciclo: %s", exc)
        await asyncio.sleep(interval_s)
