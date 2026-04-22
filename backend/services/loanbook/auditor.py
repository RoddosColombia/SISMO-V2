"""
services/loanbook/auditor.py — Auditoría de consistencia estructural del portafolio.

Función pura: recibe una lista de loanbooks (ya fetcheados del DB) y devuelve
un dict con resumen + casos de corrupción detectados.

Detecta 3 categorías de inconsistencia:
  1. valor_total_incorrecto        — no coincide con la fórmula firme
  2. total_cuotas_incorrecto       — no deriva correctamente del plan_codigo + modalidad
  3. cuotas_pagadas_fecha_imposible — cuotas futuras marcadas pagadas sin evidencia real

Nota: las constantes PLANES_RODDOS y MULTIPLICADOR_* se mueven a
state_calculator.py en BUILD 2. Este módulo importará desde allí.
"""

from datetime import date, datetime, timezone

# ─────────────────────── Constantes de negocio ────────────────────────────────
# BUILD 2 las moverá a state_calculator.py; aquí son la fuente provisional.

PLANES_RODDOS: dict[str, int] = {
    "P15S": 15,  # Comparendos — 15 cuotas semanales
    "P39S": 39,  # Motos estándar — 39 semanas ≈ 9 meses
    "P52S": 52,  # Motos estándar — 52 semanas = 1 año
    "P78S": 78,  # Motos premium — 78 semanas ≈ 18 meses
}

MULTIPLICADOR_TOTAL_CUOTAS: dict[str, float] = {
    "semanal":   1.0,
    "quincenal": 1 / 2.2,  # round(39/2.2) = 18
    "mensual":   1 / 4.4,  # round(39/4.4) = 9
}

MULTIPLICADOR_VALOR_CUOTA: dict[str, float] = {
    "semanal":   1.0,
    "quincenal": 2.2,
    "mensual":   4.4,
}


def _derivar_total_cuotas(plan_codigo: str, modalidad: str) -> int | None:
    """Número correcto de cuotas según plan y modalidad."""
    base = PLANES_RODDOS.get(plan_codigo)
    if base is None:
        return None
    factor = MULTIPLICADOR_TOTAL_CUOTAS.get(modalidad, 1.0)
    return round(base * factor)


def _cuota_base_desde_loanbook(lb: dict) -> float:
    """
    Extrae el valor de cuota semanal (base de referencia).
    Soporta tanto el schema viejo (cuota_monto / num_cuotas) como el nuevo (plan.cuota_valor).
    """
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
    """
    hoy = date.today()
    hoy_str = hoy.isoformat()

    casos_valor_total: list[dict] = []
    casos_total_cuotas: list[dict] = []
    casos_cuotas_imposibles: list[dict] = []

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

        if plan_codigo and plan_codigo in PLANES_RODDOS:
            total_cuotas_correcto = _derivar_total_cuotas(plan_codigo, modalidad)

            # ── Check 1: valor_total ──────────────────────────────────────
            valor_total_correcto = total_cuotas_correcto * cuota_monto + cuota_inicial
            if abs(valor_total_actual - valor_total_correcto) > 1:  # tolerancia $1 COP
                casos_valor_total.append({
                    "loanbook_id": loanbook_id,
                    "cliente": cliente,
                    "plan_codigo": plan_codigo,
                    "modalidad": modalidad,
                    "muestra": valor_total_actual,
                    "deberia_ser": valor_total_correcto,
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
        for c in cuotas:
            if c.get("estado") != "pagada":
                continue
            fecha_cuota = c.get("fecha", "")
            fecha_pago = c.get("fecha_pago")
            referencia = c.get("referencia")
            metodo = c.get("metodo_pago")
            # Evidencia real = tiene referencia bancaria O método explícito que no sea seed
            tiene_evidencia = bool(referencia) or bool(metodo and metodo not in ("", "seed", None))

            if fecha_cuota > hoy_str and not tiene_evidencia:
                cuotas_sospechosas.append({
                    "numero": c.get("numero"),
                    "fecha": fecha_cuota,
                    "fecha_pago": fecha_pago,
                    "tiene_referencia": bool(referencia),
                    "tiene_metodo": bool(metodo),
                })

        if cuotas_sospechosas:
            casos_cuotas_imposibles.append({
                "loanbook_id": loanbook_id,
                "cliente": cliente,
                "cuotas": cuotas_sospechosas,
            })

    return {
        "fecha_auditoria": datetime.now(timezone.utc).isoformat(),
        "total_loanbooks": len(loanbooks),
        "resumen": {
            "valor_total_incorrecto": len(casos_valor_total),
            "total_cuotas_incorrecto_segun_plan": len(casos_total_cuotas),
            "cuotas_pagadas_con_fecha_imposible": len(casos_cuotas_imposibles),
        },
        "casos": {
            "valor_total_incorrecto": casos_valor_total,
            "total_cuotas_incorrecto_segun_plan": casos_total_cuotas,
            "cuotas_pagadas_fecha_imposible": casos_cuotas_imposibles,
        },
    }
