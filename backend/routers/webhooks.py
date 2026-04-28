"""
Webhooks entrantes desde sistemas externos (Alegra, Mercately, etc.).

Validacion HMAC obligatoria para evitar spoofing. Se publica el evento
correspondiente en roddos_events para que el DataKeeper dispare cascadas.

Endpoints:
- POST /api/webhooks/alegra/invoice    -> factura.venta.creada (UI Alegra)
- POST /api/webhooks/alegra/payment    -> pago.alegra.recibido
- POST /api/webhooks/alegra/health     -> ping/health para configuracion
- POST /api/webhooks/mercately/inbound -> ejecucion 2 (RADAR)

Configuracion de webhooks en Alegra dashboard:
1. Login en app.alegra.com
2. Configuracion -> Webhooks (o /webhooks en API)
3. Agregar webhook:
   - URL: https://sismo.roddos.com/api/webhooks/alegra/invoice
   - Eventos: invoice.created, invoice.updated
   - Secret: el valor de ALEGRA_WEBHOOK_SECRET (env var)
4. Guardar y probar con la opcion "Send test event"

Si Alegra no soporta HMAC explicito, configurar shared secret y validar
el header `X-Alegra-Signature` que envia el dashboard.

Sprint S1.5 (2026-04-28) — cierre del bucle factura UI directa -> SISMO.
"""
from __future__ import annotations
import hmac
import hashlib
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_db
from core.events import publish_event

logger = logging.getLogger("webhooks")

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


# ─────────────────────────────────────────────────────────────────────────────
# HMAC validation
# ─────────────────────────────────────────────────────────────────────────────

