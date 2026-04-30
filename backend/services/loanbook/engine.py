"""
services/loanbook/engine.py — Motor unificado del Loanbook RODDOS.

API mínima (5 funciones públicas):

    crear_loanbook(...)              → produce doc canónico para insertar
    recalcular(loanbook_doc)         → reconcilia cualquier doc (sucio o no)
    registrar_pago(loanbook, monto, fecha, cuota_numero) → aplica waterfall
    plan_cobro_semanal(db, miercoles) → arma plan martes (3 secciones)
    auditar(loanbook_doc)            → devuelve violaciones por LB

Invariante del motor:
    Cada vez que un loanbook se persiste en MongoDB DEBE pasar antes por
    `recalcular()`. Use `loanbook_save()` (definido en core/database.py)
    o, en su defecto, llame a `recalcular()` antes del update_one.

Diseño:
    - Este módulo es la ÚNICA fachada pública del motor financiero.
    - Internamente delega a:
        services.loanbook.reglas_negocio  (fórmulas canónicas)
        services.loanbook.state_calculator (recalcular_loanbook existente)
        services.loanbook.catalogo_service (planes y modelos)
        services.cobranza.sub_buckets       (clasificación de mora)
        core.loanbook_model.calcular_cronograma (con regla del miércoles)

Fuentes de verdad respetadas (CLAUDE.md):
    - capital_plan: 7_800_000 Raider | 5_750_000 Sport 100 | monto_original RODANTE
    - primer_miercoles_cobro >= entrega + 7 días (canónico, sin override)
    - override fecha_primer_pago: respetado si es miércoles posterior a entrega
    - calcular_saldos() para sc/si — NUNCA cálculos inline
    - calcular_mora() para mora_acumulada y sub_bucket
"""
from __future__ import annotations

import copy
import logging
from datetime import date, datetime, timedelta
from typing import Any

from core.datetime_utils import today_bogota, now_iso_bogota
from core.loanbook_model import calcular_cronograma as _calcular_cronograma
from services.loanbook.reglas_negocio import (
    primer_miercoles_cobro,
    DIAS_ENTRE_CUOTAS,
    get_num_cuotas,
    calcular_saldos,
    calcular_mora,
    get_valor_total,
)
from services.loanbook.state_calculator import recalcular_loanbook as _recalcular_derivados
from services.cobranza.sub_buckets import asignar_sub_bucket

logger = logging.getLogger("loanbook.engine")

# ─────────────────────── Constantes ──────────────────────────────────────────

CAPITAL_PLAN_POR_MODELO: dict[str, int] = {
    "raider 125":  7_800_000,
    "raider":      7_800_000,
    "tvs raider":  7_800_000,
    "tvs raider 125": 7_800_000,
    "sport 100":   5_750_000,
    "sport":       5_750_000,
    "tvs sport":   5_750_000,
    "tvs sport 100": 5_750_000,
}

ESTADOS_TERMINALES = {"saldado", "castigado", "ChargeOff", "Charge-Off", "charge_off"}
ESTADO_NO_ENTREGADO = {"pendiente_entrega", "Pendiente Entrega", "pendiente entrega"}

WEDNESDAY = 2  # date.weekday()


# ─────────────────────── Helpers internos ────────────────────────────────────

def _normalizar_modelo(raw: Any) -> str:
    """Devuelve nombre de modelo limpio. Si raw es plan_codigo (P39S/P52S/P78S),
    lo deja vacío para forzar al caller a corregir."""
    if not raw:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    # Si es plan_codigo (P39S, P52S, P78S, P15S, P26S, etc.) lo descartamos —
    # el campo modelo NO debe contener códigos de plan
    upper = s.upper().replace(" ", "")
    if len(upper) <= 5 and upper.startswith("P") and upper.endswith("S"):
        return ""
    return s


