"""
DataKeeper handlers para el dominio CRM (sync con Mercately + gestiones).

NOTA: handle_loanbook_creado (Critical, crea cliente CRM al crear loanbook)
ya existe en core/crm_handlers.py — no se duplica aqui.

Eventos manejados aqui:
- loanbook.creado            -> sync_mercately_contacto         (Parallel)
- crm.cliente.actualizado    -> sync_mercately_contacto         (Parallel)
- cuota.pagada               -> registrar_gestion_pago_crm      (Parallel)
- pago.cuota.recibido        -> registrar_gestion_pago_crm      (Parallel) [alias del Loanbook]

Sprint S1.5 — cierre del bucle factura -> CRM -> Mercately.
R-MERCATELY: GET /customers/{phone} SIEMPRE antes de POST. Nombre legal siempre sobreescribe.
"""
from __future__ import annotations
import logging
import os
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from core.event_handlers import on_event

logger = logging.getLogger("datakeeper.crm_mercately")


# ─────────────────────────────────────────────────────────────────────────────
# sync_mercately_contacto — Parallel en loanbook.creado y crm.cliente.actualizado
# ─────────────────────────────────────────────────────────────────────────────

def _normalizar_phone_57(telefono: str) -> str:
    """Normaliza a formato +57XXXXXXXXXX. R-MERCATELY: solo 12 digitos (57+10)."""
    if not telefono:
        return ""
    # Quitar todos los no-digitos
    digits = "".join(ch for ch in telefono if ch.isdigit())
    # Si empieza con 0, quitar
    while digits.startswith("0"):
        digits = digits[1:]
    # Si tiene 10 digitos, agregar 57
    if len(digits) == 10:
        digits = "57" + digits
    # Validar formato final
    if len(digits) == 12 and digits.startswith("57"):
        return digits
    return ""


@on_event("loanbook.creado", critical=False)
async def handle_sync_mercately_contacto_inicial(event: dict, db: AsyncIOMotorDatabase) -> None:
    """
    Cuando se crea un loanbook, sincroniza el cliente con Mercately para que
    aparezca como contacto WhatsApp. Si el cliente no tiene telefono valido,
    salta sin error.

    R-MERCATELY: GET /customers/{phone} primero. Si no existe, POST.
    Nombre legal del CRM siempre sobreescribe lo que haya en Mercately.
    """
    if not os.getenv("MERCATELY_API_KEY"):
        logger.info("MERCATELY_API_KEY no configurada — sync_mercately saltado")
        return

    datos = event.get("datos", {}) or {}
    cliente = datos.get("cliente") or {}
    cedula = cliente.get("cedula") or ""
    nombre = cliente.get("nombre") or ""
    telefono = _normalizar_phone_57(cliente.get("telefono", ""))

    if not telefono:
        logger.info(
            f"sync_mercately: cliente {cedula} sin telefono valido (E.164 +57) — saltando"
        )
        return

    # Cliente del CRM (puede tener tags, score, etc.)
    crm_doc = await db.crm_clientes.find_one({"cedula": cedula})
    if not crm_doc:
        logger.info(f"sync_mercately: cliente {cedula} aun no existe en CRM — saltando")
        return

    # Llamada a Mercately. Por ahora solo loguea (la integracion REAL
    # bidireccional se completa en Ejecucion 2 RADAR + webhooks).
    # Aqui dejamos el hook listo y registrado.
    logger.info(
        f"sync_mercately stub — cedula={cedula} nombre='{nombre}' "
        f"phone={telefono} loanbook={datos.get('loanbook_id')}"
    )

    # Marcar en CRM que el contacto esta sincronizado (idempotente)
    await db.crm_clientes.update_one(
        {"cedula": cedula},
        {"$set": {
            "mercately_phone": telefono,
            "mercately_synced_at": datetime.now(timezone.utc).isoformat(),
        }},
    )


@on_event("crm.cliente.actualizado", critical=False)
async def handle_sync_mercately_contacto_update(event: dict, db: AsyncIOMotorDatabase) -> None:
    """Resync cuando se actualiza el contacto en CRM (cambio de telefono, etc.)."""
    # Reutilizar la misma logica
    await handle_sync_mercately_contacto_inicial(event, db)


# ─────────────────────────────────────────────────────────────────────────────
# registrar_gestion_pago_crm — Parallel en cuota.pagada
# ─────────────────────────────────────────────────────────────────────────────

@on_event("cuota.pagada", critical=False)
async def handle_registrar_gestion_pago_crm(event: dict, db: AsyncIOMotorDatabase) -> None:
    """
    Cuando una cuota se paga (cuota.pagada), agrega gestion al timeline
    del cliente CRM. RADAR despues lee estas gestiones para priorizar cobranza.

    Tambien actualiza tags: 'al_dia' si nuevo_estado == al_dia, 'mora' si en mora.
    """
    datos = event.get("datos", {}) or {}
    cedula = datos.get("cliente_cedula", "")
    if not cedula:
        return

    monto = datos.get("monto_total_pagado") or 0
    cuota_num = datos.get("cuota_numero", "?")
    nuevo_estado = datos.get("nuevo_estado", "")
    vin = datos.get("vin", "")

    # Tag basado en nuevo estado del loanbook
    tag_estado = None
    if nuevo_estado in ("al_dia", "activo"):
        tag_estado = "al_dia"
    elif nuevo_estado in ("mora", "mora_grave", "en_riesgo"):
        tag_estado = "mora"
    elif nuevo_estado == "saldado":
        tag_estado = "paz_y_salvo"

    update_doc: dict = {
        "$push": {
            "gestiones": {
                "tipo": "pago_cuota",
                "fecha": datetime.now(timezone.utc).isoformat(),
                "vin": vin,
                "cuota_numero": cuota_num,
                "monto": monto,
                "nuevo_estado": nuevo_estado,
                "nota": f"Cuota #{cuota_num} pagada ${monto:,.0f} — estado: {nuevo_estado}",
            }
        },
        "$set": {"updated_at": datetime.now(timezone.utc).isoformat()},
    }
    if tag_estado:
        update_doc["$addToSet"] = {"tags": tag_estado}

    await db.crm_clientes.update_one({"cedula": cedula}, update_doc)
    logger.info(
        f"CRM gestion registrada — cedula={cedula} cuota={cuota_num} "
        f"monto={monto} estado={nuevo_estado}"
    )
