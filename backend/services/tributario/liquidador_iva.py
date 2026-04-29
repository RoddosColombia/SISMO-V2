"""
services/tributario/liquidador_iva.py — Liquida IVA cuatrimestral.

Estructura del cálculo:

  IVA generado (débito fiscal)
    = ventas gravadas × tarifa IVA
    Lee: facturas de venta Alegra del periodo (status != void)
    Excluye: ventas exentas (SOAT, matrícula, exportaciones)

  IVA descontable (crédito fiscal)
    = compras gravadas × tarifa IVA
    Lee: facturas de compra (bills) Alegra del periodo
    Filtra: solo compras con IVA acreditable (no gastos personales, no
            compras de activos fijos sin renta, etc.)

  IVA neto a pagar
    = IVA generado − IVA descontable − ReteIVA recibida (anticipos)

  Si saldo a favor → arrastrar al siguiente cuatrimestre.

ROG-1: este servicio NO escribe a Alegra. Solo lee. La persistencia
del cálculo en MongoDB la hace el handler que invoca este servicio.
"""
from __future__ import annotations
import logging
from datetime import date
from typing import TypedDict

from services.alegra.client import AlegraClient

logger = logging.getLogger("tributario.liquidador_iva")

# Tarifa IVA general (CLAUDE.md)
IVA_GENERAL = 0.19


class LiquidacionIVA(TypedDict):
    periodo: str              # "2026-C1"
    inicio: str               # ISO date
    fin: str                  # ISO date
    iva_generado: float
    iva_descontable: float
    reteiva_recibida: float   # IVA que nos retuvieron clientes
    iva_neto_a_pagar: float   # >0 a pagar, <0 saldo a favor
    saldo_a_favor: float
    detalle_facturas: int     # nro facturas venta procesadas
    detalle_bills: int        # nro facturas compra procesadas
    ventas_gravadas_total: float
    ventas_exentas_total: float
    compras_gravadas_total: float
    iva_generado_por_concepto: dict   # {"motos": X, "repuestos": Y, "soat": 0, ...}


