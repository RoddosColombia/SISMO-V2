"""
agents/radar/alertas.py — Envío masivo de alertas de cobro via WhatsApp (Mercately).

Ley colombiana (Ley 2300/2023 'Ley Dejen de Fregar'):
  - Máximo 1 contacto por día, lunes-viernes 7AM-7PM, sábado 8AM-3PM.
  - Prohibido domingos y festivos.

El cobro de RODDOS es los miércoles — las alertas se lanzan a las 8:00 AM.
El scheduler corre SOLO los miércoles via run_radar_scheduler() en database.py.

Templates Mercately:
  - COBRO: 3 params — [nombre_corto, monto_formato, fecha_ddmmm]
  - MORA:  3 params — [nombre_corto, dpd_str, mora_cop_formato]

dry_run=True: calcula destinatarios y loguea sin enviar nada (para testing/preview).
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from core.datetime_utils import now_iso_bogota, today_bogota
from services.mercately.client import MercatelyClient

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger("radar.alertas")

# Estado excluidos de alertas
_ESTADOS_EXCLUIDOS = frozenset({"saldado", "castigado", "pendiente_entrega"})

# Meses en español para formato de fecha (ej: "23 abr")
_MESES = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic",
}


def _nombre_corto(nombre_completo: str) -> str:
    """Extrae el primer nombre para el mensaje (max 15 chars para no cortar template)."""
    partes = (nombre_completo or "").strip().split()
    return partes[0] if partes else "Conductor"


def _formato_monto(monto: float) -> str:
    """$120,000 sin decimales."""
    return f"${int(monto):,}".replace(",", ".")


def _formato_fecha(fecha_iso: str) -> str:
    """'2026-04-23' → '23 abr'."""
    try:
        from datetime import date
        d = date.fromisoformat(fecha_iso[:10])
        return f"{d.day} {_MESES[d.month]}"
    except Exception:
        return fecha_iso


def _proxima_cuota_pendiente(cuotas: list[dict], hoy_str: str) -> dict | None:
    """Retorna la primera cuota pendiente (no pagada) con fecha >= hoy."""
    for c in cuotas:
        if c.get("estado") == "pagada":
            continue
        fecha = c.get("fecha", "")
        if fecha and fecha >= hoy_str:
            return c
    return None


async def enviar_alertas_cobro(db: "AsyncIOMotorDatabase", dry_run: bool = False) -> dict:
    """Envía alertas de cobro WhatsApp a conductores con cuota pendiente hoy (miércoles).

    También envía alertas de mora a conductores con DPD > 0.

    Args:
        db:       Conexión MongoDB (Motor async).
        dry_run:  Si True, calcula y loguea sin enviar mensajes ni guardar en BD.

    Returns:
        {
            "alertas_cobro": int,   # mensajes de cobro enviados (o que se enviarían)
            "alertas_mora":  int,   # mensajes de mora enviados
            "errores":       int,   # mensajes que fallaron
            "skipped":       int,   # sin teléfono / sin template configurado
            "es_miercoles":  bool,
            "dry_run":       bool,
            "detalle":       list,  # resultado por loanbook
        }
    """
    hoy = today_bogota()
    hoy_str = hoy.isoformat()

    # Verificar que sea miércoles (weekday 2)
    if hoy.weekday() != 2:
        logger.info(
            "RADAR alertas: hoy es %s (%s), no es miércoles — sin envíos.",
            hoy_str, hoy.strftime("%A"),
        )
        return {
            "alertas_cobro": 0,
            "alertas_mora":  0,
            "errores":       0,
            "skipped":       0,
            "es_miercoles":  False,
            "dry_run":       dry_run,
            "detalle":       [],
            "mensaje":       f"No es miércoles ({hoy.strftime('%A')} {hoy_str}). Sin envíos.",
        }

    template_cobro_id = os.getenv("MERCATELY_TEMPLATE_COBRO_ID", "")
    template_mora_id  = os.getenv("MERCATELY_TEMPLATE_MORA_ID",  "")

    mercately = MercatelyClient()

    # Cargar loanbooks activos
    loanbooks = await db.loanbook.find(
        {"estado": {"$nin": list(_ESTADOS_EXCLUIDOS)}}
    ).to_list(length=2000)

    stats = {
        "alertas_cobro": 0,
        "alertas_mora":  0,
        "errores":       0,
        "skipped":       0,
        "es_miercoles":  True,
        "dry_run":       dry_run,
        "detalle":       [],
    }

    for lb in loanbooks:
        lb_id   = lb.get("loanbook_id", str(lb.get("_id", "?")))
        cliente = lb.get("cliente", {})
        nombre  = cliente.get("nombre") or lb.get("nombre_conductor") or "Conductor"
        telefono = (
            cliente.get("telefono")
            or cliente.get("telefono_alternativo")
            or lb.get("telefono")
            or ""
        )
        cuotas  = lb.get("cuotas", [])
        dpd     = lb.get("dpd") or 0
        mora_cop = lb.get("mora_acumulada_cop") or 0
        nombre_c = _nombre_corto(nombre)

        if not telefono:
            stats["skipped"] += 1
            stats["detalle"].append({
                "loanbook_id": lb_id,
                "tipo": "skip",
                "razon": "sin_telefono",
            })
            await _guardar_alerta(db, lb_id, "cobro", "", "skip_sin_telefono", {}, dry_run)
            continue

        # ── ALERTA COBRO: cuota pendiente hoy ──────────────────────────
        cuota_hoy = _proxima_cuota_pendiente(cuotas, hoy_str)
        if cuota_hoy and cuota_hoy.get("fecha", "") == hoy_str:
            monto_cuota = cuota_hoy.get("monto") or lb.get("cuota_monto") or 0

            if not template_cobro_id:
                stats["skipped"] += 1
                stats["detalle"].append({
                    "loanbook_id": lb_id,
                    "tipo": "skip_cobro",
                    "razon": "MERCATELY_TEMPLATE_COBRO_ID no configurado",
                })
            else:
                params = [
                    nombre_c,
                    _formato_monto(monto_cuota),
                    _formato_fecha(hoy_str),
                ]

                if dry_run:
                    result = {"success": True, "message_id": "dry_run", "raw": {}}
                    estado_log = "skip_dry_run"
                    logger.info(
                        "RADAR [DRY RUN] cobro → %s (%s) params=%s",
                        nombre_c, telefono, params,
                    )
                else:
                    result = await mercately.send_template(telefono, template_cobro_id, params)
                    estado_log = "enviado" if result["success"] else "error"

                if result["success"]:
                    stats["alertas_cobro"] += 1
                else:
                    stats["errores"] += 1

                stats["detalle"].append({
                    "loanbook_id": lb_id,
                    "tipo": "cobro",
                    "telefono": telefono,
                    "nombre": nombre_c,
                    "monto": monto_cuota,
                    "resultado": result,
                })
                await _guardar_alerta(db, lb_id, "cobro", telefono, estado_log, result, dry_run)

        # ── ALERTA MORA: DPD > 0 ───────────────────────────────────────
        if dpd and dpd > 0:
            if not template_mora_id:
                stats["skipped"] += 1
                stats["detalle"].append({
                    "loanbook_id": lb_id,
                    "tipo": "skip_mora",
                    "razon": "MERCATELY_TEMPLATE_MORA_ID no configurado",
                })
            else:
                params_mora = [
                    nombre_c,
                    str(dpd),
                    _formato_monto(mora_cop),
                ]

                if dry_run:
                    result_mora = {"success": True, "message_id": "dry_run", "raw": {}}
                    estado_log_mora = "skip_dry_run"
                    logger.info(
                        "RADAR [DRY RUN] mora → %s (%s) DPD=%d params=%s",
                        nombre_c, telefono, dpd, params_mora,
                    )
                else:
                    result_mora = await mercately.send_template(
                        telefono, template_mora_id, params_mora
                    )
                    estado_log_mora = "enviado" if result_mora["success"] else "error"

                if result_mora["success"]:
                    stats["alertas_mora"] += 1
                else:
                    stats["errores"] += 1

                stats["detalle"].append({
                    "loanbook_id": lb_id,
                    "tipo": "mora",
                    "telefono": telefono,
                    "nombre": nombre_c,
                    "dpd": dpd,
                    "mora_cop": mora_cop,
                    "resultado": result_mora,
                })
                await _guardar_alerta(db, lb_id, "mora", telefono, estado_log_mora, result_mora, dry_run)

    logger.info(
        "RADAR alertas cobro %s: cobro=%d mora=%d errores=%d skipped=%d",
        "(dry_run)" if dry_run else "",
        stats["alertas_cobro"], stats["alertas_mora"],
        stats["errores"], stats["skipped"],
    )
    return stats


async def _guardar_alerta(
    db: "AsyncIOMotorDatabase",
    loanbook_id: str,
    tipo: str,
    telefono: str,
    estado: str,
    mercately_response: dict,
    dry_run: bool,
) -> None:
    """Persiste el registro del envío en radar_alertas. No lanza excepción."""
    if dry_run:
        return
    try:
        await db.radar_alertas.insert_one({
            "loanbook_id":         loanbook_id,
            "tipo":                tipo,       # "cobro" | "mora"
            "telefono":            telefono,
            "estado":              estado,     # "enviado" | "error" | "skip_*"
            "mercately_response":  mercately_response,
            "fecha_envio":         now_iso_bogota(),
        })
    except Exception as exc:
        logger.warning("_guardar_alerta falló para %s: %s", loanbook_id, exc)


# ─────────────────────── Loop del scheduler ──────────────────────────────────

def _segundos_hasta_proximo_miercoles_8am() -> float:
    """Calcula segundos hasta el próximo miércoles 08:00 AM Bogotá."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo("America/Bogota")
    ahora = datetime.now(TZ)

    dias_hasta_miercoles = (2 - ahora.weekday()) % 7  # 2 = Wednesday
    if dias_hasta_miercoles == 0:
        # Hoy es miércoles — ¿ya pasaron las 8am?
        target_hoy = ahora.replace(hour=8, minute=0, second=0, microsecond=0)
        if ahora < target_hoy:
            return (target_hoy - ahora).total_seconds()
        # Ya pasaron las 8am → próximo miércoles
        dias_hasta_miercoles = 7

    target = (ahora + timedelta(days=dias_hasta_miercoles)).replace(
        hour=8, minute=0, second=0, microsecond=0
    )
    return (target - ahora).total_seconds()


