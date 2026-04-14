"""
Inventario REST endpoints.

ROG-4: Inventory lives IN Alegra. SISMO reads from Alegra, NEVER maintains its own.
MongoDB ONLY stores operational state: apartados (workflow) and kit definitions.

Accounts used:
- Banco entries: per banco_recibo mapping
- Anticipos recibidos: 5370 (NIIF 2805 — Anticipos y avances recibidos)
"""
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from core.database import get_db
from core.events import publish_event
from services.alegra.client import AlegraClient, AlegraError
from services.alegra_items import AlegraItemsService

router = APIRouter(prefix="/api/inventario", tags=["inventario"])

# --- Alegra account IDs ---
# Anticipos y avances recibidos (NIIF 2805) — verified in Alegra 2026-04-14
ANTICIPOS_RECIBIDOS_ID = "5370"

BANCO_CATEGORY_MAP = {
    "bancolombia_2029": "5314",
    "bancolombia_2540": "5315",
    "bbva_0210": "5318",
    "bbva_0212": "5319",
    "davivienda_482": "5322",
    "banco_bogota": "5321",
    "nequi": "5310",  # Caja general
}

BANCO_PAYMENT_MAP = {
    "bancolombia_2029": "5",
    "bancolombia_2540": "6",
    "bbva_0210": "7",
    "bbva_0212": "10",
    "davivienda_482": "3",
}


# --- Dependency helpers ---

async def _get_alegra(db: AsyncIOMotorDatabase = Depends(get_db)) -> AlegraClient:
    return AlegraClient(db=db)


async def _get_items_service(
    alegra: AlegraClient = Depends(_get_alegra),
) -> AlegraItemsService:
    return AlegraItemsService(alegra)


# ═══════════════════════════════════════════
# PARTE A: MOTOS
# ═══════════════════════════════════════════


# --- Registro manual de VIN (para las 10 Sport 100 ya en Alegra como SKU) ---

class RegistroManualRequest(BaseModel):
    vin: str
    motor: str = ""
    modelo: str = "Sport 100"
    color: str = ""
    notas: str = ""
    item_id_alegra: str = "25"  # Default: Sport 100 SKU


