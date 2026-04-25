"""
core/datetime_utils.py — Fuente única de verdad de fecha/hora en SISMO.

Render corre en UTC. Colombia (America/Bogota) es UTC-5 sin horario de verano.
Usar SIEMPRE estas funciones en el código de runtime — NUNCA datetime.utcnow()
ni date.today() directamente fuera de este módulo.

Bug histórico: el 22-abr-2026 a las 7 PM Bogotá, date.today() en Render
retornó 2026-04-23, marcando cuotas del miércoles de cobro como vencidas
antes de tiempo.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    _BOGOTA_TZ = ZoneInfo("America/Bogota")
except ImportError:
    # Python < 3.9 fallback (no DST — Colombia no usa horario de verano)
    _BOGOTA_TZ = timezone(timedelta(hours=-5))  # type: ignore[assignment]


def now_bogota() -> datetime:
    """Retorna el datetime actual con zona horaria America/Bogota."""
    return datetime.now(_BOGOTA_TZ)


def today_bogota() -> date:
    """Retorna la fecha de hoy en Bogotá (no en UTC/Render)."""
    return now_bogota().date()


def now_iso_bogota() -> str:
    """Retorna datetime actual como ISO string con offset -05:00.

    Úsase para campos updated_at/created_at en MongoDB para que los
    timestamps sean legibles en hora colombiana.
    """
    return now_bogota().isoformat()
