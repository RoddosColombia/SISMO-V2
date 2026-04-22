"""
services/loanbook/loanbook_service.py — Operaciones sobre colecciones auxiliares del loanbook.

Funciones:
  - registrar_acuerdo_pago()    → loanbook_acuerdos
  - registrar_cierre()          → loanbook_cierres + actualiza estado en loanbook
  - registrar_modificacion()    → loanbook_modificaciones (audit log)

Todas son async y reciben `db: AsyncIOMotorDatabase`.
Todas retornan el documento insertado (sin _id).

Reglas:
  - registrar_acuerdo_pago: actualiza `acuerdo_activo_id` en el loanbook original
  - registrar_cierre: solo si el loanbook no tiene ya un cierre (idempotente)
  - registrar_modificacion: append-only, nunca actualiza ni borra
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorDatabase


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────── Acuerdos de pago ─────────────────────────────────────

async def registrar_acuerdo_pago(
    db: "AsyncIOMotorDatabase",
    loanbook_id: str,
    cronograma_nuevo: list[dict],
    motivo: str,
    user_id: str,
    metadata: dict[str, Any] | None = None,
) -> dict:
    """Registra un acuerdo de pago en `loanbook_acuerdos`.

    Un acuerdo modifica el cronograma de pagos sin alterar el saldo capital.
    Solo puede haber un acuerdo activo por loanbook (el último reemplaza al anterior).

    Args:
        db:               base de datos Motor
        loanbook_id:      identificador del loanbook afectado
        cronograma_nuevo: lista de cuotas según el nuevo acuerdo
        motivo:           razón del acuerdo (texto libre)
        user_id:          quien crea el acuerdo
        metadata:         campos adicionales opcionales (ej: fecha_reunión)

    Returns:
        dict: documento insertado en loanbook_acuerdos (sin _id)

    Raises:
        ValueError: si loanbook_id no existe o cronograma_nuevo está vacío
    """
    if not cronograma_nuevo:
        raise ValueError("cronograma_nuevo no puede estar vacío")

    lb = await db.loanbook.find_one(
        {"loanbook_id": loanbook_id},
        {"_id": 0, "loanbook_id": 1, "estado": 1},
    )
    if lb is None:
        raise ValueError(f"loanbook_id='{loanbook_id}' no encontrado")

    acuerdo_id = f"ACU-{uuid.uuid4().hex[:8].upper()}"
    ts = _now_iso()

    doc = {
        "acuerdo_id":        acuerdo_id,
        "loanbook_id":       loanbook_id,
        "cronograma_nuevo":  cronograma_nuevo,
        "motivo":            motivo,
        "user_id":           user_id,
        "estado_acuerdo":    "activo",
        "created_at":        ts,
        **(metadata or {}),
    }

    await db.loanbook_acuerdos.insert_one(doc)

    # Actualizar referencia en el loanbook principal
    await db.loanbook.update_one(
        {"loanbook_id": loanbook_id},
        {"$set": {"acuerdo_activo_id": acuerdo_id}},
    )

    # Retornar sin _id
    return {k: v for k, v in doc.items() if k != "_id"}


# ─────────────────────── Cierres ──────────────────────────────────────────────

async def registrar_cierre(
    db: "AsyncIOMotorDatabase",
    loanbook_id: str,
    modo_cierre: str,
    user_id: str,
    paz_y_salvo_url: str | None = None,
    observaciones: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict:
    """Registra el cierre de un crédito en `loanbook_cierres`.

    Idempotente: si ya existe un cierre para este loanbook_id, retorna el existente.
    Actualiza `estado='saldado'` en el loanbook original.

    Args:
        db:               base de datos Motor
        loanbook_id:      identificador del loanbook cerrado
        modo_cierre:      'natural' | 'liquidacion_anticipada' | 'castigo'
        user_id:          quien registra el cierre
        paz_y_salvo_url:  URL del documento paz y salvo (puede ser None)
        observaciones:    texto libre opcional
        metadata:         campos adicionales opcionales

    Returns:
        dict: documento en loanbook_cierres (nuevo o existente, sin _id)

    Raises:
        ValueError: si loanbook_id no existe o modo_cierre no es válido
    """
    MODOS_VALIDOS = {"natural", "liquidacion_anticipada", "castigo"}
    if modo_cierre not in MODOS_VALIDOS:
        raise ValueError(
            f"modo_cierre='{modo_cierre}' inválido. "
            f"Valores válidos: {sorted(MODOS_VALIDOS)}"
        )

    lb = await db.loanbook.find_one(
        {"loanbook_id": loanbook_id},
        {"_id": 0, "loanbook_id": 1, "cliente": 1, "plan_codigo": 1},
    )
    if lb is None:
        raise ValueError(f"loanbook_id='{loanbook_id}' no encontrado")

    # Idempotencia: buscar cierre previo por loanbook_codigo (= loanbook_id)
    existente = await db.loanbook_cierres.find_one(
        {"loanbook_codigo": loanbook_id},
        {"_id": 0},
    )
    if existente:
        return existente  # type: ignore[return-value]

    ts = _now_iso()
    cierre_id = f"CIE-{uuid.uuid4().hex[:8].upper()}"

    doc = {
        "cierre_id":         cierre_id,
        "loanbook_codigo":   loanbook_id,
        "modo_cierre":       modo_cierre,
        "user_id":           user_id,
        "paz_y_salvo_url":   paz_y_salvo_url,
        "observaciones":     observaciones,
        "fecha_cierre":      ts,
        "created_at":        ts,
        **(metadata or {}),
    }

    await db.loanbook_cierres.insert_one(doc)

    # Actualizar estado en loanbook principal
    await db.loanbook.update_one(
        {"loanbook_id": loanbook_id},
        {"$set": {"estado": "saldado", "fecha_cierre": ts}},
    )

    return {k: v for k, v in doc.items() if k != "_id"}


# ─────────────────────── Modificaciones (audit log) ───────────────────────────

async def registrar_modificacion(
    db: "AsyncIOMotorDatabase",
    loanbook_id: str,
    campo: str,
    valor_anterior: Any,
    valor_nuevo: Any,
    user_id: str,
    motivo: str | None = None,
) -> dict:
    """Append-only audit log de modificaciones en `loanbook_modificaciones`.

    Nunca actualiza ni borra entradas previas. Cada llamada genera un nuevo
    documento con timestamp.

    Args:
        db:              base de datos Motor
        loanbook_id:     identificador del loanbook modificado
        campo:           nombre del campo modificado
        valor_anterior:  valor previo (cualquier tipo serializable)
        valor_nuevo:     nuevo valor
        user_id:         quien realizó el cambio
        motivo:          razón del cambio (texto libre, opcional)

    Returns:
        dict: documento insertado (sin _id)

    Raises:
        ValueError: si loanbook_id o campo están vacíos
    """
    if not loanbook_id:
        raise ValueError("loanbook_id no puede estar vacío")
    if not campo:
        raise ValueError("campo no puede estar vacío")

    ts = _now_iso()
    mod_id = f"MOD-{uuid.uuid4().hex[:8].upper()}"

    doc = {
        "mod_id":          mod_id,
        "loanbook_id":     loanbook_id,
        "campo":           campo,
        "valor_anterior":  valor_anterior,
        "valor_nuevo":     valor_nuevo,
        "user_id":         user_id,
        "motivo":          motivo,
        "ts":              ts,
    }

    await db.loanbook_modificaciones.insert_one(doc)

    return {k: v for k, v in doc.items() if k != "_id"}
