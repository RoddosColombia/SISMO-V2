"""
routers/loanbook_admin.py — Endpoints administrativos del loanbook.

Estos endpoints aplican el motor unificado (services/loanbook/engine.py) sobre
los datos en MongoDB para auditoría y reparación masiva.

Endpoints:
    GET  /api/loanbook/admin/audit-all       → reporta divergencias por LB
    POST /api/loanbook/admin/full-repair     → aplica engine.recalcular() y persiste

Diseño:
    - Solo router; toda la lógica financiera vive en engine.py
    - dry_run=true por default en full-repair para preview seguro
    - Reporte detallado: qué campo cambió por LB
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_db
from core.datetime_utils import now_iso_bogota, today_bogota
from services.loanbook.engine import recalcular, auditar

logger = logging.getLogger("routers.loanbook_admin")

router = APIRouter(prefix="/api/loanbook-admin", tags=["loanbook-admin"])


# ─────────────────────────── audit-all ──────────────────────────────────────

@router.get("/audit-all")
async def audit_all(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Audita TODOS los loanbooks y devuelve divergencias vs versión canónica.

    No modifica nada. Útil para visualizar el semáforo del módulo.

    Returns:
        {
          "fecha_corte":    "2026-04-30",
          "total":          43,
          "verdes":         N,
          "amarillas":      N,
          "rojas":          N,
          "puede_enviar_email_martes": bool (rojas == 0),
          "loanbooks": [
            {
              "loanbook_id": "...",
              "cliente":     "...",
              "severidad":   "verde" | "amarilla" | "roja",
              "violaciones": [{"campo", "antes", "despues"}, ...]
            },
            ...
          ]
        }
    """
    total = 0
    verdes = 0
    amarillas = 0
    rojas = 0
    reportes = []

    async for lb in db.loanbook.find({}):
        total += 1
        report = auditar(lb)
        if report["severidad"] == "verde":
            verdes += 1
        elif report["severidad"] == "amarilla":
            amarillas += 1
        else:
            rojas += 1
        reportes.append(report)

    # Ordenar por severidad: rojas primero, luego amarillas
    orden = {"roja": 0, "amarilla": 1, "verde": 2}
    reportes.sort(key=lambda r: (orden[r["severidad"]], r.get("loanbook_id", "")))

    return {
        "fecha_corte":   today_bogota().isoformat(),
        "fecha_analisis": now_iso_bogota(),
        "total":         total,
        "verdes":        verdes,
        "amarillas":     amarillas,
        "rojas":         rojas,
        "puede_enviar_email_martes": rojas == 0,
        "loanbooks":     reportes,
    }


# ─────────────────────────── full-repair ────────────────────────────────────