def _capital_plan_desde_modelo(modelo: str) -> int | None:
    """Mapea modelo → capital_plan canónico de RODDOS."""
    if not modelo:
        return None
    key = modelo.lower().strip()
    return CAPITAL_PLAN_POR_MODELO.get(key)


def _parse_fecha(raw: Any) -> date | None:
    """Convierte ISO string / datetime / date a date. None si vacío."""
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


def _es_pagada(cuota: dict) -> bool:
    estado = (cuota.get("estado") or "").lower()
    if estado in ("pagada", "paid", "pagado"):
        return True
    return float(cuota.get("monto_pagado") or 0) > 0


def _modalidad(lb: dict) -> str:
    return (lb.get("modalidad") or lb.get("modalidad_pago") or "semanal").strip().lower()


def _cuota_monto(lb: dict) -> int:
    """Cuota canónica del crédito (per-period). Fallbacks ordenados."""
    val = (
        lb.get("cuota_monto")
        or lb.get("cuota_periodica")
        or lb.get("cuota_estandar_plan")
        or 0
    )
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _num_cuotas(lb: dict) -> int:
    """Número canónico de cuotas. Prioridad: catálogo > num_cuotas declarado > len(cuotas)."""
    plan_codigo = (lb.get("plan_codigo") or "").strip()
    modalidad = _modalidad(lb)
    if plan_codigo:
        n_cat = get_num_cuotas(plan_codigo, modalidad)
        if n_cat is not None:
            return int(n_cat)
    val = lb.get("num_cuotas") or lb.get("cuotas_total") or lb.get("total_cuotas") or len(lb.get("cuotas") or [])
    return int(val or 0)


# ─────────────────────── Función pública 1: crear_loanbook ──────────────────

def crear_loanbook(
    *,
    loanbook_id: str,
    cliente: dict,
    plan_codigo: str,
    modelo: str,
    modalidad: str,
    fecha_entrega: date | str,
    fecha_primer_pago: date | str | None = None,
    cuota_monto: int | None = None,
    monto_original: int | None = None,
    vin: str | None = None,
    estado: str = "pendiente_entrega",
    extra_fields: dict | None = None,
) -> dict:
    """Construye un doc loanbook canónico listo para insertar.

    Aplica internamente recalcular() para que el doc resultante sea consistente
    desde el primer momento. Sin I/O.
    """
    fecha_entrega_d = _parse_fecha(fecha_entrega)
    fecha_primer_pago_d = _parse_fecha(fecha_primer_pago) if fecha_primer_pago else None

    modelo_clean = _normalizar_modelo(modelo)
    capital_plan = _capital_plan_desde_modelo(modelo_clean) or int(monto_original or 0)

    n_cuotas_cat = get_num_cuotas(plan_codigo, modalidad) if plan_codigo else None

    doc = {
        "loanbook_id":      loanbook_id,
        "vin":              vin,
        "cliente":          cliente,
        "plan_codigo":      plan_codigo,
        "modelo":           modelo_clean,
        "modalidad":        modalidad,
        "fecha_entrega":    fecha_entrega_d.isoformat() if fecha_entrega_d else None,
        "fecha_primer_pago": fecha_primer_pago_d.isoformat() if fecha_primer_pago_d else None,
        "estado":           estado,
        "cuota_monto":      int(cuota_monto or 0),
        "cuota_periodica":  int(cuota_monto or 0),
        "num_cuotas":       int(n_cuotas_cat or 0),
        "capital_plan":     capital_plan,
        "monto_original":   int(monto_original or 0),
        "cuotas":           [],
        "saldo_capital":    0,
        "saldo_intereses":  0,
        "saldo_pendiente":  0,
        "total_pagado":     0,
        "valor_total":      0,
        "dpd":              0,
        "sub_bucket":       "Current",
        "fecha_creacion":   now_iso_bogota(),
    }
    if extra_fields:
        doc.update(extra_fields)

    return recalcular(doc)


# ─────────────────────── Función pública 2: recalcular ──────────────────────

