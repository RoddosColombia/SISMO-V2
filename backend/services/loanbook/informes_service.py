"""
services/loanbook/informes_service.py — Informe semanal de créditos sin pago.

Lógica pura de generación. El scheduler llama generar_informe_semanal() los jueves.
También ejecutable manualmente via POST /api/informes/generar.

Colección MongoDB: informes_semanales
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date as date_type, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger("services.loanbook.informes")

TZ_BOGOTA = ZoneInfo("America/Bogota")

_ESTADOS_EXCLUIDOS = {"Pagado", "Aprobado", "pagado", "saldado", "Charge-Off", "castigado"}


# ─────────────────────── Semana ISO ───────────────────────────────────────────

def _semana_id(d: "datetime | None" = None) -> str:
    """Retorna semana ISO: '2026-W17'. Usa hoy si no se especifica fecha."""
    from datetime import date
    hoy = d or date.today()
    return hoy.strftime("%Y-W%W")


def _jueves_de_semana(d: "datetime | None" = None) -> str:
    """Fecha del jueves de la semana actual como ISO string."""
    from datetime import date
    hoy = d or date.today()
    dias_para_jueves = (3 - hoy.weekday()) % 7
    jueves = hoy + timedelta(days=dias_para_jueves)
    return jueves.isoformat()


# ─────────────────────── Generador principal ──────────────────────────────────

async def generar_informe_semanal(
    db: "AsyncIOMotorDatabase",
    generado_por: str = "scheduler",
    forzar: bool = False,
) -> dict:
    """Genera el informe semanal de créditos sin pago.

    Un crédito aparece si:
    - estado no está en ESTADOS_EXCLUIDOS
    - dpd > 0 (mora activa), O tiene cuotas vencidas/pendientes con fecha <= hoy

    Args:
        db:           base de datos Motor
        generado_por: "scheduler" | "manual"
        forzar:       si True, sobreescribe el informe existente de la semana

    Returns:
        dict con semana_id, total_sin_pago, ok
    """
    from datetime import date
    hoy = date.today()
    semana_id = _semana_id(hoy)
    fecha_corte = _jueves_de_semana(hoy)

    # Idempotencia: no duplicar si ya existe (a menos que forzar=True)
    existente = await db.informes_semanales.find_one({"semana_id": semana_id})
    if existente and not forzar:
        return {
            "ok": True,
            "semana_id": semana_id,
            "total_sin_pago": existente.get("total_sin_pago", 0),
            "mensaje": "Ya existe informe para esta semana",
        }

    # Loanbooks activos
    lbs = await db.loanbook.find(
        {"estado": {"$nin": list(_ESTADOS_EXCLUIDOS)}}
    ).to_list(length=None)

    sin_pago = []

    for lb in lbs:
        dpd = lb.get("dpd") or 0
        cuotas = lb.get("cuotas") or []

        # Normalizar fechas correctamente — fecha_programada puede ser datetime (Motor),
        # date, o string ISO. La comparación string vs datetime da resultados incorrectos.
        cuotas_problema = []
        for c in cuotas:
            if c.get("estado") not in ("vencida", "pendiente", "parcial"):
                continue
            fecha_raw = c.get("fecha_programada") or c.get("fecha")
            if not fecha_raw:
                continue
            if isinstance(fecha_raw, datetime):
                fecha = fecha_raw.date()
            elif isinstance(fecha_raw, date_type):
                fecha = fecha_raw
            elif isinstance(fecha_raw, str):
                try:
                    fecha = date_type.fromisoformat(fecha_raw[:10])
                except ValueError:
                    continue
            else:
                continue
            if fecha < hoy:
                cuotas_problema.append(c)

        if dpd > 0 or cuotas_problema:
            cliente = lb.get("cliente") or {}
            sin_pago.append({
                "loanbook_id": lb.get("loanbook_id") or lb.get("loanbook_codigo"),
                "cliente_nombre": cliente.get("nombre") or lb.get("cliente_nombre", ""),
                "telefono": cliente.get("telefono") or lb.get("cliente_telefono", ""),
                "saldo": float(lb.get("saldo_pendiente") or lb.get("saldo_capital") or 0),
                "cuotas_vencidas": len(cuotas_problema),
                "dpd": dpd,
                "sub_bucket": lb.get("sub_bucket_semanal"),
                "estado_gestion": "pendiente",
                "notas": "",
                "actualizado_por": None,
                "actualizado_at": None,
            })

    # Ordenar: más urgente primero (DPD desc, cuotas vencidas desc)
    sin_pago.sort(key=lambda x: (x["dpd"], x["cuotas_vencidas"]), reverse=True)

    informe = {
        "semana_id": semana_id,
        "fecha_corte": fecha_corte,
        "fecha_generacion": datetime.utcnow(),
        "generado_por": generado_por,
        "sin_pago": sin_pago,
        "total_sin_pago": len(sin_pago),
        "valor_en_riesgo": sum(x["saldo"] for x in sin_pago),
        "notas_generales": "",
    }

    if existente and forzar:
        await db.informes_semanales.replace_one({"semana_id": semana_id}, informe)
    else:
        await db.informes_semanales.insert_one(informe)

    logger.info(
        "Informe semanal %s generado: %d créditos sin pago, valor_en_riesgo=$%.0f",
        semana_id, len(sin_pago), informe["valor_en_riesgo"],
    )
    return {"ok": True, "semana_id": semana_id, "total_sin_pago": len(sin_pago)}


# ─────────────────────── Scheduler — jueves 09:00 AM Bogotá ──────────────────

def _segundos_hasta_proximo_jueves_9am() -> float:
    """Cuántos segundos faltan para el próximo jueves 09:00 AM Bogotá."""
    ahora = datetime.now(TZ_BOGOTA)
    # Jueves = weekday 3
    dias_hasta_jueves = (3 - ahora.weekday()) % 7
    proximo = ahora.replace(hour=9, minute=0, second=0, microsecond=0)
    proximo = proximo + timedelta(days=dias_hasta_jueves)
    if proximo <= ahora:
        proximo += timedelta(weeks=1)
    return (proximo - ahora).total_seconds()


async def run_informes_scheduler(db: "AsyncIOMotorDatabase") -> None:
    """Loop infinito: genera informe semanal cada jueves a las 09:00 AM Bogotá.

    Sigue el mismo patrón que run_dpd_scheduler en dpd_scheduler.py.
    """
    logger.info("Informes scheduler iniciado")

    while True:
        segundos = _segundos_hasta_proximo_jueves_9am()
        logger.info(
            "Informes scheduler: próxima ejecución en %.0f s (jueves 09:00 AM Bogotá)",
            segundos,
        )
        await asyncio.sleep(segundos)

        try:
            result = await generar_informe_semanal(db, generado_por="scheduler")
            logger.info("Informes scheduler completado: %s", result)
        except Exception as exc:
            logger.error("Informes scheduler falló: %s", exc)
