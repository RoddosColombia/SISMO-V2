"""
routers/cobranza.py — Plan de Cobro Semanal RODDOS.

Genera el listado canónico de cuotas pendientes para un miércoles de cobro
agrupadas en 3 secciones por DPD canónico (services.cobranza.sub_buckets):

    BLANCO   = dpd == 0          (cuota nueva, vence ese miércoles)
    AMARILLO = 1 <= dpd <= 7     (atraso de hasta 1 semana — Grace bucket)
    ROJO     = dpd >= 8          (atraso de 2+ semanas — Warning+ buckets)

Cada fila representa UNA CUOTA pendiente. Un cliente que adeuda la cuota
anterior y además le toca pagar la nueva aparece DOS veces (intencional —
liz debe cobrar las dos).

Usado por:
  - Página móvil /cartera/cobranza-semanal (checklist)
  - Email automático martes 5PM (cuerpo HTML del informe)
  - API consumida por scheduler martes

Reglas canónicas respetadas (CLAUDE.md):
  - Sub-bucket via services.cobranza.sub_buckets.asignar_sub_bucket()
  - Fechas via core.datetime_utils.today_bogota()
  - Estado activo definido por lista compartida con cartera_revisor.py
  - Cero cálculos inline de saldos/intereses (motor financiero intacto)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_db
from core.datetime_utils import today_bogota, now_iso_bogota
from services.cobranza.sub_buckets import asignar_sub_bucket
from services.loanbook.reglas_negocio import (
    primer_miercoles_cobro,
    DIAS_ENTRE_CUOTAS,
    get_num_cuotas,
)

logger = logging.getLogger("routers.cobranza")

router = APIRouter(prefix="/api/cobranza", tags=["cobranza"])


# ─────────────────────────── Constantes ──────────────────────────────────────

# Estados que se excluyen del plan de cobro (alineado con cartera_revisor.py)
ESTADOS_EXCLUIR_PLAN = {
    "saldado", "Pagado", "pagado",
    "castigado", "ChargeOff", "Charge-Off", "charge_off",
    "pendiente_entrega", "Pendiente Entrega", "pendiente entrega",
}

SECCION_BLANCO   = "blanco"
SECCION_AMARILLO = "amarillo"
SECCION_ROJO     = "rojo"


# ─────────────────────────── Helpers ─────────────────────────────────────────

def _normalizar_a_miercoles(d: date) -> date:
    """Devuelve el miércoles de la semana ISO (lun-dom) que contiene `d`.

    Caso típico: el frontend pasa hoy (jueves 30-abr) y queremos el miércoles
    de la semana que contiene esa fecha. Para "esta semana" definimos:
      - Si d es miércoles (weekday=2): devolver d.
      - Si d es lunes/martes: miércoles posterior (siguiente miércoles).
      - Si d es jueves..domingo: miércoles próximo (semana siguiente).

    Esto cuadra con el ciclo operativo RODDOS donde el martes 5PM se arma
    el plan del miércoles inmediatamente siguiente.
    """
    weekday = d.weekday()  # lunes=0 ... domingo=6, miércoles=2
    if weekday == 2:
        return d
    # Días hasta el próximo miércoles (siempre futuro o mismo día)
    delta = (2 - weekday) % 7
    if delta == 0:
        delta = 7
    return d + timedelta(days=delta)


def _parse_cuota_fecha(raw: str | date | datetime | None) -> date | None:
    """Tolera fecha como ISO string, datetime o date. Devuelve date o None."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return None


def _seccion_para_dpd(dpd: int) -> str | None:
    """Devuelve qué sección (blanco/amarillo/rojo) corresponde al dpd.

    Retorna None si la cuota es futura (dpd < 0): no entra al plan.
    """
    if dpd < 0:
        return None
    if dpd == 0:
        return SECCION_BLANCO
    if dpd <= 7:
        return SECCION_AMARILLO
    return SECCION_ROJO


