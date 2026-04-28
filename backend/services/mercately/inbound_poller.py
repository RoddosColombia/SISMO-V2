"""services/mercately/inbound_poller.py - Polling de mensajes WhatsApp entrantes (S2.5c).

Estrategia phones activos:
1. Cada interval_s, lee phones activos de MongoDB (loanbook + crm + radar_alertas)
2. Para cada phone: GET /customers/{phone}/whatsapp_conversations
3. Filtra direction=inbound y created_time > last_seen
4. Procesa: append gestion CRM + publish event + audit
5. Persiste last_seen_msg_id por phone

Mercately bug confirmado 2026-04-28: el endpoint global /whatsapp_conversations
da HTTP 500. Por eso usamos el endpoint por-phone que SI funciona.
"""
from __future__ import annotations
import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase

from core.events import publish_event
from services.mercately.client import get_mercately_client

logger = logging.getLogger("mercately.inbound_poller")

MAX_PHONES_POR_CICLO = int(os.getenv("MERCATELY_POLL_MAX_PHONES", "50"))
DPD_LOOKAHEAD_DIAS = int(os.getenv("MERCATELY_POLL_DPD_LOOKAHEAD", "7"))


def _iso_to_dt(iso: str):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None


def _normalize_phone(raw: str) -> str:
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if len(digits) == 10 and digits.startswith("3"):
        digits = "57" + digits
    return digits


async def _get_global_state(db: AsyncIOMotorDatabase) -> datetime:
    doc = await db.mercately_polling_state.find_one({"_id": "global"})
    if doc and doc.get("last_global_check_iso"):
        dt = _iso_to_dt(doc["last_global_check_iso"])
        if dt:
            return dt
    return datetime.now(timezone.utc) - timedelta(minutes=5)


async def _set_global_state(db: AsyncIOMotorDatabase, when: datetime) -> None:
    await db.mercately_polling_state.update_one(
        {"_id": "global"},
        {"$set": {"last_global_check_iso": when.isoformat(),
                  "actualizado_en": datetime.now(timezone.utc)}},
        upsert=True,
    )


async def _get_phone_state(db: AsyncIOMotorDatabase, phone: str):
    doc = await db.mercately_polling_state.find_one({"_id": f"phone:{phone}"})
    if not doc:
        return "", None
    return doc.get("last_seen_msg_id", ""), _iso_to_dt(doc.get("last_seen_iso", ""))


async def _set_phone_state(db: AsyncIOMotorDatabase, phone: str,
                           msg_id: str, when_iso: str) -> None:
    await db.mercately_polling_state.update_one(
        {"_id": f"phone:{phone}"},
        {"$set": {"phone": phone, "last_seen_msg_id": msg_id,
                  "last_seen_iso": when_iso,
                  "actualizado_en": datetime.now(timezone.utc)}},
        upsert=True,
    )


async def _obtener_phones_activos(db: AsyncIOMotorDatabase,
                                  limit: int = MAX_PHONES_POR_CICLO):
    """Phones a polear: loanbook activo + CRM tag radar/mora + radar_alertas 24h."""
    phones = {}
    desde_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    desde_lookahead = (datetime.now(timezone.utc) +
                       timedelta(days=DPD_LOOKAHEAD_DIAS)).isoformat()[:10]

    try:
        async for lb in db.loanbook.find(
            {"estado_credito": {"$in": ["activo", "mora", "al_dia"]},
             "$or": [{"dpd": {"$gte": 0}},
                     {"proxima_cuota_fecha": {"$lte": desde_lookahead}}]},
            {"telefono": 1, "cliente_telefono": 1, "dpd": 1},
        ).limit(limit * 3):
            tel = lb.get("telefono") or lb.get("cliente_telefono") or ""
            phone = _normalize_phone(tel)
            if not phone or len(phone) != 12:
                continue
            dpd = lb.get("dpd", 0) or 0
            prioridad = 100 + max(0, int(dpd))
            phones[phone] = max(phones.get(phone, 0), prioridad)
    except Exception as exc:
        logger.warning("phones_activos: fuente loanbook fallo: %s", exc)

    try:
        async for c in db.crm_clientes.find(
            {"tags": {"$in": ["radar", "mora", "pre-mora"]}},
            {"telefono": 1, "mercately_phone": 1, "tags": 1},
        ).limit(limit):
            tel = c.get("mercately_phone") or c.get("telefono") or ""
            phone = _normalize_phone(tel)
            if not phone or len(phone) != 12:
                continue
            tags = c.get("tags", [])
            prioridad = 80 if "mora" in tags else 50
            phones[phone] = max(phones.get(phone, 0), prioridad)
    except Exception as exc:
        logger.warning("phones_activos: fuente crm fallo: %s", exc)

    try:
        async for a in db.radar_alertas.find(
            {"fecha": {"$gte": desde_24h}, "estado": "enviado"},
            {"telefono": 1, "phone": 1},
        ).limit(limit):
            tel = a.get("telefono") or a.get("phone") or ""
            phone = _normalize_phone(tel)
            if not phone or len(phone) != 12:
                continue
            phones[phone] = max(phones.get(phone, 0), 70)
    except Exception as exc:
        logger.warning("phones_activos: fuente radar_alertas fallo: %s", exc)

    sorted_phones = sorted(phones.items(), key=lambda kv: -kv[1])[:limit]
    return [p for p, _ in sorted_phones]


