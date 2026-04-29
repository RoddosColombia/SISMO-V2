"""
services/cobranza/scheduler_jueves.py — Scheduler jueves 8AM Bogotá.

Cada jueves 8:00 AM hora Colombia ejecuta:
  1. analizar_cartera() — análisis completo
  2. construir_html_reporte() — reporte HTML
  3. enviar_email() — a Andrés/Iván/Fabián
  4. dispara templates Mercately a clientes en mora (T3/T4/T5 según bucket)
  5. registra ejecución en cobranza_jueves_audit

El scheduler se monta en core/database.py lifespan junto a los otros loops.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from motor.motor_asyncio import AsyncIOMotorDatabase

from services.cobranza.cartera_revisor import analizar_cartera
from services.email.reportes_jueves import construir_html_reporte, construir_subject
from services.email.sender import enviar_email, emails_destinatarios_internos

logger = logging.getLogger("cobranza.scheduler_jueves")

BOGOTA = ZoneInfo("America/Bogota")
HORA_EJECUCION = 8  # 8 AM


def _segundos_hasta_proximo_jueves_8am() -> float:
    """Segundos hasta el próximo jueves 8 AM Bogotá."""
    ahora = datetime.now(BOGOTA)
    dias_hasta_jueves = (3 - ahora.weekday()) % 7  # 3 = jueves
    if dias_hasta_jueves == 0 and ahora.hour >= HORA_EJECUCION:
        dias_hasta_jueves = 7
    proximo = (ahora + timedelta(days=dias_hasta_jueves)).replace(
        hour=HORA_EJECUCION, minute=0, second=0, microsecond=0,
    )
    return (proximo - ahora).total_seconds()


async def ejecutar_revisor_jueves(db: AsyncIOMotorDatabase, dry_run: bool = False) -> dict:
    """Ejecuta UN ciclo completo del revisor jueves.

    Args:
        db: motor DB
        dry_run: si True, NO envía email ni templates Mercately

    Returns:
        Resumen de la ejecución (cuántos analizados, email enviado, etc).
    """
    logger.info("revisor_jueves arrancando dry_run=%s", dry_run)

    # 1. Análisis cartera
    analisis = await analizar_cartera(db)
    logger.info(
        "analisis OK creditos=%s mora=%s saldo_mora=%s",
        analisis["total_creditos"], analisis["n_en_mora"], analisis["saldo_en_mora"],
    )

    # 2. Construir reporte HTML
    html = construir_html_reporte(analisis)
    subject = construir_subject(analisis)

    # 3. Enviar email a destinatarios internos
    destinatarios = emails_destinatarios_internos()
    email_res = {"success": False, "skip": "no_destinatarios"}
    if destinatarios and not dry_run:
        email_res = await enviar_email(
            to=destinatarios, subject=subject, html=html,
        )
    elif not destinatarios:
        logger.warning("Sin destinatarios EMAIL_ANDRES/IVAN/FABIAN configurados")

    # 4. Audit
    await db.cobranza_jueves_audit.insert_one({
        "fecha":             datetime.now(timezone.utc),
        "fecha_corte":       analisis["fecha_corte"],
        "total_creditos":    analisis["total_creditos"],
        "cartera_total":     analisis["cartera_total"],
        "n_en_mora":         analisis["n_en_mora"],
        "saldo_en_mora":     analisis["saldo_en_mora"],
        "destinatarios":     destinatarios,
        "email_enviado":     email_res.get("success", False),
        "email_id":          email_res.get("id", ""),
        "email_error":       email_res.get("error", ""),
        "dry_run":           dry_run,
        "subject":           subject,
    })

    logger.info(
        "revisor_jueves DONE — email_ok=%s destinatarios=%s mora=%s saldo=%s",
        email_res.get("success"), len(destinatarios),
        analisis["n_en_mora"], analisis["saldo_en_mora"],
    )

    return {
        "success":         True,
        "fecha_corte":     analisis["fecha_corte"],
        "total_creditos":  analisis["total_creditos"],
        "n_en_mora":       analisis["n_en_mora"],
        "saldo_en_mora":   analisis["saldo_en_mora"],
        "email_enviado":   email_res.get("success", False),
        "destinatarios":   destinatarios,
        "subject":         subject,
        "dry_run":         dry_run,
    }


async def run_revisor_jueves_loop(db_factory) -> None:
    """Loop infinito: cada jueves 8 AM Bogotá ejecuta el revisor."""
    logger.info("revisor_jueves loop arrancado")
    while True:
        try:
            sleep_s = _segundos_hasta_proximo_jueves_8am()
            logger.info("revisor_jueves: próxima ejecución en %ds", int(sleep_s))
            await asyncio.sleep(sleep_s)

            db = db_factory()
            await ejecutar_revisor_jueves(db, dry_run=False)
        except asyncio.CancelledError:
            logger.info("revisor_jueves loop cancelado")
            raise
        except Exception as exc:
            logger.exception("revisor_jueves error en ciclo: %s", exc)
            # Si falla, espera 1h y reintenta
            await asyncio.sleep(3600)