def _extraer_cliente(lb: dict) -> dict:
    """Extrae nombre/cédula/teléfono con fallbacks consistentes."""
    cliente_block = lb.get("cliente") or {}
    nombre = (
        cliente_block.get("nombre")
        or lb.get("cliente_nombre")
        or "?"
    )
    cedula = (
        cliente_block.get("cedula")
        or lb.get("cliente_cedula")
        or ""
    )
    telefono = (
        cliente_block.get("telefono")
        or lb.get("cliente_telefono")
        or ""
    )
    return {"nombre": nombre, "cedula": str(cedula), "telefono": str(telefono)}


def _es_cuota_pagada(cuota: dict) -> bool:
    """Una cuota está pagada si su estado lo indica o tiene monto_pagado>0."""
    estado = (cuota.get("estado") or "").lower()
    if estado in ("pagada", "paid", "pagado"):
        return True
    monto_pagado = float(cuota.get("monto_pagado") or 0)
    return monto_pagado > 0


def _comprobante_info(cuota: dict) -> dict:
    """Lee info de comprobante adjunto a la cuota (si existe).

    Estructura esperada (poblada por COBRANZA-MARTES-3):
        cuota["comprobante"] = {
            "url": "...",
            "subido_at": "ISO",
            "subido_por": "liz",
            "verificado_banco": false,
        }
    """
    comp = cuota.get("comprobante") or {}
    return {
        "recibido":           bool(comp.get("url")),
        "url":                comp.get("url"),
        "subido_at":          comp.get("subido_at"),
        "subido_por":         comp.get("subido_por"),
        "verificado_banco":   bool(comp.get("verificado_banco", False)),
    }


# ─────────────────────────── Endpoint principal ──────────────────────────────

