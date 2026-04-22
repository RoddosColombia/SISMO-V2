"""
services/loanbook/reparador.py — Reparación estructural de loanbooks corruptos.

Función principal:
    reparar_loanbook(lb: dict, *, hoy: date | None = None, dry_run: bool = True) -> dict

Detecta y corrige DOS tipos de corrupción, en orden:
  1. Cuotas futuras marcadas pagadas sin evidencia real (seed corrupto)
     → Revertidas a estado="pendiente"
     → Preservadas si tienen referencia bancaria o metodo_pago válido
  2. num_cuotas / valor_total incorrectos según PLANES_RODDOS
     → Corregidos via recalcular_loanbook()

Contrato:
  - dry_run=True (default): no muta el documento, devuelve el plan de reparación
  - dry_run=False: devuelve el documento reparado listo para persistir
  - Sin I/O — el caller es responsable de hacer el update_one en MongoDB

La detección de evidencia real es idéntica a la del auditor (BUILD 1) para
garantizar coherencia: sin referencia Y sin metodo_pago distinto de seed/vacío
→ sospechoso.
"""

from __future__ import annotations

import copy
from datetime import date

from services.loanbook.state_calculator import recalcular_loanbook

# ─────────────────────── Constantes ───────────────────────────────────────────

# metodo_pago values that indicate a real transaction (not seed data)
METODOS_REALES = {"efectivo", "bancolombia", "bbva", "davivienda", "nequi", "transferencia", "otro"}


# ─────────────────────── Helpers ──────────────────────────────────────────────

def _tiene_evidencia_real(cuota: dict) -> bool:
    """Determina si una cuota tiene evidencia de pago real (no seed corrupto)."""
    referencia = cuota.get("referencia")
    metodo = cuota.get("metodo_pago")
    tiene_ref = bool(referencia)
    tiene_metodo = bool(metodo and metodo.lower() in METODOS_REALES)
    return tiene_ref or tiene_metodo


# ─────────────────────── Función principal ────────────────────────────────────

def reparar_loanbook(
    lb: dict,
    *,
    hoy: date | None = None,
    dry_run: bool = True,
) -> dict:
    """
    Analiza y (opcionalmente) repara un loanbook.

    Args:
        lb:       Documento loanbook sin _id.
        hoy:      Fecha de referencia (default: date.today()). Inyectable para tests.
        dry_run:  Si True, retorna el plan de reparación sin mutar nada.
                  Si False, retorna el documento reparado (no persiste — el caller lo hace).

    Returns:
        dict con:
          - loanbook_id
          - tiene_problemas: bool
          - reparaciones: list[dict] — descripción de cada corrección
          - documento_reparado: dict | None — el doc corregido si dry_run=False
    """
    if hoy is None:
        hoy = date.today()

    hoy_str = hoy.isoformat()
    loanbook_id = lb.get("loanbook_id", "?")
    cliente = lb.get("cliente", {}).get("nombre", "Desconocido")

    reparaciones: list[dict] = []
    doc = copy.deepcopy(lb)
    cuotas: list[dict] = doc.get("cuotas", [])

    # ── Reparación 1: cuotas futuras marcadas pagadas sin evidencia ───────────
    for c in cuotas:
        if c.get("estado") != "pagada":
            continue
        fecha_cuota = c.get("fecha", "")
        if not fecha_cuota or fecha_cuota <= hoy_str:
            # Pasada o sin fecha — no es seed corrupto (aunque no tenga evidencia)
            continue
        if _tiene_evidencia_real(c):
            # Pago adelantado legítimo — no tocar
            continue

        # Cuota futura pagada sin evidencia → revertir
        reparaciones.append({
            "tipo": "cuota_seed_revertida",
            "cuota_numero": c.get("numero"),
            "fecha": fecha_cuota,
            "estado_anterior": "pagada",
            "estado_nuevo": "pendiente",
            "razon": "Cuota futura sin referencia ni método de pago real (seed corrupto)",
        })

        if not dry_run:
            c["estado"] = "pendiente"
            c["fecha_pago"] = None

    # ── Reparación 2: num_cuotas / valor_total incorrectos ────────────────────
    num_cuotas_antes = doc.get("num_cuotas")
    valor_total_antes = doc.get("valor_total")

    doc_recalculado = recalcular_loanbook(doc, hoy=hoy)

    num_cuotas_despues = doc_recalculado.get("num_cuotas")
    valor_total_despues = doc_recalculado.get("valor_total")

    if num_cuotas_antes != num_cuotas_despues:
        reparaciones.append({
            "tipo": "num_cuotas_corregido",
            "valor_anterior": num_cuotas_antes,
            "valor_nuevo": num_cuotas_despues,
            "razon": f"PLANES_RODDOS[{doc.get('plan_codigo')}] × modalidad[{doc.get('modalidad')}]",
        })

    if valor_total_antes != valor_total_despues:
        reparaciones.append({
            "tipo": "valor_total_corregido",
            "valor_anterior": valor_total_antes,
            "valor_nuevo": valor_total_despues,
            "razon": "num_cuotas × cuota_monto + cuota_inicial",
        })

    return {
        "loanbook_id": loanbook_id,
        "cliente": cliente,
        "tiene_problemas": len(reparaciones) > 0,
        "reparaciones": reparaciones,
        "documento_reparado": doc_recalculado if not dry_run else None,
    }
