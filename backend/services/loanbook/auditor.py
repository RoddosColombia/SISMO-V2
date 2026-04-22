"""
services/loanbook/auditor.py — Auditoría de consistencia estructural del portafolio.

Función pura: recibe una lista de loanbooks (ya fetcheados del DB) y devuelve
un dict con resumen + casos de corrupción detectados.

Detecta 5 categorías de inconsistencia:
  1. valor_total_incorrecto          — no coincide con tabla PLAN_CUOTAS
  2. total_cuotas_incorrecto         — no coincide con tabla PLAN_CUOTAS
  3. cuotas_pagadas_fecha_imposible  — cuotas futuras marcadas pagadas sin evidencia real
  4. combinacion_no_configurada      — plan × modalidad sin entrada en PLAN_CUOTAS
  5. cuotas_con_fecha_pago_futura    — cuotas (de cualquier estado) con fecha_pago > hoy
"""

from datetime import date, datetime, timezone

from services.loanbook.reglas_negocio import PLAN_CUOTAS, get_num_cuotas


def _cuota_base_desde_loanbook(lb: dict) -> float:
    """Extrae el valor de cuota en la modalidad del crédito."""
    return (
        lb.get("cuota_monto")
        or lb.get("plan", {}).get("cuota_valor")
        or 0.0
    )


def _plan_codigo_desde_loanbook(lb: dict) -> str | None:
    return lb.get("plan_codigo") or lb.get("plan", {}).get("codigo")


def _modalidad_desde_loanbook(lb: dict) -> str:
    return (
        lb.get("modalidad")
        or lb.get("plan", {}).get("modalidad")
        or "semanal"
    )


def _num_cuotas_desde_loanbook(lb: dict) -> int:
    """Número de cuotas que el documento cree tener."""
    return (
        lb.get("num_cuotas")
        or lb.get("plan", {}).get("total_cuotas")
        or len(lb.get("cuotas", []))
        or 0
    )


# ─────────────────────── Función pura de auditoría ────────────────────────────

