"""
core/datakeeper_handlers_comprobante.py — DataKeeper handlers para flujo
de comprobante de pago WhatsApp → causación automática.

Pipeline (B7→B8→B9→B10→B11):
  B7. inbound_poller publica `comprobante.pago.recibido` con media_url
  B8. Este handler descarga + OCR via Claude Vision → JSON estructurado
  B9. Match cliente con jerarquia de score, identifica cuota
  B10. publish `pago.cuota.recibido` → Contador handler crea journal Alegra
  B11. Mercately envia confirmacion al cliente

JERARQUIA DE MATCH CLIENTE:
  Nivel 1 (score 1.0): phone exacto + 1 solo loanbook activo
  Nivel 2 (0.85):      nombre beneficiario en comprobante == cliente CRM
  Nivel 3 (0.75):      monto exacto = cuota_periodica de loanbook activo unico
  Nivel 4 (0.60):      phone parcial + monto aproximado (+/- 1%)
  Score < 0.6:         backlog_pagos_revisar (decision humana)

TIPOS DE IDENTIFICACION soportados (campo tipo_identificacion en CRM):
  - "PPT" Permiso Proteccion Temporal — PRINCIPAL EN RODDOS (venezolanos)
  - "CC"  Cedula Ciudadania (colombianos)
  - "CE"  Cedula Extranjeria (residentes legales)
  - "PEP" Permiso Especial Permanencia (legacy, anterior a PPT)
  - "PP"  Pasaporte
  - "TI"  Tarjeta Identidad (menores)
  - "NIT" empresas

Sprint B9 (2026-04-28).
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from core.event_handlers import on_event
from core.events import publish_event
from core.tipos_identificacion import normalizar_tipo, TIPO_DEFAULT
from services.ocr.comprobante_extractor import extraer_comprobante

logger = logging.getLogger("datakeeper.comprobante")

# Anti-duplicados: una referencia procesada solo una vez (TTL 90 dias)
TTL_ANTIDUP_DIAS = 90

# Score minimo para auto-aplicar el pago. Debajo de esto, ir a backlog manual
SCORE_MIN_AUTO = 0.75

# Tolerancia de monto para nivel 4 match
MONTO_TOLERANCIA_PCT = 0.01  # ±1%


def _normalize_nombre(s: str) -> str:
    """Normaliza nombre para match: lowercase, trim, sin acentos."""
    if not s:
        return ""
    import unicodedata
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()
    return " ".join(s.split())


async def _match_cliente_y_loanbook(
    db: AsyncIOMotorDatabase,
    phone: str,
    cedula_crm: str,
    nombre_beneficiario: str,
    monto: int,
) -> dict:
    """Match jerarquico cliente + loanbook + cuota a pagar.

    Returns:
        {"match": True, "score": 0.0-1.0, "loanbook_id": str, "cliente_cedula": str,
         "tipo_identificacion": str, "cuota_objetivo": dict, "razon": str}
        |
        {"match": False, "razon": "...", "candidatos": [...]}
    """
    candidatos = []  # [(score, loanbook_doc, razon)]

    # Buscar loanbooks activos del cliente CRM
    if cedula_crm:
        cliente_crm = await db.crm_clientes.find_one({"cedula": cedula_crm})
        if cliente_crm:
            lb_ids = cliente_crm.get("loanbook_ids", [])
            for lb_id in lb_ids:
                lb = await db.loanbook.find_one({"loanbook_id": lb_id})
                if not lb or lb.get("estado") in ("Pagado", "saldado", "castigado"):
                    continue
                # Nivel 1: phone exacto + 1 loanbook activo
                score = 1.0 if len(lb_ids) == 1 else 0.85
                candidatos.append((
                    score,
                    lb,
                    f"phone+cedula match (1 de {len(lb_ids)} loanbooks activos)",
                ))

    # Nivel 2: si hay candidatos, refinar por nombre del beneficiario
    nombre_norm = _normalize_nombre(nombre_beneficiario)
    if nombre_norm and candidatos:
        for i, (score, lb, razon) in enumerate(candidatos):
            cliente_nombre = (lb.get("cliente") or {}).get("nombre", "") or lb.get("cliente_nombre", "")
            cliente_norm = _normalize_nombre(cliente_nombre)
            if cliente_norm and (cliente_norm in nombre_norm or nombre_norm in cliente_norm):
                # boost por match de nombre
                candidatos[i] = (min(1.0, score + 0.1), lb, razon + " + nombre OK")

    # Nivel 3: si SIN candidatos por phone, buscar por monto exacto en clientes activos
    if not candidatos and monto > 0:
        match_monto = []
        async for lb in db.loanbook.find({
            "estado": {"$nin": ["Pagado", "saldado", "castigado", "pendiente_entrega"]},
            "cuota_periodica": monto,
        }).limit(5):
            match_monto.append(lb)
        if len(match_monto) == 1:
            candidatos.append((0.75, match_monto[0], f"monto exacto {monto:,} en 1 cliente"))
        elif len(match_monto) > 1:
            # Ambiguo: ir a backlog
            return {
                "match": False,
                "razon": f"monto {monto:,} match con {len(match_monto)} clientes — ambiguo",
                "candidatos": [lb.get("loanbook_id") for lb in match_monto],
            }

    if not candidatos:
        return {
            "match": False,
            "razon": "no hay match por phone, cedula, nombre ni monto",
            "candidatos": [],
        }

    # Tomar el de mayor score
    candidatos.sort(key=lambda x: -x[0])
    best_score, best_lb, best_razon = candidatos[0]

    # Identificar cuota a pagar (proxima pendiente)
    cuotas = best_lb.get("cuotas") or []
    cuota_objetivo = None
    for c in cuotas:
        if c.get("estado") in ("pendiente", "vencida"):
            cuota_objetivo = c
            break

    cliente_block = best_lb.get("cliente") or {}
    return {
        "match":                True,
        "score":                best_score,
        "loanbook_id":          best_lb.get("loanbook_id"),
        "cliente_cedula":       cliente_block.get("cedula") or best_lb.get("cliente_cedula"),
        "cliente_nombre":       cliente_block.get("nombre") or best_lb.get("cliente_nombre"),
        "tipo_identificacion":  normalizar_tipo(cliente_block.get("tipo_identificacion") or TIPO_DEFAULT),
        "cuota_objetivo":       cuota_objetivo,
        "razon":                best_razon,
    }


async def _ya_procesado(db: AsyncIOMotorDatabase, referencia: str) -> bool:
    """Anti-duplicados: si ya procesamos esta referencia bancaria, skip."""
    if not referencia:
        return False
    existe = await db.pagos_procesados.find_one({"referencia": referencia})
    return existe is not None


@on_event("comprobante.pago.recibido", critical=False)
async def handle_comprobante_recibido(event: dict, db: AsyncIOMotorDatabase) -> None:
    """OCR comprobante → match cliente → aplicar pago automatico.

    Si match >= 0.75 score: aplica pago via dispatcher Loanbook (que ya
    publica cuota.pagada → Contador crea journal Alegra).
    Si <0.75 o ambiguo: guarda en backlog_pagos_revisar para humano.
    """
    datos = event.get("datos") or {}
    phone = datos.get("phone", "")
    cedula = datos.get("cedula", "")
    media_url = datos.get("media_url", "")
    media_type = datos.get("media_type", "")
    msg_id = datos.get("msg_id", "")

    if not media_url:
        logger.warning("comprobante.pago.recibido sin media_url — skip")
        return

    logger.info("OCR comprobante phone=%s cedula=%s media=%s",
                phone, cedula, media_type)

    # 1. OCR via Claude Vision
    extraccion = await extraer_comprobante(media_url, media_type)
    if not extraccion.get("success"):
        # Guardar en backlog con error OCR
        await db.backlog_pagos_revisar.insert_one({
            "fecha":         datetime.now(timezone.utc),
            "phone":         phone,
            "cedula":        cedula,
            "msg_id":        msg_id,
            "media_url":     media_url,
            "razon":         "ocr_fallo",
            "error":         extraccion.get("error"),
            "details":       extraccion.get("details", ""),
            "estado":        "pendiente_revision",
        })
        await publish_event(
            db=db, event_type="comprobante.ocr.fallo",
            source="datakeeper.comprobante",
            datos={"phone": phone, "cedula": cedula, "msg_id": msg_id,
                   "error": extraccion.get("error")},
            alegra_id=None,
            accion_ejecutada=f"OCR fallo: {extraccion.get('error')}",
        )
        return

    # 2. Validar campos clave
    monto = extraccion.get("monto_cop", 0) or 0
    fecha_pago = extraccion.get("fecha", "")
    referencia = extraccion.get("referencia", "")
    confianza_ocr = extraccion.get("confianza", 0)
    valid = extraccion.get("validacion", {})

    if not valid.get("beneficiario_es_roddos"):
        # No es para nosotros — silenciar pero loggear
        await db.backlog_pagos_revisar.insert_one({
            "fecha":     datetime.now(timezone.utc),
            "phone":     phone,
            "razon":     "beneficiario_no_es_roddos",
            "extraccion": extraccion,
            "estado":    "rechazado",
        })
        return

    if confianza_ocr < 0.7 or monto <= 0 or not fecha_pago:
        await db.backlog_pagos_revisar.insert_one({
            "fecha":      datetime.now(timezone.utc),
            "phone":      phone,
            "cedula":     cedula,
            "msg_id":     msg_id,
            "razon":      "ocr_baja_confianza",
            "extraccion": extraccion,
            "estado":     "pendiente_revision",
        })
        return

    # 3. Anti-duplicados por referencia
    if await _ya_procesado(db, referencia):
        logger.info("comprobante referencia=%s ya procesado — skip", referencia)
        return

    # 4. Match cliente + loanbook
    match_res = await _match_cliente_y_loanbook(
        db=db, phone=phone, cedula_crm=cedula,
        nombre_beneficiario=extraccion.get("beneficiario_nombre", ""),
        monto=monto,
    )

    if not match_res.get("match") or match_res.get("score", 0) < SCORE_MIN_AUTO:
        await db.backlog_pagos_revisar.insert_one({
            "fecha":           datetime.now(timezone.utc),
            "phone":           phone,
            "cedula":          cedula,
            "msg_id":          msg_id,
            "razon":           match_res.get("razon", "match_score_bajo"),
            "score_match":     match_res.get("score", 0),
            "extraccion":      extraccion,
            "candidatos":      match_res.get("candidatos", []),
            "estado":          "pendiente_revision",
        })
        await publish_event(
            db=db, event_type="comprobante.match.fallo",
            source="datakeeper.comprobante",
            datos={"phone": phone, "razon": match_res.get("razon"),
                   "score": match_res.get("score", 0),
                   "monto": monto, "referencia": referencia},
            alegra_id=None,
            accion_ejecutada=f"Match fallo: {match_res.get('razon')}",
        )
        return

    # 5. Match exitoso → publicar pago.cuota.recibido para que el Contador
    #    cree el journal en Alegra (B10) y el Loanbook actualice saldo
    loanbook_id = match_res["loanbook_id"]
    cuota_objetivo = match_res.get("cuota_objetivo") or {}

    await publish_event(
        db=db, event_type="pago.cuota.recibido",
        source="datakeeper.comprobante.auto",
        datos={
            "loanbook_id":         loanbook_id,
            "cliente_cedula":      match_res["cliente_cedula"],
            "tipo_identificacion": match_res["tipo_identificacion"],
            "cliente_nombre":      match_res["cliente_nombre"],
            "monto":               monto,
            "fecha_pago":          fecha_pago,
            "metodo":              extraccion.get("tipo_transferencia", "Transferencia"),
            "banco_origen":        extraccion.get("banco_origen", ""),
            "referencia":          referencia,
            "score_match":         match_res["score"],
            "razon_match":         match_res["razon"],
            "cuota_numero":        cuota_objetivo.get("numero"),
            "via":                 "ocr_whatsapp_auto",
            "phone":               phone,
            "msg_id":              msg_id,
        },
        alegra_id=None,
        accion_ejecutada=f"Pago auto WhatsApp ${monto:,} → {loanbook_id} (score {match_res['score']:.2f})",
    )

    # 6. Marcar referencia como procesada
    await db.pagos_procesados.insert_one({
        "fecha":         datetime.now(timezone.utc),
        "referencia":    referencia,
        "loanbook_id":   loanbook_id,
        "monto":         monto,
        "phone":         phone,
        "score_match":   match_res["score"],
        "via":           "ocr_whatsapp_auto",
    })

    logger.info(
        "comprobante OK phone=%s cedula=%s loanbook=%s monto=%s ref=%s score=%.2f",
        phone, match_res["cliente_cedula"], loanbook_id, monto, referencia,
        match_res["score"],
    )
loanbook=%s monto=%s ref=%s score=%.2f",
        phone, match_res["cliente_cedula"], loanbook_id, monto, referencia,
        match_res["score"],
    )
match_res["cliente_cedula"], loanbook_id, monto, referencia,
        match_res["score"],
    )
