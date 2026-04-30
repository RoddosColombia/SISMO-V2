"""
services/tributario/liquidador_reica.py — Liquida ReICA Bogotá bimestral.

ReICA Bogotá (Secretaría Distrital de Hacienda):
  - Tarifa comercial general: 4‰ (4 por mil) sobre ingresos brutos del bimestre
  - RODDOS es agente retenedor: retiene a sus proveedores (cuenta 5392 Alegra)
  - Lo que se declara y paga a Bogotá:
       (a) ICA causado por las ventas (4‰ × ingresos) PLUS
       (b) ReICA retenida a proveedores (cuenta 5392)
       MINUS retenciones que nos hicieron a nosotros (registradas como
            anticipo de ICA en 13551501 NIIF)

Periodicidad: 6 bimestres/año.
"""
from __future__ import annotations
import logging
from datetime import date
from typing import TypedDict

from services.alegra.client import AlegraClient

logger = logging.getLogger("tributario.liquidador_reica")

REICA_BOGOTA_TARIFA_COMERCIAL = 0.004
REICA_RETENIDA_CUENTA_ALEGRA = "5392"


class LiquidacionReICA(TypedDict):
    periodo: str  # "2026-B2"
    inicio: str
    fin: str
    ingresos_bimestre: float
    ica_causado: float            # 4‰ × ingresos
    reica_retenida_proveedores: float  # cuenta 5392
    reica_retenida_a_nosotros: float   # anticipo (rebaja)
    total_a_pagar: float
    n_invoices: int
    n_journals: int


async def liquidar_reica_bogota_bimestre(
    alegra: AlegraClient,
    inicio: date,
    fin: date,
    periodo_label: str = "",
) -> LiquidacionReICA:
    """Liquida ReICA Bogotá del bimestre."""
    inicio_str = inicio.isoformat()
    fin_str = fin.isoformat()

    # ── 1) Ingresos del bimestre (paginado + filtro Python) ─
    ingresos = 0.0
    n_inv = 0
    start = 0
    LIMIT = 30
    while True:
        try:
            page = await alegra.get(
                "invoices",
                params={"start": start, "limit": LIMIT},
            )
        except Exception as e:
            logger.warning(f"Alegra invoices page start={start}: {e}")
            break
        if not isinstance(page, list) or not page:
            break
        for inv in page:
            inv_date = (inv.get("date") or "")[:10]
            if not (inicio_str <= inv_date <= fin_str):
                continue
            if inv.get("status") in ("draft", "void", "cancelled"):
                continue
            n_inv += 1
            # Subtotal sin IVA es la base ICA
            for item in (inv.get("items") or []):
                price = float(item.get("price") or 0)
                qty = float(item.get("quantity") or 0)
                ingresos += price * qty
        start += LIMIT
        if len(page) < LIMIT:
            break

    ica_causado = ingresos * REICA_BOGOTA_TARIFA_COMERCIAL

    # ── 2) ReICA retenida a proveedores (cuenta 5392 crédito en journals) ─
    reica_a_proveedores = 0.0
    reica_a_nosotros = 0.0
    n_journals = 0
    start = 0
    while True:
        try:
            page = await alegra.get(
                "journals",
                params={"start": start, "limit": LIMIT},
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
                cuenta = str(entry.get("id") or "")
                credit = float(entry.get("credit") or 0)
                debit = float(entry.get("debit") or 0)
                if cuenta == REICA_RETENIDA_CUENTA_ALEGRA:
                    reica_a_proveedores += (credit - debit)
                # Anticipo ReICA recibida (NIIF 13551501)
                niif = (entry.get("number") or "")
                if niif.startswith("13551501") or niif.startswith("135515"):
                    reica_a_nosotros += (debit - credit)
        start += LIMIT
        if len(page) < LIMIT:
            break

    total = ica_causado + reica_a_proveedores - reica_a_nosotros

    return {
        "periodo": periodo_label,
        "inicio": inicio_str,
        "fin": fin_str,
        "reica_retenida_proveedores": round(reica_a_proveedores),
        "reica_anticipo_recibido": round(reica_a_nosotros),
        "total_a_pagar": round(max(0, total)),
        "n_journals_procesados": n_journals,
        "fecha_calculo": "",
    }

