"""
Loanbook endpoints — credit portfolio management.

GET  /api/loanbook                              — List all loanbooks with summary stats
GET  /api/loanbook/{identifier}                 — Detail with full cuotas timeline
GET  /api/loanbook/stats                        — Portfolio summary
POST /api/loanbook/{id}/registrar-pago          — Manual: register a cuota payment
POST /api/loanbook/{id}/registrar-pago-inicial  — Manual: register cuota inicial paid
POST /api/loanbook/{id}/registrar-entrega       — Manual: activate a credit on delivery
"""
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, Response
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from core.auth import get_current_user
from core.database import get_db
from services.loanbook.auditor import auditar_loanbooks as _auditar_loanbooks
from services.loanbook.excel_export import generar_excel as _generar_excel
from services.loanbook.reparador import reparar_loanbook as _reparar_loanbook
from services.loanbook.reglas_negocio import PLAN_CUOTAS as _PLAN_CUOTAS, validar_fecha_pago as _validar_fecha_pago
from services.loanbook.state_calculator import (
    PLANES_RODDOS as _PLANES_RODDOS,
    patch_set_from_recalculo as _patch_set_recalculo,
    _derivar_total_cuotas,
)
from core.datetime_utils import now_bogota, today_bogota, now_iso_bogota
from core.loanbook_model import (
    MORA_TASA_DIARIA,
    aplicar_waterfall,
    calcular_cronograma,
    calcular_dpd,
    calcular_mora,
    estado_from_dpd,
)

logger = logging.getLogger("routers.loanbook")

router = APIRouter(prefix="/api/loanbook", tags=["loanbook"])


def _clean_doc(doc: dict) -> dict:
    """Remove MongoDB _id for JSON serialization."""
    if doc:
        doc.pop("_id", None)
    return doc


def _serialize_value(v):
    """Recursively convert a MongoDB value to a JSON-safe Python type.

    Handles: datetime → ISO string, date → ISO string, ObjectId → str,
    nested dicts (strips _id), nested lists.
    """
    if isinstance(v, dict):
        return {k2: _serialize_value(v2) for k2, v2 in v.items() if k2 != "_id"}
    if isinstance(v, list):
        return [_serialize_value(i) for i in v]
    if isinstance(v, datetime):
        return v.isoformat()
    # date check after datetime (datetime subclasses date)
    if isinstance(v, date):
        return v.isoformat()
    try:
        from bson import ObjectId
        if isinstance(v, ObjectId):
            return str(v)
    except ImportError:
        pass
    return v