def recalcular(loanbook_doc: dict, *, hoy: date | None = None) -> dict:
    """Reconcilia un doc loanbook: cronograma, saldos, mora, sub_bucket, estado.

    Toma cualquier doc (sucio, parcial, inconsistente) y devuelve la versión
    canónica. Idempotente: aplicarlo N veces da el mismo resultado.

    Pasos:
        1. Limpia campo `modelo` si contenía plan_codigo (P39S/P78S/etc.).
        2. Regenera cronograma SI faltan cuotas o las fechas no son canónicas.
        3. Aplica state_calculator.recalcular_loanbook() para saldos/dpd/estado.
        4. Sobrescribe sub_bucket con clasificación canónica desde dpd.
        5. Calcula saldo_pendiente = sc + si.
        6. Recalcula mora_acumulada si dpd > 0.

    Sin I/O. El caller persiste el resultado.
    """
    if hoy is None:
        hoy = today_bogota()

    doc = copy.deepcopy(loanbook_doc)

    # ── 1. Limpieza de modelo ───────────────────────────────────────────────
    modelo_actual = doc.get("modelo") or ""
    modelo_clean = _normalizar_modelo(modelo_actual)
    if modelo_clean != modelo_actual:
        doc["modelo"] = modelo_clean

    # capital_plan derivado del modelo si está vacío
    if not doc.get("capital_plan") and modelo_clean:
        cap = _capital_plan_desde_modelo(modelo_clean)
        if cap:
            doc["capital_plan"] = cap

    # ── 2. Regenerar cronograma si es necesario ────────────────────────────
    estado = (doc.get("estado") or "").strip()
    if estado not in ESTADO_NO_ENTREGADO and estado not in ESTADOS_TERMINALES:
        doc = _reconciliar_cronograma(doc)

    # ── 3. Recalcular derivados (saldos, dpd, estado) ──────────────────────
    doc = _recalcular_derivados(doc, hoy=hoy)

    # ── 4. Sub-bucket canónico desde dpd ───────────────────────────────────
    dpd = int(doc.get("dpd") or 0)
    doc["sub_bucket"] = asignar_sub_bucket(max(0, dpd))

    # ── 5. saldo_pendiente = sc + si ───────────────────────────────────────
    sc = int(doc.get("saldo_capital") or 0)
    si = int(doc.get("saldo_intereses") or 0)
    doc["saldo_pendiente"] = max(0, sc + si)

    # ── 6. mora_acumulada si dpd > 0 ───────────────────────────────────────
    if dpd > 0:
        mora_data = calcular_mora(dpd)
        doc["mora_acumulada"] = int(mora_data["mora_acumulada_cop"])
    else:
        doc["mora_acumulada"] = 0

    doc["fecha_ultima_recalculacion"] = now_iso_bogota()
    return doc


