"""
CRM endpoints — Client management for RODDOS motorcycle credits.

GET  /api/crm/clientes          — List clients (filterable by estado, score)
GET  /api/crm/clientes/{cedula} — Client detail with loanbooks
POST /api/crm/clientes          — Create new client
PUT  /api/crm/clientes/{cedula} — Update client data
GET  /api/crm/stats             — Summary stats
"""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_db
from core.crm_model import crear_cliente_doc, validar_telefono, ESTADOS_CRM

router = APIRouter(prefix="/api/crm", tags=["crm"])


# ═══════════════════════════════════════════
# Internal functions (testable without HTTP)
# ═══════════════════════════════════════════


async def _crear_cliente(db: AsyncIOMotorDatabase, data: dict) -> dict:
    """Create a new CRM client. Raises ValueError if duplicate."""
    cedula = data["cedula"]

    existing = await db.crm_clientes.find_one({"cedula": cedula})
    if existing:
        raise ValueError(f"Cliente con cédula {cedula} ya existe.")

    doc = crear_cliente_doc(
        cedula=cedula,
        nombre=data.get("nombre", ""),
        telefono=data.get("telefono", ""),
        email=data.get("email", ""),
        direccion=data.get("direccion", ""),
    )
    await db.crm_clientes.insert_one(doc)

    # Return without _id
    doc.pop("_id", None)
    return doc


async def _get_cliente(db: AsyncIOMotorDatabase, cedula: str) -> dict | None:
    """Get client by cédula plus consolidated loanbooks + pago history.

    Enriched response adds:
      - loanbooks: list of loanbooks (resumen + cuotas summary per credit)
      - historial_pagos: all cuotas pagadas ordered by fecha_pago desc
      - comportamiento: {pagadas_a_tiempo, promedio_atraso, racha_actual}
    """
    doc = await db.crm_clientes.find_one({"cedula": cedula})
    if not doc:
        return None
    doc.pop("_id", None)

    # Enrich with loanbooks. Gracefully degrade if db.loanbook is missing
    # (some legacy unit tests only mock crm_clientes).
    try:
        cursor = db.loanbook.find({"cliente.cedula": cedula})
        lbs = await cursor.to_list(length=100)
    except (AttributeError, TypeError):
        return doc  # Legacy shape — no enrichment available
    total_financiado = 0
    total_pagado = 0
    saldo_total = 0
    cuotas_al_dia = 0
    cuotas_en_mora = 0
    historial_pagos: list[dict] = []
    loanbooks_list: list[dict] = []

    for lb in lbs:
        lb.pop("_id", None)
        tf = (lb.get("num_cuotas") or 0) * (lb.get("cuota_monto") or 0)
        tp = lb.get("total_pagado") or 0
        sp = lb.get("saldo_capital") or lb.get("saldo_pendiente") or 0
        total_financiado += tf
        total_pagado += tp
        saldo_total += sp
        cuotas = lb.get("cuotas") or []
        for c in cuotas:
            if c.get("estado") == "pagada":
                cuotas_al_dia += 1
                historial_pagos.append({
                    "loanbook_id": lb.get("loanbook_id"),
                    "cuota_numero": c.get("numero"),
                    "monto": c.get("monto"),
                    "fecha_programada": c.get("fecha"),
                    "fecha_pago": c.get("fecha_pago"),
                    "metodo_pago": c.get("metodo_pago"),
                    "referencia": c.get("referencia"),
                })
            elif (lb.get("dpd") or 0) > 0:
                cuotas_en_mora += 1
        loanbooks_list.append({
            "loanbook_id": lb.get("loanbook_id"),
            "tipo_producto": lb.get("tipo_producto", "moto"),
            "modelo": lb.get("modelo"),
            "vin": lb.get("vin"),
            "estado": lb.get("estado"),
            "plan_codigo": lb.get("plan_codigo"),
            "modalidad": lb.get("modalidad"),
            "cuota_monto": lb.get("cuota_monto"),
            "num_cuotas": lb.get("num_cuotas"),
            "cuotas_pagadas": lb.get("cuotas_pagadas", 0),
            "saldo_capital": lb.get("saldo_capital") or lb.get("saldo_pendiente"),
            "dpd": lb.get("dpd", 0),
        })

    # Comportamiento: % pagos a tiempo + racha
    pagos_a_tiempo = 0
    atraso_dias_total = 0
    pagos_con_fechas = 0
    ultimos_estados: list[str] = []  # 'a_tiempo' / 'atraso'
    for p in sorted(historial_pagos, key=lambda x: x.get("fecha_pago") or ""):
        fp = p.get("fecha_pago")
        fprog = p.get("fecha_programada")
        if fp and fprog:
            try:
                dp = date.fromisoformat(fp)
                dprog = date.fromisoformat(fprog)
                atraso = (dp - dprog).days
                if atraso <= 0:
                    pagos_a_tiempo += 1
                    ultimos_estados.append("a_tiempo")
                else:
                    atraso_dias_total += atraso
                    ultimos_estados.append("atraso")
                pagos_con_fechas += 1
            except ValueError:
                continue

    pct_a_tiempo = round((pagos_a_tiempo / pagos_con_fechas) * 100) if pagos_con_fechas else None
    promedio_atraso = round(atraso_dias_total / max(1, pagos_con_fechas - pagos_a_tiempo)) if pagos_con_fechas > pagos_a_tiempo else 0

    # Racha: cuenta consecutivos desde el último pago
    racha = 0
    racha_tipo = None
    for estado in reversed(ultimos_estados):
        if racha_tipo is None:
            racha_tipo = estado
            racha = 1
        elif estado == racha_tipo:
            racha += 1
        else:
            break

    # Sort history: most recent paid first
    historial_pagos.sort(key=lambda x: x.get("fecha_pago") or "", reverse=True)

    # Apto para nuevo crédito: no mora actual + score en {A+, A, B}
    score = doc.get("score_pago") or doc.get("score")
    apto = bool(cuotas_en_mora == 0 and score in ("A+", "A", "B"))

    return {
        **doc,
        "loanbooks": loanbooks_list,
        "resumen": {
            "total_financiado": total_financiado,
            "total_pagado": total_pagado,
            "saldo_total": saldo_total,
            "cuotas_al_dia": cuotas_al_dia,
            "cuotas_en_mora": cuotas_en_mora,
        },
        "historial_pagos": historial_pagos[:50],
        "comportamiento": {
            "pct_a_tiempo": pct_a_tiempo,
            "promedio_atraso": promedio_atraso,
            "racha": racha,
            "racha_tipo": racha_tipo,
            "ultimos_estados": ultimos_estados[-10:],
        },
        "apto_nuevo_credito": apto,
    }


