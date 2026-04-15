"""
Loanbook endpoints — credit portfolio management.

GET  /api/loanbook          — List all loanbooks with summary stats
GET  /api/loanbook/{vin}    — Detail with full cuotas timeline
GET  /api/loanbook/stats    — Portfolio summary
"""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_db
from core.loanbook_model import calcular_dpd, estado_from_dpd

router = APIRouter(prefix="/api/loanbook", tags=["loanbook"])


def _clean_doc(doc: dict) -> dict:
    """Remove MongoDB _id for JSON serialization."""
    if doc:
        doc.pop("_id", None)
    return doc


@router.get("/stats")
async def loanbook_stats(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Portfolio summary stats."""
    today = date.today()

    all_lbs = await db.loanbook.find().to_list(length=1000)
    total = len(all_lbs)
    activos = 0
    cartera_total = 0
    recaudo_semanal = 0
    en_mora = 0

    for lb in all_lbs:
        estado = lb.get("estado", "")
        if estado not in ("saldado", "castigado", "pendiente_entrega"):
            activos += 1
            cartera_total += lb.get("saldo_capital", 0)

            # Recaudo semanal: cuota_monto for semanal, cuota/2 for quincenal, cuota/4 for mensual
            modalidad = lb.get("modalidad", "semanal")
            cuota = lb.get("cuota_monto", 0)
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
        "cartera_total": round(cartera_total),
        "recaudo_semanal": round(recaudo_semanal),
        "en_mora": en_mora,
    }


@router.get("")
async def listar_loanbooks(
    estado: str | None = None,
    modelo: str | None = None,
    plan: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """List all loanbooks with computed fields."""
    today = date.today()
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
                proxima = {"fecha": c["fecha"], "monto": c["monto"]}
                break

        lb["cuotas_pagadas"] = pagadas
        lb["cuotas_total"] = total_cuotas
        lb["dpd"] = dpd
        lb["proxima_cuota"] = proxima
        # Strip full cuotas array from list view
        lb.pop("cuotas", None)
        result.append(lb)

    # Sort by DPD descending (morosos first)
    result.sort(key=lambda x: x.get("dpd", 0), reverse=True)

    return {"count": len(result), "loanbooks": result}


@router.get("/{vin}")
async def get_loanbook(
    vin: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Get full loanbook detail with cuotas timeline."""
    today = date.today()
    lb = await db.loanbook.find_one({"vin": vin})
    if not lb:
        raise HTTPException(status_code=404, detail=f"Loanbook para VIN {vin} no encontrado")

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
            proxima = {"fecha": c["fecha"], "monto": c["monto"]}
            break

    lb["cuotas_pagadas"] = pagadas
    lb["cuotas_total"] = len(cuotas)
    lb["dpd"] = dpd
    lb["proxima_cuota"] = proxima

    return lb