def auditar_loanbooks(loanbooks: list[dict]) -> dict:
    """
    Función pura: recibe loanbooks sin _id y devuelve el reporte de auditoría.

    Sin I/O — el caller (endpoint HTTP) es responsable de traer los docs de Mongo.

    Detecta 5 categorías:
      1. valor_total_incorrecto         — no coincide con tabla PLAN_CUOTAS
      2. total_cuotas_incorrecto        — no coincide con tabla PLAN_CUOTAS
      3. cuotas_pagadas_fecha_imposible — cuotas futuras pagadas sin evidencia real
      4. combinacion_no_configurada     — plan × modalidad sin entrada en PLAN_CUOTAS
      5. cuotas_con_fecha_pago_futura   — cualquier cuota con fecha_pago > hoy
    """
    hoy = date.today()
    hoy_str = hoy.isoformat()

    casos_valor_total: list[dict] = []
    casos_total_cuotas: list[dict] = []
    casos_cuotas_imposibles: list[dict] = []
    casos_combinacion_invalida: list[dict] = []
    casos_fecha_pago_futura: list[dict] = []

    for lb in loanbooks:
        loanbook_id = lb.get("loanbook_id", "???")
        cliente = lb.get("cliente", {}).get("nombre", "Desconocido")
        plan_codigo = _plan_codigo_desde_loanbook(lb)
        modalidad = _modalidad_desde_loanbook(lb)
        cuota_monto = _cuota_base_desde_loanbook(lb)
        cuota_inicial = lb.get("plan", {}).get("cuota_inicial", 0) or 0
        valor_total_actual = lb.get("valor_total", 0) or 0
        num_cuotas_actual = _num_cuotas_desde_loanbook(lb)
        cuotas = lb.get("cuotas", [])

        if plan_codigo and plan_codigo in PLAN_CUOTAS:
            total_cuotas_correcto = get_num_cuotas(plan_codigo, modalidad)

            # ── Check 4: combinación no configurada ───────────────────────
            if total_cuotas_correcto is None:
                casos_combinacion_invalida.append({
                    "loanbook_id": loanbook_id,
                    "cliente": cliente,
                    "plan_codigo": plan_codigo,
                    "modalidad": modalidad,
                    "motivo": f"PLAN_CUOTAS[{plan_codigo}][{modalidad}] = None",
                })
                continue  # no se puede auditar valor ni cuotas sin tabla

            # ── Check 1: valor_total ──────────────────────────────────────
            valor_total_correcto = total_cuotas_correcto * cuota_monto + cuota_inicial
            if abs(valor_total_actual - valor_total_correcto) > 1:  # tolerancia $1 COP
                casos_valor_total.append({
                    "loanbook_id": loanbook_id,
                    "cliente": cliente,
                    "plan_codigo": plan_codigo,
                    "modalidad": modalidad,
                    "muestra": valor_total_actual,
                    "deberia_ser": round(valor_total_correcto),
                    "formula": (
                        f"{total_cuotas_correcto} ({plan_codigo} {modalidad}) "
                        f"× {cuota_monto:,.0f} (cuota_valor) "
                        f"+ {cuota_inicial:,.0f} (cuota_inicial)"
                    ),
                    "diferencia": round(valor_total_actual - valor_total_correcto),
                })

            # ── Check 2: total_cuotas ─────────────────────────────────────
            if num_cuotas_actual != total_cuotas_correcto:
                casos_total_cuotas.append({
                    "loanbook_id": loanbook_id,
                    "cliente": cliente,
                    "plan_codigo": plan_codigo,
                    "modalidad": modalidad,
                    "total_cuotas_muestra": num_cuotas_actual,
                    "total_cuotas_correcto": total_cuotas_correcto,
                })

        # ── Check 3: cuotas futuras pagadas sin evidencia real ────────────
        cuotas_sospechosas = []
        cuotas_fecha_pago_fut = []
        for c in cuotas:
            fecha_cuota = c.get("fecha", "")
            fecha_pago_c = c.get("fecha_pago")
            referencia = c.get("referencia")
            metodo = c.get("metodo_pago")

            # Check 5: cualquier cuota con fecha_pago registrada en el futuro
            if fecha_pago_c and fecha_pago_c > hoy_str:
                cuotas_fecha_pago_fut.append({
                    "numero": c.get("numero"),
                    "estado": c.get("estado"),
                    "fecha_cuota": fecha_cuota,
                    "fecha_pago": fecha_pago_c,
                })

            # Check 3: cuota futura marcada pagada sin evidencia
            if c.get("estado") != "pagada":
                continue
            tiene_evidencia = bool(referencia) or bool(
                metodo and metodo not in ("", "seed", None)
            )
            if fecha_cuota > hoy_str and not tiene_evidencia:
                cuotas_sospechosas.append({
                    "numero": c.get("numero"),
                    "fecha": fecha_cuota,
                    "fecha_pago": fecha_pago_c,
                    "tiene_referencia": bool(referencia),
                    "tiene_metodo": bool(metodo),
                })

        if cuotas_sospechosas:
            casos_cuotas_imposibles.append({
                "loanbook_id": loanbook_id,
                "cliente": cliente,
                "cuotas": cuotas_sospechosas,
            })

        if cuotas_fecha_pago_fut:
            casos_fecha_pago_futura.append({
                "loanbook_id": loanbook_id,
                "cliente": cliente,
                "cuotas": cuotas_fecha_pago_fut,
            })

    return {
        "fecha_auditoria": datetime.now(timezone.utc).isoformat(),
        "total_loanbooks": len(loanbooks),
        "resumen": {
            "valor_total_incorrecto": len(casos_valor_total),
            "total_cuotas_incorrecto_segun_plan": len(casos_total_cuotas),
            "cuotas_pagadas_con_fecha_imposible": len(casos_cuotas_imposibles),
            "combinacion_no_configurada": len(casos_combinacion_invalida),
            "cuotas_con_fecha_pago_futura": len(casos_fecha_pago_futura),
        },
        "casos": {
            "valor_total_incorrecto": casos_valor_total,
            "total_cuotas_incorrecto_segun_plan": casos_total_cuotas,
            "cuotas_pagadas_fecha_imposible": casos_cuotas_imposibles,
            "combinacion_no_configurada": casos_combinacion_invalida,
            "cuotas_con_fecha_pago_futura": casos_fecha_pago_futura,
        },
    }