async def _process_inbound_message(db: AsyncIOMotorDatabase,
                                    phone: str, msg: dict) -> dict:
    msg_id = str(msg.get("id", "") or msg.get("message_identifier", ""))
    content_text = (msg.get("content_text") or "").strip()
    content_type = msg.get("content_type", "text")
    created_time_iso = msg.get("created_time", "")

    cliente = await db.crm_clientes.find_one({"mercately_phone": phone})
    if not cliente and len(phone) >= 10:
        cliente = await db.crm_clientes.find_one({"telefono": {"$regex": phone[-10:]}})

    cedula = (cliente or {}).get("cedula", "")

    if cliente:
        await db.crm_clientes.update_one(
            {"_id": cliente["_id"]},
            {"$push": {"gestiones": {
                "tipo": "whatsapp_inbound",
                "fecha": datetime.now(timezone.utc).isoformat(),
                "mensaje": content_text[:1024], "msg_type": content_type,
                "msg_id": msg_id, "phone": phone, "via": "polling",
                "nota": "Cliente respondio por WhatsApp (polling)",
            }}},
        )

    await publish_event(
        db=db, event_type="cliente.respondio.whatsapp",
        source="polling.mercately",
        datos={"phone": phone, "cedula": cedula, "mensaje": content_text[:1024],
               "msg_type": content_type, "msg_id": msg_id, "via": "polling",
               "created_time": created_time_iso},
        alegra_id=None,
        accion_ejecutada=f"Respuesta WhatsApp poll {cedula or phone}",
    )

    await db.mercately_inbound_audit.insert_one({
        "fecha": datetime.now(timezone.utc), "phone": phone, "msg_id": msg_id,
        "direction": msg.get("direction", "inbound"),
        "content_type": content_type, "content_text": content_text[:1024],
        "created_time_iso": created_time_iso, "evento_publicado": True,
        "cliente_crm_encontrado": bool(cliente), "cedula": cedula, "via": "polling",
    })

    logger.info("polling inbound phone=%s cedula=%s msg=%r",
                phone, cedula, content_text[:80])

    return {"msg_id": msg_id, "phone": phone, "cedula": cedula,
            "cliente_encontrado": bool(cliente)}


async def poll_once(db: AsyncIOMotorDatabase) -> dict:
    client = get_mercately_client()
    if not client.api_key:
        return {"ok": False, "skip": "no_api_key"}

    nuevo_global = datetime.now(timezone.utc)
    phones = await _obtener_phones_activos(db, limit=MAX_PHONES_POR_CICLO)
    if not phones:
        await _set_global_state(db, nuevo_global)
        return {"ok": True, "phones_consultados": 0, "mensajes_procesados": 0,
                "errores_http": 0, "nota": "sin_phones_activos"}

    mensajes_procesados = 0
    errores_http = 0

    for phone in phones:
        last_msg_id, last_seen_dt = await _get_phone_state(db, phone)

        msg_res = await client.get_whatsapp_conversations_by_phone(phone, page=1)
        if not msg_res.get("success"):
            errores_http += 1
            continue

        nuevos = []
        for m in msg_res.get("messages", []):
            if (m.get("direction") or "").lower() != "inbound":
                continue
            mid = str(m.get("id", "") or m.get("message_identifier", ""))
            ct = _iso_to_dt(m.get("created_time", ""))
            if last_seen_dt and ct and ct <= last_seen_dt:
                continue
            if mid and mid == last_msg_id:
                continue
            nuevos.append(m)

        nuevos.sort(key=lambda x: x.get("created_time", ""))

        for m in nuevos:
            try:
                await _process_inbound_message(db, phone, m)
                mensajes_procesados += 1
                await _set_phone_state(
                    db, phone=phone,
                    msg_id=str(m.get("id", "") or m.get("message_identifier", "")),
                    when_iso=m.get("created_time", ""),
                )
            except Exception as exc:
                logger.exception("polling proceso msg fallo phone=%s: %s", phone, exc)

    await _set_global_state(db, nuevo_global)
    todos_fallaron = errores_http > 0 and errores_http == len(phones)

    return {"ok": not todos_fallaron, "phones_consultados": len(phones),
            "mensajes_procesados": mensajes_procesados,
            "errores_http": errores_http,
            "last_global_iso": nuevo_global.isoformat()}


async def run_inbound_poller_loop(db_factory, interval_s: int = 60) -> None:
    logger.info("Mercately inbound poller arrancado (interval=%ds)", interval_s)
    backoff_factor = 1
    max_backoff = 16
    while True:
        had_error = False
        try:
            db = db_factory()
            res = await poll_once(db)
            if res.get("skip"):
                backoff_factor = max_backoff
            elif res.get("ok"):
                if backoff_factor > 1:
                    logger.info("inbound poll recuperado, reset interval")
                    backoff_factor = 1
                if res.get("mensajes_procesados", 0) > 0:
                    logger.info("inbound poll ok phones=%s msgs=%s",
                                res.get("phones_consultados"),
                                res.get("mensajes_procesados"))
            else:
                had_error = True
        except asyncio.CancelledError:
            logger.info("Mercately inbound poller cancelado")
            raise
        except Exception as exc:
            logger.exception("Mercately inbound poller error: %s", exc)
            had_error = True

        if had_error:
            backoff_factor = min(backoff_factor * 2, max_backoff)
        sleep_s = interval_s * backoff_factor
        await asyncio.sleep(sleep_s)