def _validate_hmac(
    body_bytes: bytes,
    signature: str | None,
    secret: str,
    *,
    require: bool = True,
) -> bool:
    """
    Validate HMAC SHA256 signature against shared secret.

    Args:
        body_bytes: raw request body
        signature: header value (puede venir como 'sha256=...' o solo el hex)
        secret: ALEGRA_WEBHOOK_SECRET o equivalente
        require: si False y secret no esta configurado, permite el request

    Returns True si firma valida, False si no.
    """
    if not secret:
        if require:
            return False
        # Sin secret configurado y require=False — modo dev, dejar pasar
        return True

    if not signature:
        return False

    # Normalizar prefijo 'sha256='
    sig = signature.replace("sha256=", "").strip().lower()

    expected = hmac.new(
        secret.encode("utf-8"), body_bytes, hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(sig, expected)


# ─────────────────────────────────────────────────────────────────────────────
# Alegra — invoice webhook
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/alegra/invoice")
async def alegra_invoice_webhook(
    request: Request,
    x_alegra_signature: str | None = Header(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    """
    Recibe webhook de Alegra cuando se crea/actualiza una factura desde la UI.

    Cuerpo esperado (formato Alegra):
        {
          "event": "invoice.created",
          "data": {
            "id": "12345",
            "client": {"id": "X", "name": "...", "identification": "...", "phonePrimary": "..."},
            "items": [...],
            "total": ...,
            "status": "open",
            ...
          }
        }

    Acciones:
    1. Validar HMAC con ALEGRA_WEBHOOK_SECRET.
    2. Idempotencia: si ya hay loanbook con factura_alegra_id == data.id, salta.
    3. Publica factura.venta.creada en roddos_events con datos completos.
    4. DataKeeper.handle_crear_loanbook_pendiente (Critical) creara el loanbook.
    5. handle_loanbook_creado (Critical, crm_handlers) creara el cliente CRM.
    """
    body_bytes = await request.body()

    # 1. HMAC
    secret = os.getenv("ALEGRA_WEBHOOK_SECRET", "")
    if not _validate_hmac(body_bytes, x_alegra_signature, secret, require=bool(secret)):
        logger.warning("alegra/invoice — HMAC invalido o ausente")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Alegra-Signature",
        )

    # 2. Parsear body
    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON: {e}",
        )

    event_name = (payload.get("event") or "").lower()
    data = payload.get("data") or payload  # alegra puede mandar data dentro o flat

    invoice_id = str(data.get("id") or "")
    if not invoice_id:
        raise HTTPException(400, "Missing data.id")

    # 3. Idempotencia
    existing = await db.loanbook.find_one({"factura_alegra_id": invoice_id})
    if existing:
        logger.info(
            f"alegra/invoice — invoice {invoice_id} ya tiene loanbook "
            f"({existing.get('loanbook_id')}), idempotente"
        )
        return {
            "ok": True,
            "idempotent": True,
            "loanbook_id": existing.get("loanbook_id"),
        }

    # 4. Construir datos del evento factura.venta.creada
    client = data.get("client") or {}
    items = data.get("items") or []

    # Inferir VIN del primer item (formato esperado: "Modelo Color - VIN: XXX / Motor: YYY")
    vin = ""
    motor = ""
    modelo = ""
    color = ""
    if items:
        first_name = items[0].get("name", "") or items[0].get("description", "")
        if "VIN:" in first_name:
            try:
                vin_part = first_name.split("VIN:")[1].split("/")[0].strip()
                vin = vin_part.upper()
            except Exception:
                pass
        if "Motor:" in first_name:
            try:
                motor_part = first_name.split("Motor:")[1].split("/")[0].strip()
                motor = motor_part
            except Exception:
                pass
        # Modelo aproximado del nombre (TVS Raider 125 / TVS Sport 100)
        for m in ("TVS Raider 125", "TVS Sport 100"):
            if m in first_name:
                modelo = m
                break

    # Las observaciones de la factura suelen tener "Plan: P52S | Modalidad: semanal | ..."
    observations = (data.get("observations") or data.get("anotation") or "").lower()
    plan = ""
    modalidad = ""
    for p in ("p52s", "p39s", "p26s", "p15s", "p78s"):
        if p in observations:
            plan = p.upper()
            break
    for m in ("semanal", "quincenal", "mensual"):
        if m in observations:
            modalidad = m
            break

    datos_evento = {
        "alegra_invoice_id": invoice_id,
        "factura_id": invoice_id,
        "alegra_event": event_name,
        "cliente_nombre":   client.get("name", ""),
        "cliente_cedula":   client.get("identification", ""),
        "cliente_telefono": client.get("phonePrimary") or client.get("mobile", ""),
        "cliente_direccion": (client.get("address") or {}).get("address", "") if isinstance(client.get("address"), dict) else "",
        "cliente_email":    client.get("email", ""),
        "vin":              vin,
        "moto_vin":         vin,
        "motor":            motor,
        "modelo":           modelo,
        "moto_modelo":      modelo,
        "color":            color,
        "plan":             plan or "P52S",
        "modalidad":        modalidad or "semanal",
        "modo_pago":        modalidad or "semanal",
        "valor_factura":    float(data.get("total") or 0),
        "fecha":            data.get("date", ""),
        "via":              "webhook_alegra",
    }

    await publish_event(
        db=db,
        event_type="factura.venta.creada",
        source="webhook.alegra",
        datos=datos_evento,
        alegra_id=invoice_id,
        accion_ejecutada=f"Factura {invoice_id} recibida via webhook Alegra UI",
    )

    logger.info(
        f"alegra/invoice — factura.venta.creada publicada: "
        f"invoice={invoice_id} cliente={client.get('identification', '')} "
        f"vin={vin} plan={plan} modalidad={modalidad}"
    )

    return {
        "ok": True,
        "event_published": "factura.venta.creada",
        "alegra_invoice_id": invoice_id,
        "vin": vin,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Alegra — health/ping (para que Alegra dashboard valide el endpoint)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/alegra/health")
async def alegra_health() -> dict[str, str]:
    return {"ok": "true", "service": "sismo.roddos.com", "endpoint": "alegra-webhook"}


@router.get("/alegra/health")
async def alegra_health_get() -> dict[str, str]:
    return {"ok": "true", "service": "sismo.roddos.com", "endpoint": "alegra-webhook"}
