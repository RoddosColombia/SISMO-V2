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

    # 5. Match exitoso → aplicar waterfall + actualizar loanbook + publicar
    #    cuota.pagada (schema canonico que el handler Contador ya escucha)
    loanbook_id = match_res["loanbook_id"]
    cuota_objetivo = match_res.get("cuota_objetivo") or {}

    # Lookup loanbook completo + aplicar waterfall canonico
    from core.loanbook_model import aplicar_waterfall, calcular_dpd, estado_from_dpd
    from datetime import date as _date
    lb = await db.loanbook.find_one({"loanbook_id": loanbook_id})
    if not lb:
        logger.error("loanbook %s no existe — abortando", loanbook_id)
        return

    saldo_capital = lb.get("saldo_capital", 0) or 0
    cuotas = lb.get("cuotas") or []
    try:
        fpago = _date.fromisoformat(fecha_pago[:10])
    except Exception:
        fpago = _date.today()

    allocation = aplicar_waterfall(
        monto_pago=monto, cuotas=cuotas, fecha_pago=fpago,
        anzi_pct=lb.get("anzi_pct", 0.02), saldo_capital=saldo_capital,
    )

    # Marcar cuotas pagadas
    rem_v = allocation["vencidas"]; rem_c = allocation["corriente"]
    fpago_str = fpago.isoformat()
    for cu in cuotas:
        if cu.get("estado") == "pagada":
            continue
        cu_monto = cu.get("monto") or lb.get("cuota_periodica", 0) or 0
        if cu.get("fecha"):
            try:
                fc = _date.fromisoformat(cu["fecha"])
            except Exception:
                continue
            if fc < fpago and rem_v >= cu_monto:
                cu["estado"] = "pagada"; cu["fecha_pago"] = fpago_str
                cu["monto_pagado"] = cu_monto; cu["metodo_pago"] = extraccion.get("tipo_transferencia", "Transferencia")
                cu["banco"] = extraccion.get("banco_origen", ""); cu["referencia"] = referencia
                rem_v -= cu_monto
                continue
            if fc >= fpago and rem_c >= cu_monto:
                cu["estado"] = "pagada"; cu["fecha_pago"] = fpago_str
                cu["monto_pagado"] = cu_monto; cu["metodo_pago"] = extraccion.get("tipo_transferencia", "Transferencia")
                cu["banco"] = extraccion.get("banco_origen", ""); cu["referencia"] = referencia
                rem_c -= cu_monto
                break

    # Actualizar saldos
    nuevo_saldo_capital = max(0, saldo_capital - allocation["corriente"] - allocation["vencidas"] - allocation["capital"])
    cuotas_pagadas_n = sum(1 for c in cuotas if c.get("estado") == "pagada")
    cuotas_vencidas_n = sum(1 for c in cuotas if c.get("estado") != "pagada"
                            and c.get("fecha") and _date.fromisoformat(c["fecha"]) < _date.today())
    dpd = calcular_dpd(cuotas, fpago)
    nuevo_estado = estado_from_dpd(dpd)
    saldo_intereses_n = lb.get("saldo_intereses", 0) or 0
    saldo_pendiente_n = nuevo_saldo_capital + saldo_intereses_n

    await db.loanbook.update_one(
        {"loanbook_id": loanbook_id},
        {"$set": {
            "cuotas": cuotas, "saldo_capital": nuevo_saldo_capital,
            "saldo_pendiente": saldo_pendiente_n, "estado": nuevo_estado,
            "cuotas_pagadas": cuotas_pagadas_n, "cuotas_vencidas": cuotas_vencidas_n,
            "dpd": dpd, "fecha_ultimo_pago": fpago_str,
            "mora_acumulada_cop": 0 if dpd == 0 else lb.get("mora_acumulada_cop", 0),
            "total_pagado": (lb.get("total_pagado", 0) or 0) + monto,
            "total_mora_pagada": (lb.get("total_mora_pagada", 0) or 0) + allocation["mora"],
            "total_anzi_pagado": (lb.get("total_anzi_pagado", 0) or 0) + allocation["anzi"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )

    # Publicar cuota.pagada con schema canonico (lo que el Contador ya escucha)
    # Mapeo banco_origen del comprobante → banco_recibo Alegra payment ID
    BANCOS_ALEGRA = {"bancolombia": "5314", "bbva": "5318", "davivienda": "5322",
                     "nequi": "5314", "global66": "5536"}
    banco_norm = (extraccion.get("banco_origen", "") or "").lower()
    banco_recibo = next((v for k, v in BANCOS_ALEGRA.items() if k in banco_norm), "5314")

    await publish_event(
        db=db, event_type="cuota.pagada",
        source="datakeeper.comprobante.auto",
        datos={
            "loanbook_id":         loanbook_id,
            "vin":                 lb.get("vin", ""),
            "cliente_nombre":      match_res["cliente_nombre"],
            "cliente_cedula":      match_res["cliente_cedula"],
            "tipo_identificacion": match_res["tipo_identificacion"],
            "cuota_numero":        cuota_objetivo.get("numero"),
            "monto_total_pagado":  monto,
            "desglose": {
                "cuota_corriente": allocation["corriente"],
                "vencidas":        allocation["vencidas"],
                "anzi":            allocation["anzi"],
                "mora":            allocation["mora"],
                "capital_extra":   allocation["capital"],
            },
            "banco_recibo":        banco_recibo,
            "banco_origen":        extraccion.get("banco_origen", ""),
            "fecha_pago":          fpago_str,
            "modelo_moto":         lb.get("modelo", ""),
            "plan_codigo":         lb.get("plan_codigo", ""),
            "modalidad":           lb.get("modalidad", ""),
            "nuevo_estado":        nuevo_estado,
            "dpd":                 dpd,
            "referencia":          referencia,
            "score_match":         match_res["score"],
            "via":                 "ocr_whatsapp_auto",
        },
        alegra_id=None,
        accion_ejecutada=f"Pago auto WhatsApp ${monto:,} → {loanbook_id} (score {match_res['score']:.2f})",
    )

    # Si saldó completamente, publicar loanbook.saldado
    if nuevo_saldo_capital == 0 and cuotas_vencidas_n == 0:
        cuotas_pendientes_n = sum(1 for c in cuotas if c.get("estado") != "pagada")
        if cuotas_pendientes_n == 0:
            await publish_event(
                db=db, event_type="loanbook.saldado",
                source="datakeeper.comprobante.auto",
                datos={"loanbook_id": loanbook_id, "vin": lb.get("vin", ""),
                       "cliente_cedula": match_res["cliente_cedula"]},
                alegra_id=None,
                accion_ejecutada=f"Loanbook {loanbook_id} saldado vía pago WhatsApp auto",
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
nto; cu["metodo_pago"] = extraccion.get("tipo_transferencia", "Transferencia")
                cu["banco"] = extraccion.get("banco_origen", ""); cu["referencia"] = referencia
                rem_c -= cu_monto
                break

    # Actualizar saldos
    nuevo_saldo_capital = max(0, saldo_capital - allocation["corriente"] - allocation["vencidas"] - allocation["capital"])
    cuotas_pagadas_n = sum(1 for c in cuotas if c.get("estado") == "pagada")
    cuotas_vencidas_n = sum(1 for c in cuotas if c.get("estado") != "pagada"
                            and c.get("fecha") and _date.fromisoformat(c["fecha"]) < _date.today())
    dpd = calcular_dpd(cuotas, fpago)
    nuevo_estado = estado_from_dpd(dpd)
    saldo_intereses_n = lb.get("saldo_intereses", 0) or 0
    saldo_pendiente_n = nuevo_saldo_capital + saldo_intereses_n

    await db.loanbook.update_one(
        {"loanbook_id": loanbook_id},
        {"$set": {
            "cuotas": cuotas, "saldo_capital": nuevo_saldo_capital,
            "saldo_pendiente": saldo_pendiente_n, "estado": nuevo_estado,
            "cuotas_pagadas": cuotas_pagadas_n, "cuotas_vencidas": cuotas_vencidas_n,
            "dpd": dpd, "fecha_ultimo_pago": fpago_str,
            "mora_acumulada_cop": 0 if dpd == 0 else lb.get("mora_acumulada_cop", 0),
            "total_pagado": (lb.get("total_pagado", 0) or 0) + monto,
            "total_mora_pagada": (lb.get("total_mora_pagada", 0) or 0) + allocation["mora"],
            "total_anzi_pagado": (lb.get("total_anzi_pagado", 0) or 0) + allocation["anzi"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )

    # Publicar cuota.pagada con schema canonico
    BANCOS_ALEGRA = {"bancolombia": "5314", "bbva": "5318", "davivienda": "5322",
                     "nequi": "5314", "global66": "5536"}
    banco_norm = (extraccion.get("banco_origen", "") or "").lower()
    banco_recibo = next((v for k, v in BANCOS_ALEGRA.items() if k in banco_norm), "5314")

    await publish_event(
        db=db, event_type="cuota.pagada",
        source="datakeeper.comprobante.auto",
        datos={
            "loanbook_id": loanbook_id, "vin": lb.get("vin", ""),
            "cliente_nombre": match_res["cliente_nombre"],
            "cliente_cedula": match_res["cliente_cedula"],
            "tipo_identificacion": match_res["tipo_identificacion"],
            "cuota_numero": cuota_objetivo.get("numero"),
            "monto_total_pagado": monto,
            "desglose": {
                "cuota_corriente": allocation["corriente"],
                "vencidas": allocation["vencidas"],
                "anzi": allocation["anzi"],
                "mora": allocation["mora"],
                "capital_extra": allocation["capital"],
            },
            "banco_recibo": banco_recibo,
            "banco_origen": extraccion.get("banco_origen", ""),
            "fecha_pago": fpago_str,
            "modelo_moto": lb.get("modelo", ""),
            "plan_codigo": lb.get("plan_codigo", ""),
            "modalidad": lb.get("modalidad", ""),
            "nuevo_estado": nuevo_estado, "dpd": dpd,
            "referencia": referencia, "score_match": match_res["score"],
            "via": "ocr_whatsapp_auto",
        },
        alegra_id=None,
        accion_ejecutada=f"Pago auto WhatsApp ${monto:,} → {loanbook_id} score={match_res['score']:.2f}",
    )

    if nuevo_saldo_capital == 0 and cuotas_vencidas_n == 0:
        cuotas_pendientes_n = sum(1 for c in cuotas if c.get("estado") != "pagada")
        if cuotas_pendientes_n == 0:
            await publish_event(
                db=db, event_type="loanbook.saldado",
                source="datakeeper.comprobante.auto",
                datos={"loanbook_id": loanbook_id, "vin": lb.get("vin", ""),
                       "cliente_cedula": match_res["cliente_cedula"]},
                alegra_id=None,
                accion_ejecutada=f"Loanbook {loanbook_id} saldado",
            )