async def _actualizar_cliente(
    db: AsyncIOMotorDatabase, cedula: str, updates: dict
) -> bool:
    """Update client fields. Returns True if found."""
    existing = await db.crm_clientes.find_one({"cedula": cedula})
    if not existing:
        return False

    updates["updated_at"] = date.today().isoformat()
    await db.crm_clientes.update_one(
        {"cedula": cedula},
        {"$set": updates},
    )
    return True


async def _listar_clientes(
    db: AsyncIOMotorDatabase,
    estado: str | None = None,
    score: str | None = None,
) -> list[dict]:
    """List clients with optional filters."""
    filtro: dict = {}
    if estado:
        filtro["estado"] = estado
    if score:
        filtro["score"] = score

    cursor = db.crm_clientes.find(filtro).sort("nombre", 1)
    items = await cursor.to_list(length=500)
    for item in items:
        item.pop("_id", None)
    return items


async def _get_stats(db: AsyncIOMotorDatabase) -> dict:
    """Get CRM summary statistics."""
    total = await db.crm_clientes.count_documents({})
    por_estado = {}
    for estado in ESTADOS_CRM:
        count = await db.crm_clientes.count_documents({"estado": estado})
        por_estado[estado] = count

    return {
        "total": total,
        "por_estado": por_estado,
    }


# ═══════════════════════════════════════════
# HTTP Endpoints
# ═══════════════════════════════════════════


@router.get("/clientes")
async def listar_clientes(
    estado: str | None = None,
    score: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """List all clients with optional filters."""
    items = await _listar_clientes(db, estado=estado, score=score)
    return {"count": len(items), "clientes": items}


@router.get("/clientes/{cedula}")
async def get_cliente(
    cedula: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Get client detail by cédula."""
    doc = await _get_cliente(db, cedula)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Cliente {cedula} no encontrado")
    return doc


@router.post("/clientes", status_code=201)
async def crear_cliente(
    data: dict,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Create a new client."""
    if not data.get("cedula") or not data.get("nombre"):
        raise HTTPException(status_code=400, detail="cedula y nombre son obligatorios")
    try:
        doc = await _crear_cliente(db, data)
        return doc
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.put("/clientes/{cedula}")
async def actualizar_cliente(
    cedula: str,
    data: dict,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Update client data."""
    # Prevent changing cedula
    data.pop("cedula", None)
    data.pop("_id", None)

    updated = await _actualizar_cliente(db, cedula, data)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Cliente {cedula} no encontrado")
    return {"ok": True, "cedula": cedula}


@router.get("/stats")
async def crm_stats(db: AsyncIOMotorDatabase = Depends(get_db)):
    """CRM summary statistics."""
    return await _get_stats(db)
