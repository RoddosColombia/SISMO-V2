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
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
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