@router.post("/full-repair")
async def full_repair(
    dry_run: Annotated[
        bool,
        Query(description="True (default) = solo preview. False = aplica cambios."),
    ] = True,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Aplica engine.recalcular() a TODOS los loanbooks y persiste cambios.

    Repara automáticamente:
      - Cronogramas con cuotas fuera de miércoles canónico
      - Saldos desfasados (sc, si, saldo_pendiente)
      - DPD y sub_bucket
      - Estado derivado
      - Modelo poblado con plan_codigo
      - num_cuotas vs catálogo
      - mora_acumulada

    Idempotente: aplicarlo dos veces no produce cambios la segunda vez.

    Args:
        dry_run: Por defecto True — solo reporta qué cambiaría. Pasar dry_run=false
                 para persistir.

    Returns:
        {
          "dry_run":        bool,
          "total":          43,
          "modificados":    N,
          "sin_cambios":    N,
          "errores":        [{"loanbook_id", "error"}, ...],
          "reparaciones":   [
            {"loanbook_id", "cliente", "cambios": [{"campo", "antes", "despues"}, ...]},
            ...
          ]
        }
    """
    total = 0
    modificados = 0
    sin_cambios = 0
    errores = []
    reparaciones = []

    async for lb in db.loanbook.find({}):
        total += 1
        loanbook_id = lb.get("loanbook_id") or str(lb.get("_id"))
        cliente = (lb.get("cliente") or {}).get("nombre") or lb.get("cliente_nombre") or "?"

        try:
            canonico = recalcular(lb)
        except Exception as exc:
            logger.exception("full-repair error en %s: %s", loanbook_id, exc)
            errores.append({"loanbook_id": loanbook_id, "error": str(exc)})
            continue

        # Detectar cambios reales (no contar fecha_ultima_recalculacion)
        cambios = _detectar_cambios(lb, canonico)
        if not cambios:
            sin_cambios += 1
            continue

        modificados += 1
        reparaciones.append({
            "loanbook_id": loanbook_id,
            "cliente":     cliente,
            "cambios":     cambios,
        })

        # Persistir solo si no es dry_run
        if not dry_run:
            # Preservar _id de MongoDB si existe
            if "_id" in lb:
                canonico["_id"] = lb["_id"]
            await db.loanbook.replace_one({"_id": lb["_id"]}, canonico)

    return {
        "dry_run":          dry_run,
        "fecha_analisis":   now_iso_bogota(),
        "total":            total,
        "modificados":      modificados,
        "sin_cambios":      sin_cambios,
        "errores":          errores,
        "reparaciones":     reparaciones,
    }


# ─────────────────────────── helpers ────────────────────────────────────────

# Campos cuyo cambio NO se reporta (volátil o esperado)
CAMPOS_IGNORAR = {"fecha_ultima_recalculacion", "fecha_analisis", "_id"}


def _detectar_cambios(antes: dict, despues: dict) -> list[dict]:
    """Devuelve lista de campos que cambiaron entre antes y después."""
    cambios = []
    keys = (set(antes.keys()) | set(despues.keys())) - CAMPOS_IGNORAR
    for k in sorted(keys):
        v_antes = antes.get(k)
        v_despues = despues.get(k)
        if v_antes == v_despues:
            continue
        # Para cuotas: solo reportar si las fechas cambiaron
        if k == "cuotas":
            fechas_antes = [c.get("fecha") for c in (v_antes or [])]
            fechas_despues = [c.get("fecha") for c in (v_despues or [])]
            if fechas_antes == fechas_despues:
                continue
            cambios.append({
                "campo":   "cuotas_fechas",
                "antes":   fechas_antes[:3] + (["..."] if len(fechas_antes) > 3 else []),
                "despues": fechas_despues[:3] + (["..."] if len(fechas_despues) > 3 else []),
            })
            continue
        cambios.append({
            "campo":   k,
            "antes":   v_antes,
            "despues": v_despues,
        })
    return cambios


# ─────────────────────── MOTOR CANÓNICO ENDPOINTS (DAY1) ────────────────────

@router.get("/motor/audit-all")
async def motor_audit_all(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Audita los 43 LBs aplicando el motor canónico (services.loanbook.motor).

    No modifica nada. Devuelve semáforo verde/amarilla/roja por LB.

    El motor aplica reglas v1.1 (Opción B):
      - 9 estados: pendiente_entrega, al_dia, mora_leve, mora_media, mora_grave,
        default, castigado, reestructurado, saldado.
      - Sub-buckets v1.1: Current/Grace/Warning/Alert/Critical/Severe/Pre-default/Default.
      - Mora $2.000 COP/día sin cap.
      - Solo recalcula derivados; NO toca cronograma.
    """
    from services.loanbook.motor import auditar
    from core.datetime_utils import today_bogota

    hoy = today_bogota()
    total = 0
    verdes = 0
    amarillas = 0
    rojas = 0
    reportes = []

    async for lb in db.loanbook.find({}):
        total += 1
        try:
            r = auditar(lb, hoy=hoy)
        except Exception as exc:
            r = {
                "loanbook_id": lb.get("loanbook_id"),
                "cliente":     (lb.get("cliente") or {}).get("nombre"),
                "ok":          False,
                "severidad":   "roja",
                "violaciones": [{"campo": "exception", "antes": "", "despues": str(exc), "tipo": "estructural"}],
            }
        if r["severidad"] == "verde":
            verdes += 1
        elif r["severidad"] == "amarilla":
            amarillas += 1
        else:
            rojas += 1
        reportes.append(r)

    orden = {"roja": 0, "amarilla": 1, "verde": 2}
    reportes.sort(key=lambda r: (orden.get(r["severidad"], 3), r.get("loanbook_id") or ""))

    return {
        "fecha_corte":               hoy.isoformat(),
        "fecha_analisis":            now_iso_bogota(),
        "motor":                     "services.loanbook.motor v1 (DAY1)",
        "total":                     total,
        "verdes":                    verdes,
        "amarillas":                 amarillas,
        "rojas":                     rojas,
        "puede_migrar_sin_riesgo":   rojas == 0,
        "loanbooks":                 reportes,
    }


@router.post("/motor/migrar")
async def motor_migrar(
    dry_run: Annotated[
        bool,
        Query(description="True (default) = solo preview. False = aplica derivar_estado y persiste."),
    ] = True,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Aplica services.loanbook.motor.derivar_estado a todos los LBs y persiste.

    SOLO recalcula derivados (saldo, dpd, sub_bucket, estado, mora, total_pagado,
    cuotas_pagadas, cuotas_vencidas). NO toca cronograma, NO toca términos pactados,
    NO toca metadata cliente. Cumple invariante: idempotente.

    Args:
        dry_run: True por defecto. False persiste cambios en MongoDB.

    Returns:
        Reporte detallado: cuántos LBs cambiaron, qué campo cambió en cada uno,
        cartera_total antes vs después.
    """
    from services.loanbook.motor import derivar_estado
    from core.datetime_utils import today_bogota

    hoy = today_bogota()
    total = 0
    modificados = 0
    sin_cambios = 0
    errores = []
    cambios_detalle = []
    cartera_antes = 0
    cartera_despues = 0

    async for lb in db.loanbook.find({}):
        total += 1
        loanbook_id = lb.get("loanbook_id") or str(lb.get("_id"))
        cliente = (lb.get("cliente") or {}).get("nombre") or lb.get("cliente_nombre") or "?"

        # Saldo antes (usa el persistido)
        saldo_antes = int(lb.get("saldo_pendiente") or 0)
        cartera_antes += saldo_antes

        try:
            canonico = derivar_estado(lb, hoy=hoy)
        except Exception as exc:
            errores.append({"loanbook_id": loanbook_id, "error": str(exc)})
            continue

        # Saldo después (canónico)
        saldo_despues = int(canonico.get("saldo_pendiente") or 0)
        cartera_despues += saldo_despues

        # Detectar cambios reales (campos derivados solamente)
        cambios = {}
        for k in ["saldo_pendiente", "total_pagado", "dpd", "estado", "sub_bucket",
                  "mora_acumulada_cop", "cuotas_pagadas", "cuotas_vencidas"]:
            v_antes = lb.get(k)
            v_despues = canonico.get(k)
            if v_antes != v_despues:
                cambios[k] = {"antes": v_antes, "despues": v_despues}

        if not cambios:
            sin_cambios += 1
            continue

        modificados += 1
        cambios_detalle.append({
            "loanbook_id": loanbook_id,
            "cliente":     cliente,
            "cambios":     cambios,
        })

        if not dry_run:
            # Persistir solo los campos derivados, no tocar cronograma ni términos
            patch = {k: canonico[k] for k in [
                "saldo_pendiente", "total_pagado", "dpd", "estado", "sub_bucket",
                "mora_acumulada_cop", "cuotas_pagadas", "cuotas_vencidas",
                "fecha_ultima_recalculacion",
            ] if k in canonico}
            await db.loanbook.update_one(
                {"_id": lb["_id"]},
                {"$set": patch},
            )

    return {
        "dry_run":                  dry_run,
        "fecha_analisis":           now_iso_bogota(),
        "motor":                    "services.loanbook.motor v1 (DAY1)",
        "total_loanbooks":          total,
        "modificados":              modificados,
        "sin_cambios":              sin_cambios,
        "errores":                  errores,
        "cartera_total_antes":      cartera_antes,
        "cartera_total_despues":    cartera_despues,
        "delta_cartera":            cartera_despues - cartera_antes,
        "cambios":                  cambios_detalle,
    }



# ─────────────────────── APLICAR PATCHES JSON (DAY2 — sin multipart) ─────────

@router.post("/aplicar-patches")
async def aplicar_patches(
    body: dict,
    dry_run: bool = Query(True, description="True (default) preview. False persiste."),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Aplica patches canónicos a los LBs desde un JSON body.

    Alternativa al endpoint multipart restaurar-desde-excel: recibe los patches
    pre-generados como JSON body, sin dependencia de python-multipart.

    Body esperado:
        {
          "total_loanbooks": 43,
          "patches": [
            {
              "loanbook_id": "LB-2026-0001",
              "saldo_capital": 6720600,
              "saldo_intereses": 1554800,
              "saldo_pendiente": 8275400,
              "valor_total": 9354800,
              "total_pagado": 1079400,
              "cuotas_pagadas": 6,
              "dpd": 1,
              "estado": "mora_leve",
              "sub_bucket": "Grace",
              ...
            },
            ...
          ]
        }

    Por cada patch hace $set sobre el doc del LB sin tocar:
      - cuotas[] (cronograma con fechas reales)
      - cliente, moto, metadata_producto
      - fechas pactadas (entrega, primer_pago)
      - factura_alegra_id

    Idempotente: aplicarlo dos veces no produce cambios la segunda vez.
    """
    patches = body.get("patches") or []
    if not patches:
        return {"error": "body debe incluir 'patches' (lista de dicts)"}

    total = len(patches)
    actualizados = 0
    no_encontrados = []
    sin_cambios = 0
    errores = []
    cambios_detalle = []

    for patch in patches:
        loanbook_id = patch.get("loanbook_id")
        if not loanbook_id:
            errores.append({"patch": patch, "error": "sin loanbook_id"})
            continue

        doc_actual = await db.loanbook.find_one({"loanbook_id": loanbook_id})
        if doc_actual is None:
            no_encontrados.append(loanbook_id)
            continue

        # Detectar cambios reales
        cambios_lb = {}
        for k, v in patch.items():
            if k == "loanbook_id":
                continue
            v_actual = doc_actual.get(k)
            if v_actual != v:
                cambios_lb[k] = {"antes": v_actual, "despues": v}

        if not cambios_lb:
            sin_cambios += 1
            continue

        actualizados += 1
        cambios_detalle.append({
            "loanbook_id": loanbook_id,
            "cliente":     (doc_actual.get("cliente") or {}).get("nombre")
                            or doc_actual.get("cliente_nombre") or "?",
            "n_cambios":   len(cambios_lb),
        })

        if not dry_run:
            patch_set = {k: v for k, v in patch.items() if k != "loanbook_id"}
            patch_set["restaurado_desde_excel_at"] = now_iso_bogota()
            await db.loanbook.update_one(
                {"loanbook_id": loanbook_id},
                {"$set": patch_set},
            )

    return {
        "dry_run":          dry_run,
        "fecha_analisis":   now_iso_bogota(),
        "total_patches":    total,
        "actualizados":     actualizados,
        "sin_cambios":      sin_cambios,
        "no_encontrados":   no_encontrados,
        "errores":          errores,
        "cambios":          cambios_detalle,
    }


# ─────────────────────── INYECTAR CUOTA INICIAL (DAY3 BLOQUE 2) ─────────────

@router.post("/inyectar-cuota-inicial")
async def inyectar_cuota_inicial(
    body: dict,
    dry_run: bool = Query(True, description="True (default) preview. False persiste."),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Inyecta cuota 0 (cuota inicial pactada) al cronograma de los LBs indicados.

    Política RODDOS V2.1:
      - Cuota 0 con monto = cuota_inicial pactada
      - es_cuota_inicial = True
      - monto_capital = cuota_inicial, monto_interes = 0
      - estado = pendiente (hasta que el operador la cobre)
      - Suma a valor_total: valor_total = cuota_inicial + Σ cuotas regulares

    Body esperado:
        {
          "loanbooks": [
            {
              "loanbook_id":         "LB-2026-0034",
              "cuota_inicial":       1460000,
              "fecha_cuota_inicial": "2026-04-30"
            },
            ...
          ]
        }

    Idempotente: si el LB ya tiene cuota 0 (es_cuota_inicial=True),
    NO la duplica. Sólo recalcula valor_total si difiere.
    """
    items = body.get("loanbooks") or []
    if not items:
        return {"error": "body debe incluir 'loanbooks' (lista)"}

    total = len(items)
    inyectados = 0
    ya_tenian = 0
    no_encontrados = []
    errores = []
    cambios = []

    for it in items:
        loanbook_id = it.get("loanbook_id")
        cuota_inicial = int(it.get("cuota_inicial") or 0)
        fecha_ci = it.get("fecha_cuota_inicial")

        if not loanbook_id or cuota_inicial <= 0:
            errores.append({"item": it, "error": "loanbook_id o cuota_inicial faltan"})
            continue

        lb = await db.loanbook.find_one({"loanbook_id": loanbook_id})
        if lb is None:
            no_encontrados.append(loanbook_id)
            continue

        cuotas = lb.get("cuotas") or []

        # ¿Ya tiene cuota 0?
        tiene_cuota_0 = any(
            (c.get("es_cuota_inicial") is True) or (int(c.get("numero") or -1) == 0)
            for c in cuotas
        )

        if tiene_cuota_0:
            # Verificar si valor_total está bien o necesita recálculo
            valor_total_calc = sum(int(c.get("monto") or 0) for c in cuotas)
            valor_total_actual = int(lb.get("valor_total") or 0)
            if valor_total_actual == valor_total_calc:
                ya_tenian += 1
                continue
            # Solo actualizar valor_total
            cambios.append({
                "loanbook_id": loanbook_id,
                "accion":      "solo_recalcular_valor_total",
                "antes":       valor_total_actual,
                "despues":     valor_total_calc,
            })
            if not dry_run:
                await db.loanbook.update_one(
                    {"loanbook_id": loanbook_id},
                    {"$set": {"valor_total": valor_total_calc}},
                )
            ya_tenian += 1
            continue

        # No tiene cuota 0 — inyectarla
        cuota_0 = {
            "numero":           0,
            "fecha":            fecha_ci or lb.get("fecha_entrega"),
            "monto":            cuota_inicial,
            "monto_capital":    cuota_inicial,
            "monto_interes":    0,
            "estado":           "pendiente",
            "monto_pagado":     0,
            "fecha_pago":       None,
            "mora_acumulada":   0,
            "anzi_pagado":      0,
            "mora_pagada":      0,
            "es_cuota_inicial": True,
        }

        cuotas_nuevas = [cuota_0] + cuotas
        valor_total_nuevo = sum(int(c.get("monto") or 0) for c in cuotas_nuevas)
        valor_total_anterior = int(lb.get("valor_total") or 0)

        cambios.append({
            "loanbook_id":              loanbook_id,
            "cliente":                  (lb.get("cliente") or {}).get("nombre")
                                        or lb.get("cliente_nombre") or "?",
            "accion":                   "inyectar_cuota_0",
            "cuota_inicial":            cuota_inicial,
            "fecha_cuota_inicial":      cuota_0["fecha"],
            "valor_total_antes":        valor_total_anterior,
            "valor_total_despues":      valor_total_nuevo,
            "cuotas_total_antes":       len(cuotas),
            "cuotas_total_despues":     len(cuotas_nuevas),
        })

        if not dry_run:
            await db.loanbook.update_one(
                {"loanbook_id": loanbook_id},
                {
                    "$set": {
                        "cuotas":               cuotas_nuevas,
                        "valor_total":          valor_total_nuevo,
                        "cuota_inicial":        cuota_inicial,
                        "saldo_pendiente":      max(0, valor_total_nuevo - int(lb.get("total_pagado") or 0)),
                        "inyectado_cuota_0_at": now_iso_bogota(),
                    }
                },
            )

        inyectados += 1

    return {
        "dry_run":         dry_run,
        "fecha_analisis":  now_iso_bogota(),
        "total":           total,
        "inyectados":      inyectados,
        "ya_tenian":       ya_tenian,
        "no_encontrados":  no_encontrados,
        "errores":         errores,
        "cambios":         cambios,
    }


# ─────────────────── REGENERAR CRONOGRAMA LB (DAY3 BLOQUE 3) ─────────────────

@router.post("/regenerar-cronograma-lb")
async def regenerar_cronograma_lb(
    body: dict,
    dry_run: bool = Query(True, description="True (default) preview. False persiste."),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Regenera el cronograma de UN loanbook usando motor.crear_cronograma.

    Caso de uso DAY3 Bloque 3: LB-30 Luis Romero — cronograma estructuralmente
    inconsistente (39 cuotas en BD, num_cuotas top-level dice 52).

    Body esperado:
        {
          "loanbook_id":          "LB-2026-0030",
          "num_cuotas":           52,
          "cuota_periodica":      182000,
          "capital_plan":         5750000,
          "fecha_primer_pago":    "2026-04-29",
          "modalidad":            "semanal",
          "cuota_inicial":        0,                       # opcional
          "fecha_cuota_inicial":  null,                    # opcional
          "plan_codigo":          "P52S",                  # opcional, fix metadata
          "preserve_pagos":       true                     # opcional, default true
        }

    Reglas inviolables:
      - Si alguna cuota existente tiene monto_pagado > 0, se preserva el pago
        (matching por número de cuota). El motor genera el cronograma limpio
        y luego se mergean los monto_pagado existentes por número.
      - Si preserve_pagos=true y se detecta más cuotas pagadas que num_cuotas
        nuevo → ABORTA con error (riesgo de pérdida de pago).
      - Persiste cronograma + valor_total nuevo. Recálculo de derivados
        (saldo_pendiente, dpd, estado, sub_bucket) NO se hace aquí — usar
        /motor/migrar después.
    """
    from services.loanbook.motor import crear_cronograma
    from datetime import date

    loanbook_id = body.get("loanbook_id")
    if not loanbook_id:
        return {"error": "body.loanbook_id es obligatorio"}

    # Parámetros del nuevo cronograma
    try:
        num_cuotas        = int(body["num_cuotas"])
        cuota_periodica   = int(body["cuota_periodica"])
        capital_plan      = int(body["capital_plan"])
        modalidad         = body["modalidad"]
        fpp_str           = body["fecha_primer_pago"]
        fecha_primer_pago = date.fromisoformat(fpp_str)
    except (KeyError, ValueError, TypeError) as e:
        return {"error": f"parámetros inválidos: {e}"}

    cuota_inicial      = int(body.get("cuota_inicial") or 0)
    fci_raw            = body.get("fecha_cuota_inicial")
    fecha_ci           = date.fromisoformat(fci_raw) if fci_raw else None
    plan_codigo_nuevo  = body.get("plan_codigo")
    preserve_pagos     = bool(body.get("preserve_pagos", True))

    # ── Lectura del LB
    lb = await db.loanbook.find_one({"loanbook_id": loanbook_id})
    if lb is None:
        return {"error": f"LB {loanbook_id} no encontrado"}

    cuotas_actuales = lb.get("cuotas") or []
    pagos_existentes = {
        int(c.get("numero") or -1): {
            "monto_pagado":   int(c.get("monto_pagado") or 0),
            "fecha_pago":     c.get("fecha_pago"),
            "anzi_pagado":    int(c.get("anzi_pagado") or 0),
            "mora_pagada":    int(c.get("mora_pagada") or 0),
            "mora_acumulada": int(c.get("mora_acumulada") or 0),
            "estado":         c.get("estado"),
        }
        for c in cuotas_actuales
        if int(c.get("monto_pagado") or 0) > 0
    }

    # ── Generar cronograma canónico
    try:
        cronograma_nuevo = crear_cronograma(
            fecha_primer_pago     = fecha_primer_pago,
            num_cuotas            = num_cuotas,
            cuota_valor           = cuota_periodica,
            modalidad             = modalidad,
            capital_plan          = capital_plan,
            cuota_estandar_plan   = cuota_periodica,
            cuota_inicial         = cuota_inicial,
            fecha_cuota_inicial   = fecha_ci,
        )
    except Exception as e:
        return {"error": f"motor.crear_cronograma falló: {e}"}

    # ── Validación: si hay pagos en cuotas que no caben en nuevo cronograma → ABORTA
    numeros_nuevos = {int(c.get("numero")) for c in cronograma_nuevo}
    pagos_huerfanos = [num for num in pagos_existentes if num not in numeros_nuevos]
    if pagos_huerfanos and preserve_pagos:
        return {
            "error":            "pagos huérfanos detectados — pago en cuota que no existe en nuevo cronograma",
            "loanbook_id":      loanbook_id,
            "pagos_huerfanos":  pagos_huerfanos,
            "pagos_existentes": pagos_existentes,
            "abort":            True,
        }

    # ── Merge: preservar monto_pagado de cuotas existentes
    if preserve_pagos and pagos_existentes:
        for c in cronograma_nuevo:
            num = int(c.get("numero"))
            if num in pagos_existentes:
                p = pagos_existentes[num]
                c["monto_pagado"]   = p["monto_pagado"]
                c["fecha_pago"]     = p["fecha_pago"]
                c["anzi_pagado"]    = p["anzi_pagado"]
                c["mora_pagada"]    = p["mora_pagada"]
                c["mora_acumulada"] = p["mora_acumulada"]
                if p["estado"] in ("pagada", "parcial"):
                    c["estado"] = p["estado"]

    # ── Cálculos del nuevo estado top-level
    valor_total_nuevo = sum(int(c.get("monto") or 0) for c in cronograma_nuevo)
    sigma_capital     = sum(int(c.get("monto_capital") or 0) for c in cronograma_nuevo)
    sigma_interes     = sum(int(c.get("monto_interes") or 0) for c in cronograma_nuevo)
    total_pagado      = sum(int(c.get("monto_pagado") or 0) for c in cronograma_nuevo)

    diff = {
        "loanbook_id":            loanbook_id,
        "cliente":                (lb.get("cliente") or {}).get("nombre")
                                  or lb.get("cliente_nombre") or "?",
        "antes": {
            "num_cuotas":         lb.get("num_cuotas"),
            "cuotas_array_count": len(cuotas_actuales),
            "valor_total":        lb.get("valor_total"),
            "plan_codigo":        lb.get("plan_codigo"),
        },
        "despues": {
            "num_cuotas":         num_cuotas,
            "cuotas_array_count": len(cronograma_nuevo),
            "valor_total":        valor_total_nuevo,
            "Σ capital":          sigma_capital,
            "Σ interes":          sigma_interes,
            "total_pagado":       total_pagado,
            "plan_codigo":        plan_codigo_nuevo or lb.get("plan_codigo"),
            "fecha_primer_pago":  fpp_str,
            "fecha_ultima_cuota": cronograma_nuevo[-1]["fecha"],
        },
        "pagos_preservados":      len(pagos_existentes),
    }

    if not dry_run:
        update_set = {
            "cuotas":                       cronograma_nuevo,
            "valor_total":                  valor_total_nuevo,
            "num_cuotas":                   num_cuotas,
            "cuota_periodica":              cuota_periodica,
            "capital_plan":                 capital_plan,
            "modalidad":                    modalidad,
            "fecha_primer_pago":            fpp_str,
            "saldo_pendiente":              max(0, valor_total_nuevo - total_pagado),
            "total_pagado":                 total_pagado,
            "regenerado_cronograma_at":     now_iso_bogota(),
        }
        if cuota_inicial > 0:
            update_set["cuota_inicial"] = cuota_inicial
        if plan_codigo_nuevo:
            update_set["plan_codigo"] = plan_codigo_nuevo

        await db.loanbook.update_one(
            {"loanbook_id": loanbook_id},
            {"$set": update_set},
        )

    return {
        "dry_run":         dry_run,
        "fecha_analisis":  now_iso_bogota(),
        "diff":            diff,
        "cronograma_preview": [
            {"numero": c["numero"], "fecha": c["fecha"], "monto": c["monto"],
             "monto_capital": c["monto_capital"], "monto_interes": c["monto_interes"],
             "monto_pagado": c.get("monto_pagado", 0)}
            for c in cronograma_nuevo[:3] + cronograma_nuevo[-3:]
        ],
    }


# ───────── MARCAR CUOTAS INICIALES PAGADAS (DAY3 B5) ─────────

@router.post("/marcar-cuotas-iniciales-pagadas")
async def marcar_cuotas_iniciales_pagadas(
    body: dict,
    dry_run: bool = Query(True, description="True (default) preview. False persiste."),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Marca cuotas iniciales como PAGADAS para LBs cuya CI fue cobrada antes de entrega.

    Política RODDOS confirmada 4-may-2026:
      - Norma: todo crédito tiene cuota_inicial > 0, cobrada ANTES de la entrega
        (para facturar y matricular). Excepción comercial: algunos LBs sin CI.
      - Cuota 0 en cronograma debe nacer como pagada cuando CI > 0.

    Body esperado (la fuente de verdad es Excel oficial loanbook_roddos_<fecha>.xlsx):
        {
          "loanbooks": [
            {
              "loanbook_id":    "LB-2026-0001",
              "cuota_inicial":  1460000,                              # del Excel col cuota_inicial
              "fecha_pago":     "2026-04-30",                         # típicamente fecha_entrega
              "metodo_pago":    "cuota_inicial_pre_entrega",          # default si no se envía
              "referencia":     "Wava-XXXX | Bancolombia | Efectivo"  # opcional
            },
            ...
          ]
        }

    Por cada LB:
      1. Si BD no tiene `cuota_inicial` top-level o difiere → $set al valor del body.
      2. Si cuotas[] no tiene cuota 0 → la inserta como pagada al inicio.
      3. Si cuotas[] tiene cuota 0 pendiente → la marca pagada con monto_pagado=cuota_inicial.
      4. Si cuotas[] tiene cuota 0 ya pagada → skip (idempotente).
      5. Recalcula valor_total = Σ cuotas[].monto.
      6. Recalcula derivados via motor.derivar_estado.

    Idempotente. Aborta el cambio puntual si la cuota 0 existente tiene monto_pagado > 0
    distinto al cuota_inicial del body (sospechoso de inconsistencia operativa).
    """
    from services.loanbook.motor import derivar_estado
    from datetime import date

    items = body.get("loanbooks") or []
    if not items:
        return {"error": "body debe incluir 'loanbooks' (lista)"}

    total = len(items)
    procesados = 0
    ya_pagadas = 0
    nuevas_cuotas_0 = 0
    actualizadas_cuota_0 = 0
    sin_cambio_ci_top = 0
    sin_ci_omitidos = 0
    no_encontrados: list[str] = []
    errores: list[dict] = []
    cambios: list[dict] = []
    sigma_delta_total_pagado = 0
    sigma_delta_valor_total = 0
    sigma_delta_saldo_pendiente = 0

    for it in items:
        lb_id = it.get("loanbook_id")
        ci = int(it.get("cuota_inicial") or 0)
        fecha_pago_str = it.get("fecha_pago")
        metodo = (it.get("metodo_pago") or "cuota_inicial_pre_entrega").lower()
        referencia = it.get("referencia") or ""

        if not lb_id:
            errores.append({"item": it, "error": "loanbook_id faltante"})
            continue
        if ci <= 0:
            sin_ci_omitidos += 1
            continue

        try:
            fecha_pago = date.fromisoformat(fecha_pago_str) if fecha_pago_str else None
        except ValueError:
            errores.append({"loanbook_id": lb_id, "error": f"fecha_pago inválida: {fecha_pago_str}"})
            continue

        lb = await db.loanbook.find_one({"loanbook_id": lb_id})
        if lb is None:
            no_encontrados.append(lb_id)
            continue

        if fecha_pago is None:
            fent = lb.get("fecha_entrega")
            try:
                fecha_pago = date.fromisoformat(fent) if fent else None
            except ValueError:
                fecha_pago = None
            if fecha_pago is None:
                errores.append({"loanbook_id": lb_id, "error": "sin fecha_pago ni fecha_entrega válida"})
                continue

        cuotas = list(lb.get("cuotas") or [])
        idx_c0 = next(
            (i for i, c in enumerate(cuotas)
             if c.get("es_cuota_inicial") is True or int(c.get("numero") or -1) == 0),
            None,
        )

        accion = ""
        if idx_c0 is None:
            cuota_0 = {
                "numero":           0,
                "fecha":            fecha_pago.isoformat(),
                "monto":            ci,
                "monto_capital":    ci,
                "monto_interes":    0,
                "estado":           "pagada",
                "monto_pagado":     ci,
                "fecha_pago":       fecha_pago.isoformat(),
                "metodo_pago":      metodo,
                "referencia":       referencia,
                "mora_acumulada":   0,
                "anzi_pagado":      0,
                "mora_pagada":      0,
                "es_cuota_inicial": True,
            }
            cuotas = [cuota_0] + cuotas
            accion = "crear_cuota_0_pagada"
            nuevas_cuotas_0 += 1
        else:
            c0 = dict(cuotas[idx_c0])
            ya_pagada = c0.get("estado") == "pagada" and int(c0.get("monto_pagado") or 0) >= ci
            if ya_pagada:
                ya_pagadas += 1
                continue
            mp_actual = int(c0.get("monto_pagado") or 0)
            if mp_actual > 0 and mp_actual != ci:
                errores.append({
                    "loanbook_id": lb_id,
                    "error": f"cuota 0 ya tiene monto_pagado={mp_actual} != cuota_inicial={ci}; revisar manualmente",
                })
                continue
            c0["estado"]       = "pagada"
            c0["monto_pagado"] = ci
            c0["monto"]        = ci
            c0["monto_capital"] = ci
            c0["monto_interes"] = 0
            c0["fecha_pago"]   = fecha_pago.isoformat()
            c0["metodo_pago"]  = metodo
            c0["es_cuota_inicial"] = True
            if referencia:
                c0["referencia"] = referencia
            cuotas[idx_c0] = c0
            accion = "marcar_cuota_0_pagada"
            actualizadas_cuota_0 += 1

        valor_total_nuevo = sum(int(c.get("monto") or 0) for c in cuotas)
        ci_top_actual = int(lb.get("cuota_inicial") or 0)
        ci_top_change = ci_top_actual != ci

        lb_proyectado = dict(lb)
        lb_proyectado.pop("_id", None)
        lb_proyectado["cuotas"] = cuotas
        lb_proyectado["cuota_inicial"] = ci
        lb_proyectado["valor_total"] = valor_total_nuevo
        # B5.2 fix: derivar al "hoy" canónico, no a fecha_pago de la cuota inicial
        # (sino los derivados quedan congelados en el pasado para LBs antiguos).
        lb_proyectado_derivado = derivar_estado(lb_proyectado, hoy=today_bogota())

        delta_tp = int(lb_proyectado_derivado.get("total_pagado") or 0) - int(lb.get("total_pagado") or 0)
        delta_vt = valor_total_nuevo - int(lb.get("valor_total") or 0)
        delta_sp = int(lb_proyectado_derivado.get("saldo_pendiente") or 0) - int(lb.get("saldo_pendiente") or 0)
        sigma_delta_total_pagado += delta_tp
        sigma_delta_valor_total += delta_vt
        sigma_delta_saldo_pendiente += delta_sp

        if not ci_top_change:
            sin_cambio_ci_top += 1

        cambios.append({
            "loanbook_id":      lb_id,
            "cliente":          (lb.get("cliente") or {}).get("nombre")
                                or lb.get("cliente_nombre") or "?",
            "accion":           accion,
            "cuota_inicial":    ci,
            "fecha_pago":       fecha_pago.isoformat(),
            "metodo_pago":      metodo,
            "ci_top_antes":     ci_top_actual,
            "valor_total":      {"antes": int(lb.get("valor_total") or 0), "despues": valor_total_nuevo},
            "total_pagado":     {"antes": int(lb.get("total_pagado") or 0),
                                 "despues": int(lb_proyectado_derivado.get("total_pagado") or 0)},
            "saldo_pendiente":  {"antes": int(lb.get("saldo_pendiente") or 0),
                                 "despues": int(lb_proyectado_derivado.get("saldo_pendiente") or 0)},
            "estado":           {"antes": lb.get("estado"), "despues": lb_proyectado_derivado.get("estado")},
        })

        if not dry_run:
            persist = {k: v for k, v in lb_proyectado_derivado.items() if k != "_id"}
            persist["updated_at"] = now_iso_bogota()
            await db.loanbook.update_one(
                {"loanbook_id": lb_id},
                {"$set": persist},
            )
        procesados += 1

    return {
        "dry_run":                dry_run,
        "fecha_analisis":         now_iso_bogota(),
        "total_input":            total,
        "procesados":             procesados,
        "ya_pagadas":             ya_pagadas,
        "nuevas_cuotas_0":        nuevas_cuotas_0,
        "actualizadas_cuota_0":   actualizadas_cuota_0,
        "sin_ci_omitidos":        sin_ci_omitidos,
        "no_encontrados":         no_encontrados,
        "errores":                errores,
        "delta_total_pagado":     sigma_delta_total_pagado,
        "delta_valor_total":      sigma_delta_valor_total,
        "delta_saldo_pendiente":  sigma_delta_saldo_pendiente,
        "cambios":                cambios,
    }