@router.get("/plan-semanal")
async def plan_semanal(
    semana: Annotated[
        str | None,
        Query(description="Fecha YYYY-MM-DD; se normaliza al miércoles de esa semana"),
    ] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Plan de cobro para el miércoles de la semana solicitada.

    Reglas:
      - Cada fila = UNA cuota pendiente del cronograma.
      - dpd = (miércoles_target - fecha_cuota).days.
      - Sección por dpd (canónico sub_buckets):
            blanco   dpd==0     | amarillo 1..7 | rojo >=8
      - Cuotas futuras (dpd<0) no aparecen.
      - Cuotas pagadas no aparecen (excepto si vienen marcadas en filtro).
      - Loanbooks en estado saldado / castigado / pendiente_entrega excluidos.

    Returns:
        {
          "semana_miercoles":   "2026-05-06",
          "fecha_corte":        "2026-04-30",
          "secciones": {
            "blanco":   {label, items[], subtotal_count, subtotal_monto},
            "amarillo": {...},
            "rojo":     {...}
          },
          "totales": {
            "esperado":          int,
            "recibido":          int,
            "pendiente":         int,
            "personas_pagaron":  int,
            "personas_faltan":   int,
            "filas_total":       int,
            "filas_pagadas":     int
          },
          "fecha_analisis": "ISO"
        }
    """
    fecha_corte = today_bogota()

    # Normalizar fecha de semana solicitada
    if semana:
        try:
            d_input = date.fromisoformat(semana)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"semana inválida '{semana}', se esperaba YYYY-MM-DD",
            )
    else:
        d_input = fecha_corte
    miercoles_target = _normalizar_a_miercoles(d_input)

    # Init secciones
    secciones: dict[str, dict] = {
        SECCION_BLANCO: {
            "label":          "Cobros normales de la semana",
            "descripcion":    "Cuotas que vencen este miércoles, sin atrasos previos",
            "color_hex":      "ffffff",
            "items":          [],
            "subtotal_count": 0,
            "subtotal_monto": 0,
            "subtotal_pagados_count": 0,
            "subtotal_pagados_monto": 0,
        },
        SECCION_AMARILLO: {
            "label":          "Atrasos de 1 semana",
            "descripcion":    "Clientes que no pagaron la cuota de la semana pasada",
            "color_hex":      "fef3c7",  # amber-100 (background)
            "items":          [],
            "subtotal_count": 0,
            "subtotal_monto": 0,
            "subtotal_pagados_count": 0,
            "subtotal_pagados_monto": 0,
        },
        SECCION_ROJO: {
            "label":          "Críticos: 2+ semanas atrasadas",
            "descripcion":    "Casos para gestión directa de Andrés / Fabián",
            "color_hex":      "fee2e2",  # red-100 (background)
            "items":          [],
            "subtotal_count": 0,
            "subtotal_monto": 0,
            "subtotal_pagados_count": 0,
            "subtotal_pagados_monto": 0,
        },
    }

    # Tracking de personas únicas (para counters)
    personas_total: set[str] = set()
    personas_pagaron: set[str] = set()

    # Recorrer loanbooks activos
    async for lb in db.loanbook.find({}):
        estado_lb = (lb.get("estado") or "").strip()
        if estado_lb in ESTADOS_EXCLUIR_PLAN:
            continue

        cuotas = lb.get("cuotas") or []
        if not cuotas:
            continue  # no hay cronograma todavía

        cliente = _extraer_cliente(lb)
        loanbook_id = lb.get("loanbook_id") or lb.get("loanbook_codigo") or str(lb.get("_id"))
        modelo = (
            lb.get("modelo")
            or (lb.get("moto") or {}).get("modelo")
            or lb.get("plan_codigo", "")
        )
        modalidad = lb.get("modalidad") or lb.get("modalidad_pago") or "semanal"

        for cuota in cuotas:
            # Solo cuotas pendientes/vencidas (no pagadas)
            if _es_cuota_pagada(cuota):
                # excepción: si es la cuota de esta semana y ya pagada, marcarla pagada
                # para que el counter "pagaron" se actualice. Pero solo si la fecha
                # está en o antes del miércoles target (no contar futuras).
                fecha_cuota = _parse_cuota_fecha(
                    cuota.get("fecha") or cuota.get("fecha_programada")
                )
                if fecha_cuota is None:
                    continue
                dpd = (miercoles_target - fecha_cuota).days
                if dpd < 0:
                    continue
                seccion = _seccion_para_dpd(dpd)
                if seccion is None:
                    continue
                # Item pagado
                item = _construir_item(
                    lb, cuota, cliente, loanbook_id, modelo, modalidad,
                    fecha_cuota, dpd, pagada=True,
                )
                secciones[seccion]["items"].append(item)
                secciones[seccion]["subtotal_count"] += 1
                secciones[seccion]["subtotal_monto"] += int(item["cuota_monto"])
                secciones[seccion]["subtotal_pagados_count"] += 1
                secciones[seccion]["subtotal_pagados_monto"] += int(item["cuota_monto"])
                personas_total.add(loanbook_id)
                personas_pagaron.add(loanbook_id)
                continue

            fecha_cuota = _parse_cuota_fecha(
                cuota.get("fecha") or cuota.get("fecha_programada")
            )
            if fecha_cuota is None:
                continue

            dpd = (miercoles_target - fecha_cuota).days
            seccion = _seccion_para_dpd(dpd)
            if seccion is None:
                continue  # cuota futura, no entra al plan de esta semana

            item = _construir_item(
                lb, cuota, cliente, loanbook_id, modelo, modalidad,
                fecha_cuota, dpd, pagada=False,
            )
            secciones[seccion]["items"].append(item)
            secciones[seccion]["subtotal_count"] += 1
            secciones[seccion]["subtotal_monto"] += int(item["cuota_monto"])
            personas_total.add(loanbook_id)

    # Ordenar dentro de cada sección por dpd desc, luego por nombre
    for sec in secciones.values():
        sec["items"].sort(
            key=lambda it: (-int(it["dpd"]), str(it["cliente_nombre"]))
        )

    # Totales globales
    esperado = sum(s["subtotal_monto"] for s in secciones.values())
    recibido = sum(s["subtotal_pagados_monto"] for s in secciones.values())
    filas_total = sum(s["subtotal_count"] for s in secciones.values())
    filas_pagadas = sum(s["subtotal_pagados_count"] for s in secciones.values())
    n_personas = len(personas_total)
    n_pagaron  = len(personas_pagaron)

    return {
        "semana_miercoles": miercoles_target.isoformat(),
        "fecha_corte":      fecha_corte.isoformat(),
        "secciones":        secciones,
        "totales": {
            "esperado":         esperado,
            "recibido":         recibido,
            "pendiente":        max(0, esperado - recibido),
            "personas_pagaron": n_pagaron,
            "personas_faltan":  max(0, n_personas - n_pagaron),
            "personas_total":   n_personas,
            "filas_total":      filas_total,
            "filas_pagadas":    filas_pagadas,
        },
        "fecha_analisis": now_iso_bogota(),
    }


def _construir_item(
    lb: dict,
    cuota: dict,
    cliente: dict,
    loanbook_id: str,
    modelo: str,
    modalidad: str,
    fecha_cuota: date,
    dpd: int,
    pagada: bool,
) -> dict:
    """Construye el dict de un item del plan (una fila de cuota)."""
    cuota_numero = (
        cuota.get("numero")
        or cuota.get("numero_cuota")
        or cuota.get("cuota_numero")
        or 0
    )
    cuota_monto = (
        cuota.get("monto")
        or cuota.get("monto_total")
        or lb.get("cuota_monto")
        or lb.get("cuota_periodica")
        or 0
    )
    sub_bucket = asignar_sub_bucket(max(0, dpd))
    comp = _comprobante_info(cuota)

    return {
        "loanbook_id":         loanbook_id,
        "cliente_nombre":      cliente["nombre"],
        "cliente_cedula":      cliente["cedula"],
        "cliente_telefono":    cliente["telefono"],
        "modelo":              modelo,
        "modalidad":           modalidad,
        "cuota_numero":        int(cuota_numero) if cuota_numero else 0,
        "cuota_fecha":         fecha_cuota.isoformat(),
        "cuota_monto":         int(cuota_monto or 0),
        "dpd":                 int(dpd),
        "sub_bucket":          sub_bucket,
        "pagada":              bool(pagada),
        "comprobante_recibido":         comp["recibido"],
        "comprobante_url":              comp["url"],
        "comprobante_subido_at":        comp["subido_at"],
        "comprobante_subido_por":       comp["subido_por"],
        "comprobante_verificado_banco": comp["verificado_banco"],
        "estado_loanbook":     lb.get("estado", ""),
    }


# ─────────────────────── Auditoría rigurosa del cronograma ──────────────────

@router.get("/audit/cronogramas")
async def audit_cronogramas(
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Audita la integridad del cronograma de TODOS los loanbooks activos.

    Para cada LB verifica:

      1. Tiene array `cuotas` no vacío.
      2. Cantidad de cuotas == num_cuotas declarado en el documento.
      3. Cantidad de cuotas == get_num_cuotas(plan_codigo, modalidad)
         cuando el plan está en el catálogo (RDX P39S+).
      4. Cuota #1 cae en el miércoles correcto (regla canónica o override).
      5. Intervalo entre cuotas consecutivas == DIAS_ENTRE_CUOTAS[modalidad].
      6. Cada cuota cae en miércoles (default) o en dia_cobro_especial.
      7. Cada cuota tiene monto > 0.
      8. Sumatoria de cuotas no pagadas == saldo_pendiente del documento
         (con tolerancia ±1 COP por redondeo).

    El email del martes NO debe enviarse si esta auditoría reporta
    violaciones rojas.

    Returns:
        {
          "fecha_corte": "...",
          "total_loanbooks_revisados": N,
          "loanbooks_ok": N,
          "loanbooks_con_violacion": N,
          "violaciones": [
            {
              "loanbook_id": "LB-...",
              "cliente_nombre": "...",
              "severidad": "roja"|"amarilla",
              "checks": [
                {"check": "1_array_cuotas_no_vacio", "ok": bool, "detalle": "..."},
                ...
              ]
            },
            ...
          ]
        }
    """
    fecha_corte = today_bogota()
    revisados = 0
    ok = 0
    violaciones = []

    async for lb in db.loanbook.find({}):
        estado = (lb.get("estado") or "").strip()
        if estado in ESTADOS_EXCLUIR_PLAN:
            continue
        revisados += 1

        cliente = _extraer_cliente(lb)
        loanbook_id = (
            lb.get("loanbook_id")
            or lb.get("loanbook_codigo")
            or str(lb.get("_id"))
        )

        checks = []
        roja = False

        # 1. Array cuotas no vacío
        cuotas = lb.get("cuotas") or []
        if not cuotas:
            checks.append({
                "check": "1_array_cuotas_no_vacio",
                "ok": False,
                "severidad": "roja",
                "detalle": "El loanbook no tiene cronograma generado",
            })
            roja = True
            violaciones.append({
                "loanbook_id":     loanbook_id,
                "cliente_nombre":  cliente["nombre"],
                "estado":          estado,
                "severidad":       "roja",
                "checks":          checks,
            })
            continue
        else:
            checks.append({
                "check": "1_array_cuotas_no_vacio",
                "ok": True,
                "severidad": "ok",
                "detalle": f"{len(cuotas)} cuotas en cronograma",
            })

        # 2. Cantidad cuotas == num_cuotas declarado
        num_cuotas_doc = int(
            lb.get("num_cuotas")
            or lb.get("cuotas_total")
            or lb.get("total_cuotas")
            or 0
        )
        if num_cuotas_doc and len(cuotas) != num_cuotas_doc:
            checks.append({
                "check": "2_cantidad_vs_declarada",
                "ok": False,
                "severidad": "roja",
                "detalle": f"Cuotas array={len(cuotas)} vs num_cuotas declarado={num_cuotas_doc}",
            })
            roja = True
        else:
            checks.append({
                "check": "2_cantidad_vs_declarada",
                "ok": True,
                "severidad": "ok",
                "detalle": f"{len(cuotas)} = {num_cuotas_doc}",
            })

        # 3. Cantidad cuotas == get_num_cuotas catalogo
        plan_codigo = (lb.get("plan_codigo") or "").strip()
        modalidad = (lb.get("modalidad") or lb.get("modalidad_pago") or "semanal").strip()
        try:
            n_canonico = get_num_cuotas(plan_codigo, modalidad)
        except Exception:
            n_canonico = None
        if n_canonico is not None:
            if len(cuotas) != n_canonico:
                checks.append({
                    "check": "3_cantidad_vs_catalogo",
                    "ok": False,
                    "severidad": "roja",
                    "detalle": (
                        f"Cuotas array={len(cuotas)} vs catalogo {plan_codigo}/{modalidad}={n_canonico}"
                    ),
                })
                roja = True
            else:
                checks.append({
                    "check": "3_cantidad_vs_catalogo",
                    "ok": True,
                    "severidad": "ok",
                    "detalle": f"{len(cuotas)} = catálogo {plan_codigo}/{modalidad}",
                })
        else:
            # Plan no en catálogo (RODANTE u otros) — saltar este check sin penalizar
            checks.append({
                "check": "3_cantidad_vs_catalogo",
                "ok": True,
                "severidad": "ok",
                "detalle": f"plan {plan_codigo or '(none)'} no en catálogo, check omitido",
            })

        # 4. Cuota #1 cae en miércoles correcto
        primera_cuota = cuotas[0]
        primera_fecha = _parse_cuota_fecha(
            primera_cuota.get("fecha") or primera_cuota.get("fecha_programada")
        )
        fecha_entrega_str = lb.get("fecha_entrega")
        fecha_primer_pago_str = lb.get("fecha_primer_pago")
        fecha_entrega = _parse_cuota_fecha(fecha_entrega_str) if fecha_entrega_str else None
        fecha_primer_pago = _parse_cuota_fecha(fecha_primer_pago_str) if fecha_primer_pago_str else None

        if primera_fecha is None:
            checks.append({
                "check": "4_primera_cuota_fecha_correcta",
                "ok": False,
                "severidad": "roja",
                "detalle": "Cuota #1 no tiene fecha asignada",
            })
            roja = True
        elif fecha_primer_pago is not None:
            # Override explícito
            if primera_fecha != fecha_primer_pago:
                checks.append({
                    "check": "4_primera_cuota_fecha_correcta",
                    "ok": False,
                    "severidad": "roja",
                    "detalle": (
                        f"Cuota #1={primera_fecha.isoformat()} vs override "
                        f"fecha_primer_pago={fecha_primer_pago.isoformat()}"
                    ),
                })
                roja = True
            else:
                checks.append({
                    "check": "4_primera_cuota_fecha_correcta",
                    "ok": True,
                    "severidad": "ok",
                    "detalle": f"Cuota #1 = override {primera_fecha.isoformat()} ✓",
                })
        elif fecha_entrega is not None and modalidad == "semanal":
            # Auto-canónica
            esperada = primer_miercoles_cobro(fecha_entrega)
            if primera_fecha != esperada:
                checks.append({
                    "check": "4_primera_cuota_fecha_correcta",
                    "ok": False,
                    "severidad": "roja",
                    "detalle": (
                        f"Cuota #1={primera_fecha.isoformat()} vs canónica "
                        f"primer_miercoles_cobro({fecha_entrega.isoformat()})="
                        f"{esperada.isoformat()}"
                    ),
                })
                roja = True
            else:
                checks.append({
                    "check": "4_primera_cuota_fecha_correcta",
                    "ok": True,
                    "severidad": "ok",
                    "detalle": (
                        f"Cuota #1 = canónica {primera_fecha.isoformat()} "
                        f"(entrega {fecha_entrega.isoformat()}) ✓"
                    ),
                })
        else:
            checks.append({
                "check": "4_primera_cuota_fecha_correcta",
                "ok": False,
                "severidad": "amarilla",
                "detalle": (
                    "Sin fecha_entrega ni fecha_primer_pago "
                    "para validar canónicamente"
                ),
            })

        # 5. Intervalo entre cuotas consecutivas
        intervalo_esperado = DIAS_ENTRE_CUOTAS.get(modalidad, 7)
        intervalos_malos = []
        for i in range(1, len(cuotas)):
            f_prev = _parse_cuota_fecha(
                cuotas[i - 1].get("fecha") or cuotas[i - 1].get("fecha_programada")
            )
            f_curr = _parse_cuota_fecha(
                cuotas[i].get("fecha") or cuotas[i].get("fecha_programada")
            )
            if f_prev is None or f_curr is None:
                intervalos_malos.append(
                    f"cuota {i + 1}: fecha faltante"
                )
                continue
            delta = (f_curr - f_prev).days
            if delta != intervalo_esperado:
                intervalos_malos.append(
                    f"cuota #{i + 1}: {delta} días (esperado {intervalo_esperado})"
                )
        if intervalos_malos:
            checks.append({
                "check": "5_intervalo_entre_cuotas",
                "ok": False,
                "severidad": "roja",
                "detalle": "; ".join(intervalos_malos[:5]),
            })
            roja = True
        else:
            checks.append({
                "check": "5_intervalo_entre_cuotas",
                "ok": True,
                "severidad": "ok",
                "detalle": f"Todas separadas por {intervalo_esperado} días",
            })

        # 6. Cada cuota cae en miércoles (default)
        target_dia_idx = 2  # Wednesday
        cuotas_no_miercoles = []
        for c in cuotas:
            f = _parse_cuota_fecha(c.get("fecha") or c.get("fecha_programada"))
            if f is not None and f.weekday() != target_dia_idx:
                cuotas_no_miercoles.append(
                    f"cuota #{c.get('numero', c.get('numero_cuota', '?'))}={f.isoformat()}"
                )
        if cuotas_no_miercoles:
            checks.append({
                "check": "6_todas_caen_en_miercoles",
                "ok": False,
                "severidad": "roja",
                "detalle": "; ".join(cuotas_no_miercoles[:5]),
            })
            roja = True
        else:
            checks.append({
                "check": "6_todas_caen_en_miercoles",
                "ok": True,
                "severidad": "ok",
                "detalle": "Todas las cuotas son miércoles",
            })

        # 7. Cada cuota tiene monto > 0
        cuotas_monto_cero = []
        for c in cuotas:
            monto = (
                c.get("monto")
                or c.get("monto_total")
                or 0
            )
            if int(monto) <= 0:
                cuotas_monto_cero.append(
                    f"cuota #{c.get('numero', c.get('numero_cuota', '?'))}=$0"
                )
        if cuotas_monto_cero:
            checks.append({
                "check": "7_montos_cuota_mayor_cero",
                "ok": False,
                "severidad": "roja",
                "detalle": "; ".join(cuotas_monto_cero[:5]),
            })
            roja = True
        else:
            checks.append({
                "check": "7_montos_cuota_mayor_cero",
                "ok": True,
                "severidad": "ok",
                "detalle": f"Las {len(cuotas)} cuotas tienen monto > 0",
            })

        # 8. Sumatoria cuotas pendientes vs saldo_pendiente
        suma_pendientes = 0
        for c in cuotas:
            if _es_cuota_pagada(c):
                continue
            monto = c.get("monto") or c.get("monto_total") or 0
            suma_pendientes += int(monto)
        saldo_pendiente_doc = int(lb.get("saldo_pendiente") or 0)
        diff = abs(suma_pendientes - saldo_pendiente_doc)
        if diff > 1:
            checks.append({
                "check": "8_suma_cuotas_vs_saldo_pendiente",
                "ok": False,
                "severidad": "amarilla",
                "detalle": (
                    f"Σ pendientes=${suma_pendientes:,} vs saldo_pendiente=${saldo_pendiente_doc:,} "
                    f"(diff=${diff:,})"
                ),
            })
            # amarilla, no roja
        else:
            checks.append({
                "check": "8_suma_cuotas_vs_saldo_pendiente",
                "ok": True,
                "severidad": "ok",
                "detalle": f"Σ pendientes=${suma_pendientes:,} ≈ saldo_pendiente",
            })

        if any(not c["ok"] for c in checks):
            severidad_lb = "roja" if roja else "amarilla"
            violaciones.append({
                "loanbook_id":     loanbook_id,
                "cliente_nombre":  cliente["nombre"],
                "estado":          estado,
                "severidad":       severidad_lb,
                "checks":          checks,
            })
        else:
            ok += 1

    # Severidad agregada del informe
    rojas = sum(1 for v in violaciones if v["severidad"] == "roja")
    amarillas = sum(1 for v in violaciones if v["severidad"] == "amarilla")
    semaforo = "verde" if rojas == 0 and amarillas == 0 else (
        "rojo" if rojas > 0 else "amarillo"
    )

    return {
        "fecha_corte":               fecha_corte.isoformat(),
        "fecha_analisis":            now_iso_bogota(),
        "semaforo":                  semaforo,
        "total_loanbooks_revisados": revisados,
        "loanbooks_ok":              ok,
        "loanbooks_con_violacion":   len(violaciones),
        "rojas":                     rojas,
        "amarillas":                 amarillas,
        "puede_enviar_email":        rojas == 0,
        "violaciones":               violaciones,
    }

