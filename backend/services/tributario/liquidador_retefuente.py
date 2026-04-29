"""
services/tributario/liquidador_retefuente.py — Liquida ReteFuente + ReteIVA mensual.

Lee journals Alegra del mes y suma los créditos a las cuentas de retención
por pagar (5381-5392 según CLAUDE.md). Esos son los importes que RODDOS
debe entregar a la DIAN.

Cuentas Alegra (CLAUDE.md):
  5381 → ReteFte Honorarios 10%
  5382 → ReteFte Honorarios 11%
  5383 → ReteFte Servicios 4%
  5386 → ReteFte Arriendo 3.5%
  5388 → ReteFte Compras 2.5%
  5392 → ReteICA (lo declara aparte SHD Bogotá, NO va al 350)

ReteIVA (15% del IVA generado en compras a régimen común) — buscar cuenta NIIF
2367 en journals.
"""
from __future__ import annotations
import logging
from datetime import date
from typing import TypedDict

from services.alegra.client import AlegraClient

logger = logging.getLogger("tributario.liquidador_retefuente")


# Mapping cuenta Alegra → concepto declarado (formulario 350)
RETEFUENTE_CUENTAS = {
    "5381": "honorarios_10",
    "5382": "honorarios_11",
    "5383": "servicios_4",
    "5386": "arriendo_35",
    "5388": "compras_25",
}

# ReteIVA cuenta (NIIF 23671501)
RETEIVA_CUENTA_NIIF = "23671501"

# ReICA cuenta — NO va al formulario 350, va al ICA Bogotá
REICA_CUENTA_ALEGRA = "5392"


class LiquidacionReteFuente(TypedDict):
    periodo: str               # "2026-04"
    inicio: str
    fin: str
    retefuente_total: float    # total a entregar DIAN (formulario 350)
    reteiva_total: float       # ReteIVA mensual a entregar DIAN
    total_a_pagar: float       # retefuente + reteiva
    detalle_por_concepto: dict # {"honorarios_10": X, "servicios_4": Y, ...}
    n_journals_procesados: int
    fecha_calculo: str


async def liquidar_retefuente_mes(
    alegra: AlegraClient,
    anio: int,
    mes: int,
) -> LiquidacionReteFuente:
    """Liquida ReteFuente + ReteIVA del mes.

    Lee todos los journals del mes y suma los créditos a cuentas de retención.
    """
    inicio = date(anio, mes, 1)
    if mes == 12:
        fin = date(anio, 12, 31)
    else:
        from datetime import timedelta
        fin = date(anio, mes + 1, 1) - timedelta(days=1)

    inicio_str = inicio.isoformat()
    fin_str = fin.isoformat()
    periodo = f"{anio:04d}-{mes:02d}"

    detalle: dict[str, float] = {k: 0.0 for k in RETEFUENTE_CUENTAS.values()}
    reteiva_total = 0.0
    n_journals = 0

    start = 0
    LIMIT = 30
    while True:
        try:
            page = await alegra.get(
                "journals",
                params={"start": start, "limit": LIMIT, "order_field": "date"},
            )
        except Exception as e:
            logger.warning(f"Alegra journals page start={start}: {e}")
            break
        if not isinstance(page, list) or not page:
            break
        for journal in page:
            j_date = (journal.get("date") or "")[:10]
            if not (inicio_str <= j_date <= fin_str):
                continue
            n_journals += 1
            for entry in (journal.get("entries") or []):
                cuenta_id = str(entry.get("id") or "")
                credit = float(entry.get("credit") or 0)
                debit = float(entry.get("debit") or 0)
                if cuenta_id in RETEFUENTE_CUENTAS:
                    # Crédito = retención causada (lo que debe la empresa)
                    # Débito = pago/reverso de retención
                    detalle[RETEFUENTE_CUENTAS[cuenta_id]] += (credit - debit)
                # ReteIVA — si el id del entry coincide con cuenta NIIF 2367*
                # Alegra puede usar diferentes ids; identificamos por nombre o numero
                niif = (entry.get("number") or "")
                if niif.startswith("2367"):
                    reteiva_total += (credit - debit)
        start += LIMIT
        if len(page) < LIMIT:
            break

    retefuente_total = sum(detalle.values())
    total = retefuente_total + reteiva_total

    return {
        "periodo": periodo,
        "inicio": inicio_str,
        "fin": fin_str,
        "retefuente_total": round(retefuente_total),
        "reteiva_total": round(reteiva_total),
        "total_a_pagar": round(total),
        "detalle_por_concepto": {k: round(v) for k, v in detalle.items()},
        "n_journals_procesados": n_journals,
        "fecha_calculo": "",  # lo setea el handler
    }