def _reconciliar_cronograma(doc: dict) -> dict:
    """Si el cronograma está mal (faltan cuotas o fechas no canónicas), lo regenera.

    Preserva el estado de pago de las cuotas existentes que coincidan por número.
    """
    fecha_entrega = _parse_fecha(doc.get("fecha_entrega"))
    if fecha_entrega is None:
        return doc  # sin fecha de entrega no se puede generar cronograma

    fecha_primer_pago = _parse_fecha(doc.get("fecha_primer_pago"))
    modalidad = _modalidad(doc)
    n_cuotas = _num_cuotas(doc)
    cuota_monto = _cuota_monto(doc)

    if n_cuotas <= 0 or cuota_monto <= 0:
        return doc  # falta data esencial

    # Calcular fechas canónicas
    try:
        fechas_canonicas = _calcular_cronograma(
            fecha_entrega=fecha_entrega,
            modalidad=modalidad,
            num_cuotas=n_cuotas,
            fecha_primer_pago=fecha_primer_pago,
        )
    except ValueError as e:
        logger.warning(
            "engine: no se pudo regenerar cronograma de %s: %s",
            doc.get("loanbook_id"), e,
        )
        return doc

    cuotas_actuales = doc.get("cuotas") or []

    # Preservar estado/monto_pagado de cuotas existentes por número
    by_numero = {}
    for c in cuotas_actuales:
        n = c.get("numero") or c.get("numero_cuota") or 0
        if n:
            by_numero[int(n)] = c

    cronograma_nuevo = []
    for i, fecha in enumerate(fechas_canonicas, start=1):
        anterior = by_numero.get(i, {})
        cronograma_nuevo.append({
            "numero":         i,
            "fecha":          fecha.isoformat(),
            "monto":          cuota_monto,
            "estado":         anterior.get("estado", "pendiente"),
            "monto_pagado":   anterior.get("monto_pagado", 0),
            "fecha_pago":     anterior.get("fecha_pago"),
            "metodo_pago":    anterior.get("metodo_pago"),
            "comprobante":    anterior.get("comprobante"),
            "mora_acumulada": anterior.get("mora_acumulada", 0),
        })

    # Solo reemplazar si hay cambio real (idempotencia)
    fechas_actuales = [c.get("fecha") for c in cuotas_actuales if c.get("fecha")]
    fechas_nuevas = [c["fecha"] for c in cronograma_nuevo]
    if fechas_actuales != fechas_nuevas or len(cuotas_actuales) != len(cronograma_nuevo):
        doc["cuotas"] = cronograma_nuevo
        doc["fecha_primera_cuota"] = cronograma_nuevo[0]["fecha"]
        doc["fecha_ultima_cuota"] = cronograma_nuevo[-1]["fecha"]

    return doc


# ─────────────────────── Función pública 3: registrar_pago ──────────────────

def registrar_pago(
    loanbook_doc: dict,
    monto: int,
    fecha_pago: date | str,
    cuota_numero: int | None = None,
    metodo_pago: str | None = None,
    comprobante: dict | None = None,
) -> dict:
    """Registra un pago aplicando waterfall canónico.

    Si cuota_numero=None, aplica al primer cuota pendiente.
    Devuelve doc actualizado y recalculado.
    """
    fecha_pago_d = _parse_fecha(fecha_pago) or today_bogota()
    doc = copy.deepcopy(loanbook_doc)
    cuotas = doc.get("cuotas") or []
    if not cuotas:
        raise ValueError("Loanbook sin cronograma — no se puede registrar pago")

    # Identificar cuota objetivo
    if cuota_numero is None:
        for c in cuotas:
            if not _es_pagada(c):
                cuota_numero = int(c.get("numero") or c.get("numero_cuota") or 0)
                break
        if cuota_numero is None:
            raise ValueError("No hay cuotas pendientes")

    target = None
    for c in cuotas:
        if int(c.get("numero") or c.get("numero_cuota") or 0) == int(cuota_numero):
            target = c
            break
    if target is None:
        raise ValueError(f"Cuota #{cuota_numero} no encontrada en el cronograma")

    target["estado"] = "pagada"
    target["monto_pagado"] = int(target.get("monto_pagado") or 0) + int(monto)
    target["fecha_pago"] = fecha_pago_d.isoformat()
    if metodo_pago:
        target["metodo_pago"] = metodo_pago
    if comprobante:
        target["comprobante"] = comprobante

    # Auto-recálculo
    return recalcular(doc, hoy=fecha_pago_d)


# ─────────────────────── Función pública 4: plan_cobro_semanal ──────────────

