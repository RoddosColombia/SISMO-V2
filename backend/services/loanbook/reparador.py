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

    Reglas de reparación (en orden):
      A. fecha_pago > hoy (físicamente imposible):
         - Sin evidencia → revertir a pendiente
         - Con evidencia  → marcar requiere_revision_manual=True (no tocar)
      B. fecha_cuota > hoy AND estado=pagada AND sin evidencia → revertir
      C. num_cuotas / valor_total incorrectos → corregir via recalcular_loanbook()

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
          - requieren_revision_manual: list[dict] — cuotas con referencia y fecha imposible
          - documento_reparado: dict | None — el doc corregido si dry_run=False
    """
    if hoy is None:
        hoy = date.today()

    hoy_str = hoy.isoformat()
    loanbook_id = lb.get("loanbook_id", "?")
    cliente = lb.get("cliente", {}).get("nombre", "Desconocido")

    reparaciones: list[dict] = []
    revision_manual: list[dict] = []
    doc = copy.deepcopy(lb)
    cuotas: list[dict] = doc.get("cuotas", [])

    for c in cuotas:
        fecha_cuota = c.get("fecha", "")
        fecha_pago_c = c.get("fecha_pago") or ""
        estado_c = c.get("estado", "")
        evidencia = _tiene_evidencia_real(c)

        # ── Regla A: fecha_pago registrada en el futuro (físicamente imposible) ──
        if fecha_pago_c and fecha_pago_c > hoy_str:
            if evidencia:
                # Tiene referencia bancaria — no tocar, pero señalar para revisión
                revision_manual.append({
                    "cuota_numero": c.get("numero"),
                    "fecha_cuota": fecha_cuota,
                    "fecha_pago": fecha_pago_c,
                    "estado": estado_c,
                    "razon": "fecha_pago futura con referencia bancaria — requiere revisión humana",
                })
                if not dry_run:
                    c["requiere_revision_manual"] = True
            else:
                # Sin referencia → revertir
                reparaciones.append({
                    "tipo": "cuota_fecha_pago_futura_revertida",
                    "cuota_numero": c.get("numero"),
                    "fecha_cuota": fecha_cuota,
                    "fecha_pago_registrada": fecha_pago_c,
                    "estado_anterior": estado_c,
                    "estado_nuevo": "pendiente",
                    "razon": "fecha_pago en el futuro sin referencia (físicamente imposible)",
                })
                if not dry_run:
                    c["estado"] = "pendiente"
                    c["fecha_pago"] = None
            continue  # ya procesada — no aplica regla B

        # ── Regla B: cuota futura marcada pagada sin evidencia ─────────────────
        if estado_c != "pagada":
            continue
        if not fecha_cuota or fecha_cuota <= hoy_str:
            continue  # cuota pasada — no es seed corrupto
        if evidencia:
            # Pago adelantado legítimo con referencia bancaria — no tocar
            continue

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

    # ── Regla C: num_cuotas / valor_total incorrectos ─────────────────────────
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
            "razon": f"PLAN_CUOTAS[{doc.get('plan_codigo')}][{doc.get('modalidad')}]",
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
        "tiene_problemas": len(reparaciones) > 0 or len(revision_manual) > 0,
        "reparaciones": reparaciones,
        "requieren_revision_manual": revision_manual,
        "documento_reparado": doc_recalculado if not dry_run else None,
    }