@router.post("/motos/registrar-manual")
async def registrar_moto_manual(
    body: RegistroManualRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Register VIN for an existing Alegra SKU moto (operational data in MongoDB).
    The 10 Sport 100 already exist in Alegra as 1 SKU — this adds individual VIN tracking.
    Future motos will be created directly in Alegra with VIN by the Agente Contador.
    """
    # Validate no duplicate VIN
    existing = await db.inventario_motos.find_one({"vin": body.vin})
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe una moto con VIN {body.vin}"
        )

    doc = {
        "vin": body.vin,
        "motor": body.motor,
        "modelo": body.modelo,
        "color": body.color,
        "notas": body.notas,
        "item_id_alegra": body.item_id_alegra,
        "estado": "disponible",
        "fecha_registro": datetime.now(timezone.utc).isoformat(),
    }
    await db.inventario_motos.insert_one(doc)

    return {"success": True, "vin": body.vin, "modelo": body.modelo}


@router.get("/motos")
async def list_motos(
    estado: str | None = None,
    categoria: str | None = None,
    service: AlegraItemsService = Depends(_get_items_service),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    List moto inventory — combines:
    1. Motos with VIN registered in MongoDB (can be reserved)
    2. Alegra SKU stock info (for motos without VIN yet)
    """
    try:
        alegra_motos = await service.list_motos()
    except AlegraError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Load manually registered motos (with VIN) from MongoDB
    registered_cursor = db.inventario_motos.find({"estado": {"$ne": "eliminada"}})
    registered = await registered_cursor.to_list(length=500)

    # Load active apartados
    apartados_activos = {}
    apt_cursor = db.apartados.find({"estado": "activo"})
    async for apt in apt_cursor:
        key = apt.get("vin") or apt.get("item_id_alegra", "")
        apartados_activos[key] = {
            "cliente": apt.get("cliente", {}).get("nombre", ""),
            "monto_acumulado": apt.get("monto_acumulado", 0),
            "cuota_inicial_total": apt.get("cuota_inicial_total", 0),
            "fecha_apartado": apt.get("fecha_apartado", ""),
            "fecha_limite": apt.get("fecha_limite", ""),
        }

    # Count registered VINs per Alegra item
    registered_per_item: dict[str, int] = {}
    for reg in registered:
        aid = reg.get("item_id_alegra", "")
        registered_per_item[aid] = registered_per_item.get(aid, 0) + 1

    result = []

    # 1. Add individually registered motos (with VIN)
    for reg in registered:
        vin = reg.get("vin", "")
        estado_moto = "Disponible"
        apartado_info = None

        if vin in apartados_activos:
            estado_moto = "Apartada"
            apartado_info = apartados_activos[vin]

        result.append({
            "id_alegra": reg.get("item_id_alegra", ""),
            "vin": vin,
            "motor": reg.get("motor", ""),
            "nombre": reg.get("modelo", ""),
            "descripcion": f"VIN: {vin}" + (f" | Motor: {reg.get('motor', '')}" if reg.get("motor") else ""),
            "referencia": "",
            "categoria": "Motos nuevas",
            "color": reg.get("color", ""),
            "stock": 1,
            "precio": 0,
            "costo_unitario": 0,
            "estado": estado_moto,
            "tiene_vin": True,
            "apartado": apartado_info,
        })

    # 2. For each Alegra SKU, show remaining unregistered units
    for moto in alegra_motos:
        aid = moto["id_alegra"]
        total_stock = moto["stock"]
        registered_count = registered_per_item.get(aid, 0)
        sin_vin = max(total_stock - registered_count, 0)

        if sin_vin > 0:
            result.append({
                **moto,
                "vin": "",
                "motor": "",
                "color": "",
                "stock": sin_vin,
                "estado": "Sin VIN",
                "tiene_vin": False,
                "descripcion": moto["descripcion"] or moto["nombre"],
            })

    # Apply filters
    if estado:
        result = [m for m in result if m["estado"].lower() == estado.lower()]
    if categoria:
        result = [m for m in result if categoria.lower() in m.get("categoria", "").lower()]

    return {"success": True, "data": result, "count": len(result)}


# --- Apartar ---

class ApartarRequest(BaseModel):
    vin: str
    cliente_nombre: str
    cliente_cedula: str
    cliente_telefono: str = ""
    monto_pago: float
    cuota_inicial_total: float
    banco_recibo: str
    plan_credito: str = ""


@router.post("/motos/{item_id}/apartar")
async def apartar_moto(
    item_id: str,
    body: ApartarRequest,
    alegra: AlegraClient = Depends(_get_alegra),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Reserve a moto by VIN:
    a) Verify VIN is registered in MongoDB and available
    b) Verify Alegra SKU has stock > 0
    c) Create journal in Alegra: D:banco / C:anticipos recibidos
    d) Create apartado in MongoDB keyed by VIN
    e) Publish event moto.apartada
    """
    # a) Verify VIN exists in MongoDB
    moto_reg = await db.inventario_motos.find_one({"vin": body.vin, "estado": "disponible"})
    if not moto_reg:
        raise HTTPException(
            status_code=404,
            detail=f"No hay moto disponible con VIN {body.vin}. Registre el VIN primero."
        )

    # b) Verify Alegra SKU stock
    try:
        item = await alegra.get(f"items/{item_id}")
    except AlegraError as e:
        raise HTTPException(status_code=404, detail=f"Item no encontrado en Alegra: {e}")

    inv = item.get("inventory") or {}
    stock = int(inv.get("availableQuantity", 0))
    if stock <= 0:
        raise HTTPException(status_code=400, detail="Moto sin stock disponible en Alegra")

    # Check no active apartado for this VIN
    existing = await db.apartados.find_one({"vin": body.vin, "estado": "activo"})
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe un apartado activo para VIN {body.vin} (cliente: {existing.get('cliente', {}).get('nombre', '?')})"
        )

    # Resolve bank account
    banco_cat_id = BANCO_CATEGORY_MAP.get(body.banco_recibo)
    if not banco_cat_id:
        raise HTTPException(
            status_code=400,
            detail=f"Banco no reconocido: {body.banco_recibo}. Opciones: {list(BANCO_CATEGORY_MAP.keys())}"
        )

    # c) Create journal in Alegra
    modelo = item.get("name", "Moto")
    obs = f"[CI] Apartado moto {modelo} VIN:{body.vin} -- {body.cliente_nombre} -- ${body.monto_pago:,.0f}"

    try:
        journal = await alegra.request_with_verify(
            "journals", "POST", {
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "observations": obs,
                "entries": [
                    {"id": banco_cat_id, "debit": body.monto_pago, "credit": 0},
                    {"id": ANTICIPOS_RECIBIDOS_ID, "debit": 0, "credit": body.monto_pago},
                ],
            }
        )
    except AlegraError as e:
        raise HTTPException(status_code=502, detail=f"Error creando journal en Alegra: {e}")

    alegra_journal_id = str(journal.get("id", ""))

    # d) Create apartado in MongoDB keyed by VIN
    now = datetime.now(timezone.utc)
    apartado = {
        "apartado_id": str(uuid.uuid4()),
        "vin": body.vin,
        "item_id_alegra": item_id,
        "modelo": modelo,
        "descripcion": item.get("description") or "",
        "cliente": {
            "nombre": body.cliente_nombre,
            "cedula": body.cliente_cedula,
            "telefono": body.cliente_telefono,
        },
        "cuota_inicial_total": body.cuota_inicial_total,
        "plan_credito": body.plan_credito,
        "pagos": [
            {
                "fecha": now.isoformat(),
                "monto": body.monto_pago,
                "alegra_journal_id": alegra_journal_id,
                "banco": body.banco_recibo,
            }
        ],
        "monto_acumulado": body.monto_pago,
        "monto_pendiente": body.cuota_inicial_total - body.monto_pago,
        "fecha_apartado": now.isoformat(),
        "fecha_limite": (now + timedelta(days=15)).isoformat(),
        "estado": "activo",
    }
    await db.apartados.insert_one(apartado)

    # Mark moto as apartada in inventario_motos
    await db.inventario_motos.update_one(
        {"vin": body.vin}, {"$set": {"estado": "apartada"}}
    )

    # e) Publish event
    await publish_event(
        db=db,
        event_type="moto.apartada",
        source="inventario",
        datos={
            "vin": body.vin,
            "item_id_alegra": item_id,
            "modelo": modelo,
            "cliente": body.cliente_nombre,
            "monto_pago": body.monto_pago,
            "cuota_inicial_total": body.cuota_inicial_total,
        },
        alegra_id=alegra_journal_id,
        accion_ejecutada=f"Moto {modelo} VIN:{body.vin} apartada para {body.cliente_nombre}",
    )

    return {
        "success": True,
        "alegra_journal_id": alegra_journal_id,
        "apartado_id": apartado["apartado_id"],
        "monto_acumulado": apartado["monto_acumulado"],
        "monto_pendiente": apartado["monto_pendiente"],
    }


# --- Pago parcial ---

class PagoParcialRequest(BaseModel):
    monto_pago: float
    banco_recibo: str


@router.post("/motos/{item_id}/pago-parcial")
async def pago_parcial(
    item_id: str,
    body: PagoParcialRequest,
    alegra: AlegraClient = Depends(_get_alegra),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Add partial payment to an active apartado. item_id can be VIN or Alegra ID."""
    # a) Find active apartado (try VIN first, then item_id_alegra)
    apartado = await db.apartados.find_one(
        {"vin": item_id, "estado": "activo"}
    )
    if not apartado:
        apartado = await db.apartados.find_one(
            {"item_id_alegra": item_id, "estado": "activo"}
        )
    if not apartado:
        raise HTTPException(status_code=404, detail="No hay apartado activo para este item/VIN")

    banco_cat_id = BANCO_CATEGORY_MAP.get(body.banco_recibo)
    if not banco_cat_id:
        raise HTTPException(
            status_code=400,
            detail=f"Banco no reconocido: {body.banco_recibo}"
        )

    # b) Journal in Alegra
    modelo = apartado.get("modelo", "Moto")
    cliente = apartado.get("cliente", {}).get("nombre", "")
    obs = f"[CI] Pago parcial apartado {modelo} -- {cliente} -- ${body.monto_pago:,.0f}"

    try:
        journal = await alegra.request_with_verify(
            "journals", "POST", {
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "observations": obs,
                "entries": [
                    {"id": banco_cat_id, "debit": body.monto_pago, "credit": 0},
                    {"id": ANTICIPOS_RECIBIDOS_ID, "debit": 0, "credit": body.monto_pago},
                ],
            }
        )
    except AlegraError as e:
        raise HTTPException(status_code=502, detail=f"Error creando journal en Alegra: {e}")

    alegra_journal_id = str(journal.get("id", ""))

    # c) Update apartado in MongoDB
    nuevo_acumulado = apartado["monto_acumulado"] + body.monto_pago
    nuevo_pendiente = apartado["cuota_inicial_total"] - nuevo_acumulado
    cuota_completa = nuevo_acumulado >= apartado["cuota_inicial_total"]

    nuevo_pago = {
        "fecha": datetime.now(timezone.utc).isoformat(),
        "monto": body.monto_pago,
        "alegra_journal_id": alegra_journal_id,
        "banco": body.banco_recibo,
    }

    update = {
        "$push": {"pagos": nuevo_pago},
        "$set": {
            "monto_acumulado": nuevo_acumulado,
            "monto_pendiente": max(nuevo_pendiente, 0),
        },
    }
    if cuota_completa:
        update["$set"]["estado"] = "completo"

    await db.apartados.update_one({"_id": apartado["_id"]}, update)

    # d) Event
    await publish_event(
        db=db,
        event_type="moto.pago_parcial",
        source="inventario",
        datos={
            "item_id_alegra": item_id,
            "monto_pago": body.monto_pago,
            "monto_acumulado": nuevo_acumulado,
            "cuota_completa": cuota_completa,
        },
        alegra_id=alegra_journal_id,
        accion_ejecutada=f"Pago parcial ${body.monto_pago:,.0f} para apartado {modelo}",
    )

    return {
        "success": True,
        "alegra_journal_id": alegra_journal_id,
        "monto_acumulado": nuevo_acumulado,
        "monto_pendiente": max(nuevo_pendiente, 0),
        "cuota_completa": cuota_completa,
    }