@router.get("/stats")
async def loanbook_stats(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Portfolio summary stats."""
    today = today_bogota()

    all_lbs = await db.loanbook.find().to_list(length=1000)
    total = len(all_lbs)
    activos = 0
    saldados = 0
    pendiente_entrega = 0
    cartera_total = 0
    recaudo_semanal = 0
    en_mora = 0

    for lb in all_lbs:
        estado = lb.get("estado", "")
        if estado in ("saldado", "castigado"):
            saldados += 1
            continue
        if estado == "pendiente_entrega":
            pendiente_entrega += 1
        # Cartera viva: todo lo que no esté saldado/castigado, INCLUYENDO
        # pendiente_entrega (son créditos reales con factura emitida que ya
        # son cartera comprometida — solo falta entregar la moto).
        activos += 1
        # cartera_total = saldo_pendiente del Excel oficial (= monto_original).
        # Si no existe saldo_pendiente, fallback a saldo_capital + saldo_intereses.
        saldo_pend = lb.get("saldo_pendiente")
        if saldo_pend is None or saldo_pend == 0:
            saldo_pend = (
                (lb.get("saldo_capital", 0) or 0)
                + (lb.get("saldo_intereses", 0) or 0)
            )
        # Nunca sumar negativos (caso bug datos como Richard LB-0017)
        cartera_total += max(0, saldo_pend)

        # Recaudo semanal: cuota_monto for semanal, cuota/2 for quincenal, cuota/4 for mensual
        # Solo considera créditos activados (pendiente_entrega aún no genera recaudo).
        if estado != "pendiente_entrega":
            modalidad = lb.get("modalidad", "semanal")
            cuota = lb.get("cuota_monto", 0) or 0
            if modalidad == "semanal":
                recaudo_semanal += cuota
            elif modalidad == "quincenal":
                recaudo_semanal += cuota / 2
            elif modalidad == "mensual":
                recaudo_semanal += cuota / 4

            cuotas = lb.get("cuotas", [])
            dpd = calcular_dpd(cuotas, today)
            if dpd > 0:
                en_mora += 1

    return {
        "total": total,
        "activos": activos,
        "saldados": saldados,
        "pendiente_entrega": pendiente_entrega,
        "cartera_total": round(cartera_total),
        "recaudo_semanal": round(recaudo_semanal),
        "en_mora": en_mora,
    }


@router.get("/auditoria")
async def get_auditoria(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Auditoría completa de inconsistencias estructurales del portafolio.

    Detecta 3 categorías de corrupción sin modificar nada:
      1. valor_total_incorrecto — no coincide con total_cuotas × cuota_valor + cuota_inicial
      2. total_cuotas_incorrecto_segun_plan — no deriva correctamente de plan_codigo + modalidad
      3. cuotas_pagadas_con_fecha_imposible — cuotas futuras marcadas pagadas sin evidencia real

    Requiere autenticación. Solo lectura.
    """
    docs = await db.loanbook.find().to_list(length=2000)
    # Strip MongoDB _id before passing to pure function
    loanbooks = [{k: v for k, v in doc.items() if k != "_id"} for doc in docs]
    return _auditar_loanbooks(loanbooks)


@router.get("/export-excel")
async def export_excel(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Descarga el portafolio completo en Excel (.xlsx) con 2 hojas.

    Hoja "Creditos": una fila por loanbook, columnas DB vs tabla PLAN_CUOTAS,
    celdas rojas donde hay diferencias.

    Hoja "Cuotas": una fila por cuota con flags es_cuota_corrupta / motivo.

    Requiere autenticación.
    """
    from datetime import date as _date
    from io import BytesIO as _BytesIO

    docs = await db.loanbook.find().to_list(length=2000)
    loanbooks = [{k: v for k, v in doc.items() if k != "_id"} for doc in docs]

    xlsx_bytes = _generar_excel(loanbooks)

    fecha_str = today_bogota().isoformat()
    filename  = f"portafolio_roddos_{fecha_str}.xlsx"

    return StreamingResponse(
        _BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/excel")
async def export_excel_alias(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Alias de /export-excel para compatibilidad con el frontend."""
    return await export_excel(db=db, current_user=current_user)


# ─────────────────────── B3: Loan Tape Excel export ──────────────────────────

@router.get("/export-loan-tape")
async def export_loan_tape_excel(
    fecha_corte: Optional[date] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Exporta el Loan Tape completo en formato Excel (.xlsx).

    Genera un archivo con 5 hojas:
      1. Loan Tape RDX     — Un loanbook RDX por fila, 38 columnas
      2. Loan Tape RODANTE — Un loanbook RODANTE por fila
      3. Cronograma        — Una cuota por fila de todos los loanbooks
      4. KPIs Mora         — 8 indicadores de cartera con semáforo
      5. Roll Rate         — Matriz 5×5 de migración entre buckets

    Parámetros:
      fecha_corte (opcional): Fecha de corte para el reporte.
                               Defaults al día de hoy si no se especifica.

    Requiere autenticación.
    """
    from services.loanbook.loan_tape_service import generar_loan_tape

    fecha = fecha_corte or today_bogota()

    loanbooks = await db.loanbook.find({}).to_list(length=5000)

    xlsx_bytes = generar_loan_tape(loanbooks, fecha_corte=fecha)

    filename = f"loanbook_roddos_{fecha.strftime('%Y-%m-%d')}.xlsx"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    return StreamingResponse(
        iter([xlsx_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


# ─────────────────────── B4: Amortización + Waterfall + Cronogramas ──────────

@router.post("/generar-cronogramas-todos")
async def generar_cronogramas_todos(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Regenera el cronograma de amortización real para todos los loanbooks activos.

    Añade monto_capital + monto_interes a cada cuota de los loanbooks que
    aún no tienen ese desglose. Los loanbooks con cuotas ya desglosadas
    se omiten para evitar sobreescribir datos reales.

    Úsese una sola vez en producción tras el deploy de B4.
    Requiere autenticación.
    """
    from services.loanbook.amortizacion_service import generar_cronograma as _gen_cron

    lbs = await db.loanbook.find(
        {"estado": {"$nin": ["Pagado", "Charge-Off", "saldado", "castigado"]}}
    ).to_list(length=5000)

    procesados = 0
    omitidos = 0
    errores = 0

    for lb in lbs:
        try:
            fechas = lb.get("fechas") or {}
            fecha_entrega_raw = lb.get("fecha_entrega") or fechas.get("entrega")
            if not fecha_entrega_raw:
                omitidos += 1
                continue
            fecha_entrega = date.fromisoformat(str(fecha_entrega_raw)[:10])
            saldo = float(lb.get("saldo_capital") or lb.get("saldo_pendiente") or 0)
            cuota_p = float(lb.get("cuota_monto") or lb.get("cuota_periodica") or 0)
            tasa = float(lb.get("tasa_ea") or (lb.get("plan") or {}).get("tasa") or 0.39)
            modalidad = lb.get("modalidad") or lb.get("modalidad_pago") or "semanal"
            n = int(lb.get("num_cuotas") or lb.get("total_cuotas") or len(lb.get("cuotas") or []) or 0)
            if saldo <= 0 or n <= 0:
                omitidos += 1
                continue

            nuevas_cuotas = _gen_cron(
                saldo_inicial=saldo,
                cuota_periodica=cuota_p,
                tasa_ea=tasa,
                modalidad=modalidad,
                fecha_entrega=fecha_entrega,
                n_cuotas=n,
            )
            await db.loanbook.update_one(
                {"_id": lb["_id"]},
                {"$set": {"cuotas": nuevas_cuotas, "updated_at": now_iso_bogota()}},
            )
            procesados += 1
        except Exception as e:
            lb_id = lb.get("loanbook_id", str(lb.get("_id", "?")))
            logger.error(f"[generar-cronogramas-todos] Error en {lb_id}: {type(e).__name__}: {e}")
            errores += 1

    return {
        "ok": True,
        "procesados": procesados,
        "omitidos": omitidos,
        "errores": errores,
    }


@router.post("/reparar-todos")
async def reparar_todos(
    dry_run: bool = True,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Repara inconsistencias estructurales en TODOS los loanbooks del portafolio.

    dry_run=True (default): solo describe qué cambiaría, sin persistir.
    dry_run=False: aplica las reparaciones en MongoDB.

    Requiere autenticación.
    """
    docs = await db.loanbook.find().to_list(length=2000)
    resultados = []
    reparados = 0

    for doc in docs:
        doc.pop("_id", None)
        resultado = _reparar_loanbook(doc, dry_run=dry_run)

        if resultado["tiene_problemas"]:
            resultados.append(resultado)
            if not dry_run and resultado["documento_reparado"]:
                doc_rep = resultado["documento_reparado"]
                campos = {k: v for k, v in doc_rep.items()
                          if k in ("num_cuotas", "valor_total", "saldo_capital",
                                   "total_pagado", "plan", "cuotas", "estado")}
                await db.loanbook.update_one(
                    {"loanbook_id": resultado["loanbook_id"]},
                    {"$set": campos},
                )
                reparados += 1

    return {
        "dry_run": dry_run,
        "total_analizados": len(docs),
        "con_problemas": len(resultados),
        "reparados": reparados if not dry_run else 0,
        "detalle": resultados,
    }


@router.get("")
async def listar_loanbooks(
    estado: str | None = None,
    modelo: str | None = None,
    plan: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """List all loanbooks with computed fields."""
    today = today_bogota()
    filtro: dict = {}
    if estado:
        filtro["estado"] = estado
    if modelo:
        filtro["modelo"] = modelo
    if plan:
        filtro["plan_codigo"] = plan

    cursor = db.loanbook.find(filtro).sort("fecha_creacion", -1)
    items = await cursor.to_list(length=500)

    result = []
    for lb in items:
        _clean_doc(lb)
        cuotas = lb.get("cuotas", [])
        pagadas = sum(1 for c in cuotas if c.get("estado") == "pagada")
        total_cuotas = len(cuotas)
        dpd = calcular_dpd(cuotas, today)

        # Find next pending cuota
        proxima = None
        for c in cuotas:
            if c.get("estado") != "pagada" and c.get("fecha"):
                proxima = {
                    "fecha": c["fecha"],
                    "monto": c.get("monto") or c.get("monto_total", 0),
                }
                break

        lb["cuotas_pagadas"] = pagadas
        lb["cuotas_total"] = total_cuotas
        lb["dpd"] = dpd
        lb["proxima_cuota"] = proxima
        # Strip full cuotas array from list view
        lb.pop("cuotas", None)
        result.append(_serialize_lb(lb))

    # Sort by DPD descending (morosos first)
    result.sort(key=lambda x: x.get("dpd", 0), reverse=True)

    return {"count": len(result), "loanbooks": result}


@router.get("/{identifier}")
async def get_loanbook(
    identifier: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Get full loanbook detail with cuotas timeline.

    Accepts either:
      - VIN (17-char vehicle id), for tipo_producto='moto'
      - loanbook_id (e.g. 'LB-2026-0026'), for any tipo_producto including
        comparendo/licencia which have no VIN.
    """
    today = today_bogota()

    # Try loanbook_id first (disambiguates when id looks like LB-XXXX)
    lb = None
    if identifier.upper().startswith("LB-"):
        lb = await db.loanbook.find_one({"loanbook_id": identifier})
    if lb is None:
        # Fall back to VIN lookup
        lb = await db.loanbook.find_one({"vin": identifier})
    if lb is None:
        # Last resort: try loanbook_id without prefix match (legacy ids)
        lb = await db.loanbook.find_one({"loanbook_id": identifier})
    if not lb:
        raise HTTPException(
            status_code=404,
            detail=f"Loanbook no encontrado para identifier '{identifier}'",
        )

    _clean_doc(lb)
    cuotas = lb.get("cuotas", [])
    pagadas = sum(1 for c in cuotas if c.get("estado") == "pagada")
    dpd = calcular_dpd(cuotas, today)

    # Classify cuotas for timeline
    for c in cuotas:
        if c.get("estado") == "pagada":
            c["timeline_status"] = "pagada"
        elif c.get("fecha"):
            fecha = date.fromisoformat(c["fecha"])
            if fecha < today:
                c["timeline_status"] = "vencida"
            elif fecha == today or (fecha > today and c == next(
                (x for x in cuotas if x.get("estado") != "pagada" and x.get("fecha")), None
            )):
                c["timeline_status"] = "proxima"
            else:
                c["timeline_status"] = "pendiente"
        else:
            c["timeline_status"] = "pendiente"

    proxima = None
    for c in cuotas:
        if c.get("estado") != "pagada" and c.get("fecha"):
            proxima = {"fecha": c["fecha"], "monto": (c.get("monto") or c.get("monto_total") or 0)}
            break

    lb["cuotas_pagadas"] = pagadas
    lb["cuotas_total"] = len(cuotas)
    lb["dpd"] = dpd
    lb["proxima_cuota"] = proxima

    return _serialize_lb(lb)


@router.post("/{identifier}/reparar")
async def reparar_uno(
    identifier: str,
    dry_run: bool = True,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Repara inconsistencias estructurales de un loanbook individual.

    dry_run=True (default): describe qué cambiaría, sin persistir.
    dry_run=False: aplica las reparaciones en MongoDB.

    Acepta VIN o loanbook_id. Requiere autenticación.
    """
    lb = await _find_lb_by_identifier(db, identifier)
    lb.pop("_id", None)

    resultado = _reparar_loanbook(lb, dry_run=dry_run)

    if not dry_run and resultado["tiene_problemas"] and resultado["documento_reparado"]:
        doc_rep = resultado["documento_reparado"]
        campos = {k: v for k, v in doc_rep.items()
                  if k in ("num_cuotas", "valor_total", "saldo_capital",
                           "total_pagado", "plan", "cuotas", "estado")}
        await db.loanbook.update_one(
            {"loanbook_id": resultado["loanbook_id"]},
            {"$set": campos},
        )
        await _publish_event(
            db,
            "loanbook.reparado",
            "routers.loanbook.reparador",
            {
                "loanbook_id": resultado["loanbook_id"],
                "reparaciones": resultado["reparaciones"],
            },
            accion=f"Reparación estructural {resultado['loanbook_id']}",
        )

    return resultado


# ═══════════════════════════════════════════
# Manual operations (BLOQUE 2)
# ═══════════════════════════════════════════

METODOS_PAGO = {"efectivo", "bancolombia", "bbva", "davivienda", "nequi", "transferencia", "otro"}
MODALIDADES = {"semanal", "quincenal", "mensual"}


class PatchLoanbookBody(BaseModel):
    """Campos opcionales para edición manual del crédito.

    Solo se aplican los campos enviados (PATCH semántico).
    No recalcula cronograma ni saldo — para eso usar registrar-entrega.
    """
    plan_codigo: str | None = None
    modalidad: str | None = None
    cuota_valor: float | None = None
    cuota_inicial_pagada: bool | None = None
    total_cuotas: int | None = None
    fecha_factura: str | None = None
    fecha_entrega: str | None = None
    primera_cuota: str | None = None
    vin: str | None = None
    modelo: str | None = None
    cliente_telefono: str | None = None
    cliente_telefono_alternativo: str | None = None
    tipo_producto: str | None = None


class RegistrarPagoBody(BaseModel):
    cuota_numero: int | None = None
    monto_pago: float
    metodo_pago: str = "efectivo"
    fecha_pago: str | None = None
    referencia: str | None = None


class RegistrarPagoInicialBody(BaseModel):
    monto_pago: float
    metodo_pago: str = "efectivo"
    fecha_pago: str | None = None
    referencia: str | None = None


class RegistrarEntregaBody(BaseModel):
    fecha_entrega: str | None = None
    fecha_primera_cuota: str | None = None
    dia_cobro_especial: str | None = None


@router.patch("/{identifier}")
async def patch_loanbook(
    identifier: str,
    body: PatchLoanbookBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Edición manual de campos del crédito.

    Solo actualiza los campos enviados (PATCH semántico).
    NO recalcula cronograma ni saldo — solo sobreescribe metadatos del crédito.
    Para regenerar cuotas, usar registrar-entrega después.
    """
    lb = await _find_lb_by_identifier(db, identifier)

    update: dict = {}

    if body.plan_codigo is not None:
        update["plan_codigo"] = body.plan_codigo
        update["plan.codigo"] = body.plan_codigo
    if body.modalidad is not None:
        if body.modalidad not in MODALIDADES:
            raise HTTPException(status_code=400, detail=f"modalidad debe ser: {sorted(MODALIDADES)}")
        update["modalidad"] = body.modalidad
        update["plan.modalidad"] = body.modalidad
    if body.cuota_valor is not None:
        update["cuota_monto"] = body.cuota_valor
        update["plan.cuota_valor"] = body.cuota_valor
    if body.cuota_inicial_pagada is not None:
        update["cuota_inicial_pagada"] = body.cuota_inicial_pagada
    if body.total_cuotas is not None:
        update["num_cuotas"] = body.total_cuotas
        update["plan.total_cuotas"] = body.total_cuotas
    if body.fecha_factura is not None:
        update["fechas.factura"] = body.fecha_factura
    if body.fecha_entrega is not None:
        update["fecha_entrega"] = body.fecha_entrega
        update["fechas.entrega"] = body.fecha_entrega
    if body.primera_cuota is not None:
        update["fecha_primer_pago"] = body.primera_cuota
        update["fechas.primera_cuota"] = body.primera_cuota
    if body.vin is not None:
        update["vin"] = body.vin
        update["moto.vin"] = body.vin
    if body.modelo is not None:
        update["modelo"] = body.modelo
        update["moto.modelo"] = body.modelo
    if body.cliente_telefono is not None:
        update["cliente.telefono"] = body.cliente_telefono
    if body.cliente_telefono_alternativo is not None:
        update["cliente.telefono_alternativo"] = body.cliente_telefono_alternativo
    if body.tipo_producto is not None:
        update["tipo_producto"] = body.tipo_producto

    if not update:
        raise HTTPException(status_code=400, detail="No se enviaron campos para actualizar")

    update["updated_at"] = datetime.now(timezone.utc).isoformat()

    await db.loanbook.update_one(
        {"loanbook_id": lb["loanbook_id"]},
        {"$set": update},
    )

    campos = list(body.model_fields_set)
    await _publish_event(
        db,
        "loanbook.editado",
        "routers.loanbook.manual",
        {
            "loanbook_id": lb["loanbook_id"],
            "campos_editados": campos,
            "valores": body.model_dump(exclude_none=True),
        },
        accion=f"Edición manual {lb['loanbook_id']}: {', '.join(campos)}",
    )

    await _recalcular_y_persistir(db, lb["loanbook_id"])
    logger.info(f"Loanbook editado: {lb['loanbook_id']} campos={campos}")

    return {
        "success": True,
        "loanbook_id": lb["loanbook_id"],
        "campos_actualizados": campos,
    }


class PatchCuotaBody(BaseModel):
    """Edición manual de una cuota individual.

    No toca saldo — solo corrige metadatos de la cuota.
    Para registrar un pago real (con waterfall + saldo), usar registrar-pago.
    """
    estado: str | None = None          # pendiente | pagada | condonada
    fecha_pago: str | None = None      # yyyy-MM-dd
    monto_pagado: float | None = None
    metodo_pago: str | None = None
    referencia: str | None = None
    valor: float | None = None         # overwrite cuota.monto (reestructura)
    fecha: str | None = None           # overwrite cuota.fecha (reprogramación)


ESTADOS_CUOTA = {"pendiente", "pagada", "condonada"}


@router.patch("/{identifier}/cuotas/{numero}")
async def patch_cuota(
    identifier: str,
    numero: int,
    body: PatchCuotaBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Edición manual de una cuota individual.

    Corrige metadatos sin tocar saldo_capital ni saldo_pendiente.
    Útil para correcciones contables, reprogramaciones puntuales y
    condonaciones que no implican movimiento de efectivo.

    Para registrar un pago con waterfall completo, usar registrar-pago.
    """
    lb = await _find_lb_by_identifier(db, identifier)
    cuotas: list[dict] = lb.get("cuotas", [])

    target = next((c for c in cuotas if c.get("numero") == numero), None)
    if target is None:
        raise HTTPException(
            status_code=404,
            detail=f"Cuota #{numero} no encontrada en {lb['loanbook_id']}",
        )

    cambios: dict = {}
    if body.estado is not None:
        if body.estado not in ESTADOS_CUOTA:
            raise HTTPException(status_code=400, detail=f"estado debe ser: {sorted(ESTADOS_CUOTA)}")
        target["estado"] = body.estado
        cambios["estado"] = body.estado
    if body.fecha_pago is not None:
        target["fecha_pago"] = body.fecha_pago
        cambios["fecha_pago"] = body.fecha_pago
    if body.monto_pagado is not None:
        target["monto_pagado"] = body.monto_pagado
        cambios["monto_pagado"] = body.monto_pagado
    if body.metodo_pago is not None:
        target["metodo_pago"] = body.metodo_pago
        cambios["metodo_pago"] = body.metodo_pago
    if body.referencia is not None:
        target["referencia"] = body.referencia
        cambios["referencia"] = body.referencia
    if body.valor is not None:
        target["monto"] = body.valor
        cambios["monto"] = body.valor
    if body.fecha is not None:
        target["fecha"] = body.fecha
        cambios["fecha"] = body.fecha

    if not cambios:
        raise HTTPException(status_code=400, detail="No se enviaron campos para actualizar")

    await db.loanbook.update_one(
        {"loanbook_id": lb["loanbook_id"]},
        {"$set": {
            "cuotas": cuotas,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )

    await _publish_event(
        db,
        "cuota.editada.manual",
        "routers.loanbook.manual",
        {
            "loanbook_id": lb["loanbook_id"],
            "cuota_numero": numero,
            "cambios": cambios,
        },
        accion=f"Edición manual cuota #{numero} en {lb['loanbook_id']}",
    )

    await _recalcular_y_persistir(db, lb["loanbook_id"])
    logger.info(f"Cuota editada: {lb['loanbook_id']} #{numero} cambios={list(cambios.keys())}")

    return {
        "success": True,
        "loanbook_id": lb["loanbook_id"],
        "cuota_numero": numero,
        "campos_actualizados": list(cambios.keys()),
        "cuota": target,
    }


async def _find_lb_by_identifier(db: AsyncIOMotorDatabase, identifier: str) -> dict:
    """Lookup helper: accept VIN or loanbook_id."""
    lb = None
    if identifier.upper().startswith("LB-"):
        lb = await db.loanbook.find_one({"loanbook_id": identifier})
    if lb is None:
        lb = await db.loanbook.find_one({"vin": identifier})
    if lb is None:
        lb = await db.loanbook.find_one({"loanbook_id": identifier})
    if not lb:
        raise HTTPException(
            status_code=404,
            detail=f"Loanbook no encontrado para identifier '{identifier}'",
        )
    return lb


async def _recalcular_y_persistir(db: AsyncIOMotorDatabase, loanbook_id: str) -> None:
    """Post-write recálculo estructural de campos derivados.

    Corrige num_cuotas, valor_total y saldo_capital a partir de PLANES_RODDOS
    y la lista de cuotas real. NO sobreescribe estado ni dpd — cada endpoint
    ya los gestiona con su propia lógica de negocio.
    """
    lb = await db.loanbook.find_one({"loanbook_id": loanbook_id})
    if not lb:
        return
    lb.pop("_id", None)
    patch = _patch_set_recalculo(lb)
    # Solo campos estructurales — estado y dpd los gestiona cada endpoint
    campos = {k: v for k, v in patch.items()
              if k in ("num_cuotas", "valor_total", "saldo_capital", "total_pagado", "plan")}
    if campos:
        await db.loanbook.update_one(
            {"loanbook_id": loanbook_id},
            {"$set": campos},
        )


async def _publish_event(db: AsyncIOMotorDatabase, event_type: str, source: str, datos: dict, alegra_id: str | None = None, accion: str = "") -> None:
    """Append-only event bus write. Per ROG-4 this is allowed from routers."""
    await db.roddos_events.insert_one({
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "source": source,
        "correlation_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "datos": datos,
        "alegra_id": alegra_id,
        "accion_ejecutada": accion,
    })


@router.post("/{identifier}/registrar-pago")
async def registrar_pago_manual(
    identifier: str,
    body: RegistrarPagoBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Registra un pago manual de cuota. Aplica waterfall.

    Flujo:
      1. MongoDB update inmediato (no bloquea si Alegra falla)
      2. publish_event("pago.cuota.registrado") al bus
      3. Alegra journal como best-effort (via DataKeeper listener)
    """
    metodo = body.metodo_pago.lower() if body.metodo_pago else "efectivo"
    if metodo not in METODOS_PAGO:
        raise HTTPException(status_code=400, detail=f"metodo_pago inválido. Use: {sorted(METODOS_PAGO)}")

    lb = await _find_lb_by_identifier(db, identifier)
    today = today_bogota()
    fecha_pago_str = body.fecha_pago or today.isoformat()
    try:
        fecha_pago = date.fromisoformat(fecha_pago_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="fecha_pago inválida (use yyyy-MM-dd)")

    cuotas = lb.get("cuotas", [])
    if not cuotas:
        raise HTTPException(status_code=400, detail="Loanbook sin cuotas — ejecuta registrar-entrega primero")

    anzi_pct = lb.get("anzi_pct", 0.02) or 0.0

    # Calcular mora pendiente
    mora_pendiente = 0
    for c in cuotas:
        if c.get("estado") == "pagada" or not c.get("fecha"):
            continue
        fc = date.fromisoformat(c["fecha"])
        mora = calcular_mora(fc, fecha_pago, MORA_TASA_DIARIA)
        c["mora_acumulada"] = mora
        mora_pendiente += mora

    # Vencidas
    vencidas_total = sum(
        (c.get("monto") or c.get("monto_total") or 0) for c in cuotas
        if c.get("estado") != "pagada" and c.get("fecha")
        and date.fromisoformat(c["fecha"]) < fecha_pago
    )

    # Corriente
    corriente_monto = 0
    for c in cuotas:
        if c.get("estado") == "pagada":
            continue
        if c.get("fecha") and date.fromisoformat(c["fecha"]) >= fecha_pago:
            corriente_monto = (c.get("monto") or c.get("monto_total") or 0)
            break
        if not c.get("fecha"):
            corriente_monto = (c.get("monto") or c.get("monto_total") or 0)
            break

    saldo_capital = lb.get("saldo_capital", 0) or lb.get("saldo_pendiente", 0) or 0

    alloc = aplicar_waterfall(
        monto_pago=body.monto_pago,
        anzi_pct=anzi_pct,
        mora_pendiente=mora_pendiente,
        cuotas_vencidas_total=vencidas_total,
        cuota_corriente=corriente_monto,
        saldo_capital=saldo_capital,
    )

    # Marcar cuotas pagadas según allocation
    # BUILD 2 FIX: cuando cuota_numero es explícito, apuntamos directo a esa cuota.
    # El monto_pago BRUTO (antes del split ANZI) es lo que cubre la cuota — ANZI es
    # solo distribución interna del banco, no reduce la cobertura de la cuota.
    pago_parcial = False
    if body.cuota_numero is not None:
        target = next((c for c in cuotas if c.get("numero") == body.cuota_numero), None)
        if target is None:
            raise HTTPException(
                status_code=404,
                detail=f"Cuota #{body.cuota_numero} no encontrada en este loanbook",
            )
        if target.get("estado") == "pagada":
            raise HTTPException(
                status_code=409,
                detail=f"Cuota #{body.cuota_numero} ya está pagada — pago duplicado bloqueado",
            )
        # Fix 2026-04-28: la cuota puede tener `monto`, `monto_total` o `valor_cuota`
        # según versión del schema. Antes target["monto"] reventaba con KeyError → 500.
        # Logs Render 2026-04-27T21:21 → 3 fallos seguidos sobre LB-2026-0014.
        target_monto = (
            target.get("monto")
            or target.get("monto_total")
            or target.get("valor_cuota")
            or 0
        )
        pago_parcial = body.monto_pago < target_monto
        target["estado"] = "pagada"
        target["fecha_pago"] = fecha_pago_str
        target["mora_acumulada"] = 0
        target["metodo_pago"] = metodo
        target["referencia"] = body.referencia
    else:
        # Waterfall genérico cuando no se especifica cuota (path original)
        rem_venc = alloc["vencidas"]
        rem_corr = alloc["corriente"]
        for c in cuotas:
            if c.get("estado") == "pagada":
                continue
            if c.get("fecha"):
                fc = date.fromisoformat(c["fecha"])
                if fc < fecha_pago and rem_venc >= (c.get("monto") or c.get("monto_total") or 0):
                    c["estado"] = "pagada"
                    c["fecha_pago"] = fecha_pago_str
                    c["mora_acumulada"] = 0
                    c["metodo_pago"] = metodo
                    c["referencia"] = body.referencia
                    rem_venc -= (c.get("monto") or c.get("monto_total") or 0)
                    continue
                if fc >= fecha_pago and rem_corr >= (c.get("monto") or c.get("monto_total") or 0):
                    c["estado"] = "pagada"
                    c["fecha_pago"] = fecha_pago_str
                    c["mora_acumulada"] = 0
                    c["metodo_pago"] = metodo
                    c["referencia"] = body.referencia
                    rem_corr -= (c.get("monto") or c.get("monto_total") or 0)
                    break
            else:
                if rem_corr >= (c.get("monto") or c.get("monto_total") or 0):
                    c["estado"] = "pagada"
                    c["fecha_pago"] = fecha_pago_str
                    c["metodo_pago"] = metodo
                    c["referencia"] = body.referencia
                    rem_corr -= (c.get("monto") or c.get("monto_total") or 0)
                    break

    new_saldo = max(saldo_capital - alloc["corriente"] - alloc["vencidas"] - alloc["capital"], 0)
    total_pagado = (lb.get("total_pagado", 0) or 0) + body.monto_pago
    total_mora = (lb.get("total_mora_pagada", 0) or 0) + alloc["mora"]
    total_anzi = (lb.get("total_anzi_pagado", 0) or 0) + alloc["anzi"]
    cuotas_pagadas = sum(1 for c in cuotas if c.get("estado") == "pagada")

    dpd = calcular_dpd(cuotas, fecha_pago)
    nuevo_estado = "saldado" if new_saldo == 0 and cuotas_pagadas == len(cuotas) else estado_from_dpd(dpd)

    await db.loanbook.update_one(
        {"loanbook_id": lb["loanbook_id"]},
        {"$set": {
            "cuotas": cuotas,
            "saldo_capital": new_saldo,
            "saldo_pendiente": new_saldo,
            "total_pagado": total_pagado,
            "total_mora_pagada": total_mora,
            "total_anzi_pagado": total_anzi,
            "cuotas_pagadas": cuotas_pagadas,
            "estado": nuevo_estado,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )

    await _publish_event(
        db,
        "pago.cuota.registrado",
        "routers.loanbook.manual",
        {
            "loanbook_id": lb["loanbook_id"],
            "vin": lb.get("vin"),
            "monto_pago": body.monto_pago,
            "fecha_pago": fecha_pago_str,
            "metodo_pago": metodo,
            "referencia": body.referencia,
            "desglose": alloc,
            "cuota_numero": body.cuota_numero,
        },
        accion=f"Pago manual ${body.monto_pago:,.0f} VIN {lb.get('vin') or lb['loanbook_id']}",
    )

    await _recalcular_y_persistir(db, lb["loanbook_id"])
    logger.info(f"Pago manual registrado: {lb['loanbook_id']} ${body.monto_pago:,.0f} método={metodo}")

    return {
        "success": True,
        "loanbook_id": lb["loanbook_id"],
        "nuevo_saldo": new_saldo,
        "nuevo_estado": nuevo_estado,
        "cuotas_pagadas": cuotas_pagadas,
        "desglose": alloc,
        "pago_parcial": pago_parcial,
    }


@router.post("/{identifier}/registrar-pago-inicial")
async def registrar_pago_inicial(
    identifier: str,
    body: RegistrarPagoInicialBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Registra la cuota inicial (solo válido en pendiente_entrega)."""
    lb = await _find_lb_by_identifier(db, identifier)
    if lb.get("estado") != "pendiente_entrega":
        raise HTTPException(
            status_code=400,
            detail=f"Solo aplica a créditos pendiente_entrega (estado actual: {lb.get('estado')})",
        )

    metodo = body.metodo_pago.lower() if body.metodo_pago else "efectivo"
    if metodo not in METODOS_PAGO:
        raise HTTPException(status_code=400, detail=f"metodo_pago inválido. Use: {sorted(METODOS_PAGO)}")

    fecha_pago_str = body.fecha_pago or today_bogota().isoformat()

    await db.loanbook.update_one(
        {"loanbook_id": lb["loanbook_id"]},
        {"$set": {
            "cuota_inicial_pagada": True,
            "cuota_inicial_monto": body.monto_pago,
            "cuota_inicial_metodo": metodo,
            "cuota_inicial_fecha": fecha_pago_str,
            "cuota_inicial_referencia": body.referencia,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )

    await _publish_event(
        db,
        "pago.inicial.registrado",
        "routers.loanbook.manual",
        {
            "loanbook_id": lb["loanbook_id"],
            "vin": lb.get("vin"),
            "monto_pago": body.monto_pago,
            "metodo_pago": metodo,
            "fecha_pago": fecha_pago_str,
        },
        accion=f"Cuota inicial ${body.monto_pago:,.0f} registrada manual",
    )

    return {
        "success": True,
        "loanbook_id": lb["loanbook_id"],
        "cuota_inicial_pagada": True,
    }


def _next_wednesday_from(d: date) -> date:
    """First Wednesday >= d."""
    offset = (2 - d.weekday()) % 7
    return d + timedelta(days=offset)


@router.post("/{identifier}/registrar-entrega")
async def registrar_entrega(
    identifier: str,
    body: RegistrarEntregaBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Activa el crédito: pendiente_entrega → activo + genera cronograma."""
    lb = await _find_lb_by_identifier(db, identifier)
    if lb.get("estado") not in ("pendiente_entrega", "activo"):
        raise HTTPException(
            status_code=400,
            detail=f"No aplicable en estado '{lb.get('estado')}'",
        )

    today = today_bogota()
    fecha_entrega_str = body.fecha_entrega or today.isoformat()
    try:
        fecha_entrega = date.fromisoformat(fecha_entrega_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="fecha_entrega inválida (yyyy-MM-dd)")

    # Auto-calcular primera cuota si no se envió
    if body.fecha_primera_cuota:
        try:
            fpc = date.fromisoformat(body.fecha_primera_cuota)
        except ValueError:
            raise HTTPException(status_code=400, detail="fecha_primera_cuota inválida (yyyy-MM-dd)")
    else:
        fpc = _next_wednesday_from(fecha_entrega + timedelta(days=7))

    modalidad = lb.get("modalidad", "semanal")
    num_cuotas = lb.get("num_cuotas", 0) or lb.get("cuotas_total", 0)
    cuota_monto = lb.get("cuota_monto", 0) or 0

    if num_cuotas <= 0:
        raise HTTPException(status_code=400, detail="Loanbook sin num_cuotas configurado")

    # Generar cronograma respetando dia_cobro_especial
    fechas = calcular_cronograma(
        fecha_entrega=fecha_entrega,
        modalidad=modalidad,
        num_cuotas=num_cuotas,
        fecha_primer_pago=fpc,
        dia_cobro_especial=body.dia_cobro_especial,
    )

    cuotas = [
        {
            "numero": i + 1,
            "monto": cuota_monto,
            "estado": "pendiente",
            "fecha": f.isoformat(),
            "fecha_pago": None,
            "mora_acumulada": 0,
        }
        for i, f in enumerate(fechas)
    ]

    # Obtener capital_plan de catalogo_planes para calcular saldos correctamente
    plan_codigo_lb = lb.get("plan_codigo") or (lb.get("plan") or {}).get("codigo")
    capital_plan_val: int | None = None
    if plan_codigo_lb:
        cat_plan = await db.catalogo_planes.find_one({"codigo": plan_codigo_lb})
        if cat_plan:
            capital_plan_val = cat_plan.get("capital_plan")
    # Fallback RODANTE: capital_plan = monto_original del producto (repuesto/servicio)
    if not capital_plan_val:
        capital_plan_val = lb.get("monto_original") or (cuota_monto * num_cuotas) or 0

    # cuota_estandar_plan: para RDX usa la del loanbook si existe; para RODANTE = cuota_periodica
    cuota_std_val = lb.get("cuota_estandar_plan") or int(cuota_monto)

    from services.loanbook.reglas_negocio import calcular_saldos as _calcular_saldos
    if capital_plan_val and num_cuotas:
        _s = _calcular_saldos(int(capital_plan_val), num_cuotas, int(cuota_monto), 0,
                              cuota_estandar_plan=cuota_std_val)
        saldo_capital_init   = _s["saldo_capital"]
        saldo_intereses_init = _s["saldo_intereses"]
    else:
        saldo_capital_init   = num_cuotas * cuota_monto
        saldo_intereses_init = 0

    update_fields = {
        "estado": "activo",
        "fecha_entrega": fecha_entrega_str,
        "fecha_primer_pago": fpc.isoformat(),
        "fechas.entrega": fecha_entrega_str,
        "fechas.primera_cuota": fpc.isoformat(),
        "cuotas": cuotas,
        "cuotas_pagadas": 0,
        "cuotas_total": len(cuotas),
        "saldo_capital":     saldo_capital_init,
        "saldo_pendiente":   saldo_capital_init,
        "saldo_intereses":   saldo_intereses_init,
        "capital_plan":      capital_plan_val or 0,
        "cuota_estandar_plan": cuota_std_val,
        "updated_at": now_iso_bogota(),
    }
    if body.dia_cobro_especial:
        update_fields["dia_cobro_especial"] = body.dia_cobro_especial

    await db.loanbook.update_one({"loanbook_id": lb["loanbook_id"]}, {"$set": update_fields})

    await _publish_event(
        db,
        "moto.entregada",
        "routers.loanbook.manual",
        {
            "loanbook_id": lb["loanbook_id"],
            "vin": lb.get("vin"),
            "fecha_entrega": fecha_entrega_str,
            "fecha_primera_cuota": fpc.isoformat(),
            "dia_cobro_especial": body.dia_cobro_especial,
        },
        accion=f"Entrega manual {lb['loanbook_id']} — primer cobro {fpc.isoformat()}",
    )

    await _recalcular_y_persistir(db, lb["loanbook_id"])

    return {
        "success": True,
        "loanbook_id": lb["loanbook_id"],
        "estado": "activo",
        "fecha_entrega": fecha_entrega_str,
        "fecha_primera_cuota": fpc.isoformat(),
        "num_cuotas": len(cuotas),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CANONICAL PUT ENDPOINTS — Sprint Estructural BUILD 4
# Reemplazan los PATCH/POST /registrar-* del Sprint Cobranza (ahora DEPRECATED).
# ═══════════════════════════════════════════════════════════════════════════════

class PutLoanbookBody(BaseModel):
    """Edición canónica de metadatos del crédito con auto-derivación.

    plan_codigo determina num_cuotas automáticamente (PLANES_RODDOS).
    valor_total se recalcula siempre: num_cuotas × cuota_valor + cuota_inicial.
    """
    plan_codigo: str | None = None          # P15S | P39S | P52S | P78S
    modalidad: str | None = None            # semanal | quincenal | mensual
    cuota_valor: float | None = None        # valor por cuota en la modalidad
    cuota_inicial: float | None = None      # enganche / cuota inicial
    vin: str | None = None
    modelo: str | None = None
    tipo_producto: str | None = None
    cliente_telefono: str | None = None
    cliente_telefono_alternativo: str | None = None
    fecha_entrega: str | None = None        # yyyy-MM-dd
    primera_cuota: str | None = None        # yyyy-MM-dd (miércoles)


@router.put("/{identifier}")
async def put_loanbook(
    identifier: str,
    body: PutLoanbookBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Edición canónica de un loanbook con auto-derivación de plan.

    - plan_codigo en PLANES_RODDOS → deriva num_cuotas automáticamente
    - valor_total recalculado al final vía recalcular_loanbook()
    - Retorna 422 si plan_codigo o modalidad son inválidos
    """
    lb = await _find_lb_by_identifier(db, identifier)
    update: dict = {}

    # Validar y aplicar plan_codigo
    if body.plan_codigo is not None:
        if body.plan_codigo not in _PLANES_RODDOS:
            raise HTTPException(
                status_code=422,
                detail=f"plan_codigo '{body.plan_codigo}' inválido. Válidos: {sorted(_PLANES_RODDOS.keys())}",
            )
        update["plan_codigo"] = body.plan_codigo
        update["plan.codigo"] = body.plan_codigo

    # Validar y aplicar modalidad
    if body.modalidad is not None:
        if body.modalidad not in MODALIDADES:
            raise HTTPException(
                status_code=422,
                detail=f"modalidad '{body.modalidad}' inválida. Válidas: {sorted(MODALIDADES)}",
            )
        update["modalidad"] = body.modalidad
        update["plan.modalidad"] = body.modalidad

    if body.cuota_valor is not None:
        update["cuota_monto"] = body.cuota_valor
        update["plan.cuota_valor"] = body.cuota_valor

    if body.cuota_inicial is not None:
        update["plan.cuota_inicial"] = body.cuota_inicial

    if body.vin is not None:
        update["vin"] = body.vin
    if body.modelo is not None:
        update["modelo"] = body.modelo
    if body.tipo_producto is not None:
        update["tipo_producto"] = body.tipo_producto
    if body.cliente_telefono is not None:
        update["cliente.telefono"] = body.cliente_telefono
    if body.cliente_telefono_alternativo is not None:
        update["cliente.telefono_alternativo"] = body.cliente_telefono_alternativo
    if body.fecha_entrega is not None:
        update["fecha_entrega"] = body.fecha_entrega
    if body.primera_cuota is not None:
        update["fecha_primer_pago"] = body.primera_cuota

    if not update:
        raise HTTPException(status_code=422, detail="No se enviaron campos para actualizar")

    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.loanbook.update_one({"loanbook_id": lb["loanbook_id"]}, {"$set": update})

    # Auto-derivación canónica: num_cuotas y valor_total desde PLANES_RODDOS
    await _recalcular_y_persistir(db, lb["loanbook_id"])

    await _publish_event(
        db, "loanbook.editado.canonico", "routers.loanbook.put",
        {"loanbook_id": lb["loanbook_id"], "campos": list(body.model_fields_set)},
        accion=f"PUT canónico {lb['loanbook_id']}",
    )

    lb_updated = await db.loanbook.find_one({"loanbook_id": lb["loanbook_id"]})
    return {"success": True, "loanbook_id": lb["loanbook_id"], "loanbook": _serialize_lb(lb_updated)}


class PutEntregaBody(BaseModel):
    """Activación canónica del crédito con validación estricta."""
    fecha_entrega: str                      # yyyy-MM-dd — obligatorio
    fecha_primera_cuota: str | None = None  # yyyy-MM-dd — debe ser miércoles
    dia_cobro_especial: str | None = None


@router.put("/{identifier}/entrega")
async def put_entrega(
    identifier: str,
    body: PutEntregaBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Activación canónica: pendiente_entrega → activo + cronograma.

    Validación estricta:
      - 422 si el crédito no está en pendiente_entrega
      - 422 si fecha_primera_cuota no es miércoles
      - 422 si num_cuotas no está configurado
    """
    lb = await _find_lb_by_identifier(db, identifier)

    if lb.get("estado") != "pendiente_entrega":
        raise HTTPException(
            status_code=422,
            detail=f"Solo aplica a créditos en pendiente_entrega (estado actual: '{lb.get('estado')}')",
        )

    try:
        fecha_entrega = date.fromisoformat(body.fecha_entrega)
    except ValueError:
        raise HTTPException(status_code=422, detail="fecha_entrega inválida (use yyyy-MM-dd)")

    if body.fecha_primera_cuota:
        try:
            fpc = date.fromisoformat(body.fecha_primera_cuota)
        except ValueError:
            raise HTTPException(status_code=422, detail="fecha_primera_cuota inválida (use yyyy-MM-dd)")
        if fpc.weekday() != 2:
            raise HTTPException(
                status_code=422,
                detail=f"fecha_primera_cuota debe ser miércoles. '{fpc.isoformat()}' es {fpc.strftime('%A')}",
            )
    else:
        fpc = _next_wednesday_from(fecha_entrega + timedelta(days=7))

    modalidad = lb.get("modalidad", "semanal")
    num_cuotas = lb.get("num_cuotas", 0) or 0
    cuota_monto = lb.get("cuota_monto", 0) or 0

    if num_cuotas <= 0:
        raise HTTPException(
            status_code=422,
            detail="num_cuotas no configurado. Use PUT /{id} para establecer plan_codigo primero.",
        )

    fechas = calcular_cronograma(
        fecha_entrega=fecha_entrega,
        modalidad=modalidad,
        num_cuotas=num_cuotas,
        fecha_primer_pago=fpc,
        dia_cobro_especial=body.dia_cobro_especial,
    )

    cuotas = [
        {"numero": i + 1, "monto": cuota_monto, "estado": "pendiente",
         "fecha": f.isoformat(), "fecha_pago": None, "mora_acumulada": 0}
        for i, f in enumerate(fechas)
    ]

    # Obtener capital_plan de catalogo_planes para calcular saldos correctamente
    plan_codigo_lb2 = lb.get("plan_codigo") or (lb.get("plan") or {}).get("codigo")
    capital_plan_val2: int | None = None
    if plan_codigo_lb2:
        cat_plan2 = await db.catalogo_planes.find_one({"codigo": plan_codigo_lb2})
        if cat_plan2:
            capital_plan_val2 = cat_plan2.get("capital_plan")
    # Fallback RODANTE: capital_plan = monto_original del producto (repuesto/servicio)
    if not capital_plan_val2:
        capital_plan_val2 = lb.get("monto_original") or (cuota_monto * num_cuotas) or 0

    # cuota_estandar_plan: para RDX usa la del loanbook si existe; para RODANTE = cuota_periodica
    cuota_std_val2 = lb.get("cuota_estandar_plan") or int(cuota_monto)

    from services.loanbook.reglas_negocio import calcular_saldos as _calcular_saldos2
    if capital_plan_val2 and num_cuotas:
        _s2 = _calcular_saldos2(int(capital_plan_val2), num_cuotas, int(cuota_monto), 0,
                                cuota_estandar_plan=cuota_std_val2)
        saldo_capital_init2   = _s2["saldo_capital"]
        saldo_intereses_init2 = _s2["saldo_intereses"]
    else:
        saldo_capital_init2   = num_cuotas * cuota_monto
        saldo_intereses_init2 = 0

    await db.loanbook.update_one(
        {"loanbook_id": lb["loanbook_id"]},
        {"$set": {
            "estado": "activo",
            "fecha_entrega": body.fecha_entrega,
            "fecha_primer_pago": fpc.isoformat(),
            "cuotas": cuotas,
            "cuotas_pagadas": 0,
            "cuotas_total": len(cuotas),
            "saldo_capital":       saldo_capital_init2,
            "saldo_pendiente":     saldo_capital_init2,
            "saldo_intereses":     saldo_intereses_init2,
            "capital_plan":        capital_plan_val2 or 0,
            "cuota_estandar_plan": cuota_std_val2,
            "updated_at": now_iso_bogota(),
        }},
    )
    await _recalcular_y_persistir(db, lb["loanbook_id"])
    await _publish_event(
        db, "moto.entregada.canonico", "routers.loanbook.put",
        {"loanbook_id": lb["loanbook_id"], "fecha_entrega": body.fecha_entrega,
         "fecha_primera_cuota": fpc.isoformat()},
        accion=f"Entrega canónica {lb['loanbook_id']}",
    )

    return {
        "success": True,
        "loanbook_id": lb["loanbook_id"],
        "estado": "activo",
        "fecha_entrega": body.fecha_entrega,
        "fecha_primera_cuota": fpc.isoformat(),
        "num_cuotas": len(cuotas),
    }


class PutPagoBody(BaseModel):
    """Registro canónico de pago con waterfall completo."""
    monto_pago: float
    metodo_pago: str = "efectivo"
    fecha_pago: str | None = None           # yyyy-MM-dd
    referencia: str | None = None
    cuota_numero: int | None = None         # apunta a cuota específica (bypass waterfall)


@router.put("/{identifier}/pago")
async def put_pago(
    identifier: str,
    body: PutPagoBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Registro canónico de pago con waterfall ANZI → mora → vencidas → corriente.

    Equivalente canónico del POST /registrar-pago (DEPRECATED).
    Requiere autenticación. Aplica recalcular_loanbook() al final.
    """
    metodo = body.metodo_pago.lower()
    if metodo not in METODOS_PAGO:
        raise HTTPException(status_code=422, detail=f"metodo_pago inválido. Use: {sorted(METODOS_PAGO)}")

    lb = await _find_lb_by_identifier(db, identifier)
    if lb.get("estado") in ("pendiente_entrega", "saldado", "castigado"):
        raise HTTPException(
            status_code=422,
            detail=f"No se puede registrar pago en estado '{lb.get('estado')}'",
        )

    today = today_bogota()
    fecha_pago_str = body.fecha_pago or today.isoformat()
    try:
        fecha_pago = date.fromisoformat(fecha_pago_str)
    except ValueError:
        raise HTTPException(status_code=422, detail="fecha_pago inválida (use yyyy-MM-dd)")

    # Gate: fecha_pago futura es físicamente imposible
    try:
        _validar_fecha_pago(fecha_pago, hoy=today)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    cuotas = lb.get("cuotas", [])
    if not cuotas:
        raise HTTPException(status_code=422, detail="Loanbook sin cuotas — ejecuta PUT /{id}/entrega primero")

    anzi_pct = lb.get("anzi_pct", 0.02) or 0.0
    mora_pendiente = 0
    for c in cuotas:
        if c.get("estado") == "pagada" or not c.get("fecha"):
            continue
        fc = date.fromisoformat(c["fecha"])
        mora = calcular_mora(fc, fecha_pago, MORA_TASA_DIARIA)
        c["mora_acumulada"] = mora
        mora_pendiente += mora

    vencidas_total = sum(
        (c.get("monto") or c.get("monto_total") or 0) for c in cuotas
        if c.get("estado") != "pagada" and c.get("fecha")
        and date.fromisoformat(c["fecha"]) < fecha_pago
    )
    corriente_monto = 0
    for c in cuotas:
        if c.get("estado") == "pagada":
            continue
        if c.get("fecha") and date.fromisoformat(c["fecha"]) >= fecha_pago:
            corriente_monto = (c.get("monto") or c.get("monto_total") or 0)
            break
        if not c.get("fecha"):
            corriente_monto = (c.get("monto") or c.get("monto_total") or 0)
            break

    saldo_capital = lb.get("saldo_capital", 0) or 0
    alloc = aplicar_waterfall(
        monto_pago=body.monto_pago,
        anzi_pct=anzi_pct,
        mora_pendiente=mora_pendiente,
        cuotas_vencidas_total=vencidas_total,
        cuota_corriente=corriente_monto,
        saldo_capital=saldo_capital,
    )

    pago_parcial = False
    if body.cuota_numero is not None:
        target = next((c for c in cuotas if c.get("numero") == body.cuota_numero), None)
        if target is None:
            raise HTTPException(status_code=404, detail=f"Cuota #{body.cuota_numero} no encontrada")
        if target.get("estado") == "pagada":
            raise HTTPException(status_code=409, detail=f"Cuota #{body.cuota_numero} ya está pagada")
        pago_parcial = body.monto_pago < target["monto"]
        target.update({"estado": "pagada", "fecha_pago": fecha_pago_str,
                        "mora_acumulada": 0, "metodo_pago": metodo, "referencia": body.referencia})
    else:
        rem_venc = alloc["vencidas"]
        rem_corr = alloc["corriente"]
        for c in cuotas:
            if c.get("estado") == "pagada":
                continue
            if c.get("fecha"):
                fc = date.fromisoformat(c["fecha"])
                if fc < fecha_pago and rem_venc >= (c.get("monto") or c.get("monto_total") or 0):
                    c.update({"estado": "pagada", "fecha_pago": fecha_pago_str,
                               "mora_acumulada": 0, "metodo_pago": metodo, "referencia": body.referencia})
                    rem_venc -= (c.get("monto") or c.get("monto_total") or 0)
                    continue
                if fc >= fecha_pago and rem_corr >= (c.get("monto") or c.get("monto_total") or 0):
                    c.update({"estado": "pagada", "fecha_pago": fecha_pago_str,
                               "mora_acumulada": 0, "metodo_pago": metodo, "referencia": body.referencia})
                    rem_corr -= (c.get("monto") or c.get("monto_total") or 0)
                    break
            elif rem_corr >= (c.get("monto") or c.get("monto_total") or 0):
                c.update({"estado": "pagada", "fecha_pago": fecha_pago_str,
                           "metodo_pago": metodo, "referencia": body.referencia})
                rem_corr -= (c.get("monto") or c.get("monto_total") or 0)
                break

    cuotas_pagadas = sum(1 for c in cuotas if c.get("estado") == "pagada")
    new_saldo = max(saldo_capital - alloc["corriente"] - alloc["vencidas"] - alloc["capital"], 0)
    nuevo_estado = "saldado" if new_saldo == 0 and cuotas_pagadas == len(cuotas) else estado_from_dpd(calcular_dpd(cuotas, fecha_pago))

    await db.loanbook.update_one(
        {"loanbook_id": lb["loanbook_id"]},
        {"$set": {
            "cuotas": cuotas,
            "saldo_capital": new_saldo,
            "saldo_pendiente": new_saldo,
            "total_pagado": (lb.get("total_pagado", 0) or 0) + body.monto_pago,
            "total_mora_pagada": (lb.get("total_mora_pagada", 0) or 0) + alloc["mora"],
            "total_anzi_pagado": (lb.get("total_anzi_pagado", 0) or 0) + alloc["anzi"],
            "cuotas_pagadas": cuotas_pagadas,
            "estado": nuevo_estado,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    await _recalcular_y_persistir(db, lb["loanbook_id"])
    await _publish_event(
        db, "pago.cuota.canonico", "routers.loanbook.put",
        {"loanbook_id": lb["loanbook_id"], "monto_pago": body.monto_pago,
         "fecha_pago": fecha_pago_str, "desglose": alloc, "cuota_numero": body.cuota_numero},
        accion=f"Pago canónico ${body.monto_pago:,.0f} {lb.get('vin') or lb['loanbook_id']}",
    )

    return {
        "success": True,
        "loanbook_id": lb["loanbook_id"],
        "nuevo_saldo": new_saldo,
        "nuevo_estado": nuevo_estado,
        "cuotas_pagadas": cuotas_pagadas,
        "desglose": alloc,
        "pago_parcial": pago_parcial,
    }


# ─────────────────────── B2: DPD scheduler + estado historial ────────────────

@router.post("/recalcular-dpd")
async def recalcular_dpd_manual(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Trigger manual del scheduler DPD.

    Recalcula DPD, estado, sub_bucket_semanal y mora_acumulada_cop en todos
    los loanbooks activos. Equivalente a la ejecución automática de las 06:00 AM.
    Requiere autenticación.
    """
    from services.loanbook.dpd_scheduler import calcular_dpd_todos
    stats = await calcular_dpd_todos(db)
    return {"ok": True, "stats": stats}


@router.get("/{codigo}/estado-historial")
async def estado_historial(
    codigo: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Historial de transiciones de estado para un loanbook.

    Lee desde loanbook_modificaciones los cambios de estado y las
    transiciones inválidas detectadas por el scheduler DPD.
    Ordenado por timestamp descendente (más reciente primero).
    """
    docs = await db.loanbook_modificaciones.find(
        {
            "loanbook_codigo": codigo,
            "tipo": {"$in": ["cambio_estado", "transicion_invalida"]},
        }
    ).sort("ts", -1).to_list(length=100)

    historial = [{k: v for k, v in d.items() if k != "_id"} for d in docs]
    return {"codigo": codigo, "total": len(historial), "historial": historial}


@router.get("/{codigo}/calcular-liquidacion")
async def calcular_liquidacion(
    codigo: str,
    fecha_liquidacion: date,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Proyecta el monto exacto para saldar anticipadamente un loanbook.

    Retorna:
      - saldo_capital: capital pendiente
      - mora_acumulada: mora acumulada a la fecha
      - monto_liquidacion: total a pagar (capital + mora)
      - cuotas_pendientes_valor: valor nominal de cuotas restantes
      - descuento_intereses_futuros: ahorro por pagar anticipado

    Requiere autenticación.
    """
    from services.loanbook.amortizacion_service import calcular_liquidacion_anticipada

    lb = await _find_lb_by_identifier(db, codigo)

    resultado = calcular_liquidacion_anticipada(lb, fecha_liquidacion)
    return resultado


@router.post("/{codigo}/generar-cronograma")
async def generar_cronograma_endpoint(
    codigo: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Genera y persiste el cronograma de amortización real para un loanbook.

    Calcula monto_capital + monto_interes por cuota usando amortización francesa.
    Solo actúa si el loanbook no tiene aún el desglose capital/interés.

    Requiere autenticación.
    """
    from services.loanbook.amortizacion_service import generar_cronograma as _gen_cron

    lb = await _find_lb_by_identifier(db, codigo)

    # fecha_entrega: campo top-level (seteado por registrar-entrega) con
    # fallback al subdocumento fechas.entrega (seteado por PATCH)
    fechas = lb.get("fechas") or {}
    fecha_entrega_raw = lb.get("fecha_entrega") or fechas.get("entrega")
    if not fecha_entrega_raw:
        raise HTTPException(
            status_code=422,
            detail="Loanbook sin fecha_entrega — ejecuta registrar-entrega primero",
        )

    try:
        fecha_entrega = date.fromisoformat(str(fecha_entrega_raw)[:10])
    except ValueError:
        raise HTTPException(status_code=422, detail=f"fecha_entrega inválida: {fecha_entrega_raw}")

    saldo = float(lb.get("saldo_capital") or lb.get("saldo_pendiente") or 0)
    if saldo <= 0:
        raise HTTPException(status_code=422, detail="saldo debe ser > 0 para generar cronograma")

    # Campos reales del schema: cuota_monto (top-level), modalidad (top-level),
    # num_cuotas (top-level) — igual que usa registrar-entrega
    cuota_p = float(lb.get("cuota_monto") or lb.get("cuota_periodica") or 0)
    tasa = float(lb.get("tasa_ea") or 0)
    modalidad = lb.get("modalidad") or lb.get("modalidad_pago") or "semanal"
    n = int(lb.get("num_cuotas") or lb.get("total_cuotas") or len(lb.get("cuotas") or []) or 0)
    if n <= 0:
        raise HTTPException(status_code=422, detail="num_cuotas debe ser > 0")

    try:
        nuevas_cuotas = _gen_cron(
            saldo_inicial=saldo,
            cuota_periodica=cuota_p,
            tasa_ea=tasa,
            modalidad=modalidad,
            fecha_entrega=fecha_entrega,
            n_cuotas=n,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    await db.loanbook.update_one(
        {"_id": lb["_id"]},
        {"$set": {"cuotas": nuevas_cuotas, "updated_at": now_iso_bogota()}},
    )

    return {"ok": True, "loanbook_id": lb["loanbook_id"], "cuotas_generadas": len(nuevas_cuotas)}


# ─────────────────────── B5: Edición manual ──────────────────────────────────

_CAMPOS_PROTEGIDOS = frozenset({"_id", "loanbook_id", "loanbook_codigo", "cuotas", "estado"})


def _serialize_lb(lb: dict) -> dict:
    """Serializa loanbook convirtiendo datetime/ObjectId a tipos JSON-safe.

    Equivalente a _clean_doc pero recursivo: maneja campos anidados (cuotas,
    comprobantes, fechas) que Motor puede retornar como datetime nativo.
    """
    if not lb:
        return {}
    return {k: _serialize_value(v) for k, v in lb.items() if k != "_id"}


@router.patch("/{codigo}/editar")
async def editar_loanbook(
    codigo: str,
    campos: dict = Body(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Edita campos del loanbook (excepto campos protegidos). Persiste en MongoDB
    y registra audit log en loanbook_modificaciones por cada campo modificado.
    """
    from services.loanbook.loanbook_service import registrar_modificacion

    campos_filtrados = {k: v for k, v in campos.items() if k not in _CAMPOS_PROTEGIDOS}
    if not campos_filtrados:
        raise HTTPException(status_code=400, detail="No hay campos válidos para actualizar")

    # Búsqueda robusta: loanbook_id → loanbook_codigo → vin
    lb = await db.loanbook.find_one({
        "$or": [
            {"loanbook_id": codigo},
            {"loanbook_codigo": codigo},
            {"vin": codigo},
        ]
    })
    if not lb:
        raise HTTPException(status_code=404, detail=f"Loanbook '{codigo}' no encontrado")

    campos_filtrados["updated_at"] = now_iso_bogota()

    result = await db.loanbook.update_one(
        {"_id": lb["_id"]},
        {"$set": campos_filtrados},
    )
    logger.info(
        "[EDITAR] %s: matched=%d modified=%d campos=%s",
        codigo, result.matched_count, result.modified_count,
        list(k for k in campos_filtrados if k != "updated_at"),
    )

    user_id = current_user.get("id") or current_user.get("sub") or "admin"
    lb_id = lb.get("loanbook_id") or codigo
    for campo, valor_nuevo in campos_filtrados.items():
        if campo == "updated_at":
            continue
        try:
            await registrar_modificacion(
                db, lb_id, campo, lb.get(campo), valor_nuevo, user_id, "Edición manual"
            )
        except Exception as exc:
            logger.warning("[EDITAR] audit log falló para %s.%s: %s", lb_id, campo, exc)

    lb_actualizado = await db.loanbook.find_one({"_id": lb["_id"]})
    return {
        "ok": True,
        "matched": result.matched_count,
        "modified": result.modified_count,
        "campos_actualizados": [k for k in campos_filtrados if k != "updated_at"],
        "loanbook": _serialize_lb(lb_actualizado),
    }


# ─────────────────────── B5: Comprobantes de pago ────────────────────────────

import base64  # noqa: E402 — grouped with feature for readability
from fastapi import UploadFile, File

_FECHA_MINIMA_COMPROBANTE = date(2026, 4, 22)
_TIPOS_PERMITIDOS = {"image/jpeg", "image/png", "application/pdf"}
_LIMITES_BYTES = {"image/jpeg": 2 * 1024 * 1024, "image/png": 2 * 1024 * 1024, "application/pdf": 5 * 1024 * 1024}


@router.post("/{codigo}/cuotas/{numero_cuota}/comprobante")
async def subir_comprobante(
    codigo: str,
    numero_cuota: int,
    file: UploadFile = File(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Sube comprobante de pago (JPEG/PNG/PDF) para una cuota.
    Solo aplica a cuotas con fecha_programada >= 2026-04-22.
    Se almacena como base64 dentro del documento de la cuota en MongoDB.
    """
    if file.content_type not in _TIPOS_PERMITIDOS:
        raise HTTPException(
            status_code=422,
            detail=f"Tipo no permitido: {file.content_type}. Acepta: JPEG, PNG, PDF",
        )

    contenido = await file.read()
    limite = _LIMITES_BYTES.get(file.content_type, 2 * 1024 * 1024)
    if len(contenido) > limite:
        raise HTTPException(
            status_code=422,
            detail=f"Archivo muy grande. Máximo {limite // (1024 * 1024)}MB para {file.content_type}",
        )

    lb = await _find_lb_by_identifier(db, codigo)
    cuotas = lb.get("cuotas") or []
    cuota_idx = next((i for i, c in enumerate(cuotas) if c.get("numero") == numero_cuota), None)
    if cuota_idx is None:
        raise HTTPException(status_code=404, detail=f"Cuota {numero_cuota} no encontrada")

    cuota = cuotas[cuota_idx]

    # Validar fecha mínima
    fecha_prog_raw = cuota.get("fecha_programada") or cuota.get("fecha")
    if fecha_prog_raw:
        try:
            fecha_prog = date.fromisoformat(str(fecha_prog_raw)[:10])
            if fecha_prog < _FECHA_MINIMA_COMPROBANTE:
                raise HTTPException(
                    status_code=422,
                    detail="Los comprobantes solo aplican a cuotas desde el 22 de abril de 2026",
                )
        except ValueError:
            pass  # fecha inválida — no bloquear

    comprobante_b64 = base64.b64encode(contenido).decode("utf-8")
    user_id = current_user.get("id") or current_user.get("sub") or "admin"

    await db.loanbook.update_one(
        {"_id": lb["_id"]},
        {
            "$set": {
                f"cuotas.{cuota_idx}.comprobante": {
                    "filename": file.filename,
                    "content_type": file.content_type,
                    "data_b64": comprobante_b64,
                    "uploaded_at": now_iso_bogota(),
                    "uploaded_by": user_id,
                    "size_bytes": len(contenido),
                },
                "updated_at": now_iso_bogota(),
            }
        },
    )

    return {
        "ok": True,
        "cuota": numero_cuota,
        "filename": file.filename,
        "tipo": file.content_type,
        "size_kb": round(len(contenido) / 1024, 1),
    }


@router.get("/{codigo}/cuotas/{numero_cuota}/comprobante")
async def obtener_comprobante(
    codigo: str,
    numero_cuota: int,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Obtiene el comprobante de pago de una cuota (base64)."""
    lb = await _find_lb_by_identifier(db, codigo)
    cuotas = lb.get("cuotas") or []
    cuota = next((c for c in cuotas if c.get("numero") == numero_cuota), None)
    if not cuota or not cuota.get("comprobante"):
        raise HTTPException(status_code=404, detail="Esta cuota no tiene comprobante")

    comp = cuota["comprobante"]
    uploaded_at = comp.get("uploaded_at")
    if hasattr(uploaded_at, "isoformat"):
        uploaded_at = uploaded_at.isoformat()

    return {
        "filename": comp["filename"],
        "content_type": comp["content_type"],
        "data_b64": comp["data_b64"],
        "uploaded_at": uploaded_at,
        "size_kb": round(comp.get("size_bytes", 0) / 1024, 1),
    }


# ───────────────────────────────────────────────────────────────────────────
# B11: Backlog pagos pendientes de revisar (OCR comprobantes WhatsApp)
# ───────────────────────────────────────────────────────────────────────────

@router.get("/pagos-revisar")
async def listar_pagos_revisar(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Lista comprobantes WhatsApp que el OCR no pudo aplicar automáticamente.

    Casos típicos:
    - Match score < 0.75 (cliente ambiguo)
    - OCR baja confianza
    - Beneficiario no es RODDOS
    - Múltiples loanbooks con mismo monto exacto
    """
    cursor = db.backlog_pagos_revisar.find(
        {"estado": "pendiente_revision"}
    ).sort("fecha", -1).limit(200)
    items = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        # Limpiar fechas serializables
        if hasattr(doc.get("fecha"), "isoformat"):
            doc["fecha"] = doc["fecha"].isoformat()
        items.append(doc)
    return {"count": len(items), "pagos": items}


class ConfirmarPagoExtraidoBody(BaseModel):
    backlog_id: str
    loanbook_id: str
    monto: int | None = None  # opcional: si no se pasa, usa el del comprobante
    fecha_pago: str | None = None
    metodo: str = "Transferencia"
    banco: str = ""
    referencia: str = ""


@router.post("/pagos-revisar/confirmar")
async def confirmar_pago_extraido(
    body: ConfirmarPagoExtraidoBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Confirma manualmente un pago del backlog y lo aplica al loanbook
    indicado, publicando cuota.pagada para que el Contador cree el journal."""
    from bson import ObjectId
    try:
        oid = ObjectId(body.backlog_id)
    except Exception:
        raise HTTPException(400, "backlog_id invalido")

    backlog = await db.backlog_pagos_revisar.find_one({"_id": oid})
    if not backlog:
        raise HTTPException(404, "backlog item no existe")
    if backlog.get("estado") != "pendiente_revision":
        raise HTTPException(409, f"backlog ya en estado {backlog.get('estado')}")

    extraccion = backlog.get("extraccion") or {}
    monto = body.monto or extraccion.get("monto_cop", 0)
    fecha_pago = body.fecha_pago or extraccion.get("fecha", "")
    referencia = body.referencia or extraccion.get("referencia", "")
    banco_origen = body.banco or extraccion.get("banco_origen", "")

    if not monto or not fecha_pago:
        raise HTTPException(400, "monto y fecha_pago obligatorios")

    lb = await db.loanbook.find_one({"loanbook_id": body.loanbook_id})
    if not lb:
        raise HTTPException(404, f"loanbook {body.loanbook_id} no existe")

    # Re-publicar evento comprobante.pago.recibido apuntando al loanbook correcto
    # via override manual. El handler comprobante toma datos de extraccion.
    cliente_block = lb.get("cliente") or {}
    await _publish_event(
        db,
        "pago.cuota.recibido.manual",
        "routers.loanbook.pagos_revisar",
        {
            "loanbook_id":      body.loanbook_id,
            "cliente_cedula":   cliente_block.get("cedula") or lb.get("cliente_cedula"),
            "cliente_nombre":   cliente_block.get("nombre") or lb.get("cliente_nombre"),
            "monto":            int(monto),
            "fecha_pago":       fecha_pago,
            "metodo":           body.metodo,
            "banco_origen":     banco_origen,
            "referencia":       referencia,
            "via":              "backlog_manual",
            "backlog_id":       body.backlog_id,
            "extraccion":       extraccion,
        },
        accion=f"Confirmacion manual pago ${monto:,} → {body.loanbook_id}",
    )

    # Marcar backlog como resuelto
    await db.backlog_pagos_revisar.update_one(
        {"_id": oid},
        {"$set": {
            "estado":        "aplicado_manual",
            "loanbook_id":   body.loanbook_id,
            "monto_final":   int(monto),
            "fecha_aplicado": fecha_pago,
            "resolved_by":   "admin",
        }},
    )

    return {
        "success":        True,
        "backlog_id":     body.backlog_id,
        "loanbook_id":    body.loanbook_id,
        "monto_aplicado": int(monto),
        "mensaje":        "Pago aplicado manualmente. Saldo actualizado.",
    }


@router.post("/pagos-revisar/rechazar")
async def rechazar_pago_backlog(
    body: dict,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Rechaza un comprobante del backlog (ej: no es RODDOS, duplicado, etc.)."""
    from bson import ObjectId
    backlog_id = body.get("backlog_id", "")
    motivo = body.get("motivo", "rechazado_admin")
    try:
        oid = ObjectId(backlog_id)
    except Exception:
        raise HTTPException(400, "backlog_id invalido")
    res = await db.backlog_pagos_revisar.update_one(
        {"_id": oid},
        {"$set": {"estado": "rechazado", "motivo_rechazo": motivo}},
    )
    return {"success": res.modified_count > 0, "backlog_id": backlog_id}


# ───────────────────────────────────────────────────────────────────────────
# L5/B6: Revisor cobranza jueves — endpoints manuales (preview + run on-demand)
# ───────────────────────────────────────────────────────────────────────────

@router.get("/cobranza-jueves/preview")
async def preview_cobranza_jueves(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Preview del análisis cartera + cola priorizada SIN enviar email.
    Útil para revisar cómo quedaría el reporte antes de jueves 8AM."""
    from services.cobranza.cartera_revisor import analizar_cartera
    return await analizar_cartera(db)


@router.post("/cobranza-jueves/run")
async def ejecutar_cobranza_jueves_now(
    body: dict | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Ejecuta el revisor cobranza inmediatamente (no espera al jueves 8AM).
    Body opcional: {"dry_run": true} para no enviar email/WhatsApp."""
    from services.cobranza.scheduler_jueves import ejecutar_revisor_jueves
    dry_run = bool((body or {}).get("dry_run", False))
    return await ejecutar_revisor_jueves(db, dry_run=dry_run)


@router.get("/cobranza-jueves/preview-html", response_class=Response)
async def preview_html_reporte(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Devuelve el HTML del reporte semanal para previsualizar en navegador.

    Resiliente: si el análisis falla, devuelve HTML con el error visible
    (no 500 con body vacío que aparece "en blanco" en el navegador).
    """
    import traceback
    try:
        from services.cobranza.cartera_revisor import analizar_cartera
        from services.email.reportes_jueves import construir_html_reporte
        analisis = await analizar_cartera(db)
        html = construir_html_reporte(analisis)
        return Response(content=html, media_type="text/html; charset=utf-8")
    except Exception as e:
        tb = traceback.format_exc()
        logger.exception("preview-html falló")
        error_html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Preview error</title>
<style>body{{font-family:monospace;padding:24px;background:#fef2f2;color:#7f1d1d;}}
pre{{background:#fff;padding:16px;border-radius:8px;border:1px solid #fecaca;overflow:auto;}}
h1{{color:#dc2626;}}</style></head><body>
<h1>Error generando reporte cobranza-jueves</h1>
<p><strong>{type(e).__name__}:</strong> {str(e)}</p>
<pre>{tb}</pre>
<hr><p>Si ves esto significa que el endpoint funciona pero falla el análisis. Revisa logs.</p>
</body></html>"""
        return Response(content=error_html, media_type="text/html; charset=utf-8", status_code=500)


# ───────────────────────────────────────────────────────────────────────────
# CRM-GAP: diagnóstico y reconciliación CRM ↔ loanbook
# ───────────────────────────────────────────────────────────────────────────

@router.get("/diagnostico/crm-gap")
async def diagnostico_crm_gap(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Audita gap entre loanbook y crm_clientes.

    Returns JSON con:
    - clientes_en_loanbook: cédulas únicas de loanbooks activos
    - clientes_en_crm: cédulas en crm_clientes
    - faltantes_en_crm: en loanbook pero NO en crm_clientes (← bug que rompe RADAR)
    - phone_desincronizado: en ambos pero teléfono difiere
    - sin_telefono_loanbook: loanbooks activos sin teléfono cliente
    """
    estados_excluir = {"saldado", "Pagado", "castigado", "ChargeOff"}

    loanbooks_clientes = {}
    sin_telefono = []
    async for lb in db.loanbook.find({}):
        if lb.get("estado") in estados_excluir:
            continue
        cli = lb.get("cliente") or {}
        ced = (cli.get("cedula") or lb.get("cliente_cedula") or "").strip()
        if not ced:
            continue
        nombre = cli.get("nombre") or lb.get("cliente_nombre") or ""
        tel = cli.get("telefono") or lb.get("cliente_telefono") or ""
        loanbooks_clientes[ced] = {
            "nombre": nombre,
            "telefono": tel,
            "loanbook_id": lb.get("loanbook_id", ""),
            "estado": lb.get("estado", ""),
        }
        if not tel:
            sin_telefono.append({
                "cedula": ced, "nombre": nombre,
                "loanbook_id": lb.get("loanbook_id", "")
            })

    crm_clientes_dict = {}
    async for c in db.crm_clientes.find({}):
        ced = (c.get("cedula") or "").strip()
        if ced:
            crm_clientes_dict[ced] = {
                "nombre": c.get("nombre") or "",
                "telefono": c.get("telefono") or c.get("mercately_phone") or "",
            }

    faltantes = []
    desincronizados = []
    for ced, lb_data in loanbooks_clientes.items():
        if ced not in crm_clientes_dict:
            faltantes.append({"cedula": ced, **lb_data})
        else:
            crm_data = crm_clientes_dict[ced]
            tel_lb = (lb_data["telefono"] or "").strip()
            tel_crm = (crm_data["telefono"] or "").strip()
            # Solo flagear si ambos tienen tel y difieren significativamente
            if tel_lb and tel_crm:
                # Normalizar para comparar (quitar +57, espacios, guiones)
                norm_lb = "".join(c for c in tel_lb if c.isdigit())[-10:]
                norm_crm = "".join(c for c in tel_crm if c.isdigit())[-10:]
                if norm_lb and norm_crm and norm_lb != norm_crm:
                    desincronizados.append({
                        "cedula": ced,
                        "nombre": lb_data["nombre"],
                        "telefono_loanbook": tel_lb,
                        "telefono_crm": tel_crm,
                        "loanbook_id": lb_data["loanbook_id"],
                    })

    return {
        "total_loanbook_activos_unicos": len(loanbooks_clientes),
        "total_crm_clientes": len(crm_clientes_dict),
        "faltantes_en_crm_count": len(faltantes),
        "phone_desincronizado_count": len(desincronizados),
        "sin_telefono_en_loanbook_count": len(sin_telefono),
        "faltantes_en_crm": faltantes,
        "phone_desincronizado": desincronizados,
        "sin_telefono_en_loanbook": sin_telefono,
    }


@router.post("/diagnostico/crm-reconciliar")
async def diagnostico_crm_reconciliar(
    body: dict | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Reconcilia crm_clientes contra loanbook (loanbook = source of truth para clientes activos).

    Body opcional: {"dry_run": true} → solo muestra qué haría, no escribe.
    Default: dry_run=true (seguro).

    Para cada cliente en loanbook activo:
    - Si NO existe en crm_clientes → crear con datos del loanbook
    - Si existe pero phone difiere → actualizar phone (loanbook gana)
    - Si tiene loanbooks[] sin el loanbook_id actual → agregarlo
    """
    from datetime import datetime, timezone
    from core.crm_model import crear_cliente_doc

    dry_run = bool((body or {}).get("dry_run", True))
    estados_excluir = {"saldado", "Pagado", "castigado", "ChargeOff"}

    creados = []
    actualizados_phone = []
    loanbook_ids_agregados = []
    errores = []

    async for lb in db.loanbook.find({}):
        if lb.get("estado") in estados_excluir:
            continue
        cli = lb.get("cliente") or {}
        ced = (cli.get("cedula") or lb.get("cliente_cedula") or "").strip()
        if not ced:
            continue
        lb_id = lb.get("loanbook_id", "")
        nombre = cli.get("nombre") or lb.get("cliente_nombre") or ""
        tel = cli.get("telefono") or lb.get("cliente_telefono") or ""
        email = cli.get("email") or lb.get("cliente_email") or ""
        direccion = cli.get("direccion") or lb.get("cliente_direccion") or ""

        try:
            existing = await db.crm_clientes.find_one({"cedula": ced})
            if not existing:
                if not dry_run:
                    doc = crear_cliente_doc(
                        cedula=ced, nombre=nombre, telefono=tel,
                        email=email, direccion=direccion,
                    )
                    doc["loanbooks"] = [lb_id] if lb_id else []
                    doc["fuente"] = "reconciliar_crm_2026-04-29"
                    await db.crm_clientes.insert_one(doc)
                creados.append({"cedula": ced, "nombre": nombre, "telefono": tel, "loanbook_id": lb_id})
            else:
                update_set = {}
                # Phone update si difiere — defensivo: telefono puede venir int en BD legacy
                tel_existing_raw = existing.get("telefono") or ""
                tel_existing = str(tel_existing_raw).strip() if tel_existing_raw else ""
                tel_normalized = str(tel).strip() if tel else ""
                if tel_normalized and tel_normalized != tel_existing:
                    if not dry_run:
                        update_set["telefono"] = tel_normalized
                        update_set["telefono_actualizado_at"] = datetime.now(timezone.utc).isoformat()
                    actualizados_phone.append({
                        "cedula": ced, "nombre": nombre,
                        "telefono_anterior": tel_existing, "telefono_nuevo": tel_normalized,
                    })
                # Agregar loanbook_id si falta — defensivo: loanbooks puede venir int/str/None en BD legacy
                lb_array_raw = existing.get("loanbooks")
                if isinstance(lb_array_raw, list):
                    lb_array = lb_array_raw
                elif lb_array_raw:
                    # Legacy: era un solo valor, no array. Lo convertimos
                    lb_array = [str(lb_array_raw)]
                else:
                    lb_array = []
                if lb_id and lb_id not in lb_array:
                    if not dry_run:
                        # Si el campo era no-array, primero lo reseteamos a array válido
                        if not isinstance(lb_array_raw, list):
                            await db.crm_clientes.update_one(
                                {"cedula": ced},
                                {"$set": {"loanbooks": lb_array}},
                            )
                        await db.crm_clientes.update_one(
                            {"cedula": ced},
                            {"$addToSet": {"loanbooks": lb_id}},
                        )
                    loanbook_ids_agregados.append({"cedula": ced, "loanbook_id": lb_id})
                if update_set and not dry_run:
                    update_set["updated_at"] = datetime.now(timezone.utc).isoformat()
                    await db.crm_clientes.update_one({"cedula": ced}, {"$set": update_set})
        except Exception as e:
            errores.append({
                "cedula": ced, "loanbook_id": lb_id,
                "error": f"{type(e).__name__}: {e}",
                "telefono_tipo": type(existing.get("telefono") if existing else None).__name__,
                "loanbooks_tipo": type(existing.get("loanbooks") if existing else None).__name__,
            })

    return {
        "dry_run": dry_run,
        "creados_count": len(creados),
        "phones_actualizados_count": len(actualizados_phone),
        "loanbook_ids_agregados_count": len(loanbook_ids_agregados),
        "errores_count": len(errores),
        "creados": creados,
        "phones_actualizados": actualizados_phone,
        "loanbook_ids_agregados": loanbook_ids_agregados,
        "errores": errores,
    }


@router.post("/diagnostico/crm-cleanup-legacy")
async def diagnostico_crm_cleanup_legacy(
    body: dict | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Limpia entradas basura en crm_clientes.loanbooks[].

    Remueve cualquier entrada del array que NO matchee el patrón LB-YYYY-NNNN.
    Esto repara los docs donde 'loanbooks' era un int legacy (ej: 1, 2)
    que se convirtió a string durante el reconciliar.

    Body opcional: {"dry_run": true} → solo muestra qué haría.
    Default: dry_run=true.
    """
    import re
    PATRON_LB = re.compile(r"^LB-\d{4}-\d{4}$")
    dry_run = bool((body or {}).get("dry_run", True))

    limpiados = []
    sin_cambios = []
    errores = []

    async for c in db.crm_clientes.find({}):
        ced = c.get("cedula", "")
        nombre = c.get("nombre", "")
        lb_array = c.get("loanbooks")
        if not isinstance(lb_array, list):
            # No-array: convertir a array vacio si no es lista
            if lb_array is None:
                continue
            try:
                if not dry_run:
                    await db.crm_clientes.update_one(
                        {"_id": c["_id"]},
                        {"$set": {"loanbooks": []}},
                    )
                limpiados.append({
                    "cedula": ced, "nombre": nombre,
                    "antes": str(lb_array), "despues": [],
                    "tipo_anterior": type(lb_array).__name__,
                })
            except Exception as e:
                errores.append({"cedula": ced, "error": str(e)})
            continue

        validos = [x for x in lb_array if isinstance(x, str) and PATRON_LB.match(x)]
        if len(validos) != len(lb_array):
            invalidos = [x for x in lb_array if not (isinstance(x, str) and PATRON_LB.match(x))]
            try:
                if not dry_run:
                    await db.crm_clientes.update_one(
                        {"_id": c["_id"]},
                        {"$set": {"loanbooks": validos}},
                    )
                limpiados.append({
                    "cedula": ced, "nombre": nombre,
                    "antes": lb_array, "despues": validos,
                    "removidos": invalidos,
                })
            except Exception as e:
                errores.append({"cedula": ced, "error": str(e)})
        else:
            sin_cambios.append(ced)

    return {
        "dry_run": dry_run,
        "limpiados_count": len(limpiados),
        "sin_cambios_count": len(sin_cambios),
        "errores_count": len(errores),
        "limpiados": limpiados,
        "errores": errores,
    }


@router.get("/diagnostico/crm-html", response_class=Response)
async def diagnostico_crm_html(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Versión HTML visual del diagnóstico CRM-gap (abrir en navegador)."""
    import traceback
    try:
        gap = await diagnostico_crm_gap(db)
        rows_falt = "".join(
            f"<tr><td>{c['cedula']}</td><td>{c['nombre']}</td><td>{c['telefono'] or '<em>sin tel</em>'}</td><td>{c['loanbook_id']}</td><td><span style='color:#dc2626'>FALTANTE</span></td></tr>"
            for c in gap["faltantes_en_crm"]
        )
        rows_des = "".join(
            f"<tr><td>{c['cedula']}</td><td>{c['nombre']}</td><td>{c['telefono_loanbook']}</td><td>{c['telefono_crm']}</td><td>{c['loanbook_id']}</td></tr>"
            for c in gap["phone_desincronizado"]
        )
        rows_st = "".join(
            f"<tr><td>{c['cedula']}</td><td>{c['nombre']}</td><td>{c['loanbook_id']}</td></tr>"
            for c in gap["sin_telefono_en_loanbook"]
        )
        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>CRM Gap Audit</title>
<style>body{{font-family:-apple-system,'Segoe UI',sans-serif;padding:24px;background:#f6f3f2;color:#1f2937;max-width:1200px;margin:0 auto;}}
h1{{color:#006e2a;}}h2{{margin-top:32px;color:#1f2937;}}
.card{{background:white;padding:16px;border-radius:8px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,0.06);}}
.metric{{display:inline-block;margin-right:24px;}}.metric-val{{font-size:28px;font-weight:600;color:#006e2a;}}
.metric-bad{{color:#dc2626;}}table{{width:100%;border-collapse:collapse;margin-top:8px;}}
th,td{{padding:8px 12px;text-align:left;border-bottom:1px solid #e5e7eb;font-size:13px;}}
th{{background:#f9fafb;text-transform:uppercase;font-size:11px;color:#6b7280;}}
.warn{{background:#fef3c7;padding:12px 16px;border-left:4px solid #f59e0b;border-radius:4px;}}
button{{background:#006e2a;color:white;border:none;padding:10px 20px;border-radius:6px;cursor:pointer;font-weight:600;margin-right:8px;}}
button:hover{{background:#004d1d;}}.btn-danger{{background:#dc2626;}}.btn-danger:hover{{background:#991b1b;}}
code{{background:#f3f4f6;padding:2px 6px;border-radius:4px;font-family:monospace;}}
</style></head><body>
<h1>📊 Auditoría CRM ↔ Loanbook</h1>
<div class="card">
  <span class="metric"><div>Loanbooks activos (clientes únicos)</div><div class="metric-val">{gap['total_loanbook_activos_unicos']}</div></span>
  <span class="metric"><div>Total clientes en CRM</div><div class="metric-val">{gap['total_crm_clientes']}</div></span>
  <span class="metric"><div>Faltantes en CRM</div><div class="metric-val metric-bad">{gap['faltantes_en_crm_count']}</div></span>
  <span class="metric"><div>Phones desincronizados</div><div class="metric-val metric-bad">{gap['phone_desincronizado_count']}</div></span>
  <span class="metric"><div>Sin tel en Loanbook</div><div class="metric-val metric-bad">{gap['sin_telefono_en_loanbook_count']}</div></span>
</div>

{('<div class="warn"><strong>⚠️ Acción requerida:</strong> hay '+str(gap['faltantes_en_crm_count'])+' clientes activos en loanbook que NO existen en crm_clientes. Esto rompe RADAR (alertas WhatsApp) y el OCR matcher.</div>') if gap['faltantes_en_crm_count'] else '<p style="color:#10b981">✅ Todos los clientes loanbook están en crm_clientes.</p>'}

<h2>🔧 Reconciliar (poblar/actualizar crm_clientes desde loanbook)</h2>
<div class="card">
  <p>Loanbook es la fuente de verdad. Esta acción:</p>
  <ol><li>Crea en <code>crm_clientes</code> los clientes que solo están en loanbook</li>
  <li>Actualiza el teléfono en <code>crm_clientes</code> si difiere del loanbook</li>
  <li>Agrega <code>loanbook_id</code> al array <code>loanbooks[]</code> del cliente CRM si falta</li></ol>
  <p>
    <button onclick="reconciliar(true)">🔍 DRY-RUN (solo simular)</button>
    <button class="btn-danger" onclick="reconciliar(false)">🚀 EJECUTAR (escribe a la BD)</button>
  </p>
  <pre id="result" style="background:#1f2937;color:#10b981;padding:12px;border-radius:6px;display:none;max-height:300px;overflow:auto;"></pre>
</div>

<h2>❌ Faltantes en CRM ({gap['faltantes_en_crm_count']})</h2>
<table><thead><tr><th>Cédula</th><th>Nombre</th><th>Teléfono</th><th>Loanbook ID</th><th>Estado</th></tr></thead><tbody>{rows_falt or '<tr><td colspan=5 style=text-align:center>Ninguno ✅</td></tr>'}</tbody></table>

<h2>⚠️ Phones desincronizados ({gap['phone_desincronizado_count']})</h2>
<table><thead><tr><th>Cédula</th><th>Nombre</th><th>Tel en Loanbook</th><th>Tel en CRM</th><th>Loanbook ID</th></tr></thead><tbody>{rows_des or '<tr><td colspan=5 style=text-align:center>Ninguno ✅</td></tr>'}</tbody></table>

<h2>📵 Sin teléfono en Loanbook ({gap['sin_telefono_en_loanbook_count']})</h2>
<table><thead><tr><th>Cédula</th><th>Nombre</th><th>Loanbook ID</th></tr></thead><tbody>{rows_st or '<tr><td colspan=3 style=text-align:center>Ninguno ✅</td></tr>'}</tbody></table>

<script>
async function reconciliar(dryRun){{
  const r=document.getElementById('result');r.style.display='block';r.textContent='Procesando…';
  try{{
    const resp=await fetch('/api/loanbook/diagnostico/crm-reconciliar',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{dry_run:dryRun}})}});
    const data=await resp.json();r.textContent=JSON.stringify(data,null,2);
    if(!dryRun)setTimeout(()=>location.reload(),2000);
  }}catch(e){{r.textContent='Error: '+e.message;}}
}}
</script>
</body></html>"""
        return Response(content=html, media_type="text/html; charset=utf-8")
    except Exception as e:
        return Response(
            content=f"<pre>Error: {type(e).__name__}: {e}\n\n{traceback.format_exc()}</pre>",
            media_type="text/html; charset=utf-8",
            status_code=500,
        )


# ───────────────────────────────────────────────────────────────────────────
# LOANBOOK-FIX — Auditoría integridad + reparación batch
# ───────────────────────────────────────────────────────────────────────────

@router.get("/audit/integridad")
async def audit_integridad_loanbooks(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Audita TODOS los loanbooks y reporta problemas que rompen operación.

    Status por LB:
      VERDE: todo OK
      AMARILLO: warnings menores (cuotas sin fecha, saldos inconsistentes)
      ROJO: bloquea operación (estado activo sin cuotas, pendiente_entrega con pagos)
    """
    rojos = []
    amarillos = []
    verdes = []
    total = 0

    async for lb in db.loanbook.find({}):
        total += 1
        lb_id = lb.get("loanbook_id", "?")
        estado = lb.get("estado", "?")
        cuotas = lb.get("cuotas") or []
        n_cuotas = len(cuotas)
        nombre = (lb.get("cliente") or {}).get("nombre") or lb.get("cliente_nombre", "")

        warnings = []
        criticos = []

        # CRÍTICO: estado activo sin cuotas
        if estado == "activo" and n_cuotas == 0:
            criticos.append("estado=activo pero cuotas vacío")

        # CRÍTICO: pendiente_entrega que ya tiene pagos registrados
        if estado == "pendiente_entrega":
            criticos.append("pendiente_entrega — debe registrarse entrega para cobrar cuotas")

        # CRÍTICO: cuotas sin fechas si activo
        if estado == "activo" and n_cuotas > 0:
            sin_fecha = [c.get("numero", "?") for c in cuotas if not c.get("fecha")]
            if sin_fecha:
                criticos.append(f"{len(sin_fecha)} cuotas sin fecha: {sin_fecha[:5]}")

        # AMARILLO: cuotas con números no consecutivos
        if cuotas:
            numeros = sorted(int(c.get("numero", 0)) for c in cuotas if c.get("numero"))
            esperado = list(range(1, len(numeros) + 1))
            if numeros != esperado:
                warnings.append(f"numeración cuotas no consecutiva: {numeros[:10]}")

        # AMARILLO: saldos inconsistentes
        saldo_pendiente = lb.get("saldo_pendiente", 0)
        valor_total = lb.get("valor_total") or lb.get("monto_original", 0)
        total_pagado = lb.get("total_pagado", 0)
        if valor_total > 0:
            esperado_saldo = valor_total - total_pagado
            if abs(saldo_pendiente - esperado_saldo) > 1000:
                warnings.append(f"saldo_pendiente={saldo_pendiente:,} no cuadra con valor_total-total_pagado={esperado_saldo:,}")

        # AMARILLO: capital_plan ausente
        if not lb.get("capital_plan"):
            warnings.append("capital_plan ausente")

        # AMARILLO: fecha_entrega ausente si activo
        if estado == "activo" and not lb.get("fecha_entrega"):
            warnings.append("fecha_entrega ausente aunque activo")

        item = {
            "loanbook_id": lb_id,
            "cliente": nombre,
            "estado": estado,
            "modelo": lb.get("modelo", ""),
            "modalidad": lb.get("modalidad", ""),
            "n_cuotas": n_cuotas,
            "cuotas_total_plan": lb.get("num_cuotas") or lb.get("cuotas_total", 0),
            "saldo_pendiente": saldo_pendiente,
            "valor_total": valor_total,
            "fecha_entrega": lb.get("fecha_entrega"),
            "criticos": criticos,
            "warnings": warnings,
        }
        if criticos:
            rojos.append(item)
        elif warnings:
            amarillos.append(item)
        else:
            verdes.append(item)

    return {
        "fecha_corte": today_bogota().isoformat(),
        "total_loanbooks": total,
        "rojos_count": len(rojos),
        "amarillos_count": len(amarillos),
        "verdes_count": len(verdes),
        "rojos": rojos,
        "amarillos": amarillos,
        "verdes": verdes,
    }


@router.post("/audit/reparar-batch")
async def audit_reparar_batch(
    body: dict | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Auto-repara loanbooks con estado=pendiente_entrega que ya recibieron pagos.

    Para cada LB pendiente_entrega:
    1. Si tiene fecha_entrega proxy (fecha_factura, created_at, etc.):
       → ejecutar registrar_entrega() automáticamente con esa fecha
    2. Si no, queda en lista no_reparable para acción manual

    Body: {"dry_run": true (default), "fecha_default": "2026-04-28"}
    """
    dry_run = bool((body or {}).get("dry_run", True))
    fecha_default_str = (body or {}).get("fecha_default") or today_bogota().isoformat()

    reparados = []
    no_reparables = []
    errores = []

    # Búsqueda tolerante: cualquier variante de "pendiente_entrega" o "pendiente entrega"
    # Y también LBs activos sin cuotas (caso bug donde se quedó rota la creación)
    query = {
        "$or": [
            {"estado": {"$regex": "pendiente.entrega", "$options": "i"}},
            {"$and": [
                {"estado": {"$in": ["activo", "Activo", "ACTIVO"]}},
                {"$or": [{"cuotas": {"$exists": False}}, {"cuotas": []}, {"cuotas": None}]},
            ]},
        ]
    }
    async for lb in db.loanbook.find(query):
        lb_id = lb.get("loanbook_id", "?")
        nombre = (lb.get("cliente") or {}).get("nombre") or lb.get("cliente_nombre", "")

        # Buscar fecha proxy en orden de prioridad
        fecha_proxy = (
            lb.get("fecha_entrega")
            or lb.get("fecha_factura")
            or lb.get("fecha_venta")
            or (lb.get("created_at") or "")[:10]
            or fecha_default_str
        )

        if not fecha_proxy:
            no_reparables.append({"loanbook_id": lb_id, "cliente": nombre, "razon": "sin fecha proxy"})
            continue

        try:
            fecha_entrega = date.fromisoformat(fecha_proxy[:10])
        except ValueError:
            no_reparables.append({"loanbook_id": lb_id, "cliente": nombre, "razon": f"fecha proxy inválida: {fecha_proxy}"})
            continue

        if dry_run:
            reparados.append({
                "loanbook_id": lb_id, "cliente": nombre,
                "fecha_entrega_a_aplicar": fecha_entrega.isoformat(),
                "modalidad": lb.get("modalidad"),
                "num_cuotas": lb.get("num_cuotas") or lb.get("cuotas_total"),
                "DRY_RUN": True,
            })
            continue

        # Ejecutar registrar_entrega real
        try:
            body_re = RegistrarEntregaBody(
                fecha_entrega=fecha_entrega.isoformat(),
                fecha_primera_cuota=None,
                dia_cobro_especial=None,
            )
            result = await registrar_entrega(lb_id, body_re, db)
            reparados.append({"loanbook_id": lb_id, "cliente": nombre, "result": "OK"})
        except Exception as e:
            errores.append({"loanbook_id": lb_id, "cliente": nombre, "error": str(e)})

    return {
        "dry_run": dry_run,
        "reparados_count": len(reparados),
        "no_reparables_count": len(no_reparables),
        "errores_count": len(errores),
        "reparados": reparados,
        "no_reparables": no_reparables,
        "errores": errores,
    }


@router.post("/audit/recalcular-saldos")
async def audit_recalcular_saldos(
    body: dict | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Recalcula y persiste saldos canónicos de cada loanbook desde su array cuotas.

    Para cada LB:
      total_pagado_real    = Σ cuotas[].monto_pagado donde estado="pagada"
      cuotas_pagadas       = count cuotas con estado="pagada"
      saldo_pendiente_real = valor_total - total_pagado_real

    Body: {"dry_run": true (default)}
    """
    dry_run = bool((body or {}).get("dry_run", True))
    ajustados = []
    sin_cambios = []
    errores = []

    async for lb in db.loanbook.find({}):
        lb_id = lb.get("loanbook_id", "?")
        nombre = (lb.get("cliente") or {}).get("nombre") or lb.get("cliente_nombre", "")
        cuotas = lb.get("cuotas") or []

        total_pagado_real = 0.0
        cuotas_pagadas_real = 0
        cuotas_vencidas_real = 0
        from core.datetime_utils import today_bogota
        today_iso = today_bogota().isoformat()

        for c in cuotas:
            estado = (c.get("estado") or "").lower()
            if estado == "pagada":
                cuotas_pagadas_real += 1
                total_pagado_real += float(c.get("monto_pagado") or c.get("monto") or 0)
            elif c.get("fecha") and c.get("fecha") < today_iso:
                cuotas_vencidas_real += 1

        valor_total = float(lb.get("valor_total") or lb.get("monto_original", 0) or 0)
        saldo_pendiente_real = max(0, valor_total - total_pagado_real)
        capital_plan = float(lb.get("capital_plan") or 0)
        # Distribuir saldo: primero capital, después intereses
        if total_pagado_real >= capital_plan:
            saldo_capital_real = 0
            saldo_intereses_real = max(0, valor_total - total_pagado_real)
        else:
            saldo_capital_real = capital_plan - total_pagado_real
            saldo_intereses_real = max(0, valor_total - capital_plan)

        # Comparar con campos persistidos
        cambios = {}
        if abs(float(lb.get("total_pagado", 0)) - total_pagado_real) > 1:
            cambios["total_pagado"] = {"antes": lb.get("total_pagado", 0), "despues": round(total_pagado_real)}
        if abs(float(lb.get("saldo_pendiente", 0)) - saldo_pendiente_real) > 1:
            cambios["saldo_pendiente"] = {"antes": lb.get("saldo_pendiente", 0), "despues": round(saldo_pendiente_real)}
        if int(lb.get("cuotas_pagadas", 0)) != cuotas_pagadas_real:
            cambios["cuotas_pagadas"] = {"antes": lb.get("cuotas_pagadas", 0), "despues": cuotas_pagadas_real}
        if int(lb.get("cuotas_vencidas", 0)) != cuotas_vencidas_real:
            cambios["cuotas_vencidas"] = {"antes": lb.get("cuotas_vencidas", 0), "despues": cuotas_vencidas_real}
        if abs(float(lb.get("saldo_capital", 0)) - saldo_capital_real) > 1:
            cambios["saldo_capital"] = {"antes": lb.get("saldo_capital", 0), "despues": round(saldo_capital_real)}

        if not cambios:
            sin_cambios.append(lb_id)
            continue

        if not dry_run:
            try:
                await db.loanbook.update_one(
                    {"_id": lb["_id"]},
                    {"$set": {
                        "total_pagado": round(total_pagado_real),
                        "saldo_pendiente": round(saldo_pendiente_real),
                        "saldo_capital": round(saldo_capital_real),
                        "saldo_intereses": round(saldo_intereses_real),
                        "cuotas_pagadas": cuotas_pagadas_real,
                        "cuotas_vencidas": cuotas_vencidas_real,
                        "saldos_recalculados_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                    }},
                )
            except Exception as e:
                errores.append({"loanbook_id": lb_id, "error": str(e)})
                continue

        ajustados.append({"loanbook_id": lb_id, "cliente": nombre, "cambios": cambios})

    return {
        "dry_run": dry_run,
        "ajustados_count": len(ajustados),
        "sin_cambios_count": len(sin_cambios),
        "errores_count": len(errores),
        "ajustados": ajustados,
        "errores": errores,
    }


@router.get("/audit/inspeccionar-reparados")
async def audit_inspeccionar_reparados(
    desde: Annotated[str, Query()] = "LB-2026-0030",
    hasta: Annotated[str, Query()] = "LB-2026-0050",
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Lista LBs en rango con su estado de cronograma para validar fechas aplicadas en reparar-batch."""
    out = []
    async for lb in db.loanbook.find({"loanbook_id": {"$gte": desde, "$lte": hasta}}):
        cuotas = lb.get("cuotas") or []
        primera_cuota_fecha = None
        ultima_cuota_fecha = None
        if cuotas:
            fechas = [c.get("fecha") for c in cuotas if c.get("fecha")]
            if fechas:
                primera_cuota_fecha = min(fechas)
                ultima_cuota_fecha = max(fechas)
        nombre = (lb.get("cliente") or {}).get("nombre") or lb.get("cliente_nombre", "")
        out.append({
            "loanbook_id": lb.get("loanbook_id"),
            "cliente": nombre,
            "estado": lb.get("estado"),
            "modelo": lb.get("modelo"),
            "modalidad": lb.get("modalidad"),
            "fecha_entrega": lb.get("fecha_entrega"),
            "fecha_factura": lb.get("fecha_factura"),
            "created_at": lb.get("created_at"),
            "n_cuotas": len(cuotas),
            "primera_cuota_fecha": primera_cuota_fecha,
            "ultima_cuota_fecha": ultima_cuota_fecha,
            "cuotas_pagadas": lb.get("cuotas_pagadas", 0),
            "saldo_pendiente": lb.get("saldo_pendiente", 0),
        })
    out.sort(key=lambda x: x["loanbook_id"] or "")
    return {"total": len(out), "loanbooks": out}


@router.post("/admin-repoblar-monto-cuotas")
async def admin_repoblar_monto_cuotas(
    body: dict | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Repobla cuotas[].monto en LBs donde está en 0 o vacío.

    Lógica:
    1. Toma cuota_monto del LB (top-level)
    2. Si está vacío, busca en lb.plan o catalogo_planes por plan_codigo
    3. Para cada cuota con monto 0, le asigna ese cuota_monto
    4. También actualiza cuota_monto top-level del LB si estaba vacío

    Body: {"dry_run": true (default)}
    """
    dry_run = bool((body or {}).get("dry_run", True))
    actualizados = []
    sin_cambios = []
    sin_solucion = []

    async for lb in db.loanbook.find({}):
        lb_id = lb.get("loanbook_id", "?")
        nombre = (lb.get("cliente") or {}).get("nombre") or lb.get("cliente_nombre", "")
        cuotas = lb.get("cuotas") or []
        if not cuotas:
            continue

        cuotas_en_cero = [c for c in cuotas if (c.get("monto") or 0) == 0]
        if not cuotas_en_cero:
            sin_cambios.append(lb_id)
            continue

        # Estrategia 1: cuota_monto top-level
        cuota_monto = lb.get("cuota_monto") or 0
        # Estrategia 2: lb.plan.cuota_monto (a veces guardado anidado)
        if not cuota_monto:
            plan = lb.get("plan") or {}
            cuota_monto = plan.get("cuota_monto") or plan.get("valor_cuota") or 0
        # Estrategia 3: lookup catalogo_planes
        if not cuota_monto:
            plan_codigo = lb.get("plan_codigo") or (lb.get("plan") or {}).get("codigo")
            if plan_codigo:
                plan_doc = await db.catalogo_planes.find_one(
                    {"$or": [{"plan_codigo": plan_codigo}, {"codigo": plan_codigo}]}
                )
                if plan_doc:
                    cuota_monto = plan_doc.get("cuota_monto") or plan_doc.get("valor_cuota") or 0

        if not cuota_monto:
            sin_solucion.append({
                "loanbook_id": lb_id, "cliente": nombre,
                "razon": f"sin cuota_monto en lb top, plan, ni catalogo (plan_codigo={lb.get('plan_codigo')})",
            })
            continue

        # Actualizar las cuotas con monto 0
        cuotas_nuevas = []
        for c in cuotas:
            if (c.get("monto") or 0) == 0:
                cuotas_nuevas.append({**c, "monto": cuota_monto})
            else:
                cuotas_nuevas.append(c)

        if not dry_run:
            try:
                await db.loanbook.update_one(
                    {"_id": lb["_id"]},
                    {"$set": {
                        "cuota_monto": cuota_monto,
                        "cuotas": cuotas_nuevas,
                    }},
                )
            except Exception as e:
                sin_solucion.append({"loanbook_id": lb_id, "error": str(e)})
                continue

        actualizados.append({
            "loanbook_id": lb_id,
            "cliente": nombre,
            "cuota_monto_aplicado": cuota_monto,
            "cuotas_corregidas": len(cuotas_en_cero),
        })

    return {
        "dry_run": dry_run,
        "actualizados_count": len(actualizados),
        "sin_cambios_count": len(sin_cambios),
        "sin_solucion_count": len(sin_solucion),
        "actualizados": actualizados,
        "sin_solucion": sin_solucion,
    }


@router.post("/audit/reconciliacion-completa")
async def admin_reconciliacion_completa(
    body: dict | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Reconciliación INTEGRAL de TODOS los loanbooks en una sola pasada.

    Por cada LB no-saldado:
    1. Marca las primeras N cuotas como "pagada" (según cuotas_pagadas agregado)
       con fecha_pago = fecha_cuota (estimación) y monto_pagado = monto cuota
    2. Recalcula valor_total = num_cuotas × cuota_monto (canónico)
    3. Recalcula saldo_pendiente desde array cuotas
    4. Recalcula dpd: días desde la primera cuota no-pagada con fecha < hoy
    5. Recalcula cuotas_vencidas: cuotas pendientes con fecha < hoy
    6. Recalcula sub_bucket Phase 7 según DPD real
    7. Si fecha_primer_pago es futura (LB nuevos), dpd=0, cuotas_vencidas=0

    Body: {"dry_run": true (default)}
    """
    from datetime import date, datetime as dt, timezone as tz
    from core.datetime_utils import today_bogota
    dry_run = bool((body or {}).get("dry_run", True))
    today = today_bogota()
    today_iso = today.isoformat()

    def _phase7_bucket(dpd: int) -> str:
        if dpd <= 0: return "Current"
        if dpd <= 7: return "Grace"
        if dpd <= 15: return "Warning"
        if dpd <= 30: return "Alert"
        if dpd <= 45: return "Critical"
        if dpd <= 60: return "Severe"
        if dpd <= 90: return "PreDefault"
        if dpd <= 120: return "Default"
        return "ChargeOff"

    def _estado_from_dpd(dpd: int) -> str:
        if dpd <= 0: return "al_dia"
        if dpd <= 30: return "mora"
        return "mora_grave"

    reconciliados = []
    sin_cambios = []
    errores = []
    total_saldo_antes = 0.0
    total_saldo_despues = 0.0

    estados_excluir = {"saldado", "Pagado", "castigado", "ChargeOff", "pendiente_entrega"}

    async for lb in db.loanbook.find({}):
        lb_id = lb.get("loanbook_id", "?")
        nombre = (lb.get("cliente") or {}).get("nombre") or lb.get("cliente_nombre", "")
        estado = lb.get("estado", "")

        # Saltar saldados/pagados
        if estado in estados_excluir:
            sin_cambios.append({"loanbook_id": lb_id, "razon": f"estado={estado}"})
            continue

        cuotas = lb.get("cuotas") or []
        if not cuotas:
            errores.append({"loanbook_id": lb_id, "cliente": nombre, "error": "sin cuotas en array"})
            continue

        cuota_monto = float(lb.get("cuota_monto") or 0)
        num_cuotas = int(lb.get("num_cuotas") or lb.get("cuotas_total") or len(cuotas))
        cuotas_pagadas_agregado = int(lb.get("cuotas_pagadas") or 0)
        total_pagado_agregado = float(lb.get("total_pagado") or 0)
        cuota_inicial = float(lb.get("cuota_inicial") or 0)
        cuota_inicial_pagada = bool(lb.get("cuota_inicial_pagada", False))
        cuota_inicial_monto_pagado = float(lb.get("cuota_inicial_monto") or 0)

        if cuota_monto <= 0:
            errores.append({"loanbook_id": lb_id, "cliente": nombre, "error": "cuota_monto=0"})
            continue

        saldo_antes = float(lb.get("saldo_pendiente") or 0)
        total_saldo_antes += saldo_antes

        # 1. Marcar las primeras N cuotas como "pagada"
        cuotas_nuevas = []
        cuotas_pagadas_array = sum(1 for c in cuotas if (c.get("estado") or "") == "pagada")
        # Si el agregado dice más pagadas que el array, marcar las primeras (N - array) como pagada
        n_a_marcar = max(0, cuotas_pagadas_agregado - cuotas_pagadas_array)
        marcadas_count = 0
        for c in cuotas:
            estado_c = (c.get("estado") or "").lower()
            if estado_c == "pagada":
                cuotas_nuevas.append(c)
                continue
            if marcadas_count < n_a_marcar:
                # Marcar como pagada
                fecha_estimada = c.get("fecha") or today_iso
                cuotas_nuevas.append({
                    **c,
                    "estado": "pagada",
                    "fecha_pago": fecha_estimada,
                    "monto_pagado": c.get("monto") or cuota_monto,
                    "mora_acumulada": 0,
                    "reconciliado_at": dt.now(tz.utc).isoformat(),
                })
                marcadas_count += 1
            else:
                cuotas_nuevas.append(c)

        # 2-3. Recalcular valor_total y total_pagado canónicos
        # Fórmula canónica RODDOS: valor_total = cuota_inicial + (num_cuotas × cuota_monto)
        valor_total_canonico = cuota_inicial + (num_cuotas * cuota_monto)
        total_pagado_cuotas = sum(
            float(c.get("monto_pagado") or c.get("monto") or 0)
            for c in cuotas_nuevas
            if (c.get("estado") or "").lower() == "pagada"
        )
        # Si el agregado dice más pagado, usar (info real)
        total_pagado_cuotas = max(total_pagado_cuotas, total_pagado_agregado)
        # Sumar cuota inicial pagada al total
        total_pagado_real = total_pagado_cuotas
        if cuota_inicial_pagada and cuota_inicial_monto_pagado > 0:
            total_pagado_real += cuota_inicial_monto_pagado
        elif cuota_inicial_pagada and cuota_inicial > 0:
            total_pagado_real += cuota_inicial
        saldo_pendiente_canonico = max(0, valor_total_canonico - total_pagado_real)

        # 4-5. Recalcular DPD y cuotas_vencidas
        cuotas_vencidas_real = 0
        primera_pendiente_fecha = None
        for c in cuotas_nuevas:
            if (c.get("estado") or "").lower() == "pagada":
                continue
            fc = c.get("fecha")
            if not fc:
                continue
            if fc < today_iso:
                cuotas_vencidas_real += 1
                if primera_pendiente_fecha is None:
                    primera_pendiente_fecha = fc
        dpd_real = 0
        if primera_pendiente_fecha:
            try:
                dpd_real = (today - date.fromisoformat(primera_pendiente_fecha)).days
            except Exception:
                pass

        # Si todas las cuotas son futuras (LB nuevo no entregado todavía), DPD=0
        if cuotas_vencidas_real == 0:
            dpd_real = 0

        # 6. Sub-bucket Phase 7
        sub_bucket = _phase7_bucket(dpd_real)
        # 7. Estado canónico
        cuotas_pagadas_real = sum(1 for c in cuotas_nuevas if (c.get("estado") or "").lower() == "pagada")
        if cuotas_pagadas_real >= num_cuotas:
            estado_canonico = "saldado"
        else:
            estado_canonico = _estado_from_dpd(dpd_real)

        cambios = {
            "valor_total":      {"antes": lb.get("valor_total"), "despues": int(valor_total_canonico)},
            "saldo_pendiente":  {"antes": int(saldo_antes), "despues": int(saldo_pendiente_canonico)},
            "total_pagado":     {"antes": int(total_pagado_agregado), "despues": int(total_pagado_real)},
            "cuotas_pagadas":   {"antes": cuotas_pagadas_agregado, "despues": cuotas_pagadas_real},
            "cuotas_vencidas":  {"antes": int(lb.get("cuotas_vencidas") or 0), "despues": cuotas_vencidas_real},
            "dpd":              {"antes": int(lb.get("dpd") or 0), "despues": dpd_real},
            "estado":           {"antes": estado, "despues": estado_canonico},
            "sub_bucket":       {"antes": lb.get("sub_bucket_semanal") or "", "despues": sub_bucket},
            "cuotas_marcadas_pagada_ahora": marcadas_count,
        }

        if not dry_run:
            try:
                await db.loanbook.update_one(
                    {"_id": lb["_id"]},
                    {"$set": {
                        "cuotas":           cuotas_nuevas,
                        "valor_total":      int(valor_total_canonico),
                        "saldo_pendiente":  int(saldo_pendiente_canonico),
                        "total_pagado":     int(total_pagado_real),
                        "cuotas_pagadas":   cuotas_pagadas_real,
                        "cuotas_vencidas":  cuotas_vencidas_real,
                        "dpd":              dpd_real,
                        "estado":           estado_canonico,
                        "sub_bucket_semanal": sub_bucket,
                        "reconciliacion_completa_at": dt.now(tz.utc).isoformat(),
                    }},
                )
            except Exception as e:
                errores.append({"loanbook_id": lb_id, "cliente": nombre, "error": str(e)})
                continue

        total_saldo_despues += saldo_pendiente_canonico
        reconciliados.append({
            "loanbook_id": lb_id,
            "cliente": nombre,
            "cambios": cambios,
        })

    return {
        "dry_run": dry_run,
        "fecha_corte": today_iso,
        "reconciliados_count": len(reconciliados),
        "sin_cambios_count": len(sin_cambios),
        "errores_count": len(errores),
        "cartera_total_antes": int(total_saldo_antes),
        "cartera_total_despues": int(total_saldo_despues),
        "delta_cartera": int(total_saldo_despues - total_saldo_antes),
        "reconciliados": reconciliados,
        "sin_cambios": sin_cambios,
        "errores": errores,
    }


@router.get("/admin-diagnostico-integral")
async def admin_diagnostico_integral(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Diagnóstico completo: para cada LB, todos los campos críticos + plan match.

    Devuelve para cada LB:
    - Estado actual de campos top-level (cuota_monto, num_cuotas, fecha_entrega, etc)
    - Plan asociado y si existe en catalogo_planes
    - Estado de cada cuota (count, primera con monto 0, sin fecha)
    - Issues detectados con prioridad

    Y al final lista de planes únicos y cuáles existen en catalogo_planes.
    """
    # 1) Cargar catálogo planes
    planes_catalogo = {}
    async for p in db.catalogo_planes.find({}):
        codigo = p.get("plan_codigo") or p.get("codigo")
        if codigo:
            planes_catalogo[codigo] = {
                "plan_codigo": codigo,
                "modalidad": p.get("modalidad"),
                "num_cuotas": p.get("num_cuotas"),
                "cuota_monto": p.get("cuota_monto") or p.get("valor_cuota"),
                "capital_plan": p.get("capital_plan"),
                "modelo_default": p.get("modelo"),
            }

    # 2) Iterar loanbooks
    loanbooks = []
    planes_usados = {}
    async for lb in db.loanbook.find({}):
        lb_id = lb.get("loanbook_id", "?")
        nombre = (lb.get("cliente") or {}).get("nombre") or lb.get("cliente_nombre", "")
        plan_codigo = lb.get("plan_codigo") or (lb.get("plan") or {}).get("codigo") or ""
        cuotas = lb.get("cuotas") or []

        # Stats de cuotas
        n_cuotas = len(cuotas)
        cuotas_sin_monto = sum(1 for c in cuotas if (c.get("monto") or 0) == 0)
        cuotas_sin_fecha = sum(1 for c in cuotas if not c.get("fecha"))
        cuotas_sin_numero = sum(1 for c in cuotas if not c.get("numero"))
        cuotas_pagadas = sum(1 for c in cuotas if c.get("estado") == "pagada")

        # Issues
        issues = []
        if not plan_codigo:
            issues.append("plan_codigo vacío")
        elif plan_codigo not in planes_catalogo:
            issues.append(f"plan_codigo '{plan_codigo}' no existe en catalogo_planes")

        if not lb.get("cuota_monto"):
            issues.append("cuota_monto top-level vacío")
        if not lb.get("num_cuotas") and not lb.get("cuotas_total"):
            issues.append("num_cuotas vacío")
        if not lb.get("fecha_entrega") and lb.get("estado") not in ("pendiente_entrega", "saldado"):
            issues.append("fecha_entrega vacía aunque activo")
        if cuotas_sin_monto > 0:
            issues.append(f"{cuotas_sin_monto} cuotas con monto 0")
        if cuotas_sin_fecha > 0:
            issues.append(f"{cuotas_sin_fecha} cuotas sin fecha")
        if cuotas_sin_numero > 0:
            issues.append(f"{cuotas_sin_numero} cuotas sin numero")

        plan_existe = plan_codigo in planes_catalogo
        planes_usados[plan_codigo] = planes_usados.get(plan_codigo, 0) + 1

        loanbooks.append({
            "loanbook_id": lb_id,
            "cliente": nombre,
            "estado": lb.get("estado"),
            "modelo": lb.get("modelo"),
            "modalidad": lb.get("modalidad"),
            "plan_codigo": plan_codigo,
            "plan_existe_en_catalogo": plan_existe,
            "plan_catalogo_data": planes_catalogo.get(plan_codigo),
            "cuota_monto_lb": lb.get("cuota_monto"),
            "num_cuotas_lb": lb.get("num_cuotas") or lb.get("cuotas_total"),
            "fecha_entrega": lb.get("fecha_entrega"),
            "n_cuotas_array": n_cuotas,
            "cuotas_pagadas": cuotas_pagadas,
            "cuotas_sin_monto": cuotas_sin_monto,
            "cuotas_sin_fecha": cuotas_sin_fecha,
            "cuotas_sin_numero": cuotas_sin_numero,
            "issues": issues,
            "primera_cuota_sample": cuotas[0] if cuotas else None,
        })

    # Resumen
    return {
        "total_loanbooks": len(loanbooks),
        "loanbooks_con_issues": sum(1 for lb in loanbooks if lb["issues"]),
        "planes_en_catalogo": list(planes_catalogo.keys()),
        "planes_usados_por_lbs": planes_usados,
        "planes_sin_catalogo": [p for p in planes_usados if p not in planes_catalogo],
        "loanbooks": loanbooks,
    }


@router.post("/admin-fijar-cuota-monto-manual")
async def admin_fijar_cuota_monto_manual(
    body: dict = Body(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Fija cuota_monto manualmente para una lista de LBs.

    Body: {
      "asignaciones": [
        {"loanbook_id": "LB-2026-0029", "cuota_monto": 210000},
        ...
      ],
      "dry_run": true
    }

    Por cada LB:
    - Setea cuota_monto top-level
    - Recalcula cuotas[].monto = cuota_monto para cuotas con monto 0
    """
    asignaciones = body.get("asignaciones") or []
    dry_run = bool(body.get("dry_run", True))

    aplicados = []
    errores = []
    for a in asignaciones:
        lb_id = a.get("loanbook_id")
        nuevo_monto = a.get("cuota_monto")
        if not lb_id or not nuevo_monto:
            errores.append({"input": a, "error": "loanbook_id y cuota_monto obligatorios"})
            continue
        try:
            lb = await db.loanbook.find_one({"loanbook_id": lb_id})
            if not lb:
                errores.append({"loanbook_id": lb_id, "error": "no existe"})
                continue
            cuotas = lb.get("cuotas") or []
            cuotas_nuevas = [
                {**c, "monto": nuevo_monto} if (c.get("monto") or 0) == 0 else c
                for c in cuotas
            ]
            cambios_count = sum(1 for c in cuotas if (c.get("monto") or 0) == 0)
            if not dry_run:
                await db.loanbook.update_one(
                    {"_id": lb["_id"]},
                    {"$set": {"cuota_monto": nuevo_monto, "cuotas": cuotas_nuevas}},
                )
            aplicados.append({
                "loanbook_id": lb_id,
                "cuota_monto_aplicado": nuevo_monto,
                "cuotas_corregidas": cambios_count,
            })
        except Exception as e:
            errores.append({"loanbook_id": lb_id, "error": str(e)})

    return {
        "dry_run": dry_run,
        "aplicados_count": len(aplicados),
        "errores_count": len(errores),
        "aplicados": aplicados,
        "errores": errores,
    }


@router.post("/admin-batch-corregir-fechas")
async def admin_batch_corregir_fechas(
    body: dict = Body(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Corrige fecha_entrega + fecha_primera_cuota para una lista de loanbooks.

    Body: {
      "loanbook_ids": ["LB-2026-0034", ...],
      "fecha_entrega": "2026-04-30",
      "fecha_primera_cuota": "2026-05-06",
      "dry_run": false
    }

    Para cada LB:
    1. Si no es pendiente_entrega, lo regresa a ese estado y limpia cuotas[]
    2. Llama registrar_entrega() con las nuevas fechas
    3. El cronograma se regenera limpio
    """
    lb_ids = body.get("loanbook_ids") or []
    fecha_entrega = body.get("fecha_entrega")
    fecha_primera_cuota = body.get("fecha_primera_cuota")
    dia_cobro_especial = body.get("dia_cobro_especial")
    dry_run = bool(body.get("dry_run", False))

    if not lb_ids or not fecha_entrega:
        raise HTTPException(status_code=400, detail="loanbook_ids y fecha_entrega obligatorios")

    corregidos = []
    errores = []

    for lb_id in lb_ids:
        try:
            lb = await db.loanbook.find_one({"loanbook_id": lb_id})
            if not lb:
                errores.append({"loanbook_id": lb_id, "error": "no existe"})
                continue
            if dry_run:
                corregidos.append({
                    "loanbook_id": lb_id,
                    "cliente": (lb.get("cliente") or {}).get("nombre") or lb.get("cliente_nombre", ""),
                    "fecha_entrega_a_aplicar": fecha_entrega,
                    "fecha_primera_cuota_a_aplicar": fecha_primera_cuota,
                    "DRY_RUN": True,
                })
                continue
            # Reset a pendiente_entrega para regenerar
            await db.loanbook.update_one(
                {"_id": lb["_id"]},
                {"$set": {"estado": "pendiente_entrega", "cuotas": []}},
            )
            body_re = RegistrarEntregaBody(
                fecha_entrega=fecha_entrega,
                fecha_primera_cuota=fecha_primera_cuota,
                dia_cobro_especial=dia_cobro_especial,
            )
            await registrar_entrega(lb_id, body_re, db)
            corregidos.append({
                "loanbook_id": lb_id,
                "cliente": (lb.get("cliente") or {}).get("nombre") or lb.get("cliente_nombre", ""),
                "result": "OK",
            })
        except Exception as e:
            errores.append({"loanbook_id": lb_id, "error": str(e)})

    return {
        "dry_run": dry_run,
        "corregidos_count": len(corregidos),
        "errores_count": len(errores),
        "corregidos": corregidos,
        "errores": errores,
    }


@router.post("/{identifier}/corregir-fecha-entrega")
async def corregir_fecha_entrega(
    identifier: str,
    body: dict = Body(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Cambia fecha_entrega y regenera cronograma. Body: {fecha_entrega: ISO, fecha_primera_cuota: ISO?}.

    Si el cliente paga la próxima semana, fecha_primera_cuota = primer miércoles después
    de fecha_entrega + 7 días (regla canónica).
    """
    fecha_entrega = body.get("fecha_entrega")
    if not fecha_entrega:
        raise HTTPException(status_code=400, detail="fecha_entrega obligatoria (ISO yyyy-MM-dd)")

    lb = await _find_lb_by_identifier(db, identifier)
    # Volver a estado pendiente_entrega para que registrar_entrega no rechace
    if lb.get("estado") not in ("pendiente_entrega",):
        await db.loanbook.update_one(
            {"_id": lb["_id"]},
            {"$set": {"estado": "pendiente_entrega"},
             "$unset": {"cuotas": ""}},
        )

    body_re = RegistrarEntregaBody(
        fecha_entrega=fecha_entrega,
        fecha_primera_cuota=body.get("fecha_primera_cuota"),
        dia_cobro_especial=body.get("dia_cobro_especial"),
    )
    return await registrar_entrega(identifier, body_re, db)


@router.get("/audit/integridad-html", response_class=Response)
async def audit_integridad_html(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Versión HTML visual del audit con botones de reparación."""
    import traceback as _tb
    try:
        audit = await audit_integridad_loanbooks(db)

        def _row_lb(lb, color):
            criticos = "<br>".join(f"<span style='color:#dc2626'>❌ {c}</span>" for c in lb.get("criticos", []))
            warnings = "<br>".join(f"<span style='color:#f59e0b'>⚠️ {w}</span>" for w in lb.get("warnings", []))
            issues = (criticos + ("<br>" if criticos and warnings else "") + warnings) or "✅"
            return (
                f"<tr style='background:{color}'>"
                f"<td><a href='/loanbook/{lb['loanbook_id']}' style='color:#006e2a;text-decoration:none;'><b>{lb['loanbook_id']}</b></a></td>"
                f"<td>{lb.get('cliente','')[:30]}</td>"
                f"<td><span class='badge badge-{lb.get('estado','?')}'>{lb.get('estado','')}</span></td>"
                f"<td>{lb.get('modelo','')}</td>"
                f"<td>{lb.get('modalidad','')}</td>"
                f"<td style='text-align:right'>{lb.get('n_cuotas',0)} / {lb.get('cuotas_total_plan',0)}</td>"
                f"<td style='text-align:right'>${int(lb.get('saldo_pendiente',0)):,}</td>"
                f"<td style='font-size:11px'>{issues}</td>"
                f"</tr>"
            )

        rows = (
            "".join(_row_lb(lb, "#fee2e2") for lb in audit["rojos"]) +
            "".join(_row_lb(lb, "#fef3c7") for lb in audit["amarillos"]) +
            "".join(_row_lb(lb, "#fff") for lb in audit["verdes"][:30])  # solo 30 verdes
        )

        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Auditoría Loanbook</title>
<style>body{{font-family:-apple-system,sans-serif;padding:24px;background:#f6f3f2;max-width:1400px;margin:0 auto;}}
h1{{color:#006e2a;}}.metric{{display:inline-block;margin-right:24px;}}.metric-val{{font-size:32px;font-weight:600;}}
.card{{background:white;padding:16px;border-radius:8px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,0.06);}}
table{{width:100%;border-collapse:collapse;font-size:13px;}}
th,td{{padding:8px 12px;text-align:left;border-bottom:1px solid #e5e7eb;}}
th{{background:#f9fafb;text-transform:uppercase;font-size:11px;color:#6b7280;}}
.badge{{padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;}}
.badge-pendiente_entrega{{background:#fef3c7;color:#92400e;}}
.badge-activo{{background:#d1fae5;color:#065f46;}}
.badge-saldado{{background:#e5e7eb;color:#374151;}}
.badge-mora{{background:#fee2e2;color:#991b1b;}}
button{{background:#006e2a;color:white;border:none;padding:10px 20px;border-radius:6px;cursor:pointer;font-weight:600;margin-right:8px;}}
.btn-danger{{background:#dc2626;}}
</style></head><body>
<h1>🔍 Auditoría Integridad Loanbooks</h1>
<div class="card">
<span class="metric"><div>Total</div><div class="metric-val" style="color:#006e2a">{audit['total_loanbooks']}</div></span>
<span class="metric"><div>🔴 Críticos</div><div class="metric-val" style="color:#dc2626">{audit['rojos_count']}</div></span>
<span class="metric"><div>🟡 Warnings</div><div class="metric-val" style="color:#f59e0b">{audit['amarillos_count']}</div></span>
<span class="metric"><div>🟢 OK</div><div class="metric-val" style="color:#10b981">{audit['verdes_count']}</div></span>
</div>

<div class="card">
<h2>🔧 Reparación batch (pendiente_entrega → activo + cronograma)</h2>
<p>Para cada LB en estado pendiente_entrega, se calcula fecha_entrega proxy y se ejecuta registrar_entrega automáticamente.</p>
<button onclick="reparar(true)">🔍 DRY-RUN</button>
<button class="btn-danger" onclick="reparar(false)">🚀 EJECUTAR</button>
<pre id="result" style="background:#1f2937;color:#10b981;padding:12px;border-radius:6px;display:none;max-height:400px;overflow:auto;font-size:11px;"></pre>
</div>

<div class="card">
<h2>Loanbooks (rojos primero, luego amarillos, luego 30 verdes)</h2>
<table>
<thead><tr><th>ID</th><th>Cliente</th><th>Estado</th><th>Modelo</th><th>Modalidad</th><th>Cuotas</th><th>Saldo</th><th>Issues</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</div>

<script>
async function reparar(dryRun){{
  const r=document.getElementById('result');r.style.display='block';r.textContent='Procesando…';
  try{{
    const resp=await fetch('/api/loanbook/audit/reparar-batch',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{dry_run:dryRun}})}});
    const data=await resp.json();r.textContent=JSON.stringify(data,null,2);
    if(!dryRun)setTimeout(()=>location.reload(),3000);
  }}catch(e){{r.textContent='Error: '+e.message;}}
}}
</script>
</body></html>"""
        return Response(content=html, media_type="text/html; charset=utf-8")
    except Exception as e:
        return Response(
            content=f"<pre>Error: {type(e).__name__}: {e}\n\n{_tb.format_exc()}</pre>",
            media_type="text/html; charset=utf-8",
            status_code=500,
        )