async def plan_cobro_semanal(db, miercoles: date) -> dict:
    """Construye el plan de cobro para el miércoles dado.

    3 secciones:
        BLANCO   = cuotas que vencen ese miércoles, dpd=0
        AMARILLO = cuotas pendientes con dpd 1-7
        ROJO     = cuotas pendientes con dpd >= 8 (críticas)

    Reglas:
        - Solo cuotas PENDIENTES entran (no pagadas).
        - Excepción: en sección BLANCO, las del miércoles target ya pagadas
          aparecen marcadas pagada=true (para checklist visual).
        - No incluye cuotas futuras (dpd < 0).
        - Excluye loanbooks saldado/castigado/pendiente_entrega.
    """
    estados_excluir = ESTADOS_TERMINALES | ESTADO_NO_ENTREGADO

    secciones = {
        "blanco":   {"label": "Cobros normales de la semana", "items": [],
                     "subtotal_count": 0, "subtotal_monto": 0,
                     "subtotal_pagados_count": 0, "subtotal_pagados_monto": 0},
        "amarillo": {"label": "Atrasos de 1 semana", "items": [],
                     "subtotal_count": 0, "subtotal_monto": 0,
                     "subtotal_pagados_count": 0, "subtotal_pagados_monto": 0},
        "rojo":     {"label": "Críticos: 2+ semanas atrasadas", "items": [],
                     "subtotal_count": 0, "subtotal_monto": 0,
                     "subtotal_pagados_count": 0, "subtotal_pagados_monto": 0},
    }

    personas_total: set = set()
    personas_pagaron: set = set()

    async for lb in db.loanbook.find({}):
        if (lb.get("estado") or "").strip() in estados_excluir:
            continue
        cuotas = lb.get("cuotas") or []
        if not cuotas:
            continue

        cliente = lb.get("cliente") or {}
        loanbook_id = lb.get("loanbook_id") or str(lb.get("_id"))
        modelo = _normalizar_modelo(lb.get("modelo") or "")
        modalidad = _modalidad(lb)

        for cuota in cuotas:
            fecha_cuota = _parse_fecha(cuota.get("fecha") or cuota.get("fecha_programada"))
            if fecha_cuota is None:
                continue
            dpd = (miercoles - fecha_cuota).days
            if dpd < 0:
                continue  # cuota futura

            pagada = _es_pagada(cuota)
            es_target = (fecha_cuota == miercoles)

            # Regla: cuotas pagadas históricas NO entran (excepto las del miércoles target)
            if pagada and not es_target:
                continue

            # Sección por dpd
            if dpd == 0:
                seccion = "blanco"
            elif dpd <= 7:
                seccion = "amarillo"
            else:
                seccion = "rojo"

            # Filas en amarillo/rojo solo si NO están pagadas
            if seccion in ("amarillo", "rojo") and pagada:
                continue

            cuota_monto_v = int(cuota.get("monto") or cuota.get("monto_total") or 0)
            comp = cuota.get("comprobante") or {}
            item = {
                "loanbook_id":     loanbook_id,
                "cliente_nombre":  cliente.get("nombre") or lb.get("cliente_nombre") or "?",
                "cliente_cedula":  str(cliente.get("cedula") or lb.get("cliente_cedula") or ""),
                "cliente_telefono": str(cliente.get("telefono") or lb.get("cliente_telefono") or ""),
                "modelo":          modelo,
                "modalidad":       modalidad,
                "cuota_numero":    int(cuota.get("numero") or cuota.get("numero_cuota") or 0),
                "cuota_fecha":     fecha_cuota.isoformat(),
                "cuota_monto":     cuota_monto_v,
                "dpd":             dpd,
                "sub_bucket":      asignar_sub_bucket(max(0, dpd)),
                "pagada":          pagada,
                "comprobante_recibido":   bool(comp.get("url")),
                "comprobante_url":        comp.get("url"),
                "comprobante_subido_at":  comp.get("subido_at"),
                "comprobante_verificado_banco": bool(comp.get("verificado_banco", False)),
                "estado_loanbook": lb.get("estado", ""),
            }
            secciones[seccion]["items"].append(item)
            secciones[seccion]["subtotal_count"] += 1
            secciones[seccion]["subtotal_monto"] += cuota_monto_v
            personas_total.add(loanbook_id)
            if pagada:
                secciones[seccion]["subtotal_pagados_count"] += 1
                secciones[seccion]["subtotal_pagados_monto"] += cuota_monto_v
                personas_pagaron.add(loanbook_id)

    # Ordenar por dpd desc dentro de cada sección
    for sec in secciones.values():
        sec["items"].sort(key=lambda it: (-int(it["dpd"]), str(it["cliente_nombre"])))

    esperado = sum(s["subtotal_monto"] for s in secciones.values())
    recibido = sum(s["subtotal_pagados_monto"] for s in secciones.values())
    return {
        "semana_miercoles": miercoles.isoformat(),
        "fecha_corte":      today_bogota().isoformat(),
        "secciones":        secciones,
        "totales": {
            "esperado":         esperado,
            "recibido":         recibido,
            "pendiente":        max(0, esperado - recibido),
            "personas_total":   len(personas_total),
            "personas_pagaron": len(personas_pagaron),
            "personas_faltan":  max(0, len(personas_total) - len(personas_pagaron)),
            "filas_total":      sum(s["subtotal_count"] for s in secciones.values()),
            "filas_pagadas":    sum(s["subtotal_pagados_count"] for s in secciones.values()),
        },
        "fecha_analisis":   now_iso_bogota(),
    }