# --- Liberar ---

@router.post("/motos/{item_id}/liberar")
async def liberar_moto(
    item_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Release a reserved moto — set apartado to liberado. item_id can be VIN or Alegra ID."""
    apartado = await db.apartados.find_one({"vin": item_id, "estado": "activo"})
    if not apartado:
        apartado = await db.apartados.find_one(
            {"item_id_alegra": item_id, "estado": "activo"}
        )
    if not apartado:
        raise HTTPException(status_code=404, detail="No hay apartado activo para este item/VIN")

    await db.apartados.update_one(
        {"_id": apartado["_id"]},
        {"$set": {"estado": "liberado", "fecha_liberacion": datetime.now(timezone.utc).isoformat()}},
    )

    # Restore moto to disponible if it has a VIN
    vin = apartado.get("vin")
    if vin:
        await db.inventario_motos.update_one(
            {"vin": vin}, {"$set": {"estado": "disponible"}}
        )

    await publish_event(
        db=db,
        event_type="moto.liberada",
        source="inventario",
        datos={
            "item_id_alegra": item_id,
            "modelo": apartado.get("modelo", ""),
            "cliente": apartado.get("cliente", {}).get("nombre", ""),
        },
        alegra_id=None,
        accion_ejecutada=f"Moto {apartado.get('modelo', '')} liberada",
    )

    return {"success": True, "estado": "liberado"}


# ═══════════════════════════════════════════
# PARTE B: REPUESTOS Y KITS
# ═══════════════════════════════════════════


@router.get("/repuestos")
async def list_repuestos(
    service: AlegraItemsService = Depends(_get_items_service),
):
    """List repuestos from Alegra (non-moto product items)."""
    try:
        repuestos = await service.list_repuestos()
    except AlegraError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return {"success": True, "data": repuestos, "count": len(repuestos)}


# --- Kits (Opcion B: definitions in MongoDB, stock from Alegra) ---

class KitComponente(BaseModel):
    item_id_alegra: str
    cantidad: int


class KitDefinition(BaseModel):
    nombre: str
    modelo: str = ""
    tipo: str = ""
    componentes: list[KitComponente]
    precio_kit: float = 0


@router.post("/kits")
async def crear_kit(
    body: KitDefinition,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Create or update a kit definition in MongoDB (operational config, not accounting)."""
    kit_doc = {
        "nombre": body.nombre,
        "modelo": body.modelo,
        "tipo": body.tipo,
        "componentes": [c.model_dump() for c in body.componentes],
        "precio_kit": body.precio_kit,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    result = await db.kits_definiciones.update_one(
        {"nombre": body.nombre},
        {"$set": kit_doc},
        upsert=True,
    )

    return {
        "success": True,
        "upserted": result.upserted_id is not None,
        "nombre": body.nombre,
    }


@router.get("/kits")
async def list_kits(
    service: AlegraItemsService = Depends(_get_items_service),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    List kits with real-time stock calculation.
    Definitions from MongoDB, stock from Alegra.
    kits_disponibles = MIN(stock_componente / cantidad_requerida)
    """
    # Load kit definitions from MongoDB
    cursor = db.kits_definiciones.find()
    kits_defs = await cursor.to_list(length=100)

    if not kits_defs:
        return {"success": True, "data": [], "count": 0}

    # Collect all unique item IDs needed
    all_item_ids = set()
    for kit in kits_defs:
        for comp in kit.get("componentes", []):
            all_item_ids.add(comp["item_id_alegra"])

    # Fetch stock from Alegra for each component
    stock_map = {}
    for iid in all_item_ids:
        try:
            stock = await service.get_item_stock(iid)
            stock_map[iid] = stock
        except AlegraError:
            stock_map[iid] = 0

    # Calculate kits disponibles
    result = []
    for kit in kits_defs:
        componentes_detail = []
        min_kits = float("inf")
        limitante = None

        for comp in kit.get("componentes", []):
            iid = comp["item_id_alegra"]
            necesita = comp["cantidad"]
            stock = stock_map.get(iid, 0)
            alcanza = stock // necesita if necesita > 0 else 0

            componentes_detail.append({
                "item_id_alegra": iid,
                "nombre": iid,  # Would need item name lookup
                "stock_alegra": stock,
                "necesita": necesita,
                "alcanza_para": alcanza,
            })

            if alcanza < min_kits:
                min_kits = alcanza
                limitante = {
                    "item_id_alegra": iid,
                    "stock": stock,
                    "necesita": necesita,
                    "alcanza_para": alcanza,
                }

        kits_disp = min_kits if min_kits != float("inf") else 0

        result.append({
            "nombre": kit.get("nombre", ""),
            "modelo": kit.get("modelo", ""),
            "tipo": kit.get("tipo", ""),
            "precio_kit": kit.get("precio_kit", 0),
            "kits_disponibles": kits_disp,
            "componente_limitante": limitante,
            "componentes": componentes_detail,
            "alerta": kits_disp <= 3,
        })

    return {"success": True, "data": result, "count": len(result)}