async def run_radar_scheduler(db: "AsyncIOMotorDatabase") -> None:
    """Loop infinito que corre enviar_alertas_cobro() los miércoles 08:00 AM Bogotá."""
    import asyncio

    logger.info("RADAR scheduler iniciado (corre miércoles 08:00 AM Bogotá)")

    while True:
        segundos = _segundos_hasta_proximo_miercoles_8am()
        logger.info(
            "RADAR scheduler: próxima ejecución en %.0f segundos (miércoles 08:00 AM Bogotá)",
            segundos,
        )
        await asyncio.sleep(segundos)

        try:
            stats = await enviar_alertas_cobro(db, dry_run=False)
            logger.info("RADAR scheduler completado: %s", stats)
        except Exception as exc:
            logger.error("RADAR scheduler falló: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Schedulers extra (Sprint S2 — Ejecucion 2)
# Martes 9AM: recordatorio T1 a clientes con cuota miercoles -2d
# Jueves 10AM: mora T3/T4/T5 a clientes que no pagaron miercoles
# ─────────────────────────────────────────────────────────────────────────────


def _segundos_hasta_dia_hora(target_weekday: int, target_hour: int) -> float:
    """Calcula segundos hasta el proximo target_weekday a las target_hour:00 AM Bogota.

    target_weekday: 0=Lun ... 6=Dom. Ejemplo: martes=1, jueves=3.
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo("America/Bogota")
    ahora = datetime.now(TZ)

    dias_hasta = (target_weekday - ahora.weekday()) % 7
    if dias_hasta == 0:
        target_hoy = ahora.replace(hour=target_hour, minute=0, second=0, microsecond=0)
        if ahora < target_hoy:
            return (target_hoy - ahora).total_seconds()
        dias_hasta = 7

    target = (ahora + timedelta(days=dias_hasta)).replace(
        hour=target_hour, minute=0, second=0, microsecond=0
    )
    return (target - ahora).total_seconds()


async def enviar_recordatorios_martes(db: "AsyncIOMotorDatabase") -> dict:
    """Martes 9AM — Envia template T1 a clientes cuya cuota es el miercoles siguiente.

    Filtros:
    - loanbook estado activo/al_dia/en_riesgo
    - tiene cuota pendiente con fecha == hoy + 1 (miercoles)
    - no contactado hoy (Ley 2300)

    Returns: {"enviados": N, "errores": M, "saltados": K}
    """
    from datetime import timedelta
    hoy = today_bogota()
    if hoy.weekday() != 1:  # 1 = Tuesday
        logger.info("recordatorios_martes: hoy no es martes (weekday=%d), saltado", hoy.weekday())
        return {"enviados": 0, "errores": 0, "saltados": 0, "razon": "no_es_martes"}

    miercoles = hoy + timedelta(days=1)
    miercoles_iso = miercoles.isoformat()

    enviados = 0
    errores = 0
    saltados = 0

    cursor = db.loanbook.find({"estado": {"$nin": list(_ESTADOS_EXCLUIDOS)}})
    async for lb in cursor:
        cliente = lb.get("cliente") or {}
        cedula = cliente.get("cedula", "")
        nombre = cliente.get("nombre", "")
        telefono = cliente.get("telefono", "")
        if not cedula or not telefono:
            saltados += 1
            continue

        # Buscar cuota pendiente para mañana (miercoles)
        cuota_target = None
        for c in lb.get("cuotas") or []:
            if c.get("estado") == "pagada":
                continue
            fecha_c = (c.get("fecha") or "")[:10]
            if fecha_c == miercoles_iso:
                cuota_target = c
                break

        if not cuota_target:
            saltados += 1
            continue

        # Ya contactado hoy?
        crm = await db.crm_clientes.find_one({"cedula": cedula}, {"gestiones": 1, "_id": 0})
        if crm:
            today_iso = hoy.isoformat()
            ya_contactado = any(
                (g.get("fecha") or "")[:10] == today_iso and (g.get("tipo") or "").startswith("whatsapp")
                for g in (crm.get("gestiones") or [])
            )
            if ya_contactado:
                saltados += 1
                continue

        monto = cuota_target.get("monto") or cuota_target.get("monto_total") or 0
        template_id = os.getenv("MERCATELY_TEMPLATE_T1_RECORDATORIO_ID",
                                os.getenv("MERCATELY_TEMPLATE_COBRO_ID", ""))
        if not template_id:
            logger.warning("recordatorios_martes: MERCATELY_TEMPLATE_T1_RECORDATORIO_ID no configurado")
            return {"enviados": 0, "errores": 1, "saltados": saltados,
                    "razon": "template_no_configurado"}

        client = MercatelyClient()
        result = await client.send_template(
            phone_number=telefono,
            template_id=template_id,
            template_params=[_nombre_corto(nombre), _formato_monto(monto), _formato_fecha(miercoles_iso)],
        )
        if result.get("success"):
            enviados += 1
            await db.crm_clientes.update_one(
                {"cedula": cedula},
                {"$push": {"gestiones": {
                    "tipo": "whatsapp_t1",
                    "fecha": now_iso_bogota(),
                    "resultado": "enviado",
                    "template": "T1",
                    "vin": lb.get("vin"),
                }}},
            )
        else:
            errores += 1
        await db.radar_alertas.insert_one({
            "scheduler": "martes_9am",
            "cedula": cedula,
            "telefono": telefono,
            "vin": lb.get("vin"),
            "template": "T1",
            "estado": "enviado" if result.get("success") else "error",
            "raw_result": result,
            "fecha": now_iso_bogota(),
        })

    logger.info("recordatorios_martes: enviados=%d errores=%d saltados=%d", enviados, errores, saltados)
    return {"enviados": enviados, "errores": errores, "saltados": saltados}


async def enviar_alertas_mora_jueves(db: "AsyncIOMotorDatabase") -> dict:
    """Jueves 10AM — Envia template T3/T4/T5 a clientes que NO pagaron miercoles."""
    hoy = today_bogota()
    if hoy.weekday() != 3:  # 3 = Thursday
        logger.info("alertas_mora_jueves: hoy no es jueves (weekday=%d), saltado", hoy.weekday())
        return {"enviados": 0, "errores": 0, "saltados": 0, "razon": "no_es_jueves"}

    enviados = 0
    errores = 0
    saltados = 0

    cursor = db.loanbook.find({"estado": {"$nin": list(_ESTADOS_EXCLUIDOS)}})
    async for lb in cursor:
        cliente = lb.get("cliente") or {}
        cedula = cliente.get("cedula", "")
        nombre = cliente.get("nombre", "")
        telefono = cliente.get("telefono", "")
        if not cedula or not telefono:
            saltados += 1
            continue

        # Encontrar la cuota mas vencida no pagada
        cuotas = lb.get("cuotas") or []
        max_dpd = 0
        cuota_mora = None
        for c in cuotas:
            if c.get("estado") == "pagada":
                continue
            fecha_str = c.get("fecha")
            if not fecha_str:
                continue
            try:
                from datetime import date
                f = date.fromisoformat(fecha_str[:10])
            except Exception:
                continue
            if f < hoy:
                d = (hoy - f).days
                if d > max_dpd:
                    max_dpd = d
                    cuota_mora = c

        if not cuota_mora or max_dpd <= 0:
            saltados += 1
            continue

        # Decidir template segun DPD
        if max_dpd >= 30:
            template_key = "T5"
            template_id = os.getenv("MERCATELY_TEMPLATE_T5_ULTIMO_AVISO_ID",
                                    os.getenv("MERCATELY_TEMPLATE_MORA_ID", ""))
        elif max_dpd >= 7:
            template_key = "T4"
            template_id = os.getenv("MERCATELY_TEMPLATE_T4_MORA_MEDIA_ID",
                                    os.getenv("MERCATELY_TEMPLATE_MORA_ID", ""))
        else:
            template_key = "T3"
            template_id = os.getenv("MERCATELY_TEMPLATE_T3_MORA_CORTA_ID",
                                    os.getenv("MERCATELY_TEMPLATE_MORA_ID", ""))

        if not template_id:
            logger.warning("alertas_mora_jueves: template %s no configurado", template_key)
            saltados += 1
            continue

        # Mora COP acumulada $2000/dia desde el dia siguiente a la cuota
        mora_cop = max(0, (max_dpd - 1)) * 2_000

        # Ya contactado hoy?
        crm = await db.crm_clientes.find_one({"cedula": cedula}, {"gestiones": 1, "_id": 0})
        if crm:
            today_iso = hoy.isoformat()
            ya_contactado = any(
                (g.get("fecha") or "")[:10] == today_iso and (g.get("tipo") or "").startswith("whatsapp")
                for g in (crm.get("gestiones") or [])
            )
            if ya_contactado:
                saltados += 1
                continue

        client = MercatelyClient()
        result = await client.send_template(
            phone_number=telefono,
            template_id=template_id,
            template_params=[_nombre_corto(nombre), str(max_dpd), _formato_monto(mora_cop)],
        )
        if result.get("success"):
            enviados += 1
            await db.crm_clientes.update_one(
                {"cedula": cedula},
                {"$push": {"gestiones": {
                    "tipo": f"whatsapp_{template_key.lower()}",
                    "fecha": now_iso_bogota(),
                    "resultado": "enviado",
                    "template": template_key,
                    "vin": lb.get("vin"),
                    "dpd": max_dpd,
                }},
                 "$addToSet": {"tags": "mora"}},
            )
        else:
            errores += 1
        await db.radar_alertas.insert_one({
            "scheduler": "jueves_10am",
            "cedula": cedula,
            "telefono": telefono,
            "vin": lb.get("vin"),
            "template": template_key,
            "dpd": max_dpd,
            "estado": "enviado" if result.get("success") else "error",
            "raw_result": result,
            "fecha": now_iso_bogota(),
        })

    logger.info("alertas_mora_jueves: enviados=%d errores=%d saltados=%d", enviados, errores, saltados)
    return {"enviados": enviados, "errores": errores, "saltados": saltados}


async def run_radar_scheduler_martes(db: "AsyncIOMotorDatabase") -> None:
    """Loop infinito martes 09:00 AM Bogota."""
    import asyncio
    logger.info("RADAR scheduler-martes iniciado (corre martes 09:00 AM Bogota)")
    while True:
        segundos = _segundos_hasta_dia_hora(target_weekday=1, target_hour=9)
        logger.info("RADAR scheduler-martes: proxima ejecucion en %.0fs", segundos)
        await asyncio.sleep(segundos)
        try:
            stats = await enviar_recordatorios_martes(db)
            logger.info("RADAR scheduler-martes completado: %s", stats)
        except Exception as exc:
            logger.error("RADAR scheduler-martes fallo: %s", exc)


async def run_radar_scheduler_jueves(db: "AsyncIOMotorDatabase") -> None:
    """Loop infinito jueves 10:00 AM Bogota."""
    import asyncio
    logger.info("RADAR scheduler-jueves iniciado (corre jueves 10:00 AM Bogota)")
    while True:
        segundos = _segundos_hasta_dia_hora(target_weekday=3, target_hour=10)
        logger.info("RADAR scheduler-jueves: proxima ejecucion en %.0fs", segundos)
        await asyncio.sleep(segundos)
        try:
            stats = await enviar_alertas_mora_jueves(db)
            logger.info("RADAR scheduler-jueves completado: %s", stats)
        except Exception as exc:
            logger.error("RADAR scheduler-jueves fallo: %s", exc)