# ─────────────────────── Función pública 5: auditar ─────────────────────────

def auditar(loanbook_doc: dict) -> dict:
    """Compara doc actual vs versión canónica recalculada y lista divergencias.

    Retorna:
        {
          "loanbook_id": "...",
          "ok": bool,
          "severidad": "verde" | "amarilla" | "roja",
          "violaciones": [{"campo": ..., "antes": ..., "despues": ...}, ...]
        }
    """
    canonico = recalcular(loanbook_doc)
    violaciones = []

    campos_criticos = [
        "num_cuotas", "valor_total", "saldo_capital", "saldo_intereses",
        "saldo_pendiente", "dpd", "sub_bucket", "modelo", "capital_plan",
    ]
    for k in campos_criticos:
        v_actual = loanbook_doc.get(k)
        v_canonico = canonico.get(k)
        if v_actual != v_canonico:
            violaciones.append({
                "campo": k,
                "antes": v_actual,
                "despues": v_canonico,
            })

    # Cronograma: comparar fechas
    fechas_actuales = [c.get("fecha") for c in (loanbook_doc.get("cuotas") or [])]
    fechas_canonicas = [c.get("fecha") for c in (canonico.get("cuotas") or [])]
    if fechas_actuales != fechas_canonicas:
        violaciones.append({
            "campo": "cronograma_fechas",
            "antes": fechas_actuales[:5],
            "despues": fechas_canonicas[:5],
        })

    severidad = "verde" if not violaciones else (
        "roja" if any(v["campo"] in ("cronograma_fechas", "num_cuotas", "saldo_capital") for v in violaciones)
        else "amarilla"
    )

    return {
        "loanbook_id":  loanbook_doc.get("loanbook_id"),
        "cliente":      (loanbook_doc.get("cliente") or {}).get("nombre")
                        or loanbook_doc.get("cliente_nombre"),
        "ok":           not violaciones,
        "severidad":    severidad,
        "violaciones":  violaciones,
    }


# ─────────────────────── Helper de persistencia ─────────────────────────────

async def loanbook_save(db, loanbook_doc: dict) -> dict:
    """Persiste loanbook en MongoDB pasando SIEMPRE por recalcular() antes.

    Uso preferido en lugar de db.loanbook.update_one/insert_one directos.

    Returns:
        El doc canónico que quedó persistido.
    """
    canonico = recalcular(loanbook_doc)
    loanbook_id = canonico.get("loanbook_id")
    if not loanbook_id:
        raise ValueError("loanbook_id requerido para persistir")
    await db.loanbook.replace_one(
        {"loanbook_id": loanbook_id},
        canonico,
        upsert=True,
    )
    return canonico