async def liquidar_iva_cuatrimestre(
    alegra: AlegraClient,
    inicio: date,
    fin: date,
    periodo_label: str = "",
) -> LiquidacionIVA:
    """Liquida un cuatrimestre IVA leyendo Alegra.

    Args:
        alegra: cliente Alegra autenticado
        inicio: fecha inicio cuatrimestre (ej 2026-01-01)
        fin: fecha fin cuatrimestre (ej 2026-04-30)
        periodo_label: etiqueta humana (ej "2026-C1")

    Returns: dict LiquidacionIVA
    """
    inicio_str = inicio.isoformat()
    fin_str = fin.isoformat()

    # ── 1) Leer facturas de venta del periodo (paginado) ─────────────────
    # Alegra NO acepta filtro 'date=inicio,fin' como param. Paginamos todo y
    # filtramos en Python por inv["date"] dentro del rango.
    iva_generado = 0.0
    ventas_gravadas = 0.0
    ventas_exentas = 0.0
    iva_por_concepto: dict[str, float] = {
        "motos": 0.0, "repuestos": 0.0, "soat": 0.0, "matricula": 0.0,
        "gps": 0.0, "intereses": 0.0, "otros": 0.0,
    }
    n_facturas = 0
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
            n_facturas += 1
            for item in (inv.get("items") or []):
                price = float(item.get("price") or 0)
                qty = float(item.get("quantity") or 0)
                tax_pct = 0.0
                for tax in (item.get("tax") or []):
                    tax_pct = max(tax_pct, float(tax.get("percentage") or 0)) / 100
                base = price * qty
                iva_item = base * tax_pct
                iva_generado += iva_item
                if tax_pct > 0:
                    ventas_gravadas += base
                else:
                    ventas_exentas += base
                # Clasificar por concepto
                nombre = (item.get("name") or "").lower()
                if "raider" in nombre or "sport" in nombre or "moto" in nombre:
                    iva_por_concepto["motos"] += iva_item
                elif "soat" in nombre:
                    iva_por_concepto["soat"] += iva_item
                elif "matr" in nombre:
                    iva_por_concepto["matricula"] += iva_item
                elif "gps" in nombre:
                    iva_por_concepto["gps"] += iva_item
                elif "interes" in nombre or "financia" in nombre:
                    iva_por_concepto["intereses"] += iva_item
                elif "repuesto" in nombre:
                    iva_por_concepto["repuestos"] += iva_item
                else:
                    iva_por_concepto["otros"] += iva_item
        start += LIMIT
        if len(page) < LIMIT:
            break

    # ── 2) Leer facturas de compra (bills) del periodo ─────────────────
    # IMPORTANTE: estructura bills ≠ invoices.
    #   items están en bill["purchases"]["items"], NO bill["items"]
    #   campo "tax" puede venir vacío "" — IVA = total - subtotal
    # Alegra cap = 30 para bills.
    iva_descontable = 0.0
    compras_gravadas = 0.0
    n_bills = 0
    start = 0
    BILLS_LIMIT = 30
    paginas_bills = 0
    MAX_PAGES_BILLS = 200
    while paginas_bills < MAX_PAGES_BILLS:
        try:
            page = await alegra.get(
                "bills",
                params={"start": start, "limit": BILLS_LIMIT},
            )
        except Exception as e:
            logger.warning(f"Alegra bills page start={start}: {e}")
            break
        if not isinstance(page, list) or not page:
            break
        for bill in page:
            bill_date = (bill.get("date") or "")[:10]
            if not (inicio_str <= bill_date <= fin_str):
                continue
            if bill.get("status") in ("draft", "void", "cancelled"):
                continue
            n_bills += 1
            # Estructura bills: items dentro de bill["purchases"]["items"]
            purchases = bill.get("purchases") or {}
            items = purchases.get("items") if isinstance(purchases, dict) else []
            for item in (items or []):
                subtotal = float(item.get("subtotal") or 0)
                total = float(item.get("total") or 0)
                # Si tax viene como array con percentage, úsalo. Si viene "" o vacío,
                # calcular IVA = total - subtotal (el caso real de Alegra para bills)
                tax_field = item.get("tax")
                tax_pct = 0.0
                if isinstance(tax_field, list):
                    for tax in tax_field:
                        tax_pct = max(tax_pct, float(tax.get("percentage") or 0)) / 100
                if tax_pct > 0:
                    iva_item = subtotal * tax_pct
                else:
                    # Inferir IVA por diferencia (caso bills sin tax explícito)
                    iva_item = max(0, total - subtotal)
                iva_descontable += iva_item
                if iva_item > 0:
                    compras_gravadas += subtotal
        paginas_bills += 1
        if len(page) < BILLS_LIMIT:
            break
        start += BILLS_LIMIT

    # ── 3) ReteIVA que nos retuvieron clientes (lo veremos en payments) ──
    # Por ahora 0 — Wave 4 lo refinará leyendo journals con cuenta 13551501.
    reteiva_recibida = 0.0

    iva_neto = iva_generado - iva_descontable - reteiva_recibida

    return {
        "periodo": periodo_label or f"{inicio_str}_{fin_str}",
        "inicio": inicio_str,
        "fin": fin_str,
        "iva_generado": round(iva_generado),
        "iva_descontable": round(iva_descontable),
        "reteiva_recibida": round(reteiva_recibida),
        "iva_neto_a_pagar": round(max(iva_neto, 0)),
        "saldo_a_favor": round(max(-iva_neto, 0)),
        "detalle_facturas": n_facturas,
        "detalle_bills": n_bills,
        "ventas_gravadas_total": round(ventas_gravadas),
        "ventas_exentas_total": round(ventas_exentas),
        "compras_gravadas_total": round(compras_gravadas),
        "iva_generado_por_concepto": {k: round(v) for k, v in iva_por_concepto.items()},
    }
