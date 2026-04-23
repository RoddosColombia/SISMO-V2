"""
services/loanbook/dpd_scheduler.py — Scheduler DPD diario para el módulo Loanbook.

Recalcula DPD, estado, sub_bucket_semanal y mora_acumulada_cop en todos los
loanbooks activos. Corre diariamente a las 06:00 AM America/Bogotá.

Patrón de scheduler: asyncio loop (mismo patrón que core/alegra_sync.py).
Se registra en core/database.py dentro del lifespan de FastAPI.

Emite evento `loanbook.estado.cambiado` al bus cuando hay transición.
Registra en `loanbook_modificaciones` (audit log) cada cambio de estado.

Ref: .planning/LOANBOOK_MAESTRO_v1.1.md cap 3 + cap 4.7
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Optional
from zoneinfo import ZoneInfo

from services.loanbook.estados_service import (
    ESTADOS_ACTIVOS,
    calcular_mora_acumulada,
    clasificar_estado,
    clasificar_sub_bucket,
    validar_transicion,
)

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger("dpd_scheduler")

TZ_BOGOTA = ZoneInfo("America/Bogota")


# ─────────────────────── Cálculo de DPD ──────────────────────────────────────

def _a_fecha(x) -> date:
    """Normaliza datetime / date / ISO string → date."""
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    if isinstance(x, str):
        try:
            return date.fromisoformat(x[:10])
        except ValueError:
            return date.today()
    return date.today()


def _calcular_dpd(cuotas: list[dict], hoy: date) -> int:
    """Calcula DPD basado en la cuota pendiente más antigua.

    Regla (R-22): DPD = días desde fecha_programada de la cuota más antigua
    con estado 'pendiente' o 'parcial' cuya fecha < hoy.

    Args:
        cuotas: lista de documentos cuota del loanbook.
        hoy:    fecha de referencia (normalmente hoy en Bogotá).

    Returns:
        0 si no hay cuotas vencidas. Int >= 1 en caso contrario.
    """
    cuotas_vencidas = [
        c for c in cuotas
        if c.get("estado") in ("pendiente", "parcial", "vencida")
        and c.get("fecha") or c.get("fecha_programada")
        and _a_fecha(c.get("fecha") or c.get("fecha_programada")) < hoy
    ]
    # Re-filtrar correctamente (evitar short-circuit de `and` en la list comp)
    cuotas_vencidas = []
    for c in cuotas:
        if c.get("estado") not in ("pendiente", "parcial", "vencida"):
            continue
        fecha_raw = c.get("fecha") or c.get("fecha_programada")
        if not fecha_raw:
            continue
        fecha = _a_fecha(fecha_raw)
        if fecha < hoy:
            cuotas_vencidas.append((fecha, c))

    if not cuotas_vencidas:
        return 0

    # La cuota más antigua determina el DPD
    mas_antigua_fecha = min(f for f, _ in cuotas_vencidas)
    dias = (hoy - mas_antigua_fecha).days
    return max(0, dias)


# ─────────────────────── Procesamiento de un loanbook ────────────────────────

async def procesar_un_loanbook(
    db: "AsyncIOMotorDatabase",
    lb: dict,
    hoy: date,
) -> dict:
    """Procesa un loanbook: recalcula DPD, estado, sub_bucket, mora.

    Si hay cambio de estado:
      - Valida la transición contra TRANSICIONES_PERMITIDAS
      - Registra en loanbook_modificaciones (audit log)
      - Emite evento loanbook.estado.cambiado al bus

    Args:
        db:  base de datos Motor
        lb:  documento de loanbook
        hoy: fecha de referencia

    Returns:
        dict con { codigo, cambio, estado_anterior, estado_nuevo, dpd_nuevo, error? }
    """
    # Extraer identificadores
    lb_id = lb.get("_id")
    codigo = lb.get("loanbook_id") or lb.get("loanbook_codigo") or str(lb_id)

    estado_anterior = lb.get("estado")
    cuotas = list(lb.get("cuotas", []))  # copia mutable
    saldo_capital = float(lb.get("saldo_capital") or lb.get("saldo_pendiente") or 0)
    plan_codigo = lb.get("plan_codigo") or (lb.get("plan") or {}).get("codigo") or ""

    # 0. Marcar como "vencida" las cuotas pendientes con fecha < hoy (persistir en MongoDB)
    cuotas_a_vencer: list[int] = []
    for i, c in enumerate(cuotas):
        if c.get("estado") != "pendiente":
            continue
        fecha_raw = c.get("fecha_programada") or c.get("fecha")
        if not fecha_raw:
            continue
        fecha = _a_fecha(fecha_raw)
        if fecha < hoy:
            cuotas[i] = {**c, "estado": "vencida"}
            cuotas_a_vencer.append(i)

    if cuotas_a_vencer:
        update_ops = {f"cuotas.{i}.estado": "vencida" for i in cuotas_a_vencer}
        await db.loanbook.update_one({"_id": lb_id}, {"$set": update_ops})
        logger.debug("[DPD] %s: %d cuota(s) marcadas como vencida", codigo, len(cuotas_a_vencer))

    # 1. DPD (sobre la lista local ya actualizada)
    dpd_nuevo = _calcular_dpd(cuotas, hoy)

    # 2. Estado desde clasificador puro
    estado_nuevo = clasificar_estado(dpd_nuevo, saldo_capital, plan_codigo)

    # 3. Sub-bucket
    sub_bucket_nuevo = clasificar_sub_bucket(dpd_nuevo)

    # 4. Mora acumulada sin cap (R-22)
    mora_nueva = calcular_mora_acumulada(dpd_nuevo)

    ts = datetime.now(TZ_BOGOTA)

    updates: dict = {
        "dpd": dpd_nuevo,
        "sub_bucket_semanal": sub_bucket_nuevo,
        "mora_acumulada_cop": mora_nueva,
        "updated_at": ts.isoformat(),
    }

    cambio_estado = estado_nuevo != estado_anterior

    if cambio_estado:
        # Validar transición; si es inválida → no cambiar, registrar alerta
        try:
            validar_transicion(estado_anterior, estado_nuevo)
        except Exception as exc:
            # Log de transición inválida detectada por scheduler
            await db.loanbook_modificaciones.insert_one({
                "loanbook_id": lb_id,
                "loanbook_codigo": codigo,
                "tipo": "transicion_invalida",
                "detalle": str(exc),
                "estado_anterior": estado_anterior,
                "estado_nuevo_propuesto": estado_nuevo,
                "dpd": dpd_nuevo,
                "ts": ts.isoformat(),
                "user_id": "scheduler_dpd",
            })
            # Aún actualizar DPD/sub_bucket/mora, pero no el estado
            await db.loanbook.update_one({"_id": lb_id}, {"$set": updates})
            return {
                "codigo": codigo,
                "cambio": False,
                "estado_anterior": estado_anterior,
                "estado_nuevo": estado_anterior,
                "dpd_nuevo": dpd_nuevo,
                "error": f"Transición inválida: {exc}",
            }

        updates["estado"] = estado_nuevo

        # Audit log en loanbook_modificaciones
        await db.loanbook_modificaciones.insert_one({
            "loanbook_id": lb_id,
            "loanbook_codigo": codigo,
            "tipo": "cambio_estado",
            "campo": "estado",
            "valor_anterior": estado_anterior,
            "valor_nuevo": estado_nuevo,
            "dpd": dpd_nuevo,
            "sub_bucket": sub_bucket_nuevo,
            "ts": ts.isoformat(),
            "user_id": "scheduler_dpd",
            "motivo": "Recálculo automático 06:00 AM",
        })

        # Emitir evento al bus
        try:
            from core.events import publish_event
            await publish_event(
                db=db,
                event_type="loanbook.estado.cambiado",
                source="dpd_scheduler",
                datos={
                    "loanbook_codigo": codigo,
                    "estado_anterior": estado_anterior,
                    "estado_nuevo": estado_nuevo,
                    "dpd": dpd_nuevo,
                    "sub_bucket": sub_bucket_nuevo,
                    "mora_acumulada_cop": mora_nueva,
                },
                alegra_id=None,
                accion_ejecutada=(
                    f"Estado {codigo}: {estado_anterior} → {estado_nuevo} (DPD={dpd_nuevo})"
                ),
            )
        except Exception as exc_ev:
            logger.warning("No se pudo publicar evento loanbook.estado.cambiado: %s", exc_ev)

    # Persistir cambios
    await db.loanbook.update_one({"_id": lb_id}, {"$set": updates})

    return {
        "codigo": codigo,
        "cambio": cambio_estado,
        "estado_anterior": estado_anterior,
        "estado_nuevo": estado_nuevo,
        "dpd_nuevo": dpd_nuevo,
    }


# ─────────────────────── Tarea principal ─────────────────────────────────────

async def calcular_dpd_todos(db: "AsyncIOMotorDatabase") -> dict:
    """Procesa todos los loanbooks activos y actualiza DPD/estado/sub_bucket/mora.

    Args:
        db: base de datos Motor (inyectada desde lifespan o endpoint).

    Returns:
        dict: { total, cambios, sin_cambio, errores, detalle[] }
    """
    hoy = datetime.now(TZ_BOGOTA).date()

    # Incluye Aprobado por si se entrega hoy y pasa a Current
    estados_a_procesar = list(ESTADOS_ACTIVOS)

    loanbooks = await db.loanbook.find(
        {"estado": {"$in": estados_a_procesar}}
    ).to_list(length=None)

    stats: dict = {
        "total": len(loanbooks),
        "cambios": 0,
        "sin_cambio": 0,
        "errores": 0,
        "fecha": hoy.isoformat(),
        "detalle": [],
    }

    for lb in loanbooks:
        try:
            resultado = await procesar_un_loanbook(db, lb, hoy)
            stats["detalle"].append(resultado)
            if resultado.get("error"):
                stats["errores"] += 1
            elif resultado["cambio"]:
                stats["cambios"] += 1
            else:
                stats["sin_cambio"] += 1
        except Exception as exc:
            codigo = lb.get("loanbook_id") or lb.get("loanbook_codigo") or str(lb.get("_id", "?"))
            logger.error("Error procesando %s: %s", codigo, exc)
            stats["errores"] += 1
            stats["detalle"].append({"codigo": codigo, "error": str(exc)})

    logger.info(
        "DPD recalculado: %d total, %d cambios, %d sin cambio, %d errores",
        stats["total"], stats["cambios"], stats["sin_cambio"], stats["errores"],
    )
    return stats


# ─────────────────────── Loop del scheduler ──────────────────────────────────

def _segundos_hasta_proximas_6am() -> float:
    """Calcula cuántos segundos faltan para las 06:00 AM Bogotá."""
    ahora = datetime.now(TZ_BOGOTA)
    proximas_6am = ahora.replace(hour=6, minute=0, second=0, microsecond=0)
    if ahora >= proximas_6am:
        # Ya pasaron las 6am de hoy → siguiente es mañana
        proximas_6am += timedelta(days=1)
    return (proximas_6am - ahora).total_seconds()


async def run_dpd_scheduler(db: "AsyncIOMotorDatabase") -> None:
    """Loop infinito que corre calcular_dpd_todos() a las 06:00 AM Bogotá.

    Patrón: asyncio.create_task() en lifespan (igual que core/alegra_sync.py).
    """
    logger.info("DPD scheduler iniciado")

    while True:
        segundos = _segundos_hasta_proximas_6am()
        logger.info(
            "DPD scheduler: próxima ejecución en %.0f segundos (06:00 AM Bogotá)",
            segundos,
        )
        await asyncio.sleep(segundos)

        try:
            stats = await calcular_dpd_todos(db)
            logger.info("DPD scheduler completado: %s", stats)
        except Exception as exc:
            logger.error("DPD scheduler falló: %s", exc)
