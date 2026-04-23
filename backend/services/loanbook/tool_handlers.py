"""
services/loanbook/tool_handlers.py — Handlers para las 11 tools del Agente Loanbook.

Cada handler recibe parámetros planos (no request/response), consulta MongoDB
y retorna un dict serializable. Sin I/O Alegra — el agente publica eventos y
el Contador actúa.

TOOL_HANDLERS mapea tool_name → función async para el dispatcher.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger("services.loanbook.tool_handlers")


# ─────────────────────── Helpers internos ─────────────────────────────────────

def _serialize(lb: dict) -> dict:
    """Resumen plano de un loanbook para respuestas del agente."""
    if not lb:
        return {}
    cliente = lb.get("cliente") or {}
    return {
        "codigo": lb.get("loanbook_id") or lb.get("loanbook_codigo"),
        "cliente": cliente.get("nombre") or lb.get("cliente_nombre"),
        "cedula": cliente.get("cedula") or lb.get("cliente_cedula"),
        "telefono": cliente.get("telefono") or lb.get("cliente_telefono"),
        "producto": lb.get("tipo_producto") or lb.get("producto"),
        "plan": lb.get("plan_codigo") or (lb.get("plan") or {}).get("codigo"),
        "modalidad": lb.get("modalidad") or lb.get("modalidad_pago"),
        "estado": lb.get("estado"),
        "dpd": lb.get("dpd", 0),
        "sub_bucket": lb.get("sub_bucket_semanal"),
        "saldo_cop": lb.get("saldo_pendiente") or lb.get("saldo_capital") or 0,
        "mora_acumulada_cop": lb.get("mora_acumulada_cop", 0),
        "cuotas_vencidas": sum(
            1 for c in (lb.get("cuotas") or [])
            if c.get("estado") in ("vencida", "parcial")
        ),
    }


async def _find_lb(db: "AsyncIOMotorDatabase", identificador: str) -> dict | None:
    """Busca loanbook por código, VIN o nombre parcial de cliente."""
    lb = await db.loanbook.find_one({
        "$or": [
            {"loanbook_id": identificador},
            {"loanbook_codigo": identificador},
            {"vin": identificador},
            {"cliente.nombre": {"$regex": identificador, "$options": "i"}},
        ]
    })
    return lb


# ─────────────────────── Handlers (7 read-only + 4 write) ─────────────────────

async def handle_consultar_loanbook(db: "AsyncIOMotorDatabase", busqueda: str) -> dict:
    """Consulta estado completo de un crédito por código, VIN o nombre."""
    lb = await _find_lb(db, busqueda)
    if not lb:
        return {"error": f"Crédito '{busqueda}' no encontrado"}
    result = _serialize(lb)
    # Agregar próxima cuota
    cuotas = lb.get("cuotas") or []
    proxima = next(
        (c for c in cuotas if c.get("estado") in ("pendiente", "vencida", "parcial")),
        None,
    )
    if proxima:
        result["proxima_cuota"] = {
            "numero": proxima.get("numero"),
            "fecha": proxima.get("fecha_programada") or proxima.get("fecha"),
            "monto_cop": proxima.get("monto") or proxima.get("monto_total", 0),
            "estado": proxima.get("estado"),
        }
    return result


async def handle_listar_loanbooks(
    db: "AsyncIOMotorDatabase",
    estado: str | None = None,
    producto: str | None = None,
    dpd_min: int | None = None,
    dpd_max: int | None = None,
    page: int = 1,
) -> dict:
    """Lista créditos con filtros opcionales. 20 por página."""
    query: dict[str, Any] = {}
    if estado:
        query["estado"] = estado
    if producto:
        query["$or"] = [{"tipo_producto": producto}, {"producto": producto}]
    if dpd_min is not None or dpd_max is not None:
        dpd_q: dict[str, Any] = {}
        if dpd_min is not None:
            dpd_q["$gte"] = dpd_min
        if dpd_max is not None:
            dpd_q["$lte"] = dpd_max
        query["dpd"] = dpd_q
    skip = (page - 1) * 20
    lbs = await db.loanbook.find(query).skip(skip).limit(20).to_list(20)
    total = await db.loanbook.count_documents(query)
    return {
        "total": total,
        "page": page,
        "pages": -(-total // 20),  # ceil division
        "loanbooks": [_serialize(lb) for lb in lbs],
    }


async def handle_consultar_mora(
    db: "AsyncIOMotorDatabase",
    vin: str | None = None,
    loanbook_codigo: str | None = None,
    bucket: str | None = None,
) -> dict:
    """Mora global o de un crédito específico."""
    query: dict[str, Any] = {"dpd": {"$gt": 0}}
    identificador = vin or loanbook_codigo
    if identificador:
        query["$or"] = [
            {"loanbook_id": identificador},
            {"loanbook_codigo": identificador},
            {"vin": identificador},
        ]
    if bucket:
        query["sub_bucket_semanal"] = bucket
    lbs = await db.loanbook.find(query).to_list(None)
    total_saldo = sum(
        float(lb.get("saldo_pendiente") or lb.get("saldo_capital") or 0) for lb in lbs
    )
    total_mora = sum(float(lb.get("mora_acumulada_cop", 0)) for lb in lbs)
    return {
        "en_mora": len(lbs),
        "valor_cartera_mora_cop": round(total_saldo),
        "mora_acumulada_total_cop": round(total_mora),
        "detalle": [
            {
                "codigo": lb.get("loanbook_id"),
                "cliente": (lb.get("cliente") or {}).get("nombre"),
                "dpd": lb.get("dpd"),
                "bucket": lb.get("sub_bucket_semanal"),
                "saldo_cop": lb.get("saldo_pendiente") or lb.get("saldo_capital"),
                "mora_cop": lb.get("mora_acumulada_cop", 0),
            }
            for lb in lbs
        ],
    }


async def handle_calcular_liquidacion(
    db: "AsyncIOMotorDatabase",
    vin: str | None = None,
    loanbook_codigo: str | None = None,
    fecha_liquidacion: str | None = None,
) -> dict:
    """Calcula monto total para liquidar anticipadamente un crédito."""
    from services.loanbook.amortizacion_service import calcular_liquidacion_anticipada

    identificador = vin or loanbook_codigo
    if not identificador:
        return {"error": "Se requiere vin o loanbook_codigo"}
    lb = await _find_lb(db, identificador)
    if not lb:
        return {"error": f"Crédito '{identificador}' no encontrado"}

    fecha = (
        date.fromisoformat(fecha_liquidacion[:10])
        if fecha_liquidacion
        else date.today()
    )
    return calcular_liquidacion_anticipada(lb, fecha)


async def handle_consultar_inventario(
    db: "AsyncIOMotorDatabase",
    modelo: str | None = None,
) -> dict:
    """Motos disponibles en inventario."""
    query: dict[str, Any] = {"estado": "disponible"}
    if modelo:
        query["$or"] = [
            {"modelo": {"$regex": modelo, "$options": "i"}},
            {"metadata_producto.moto_modelo": {"$regex": modelo, "$options": "i"}},
        ]
    motos = await db.inventario_motos.find(query).limit(50).to_list(50)
    for m in motos:
        m.pop("_id", None)
    return {"disponibles": len(motos), "motos": motos}


async def handle_consultar_cliente(
    db: "AsyncIOMotorDatabase",
    busqueda: str,
) -> dict:
    """Busca un cliente por cédula o nombre."""
    cliente = await db.crm_clientes.find_one({
        "$or": [
            {"cedula": busqueda},
            {"nombre": {"$regex": busqueda, "$options": "i"}},
        ]
    })
    if not cliente:
        return {"error": f"Cliente '{busqueda}' no encontrado"}
    cliente.pop("_id", None)
    # Agregar loanbooks asociados
    lbs = await db.loanbook.find(
        {"$or": [
            {"cliente.cedula": cliente.get("cedula")},
            {"cliente_cedula": cliente.get("cedula")},
        ]}
    ).to_list(20)
    cliente["loanbooks"] = [_serialize(lb) for lb in lbs]
    return cliente


async def handle_resumen_cartera(db: "AsyncIOMotorDatabase") -> dict:
    """Resumen ejecutivo del portafolio completo."""
    lbs = await db.loanbook.find({}).to_list(None)
    total = len(lbs)
    activos = sum(1 for lb in lbs if lb.get("estado") not in ("saldado", "castigado", "Charge-Off"))
    en_mora = sum(1 for lb in lbs if (lb.get("dpd") or 0) > 0)
    cartera_total = sum(float(lb.get("saldo_pendiente") or lb.get("saldo_capital") or 0) for lb in lbs)
    recaudo_semanal = sum(
        float(lb.get("cuota_monto") or lb.get("cuota_periodica") or 0)
        for lb in lbs
        if lb.get("modalidad") in ("semanal", None)
        and lb.get("estado") not in ("saldado", "castigado")
    )
    por_estado: dict[str, int] = {}
    for lb in lbs:
        est = lb.get("estado") or "desconocido"
        por_estado[est] = por_estado.get(est, 0) + 1
    return {
        "total_creditos": total,
        "activos": activos,
        "en_mora": en_mora,
        "cartera_total_cop": round(cartera_total),
        "recaudo_semanal_esperado_cop": round(recaudo_semanal),
        "por_estado": por_estado,
    }


# ─────────────────────── Write handlers ───────────────────────────────────────

async def handle_registrar_apartado(
    db: "AsyncIOMotorDatabase",
    vin: str,
    cliente: dict,
    plan_codigo: str,
    modelo: str,
    modalidad: str,
    fecha_entrega: str,
    fecha_primer_pago: str | None = None,
) -> dict:
    """Aparta una moto y crea el loanbook en estado pendiente_entrega."""
    moto = await db.inventario_motos.find_one({"vin": vin})
    if not moto:
        return {"error": f"Moto VIN {vin} no encontrada en inventario"}
    if moto.get("estado") != "disponible":
        return {"error": f"Moto VIN {vin} no está disponible (estado: {moto.get('estado')})"}
    # Delegamos: publicar evento para que el listener cree el loanbook
    import uuid
    from datetime import timezone
    evento = {
        "event_id": str(uuid.uuid4()),
        "event_type": "apartado.iniciado",
        "source": "agente_loanbook",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "datos": {
            "vin": vin,
            "cliente": cliente,
            "plan_codigo": plan_codigo,
            "modelo": modelo,
            "modalidad": modalidad,
            "fecha_entrega": fecha_entrega,
            "fecha_primer_pago": fecha_primer_pago,
        },
    }
    await db.roddos_events.insert_one(evento)
    return {"ok": True, "mensaje": f"Evento apartado.iniciado publicado para VIN {vin}"}


async def handle_registrar_pago_parcial(
    db: "AsyncIOMotorDatabase",
    vin: str,
    monto: float,
    referencia: str,
) -> dict:
    """Registra pago parcial del apartado."""
    lb = await db.loanbook.find_one({"vin": vin})
    if not lb:
        return {"error": f"Loanbook para VIN {vin} no encontrado"}
    pagado_previo = float(lb.get("cuota_inicial_pagada") or 0)
    nuevo_total = pagado_previo + monto
    await db.loanbook.update_one(
        {"_id": lb["_id"]},
        {"$set": {"cuota_inicial_pagada": nuevo_total, "updated_at": datetime.utcnow()}},
    )
    return {
        "ok": True,
        "vin": vin,
        "monto_pagado": monto,
        "total_acumulado_cop": nuevo_total,
        "referencia": referencia,
    }


async def handle_registrar_entrega(
    db: "AsyncIOMotorDatabase",
    vin: str,
    fecha_entrega: str,
    fecha_primer_pago: str | None = None,
) -> dict:
    """Publica evento entrega.realizada para activar el loanbook."""
    import uuid
    from datetime import timezone
    lb = await db.loanbook.find_one({"vin": vin})
    if not lb:
        return {"error": f"Loanbook para VIN {vin} no encontrado"}
    evento = {
        "event_id": str(uuid.uuid4()),
        "event_type": "entrega.realizada",
        "source": "agente_loanbook",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "datos": {
            "vin": vin,
            "loanbook_id": lb.get("loanbook_id"),
            "fecha_entrega": fecha_entrega,
            "fecha_primer_pago": fecha_primer_pago,
        },
    }
    await db.roddos_events.insert_one(evento)
    return {"ok": True, "mensaje": f"Evento entrega.realizada publicado para VIN {vin}"}


async def handle_registrar_pago_cuota(
    db: "AsyncIOMotorDatabase",
    vin: str,
    monto: float,
    fecha_pago: str,
    banco: str,
) -> dict:
    """Registra pago de cuota aplicando waterfall ANZI → mora → cuotas."""
    from services.loanbook.amortizacion_service import aplicar_waterfall

    lb = await db.loanbook.find_one({"vin": vin})
    if not lb:
        return {"error": f"Loanbook para VIN {vin} no encontrado"}

    fecha = date.fromisoformat(fecha_pago[:10])
    if fecha > date.today():
        return {"error": f"No se puede registrar pago con fecha futura: {fecha_pago}"}

    resultado = aplicar_waterfall(lb, monto, fecha)
    cuotas_nuevas = resultado["cuotas_actualizadas"]
    saldo_nuevo = resultado["saldo_capital_nuevo"]

    await db.loanbook.update_one(
        {"_id": lb["_id"]},
        {
            "$set": {
                "cuotas": cuotas_nuevas,
                "saldo_capital": saldo_nuevo,
                "saldo_pendiente": saldo_nuevo,
                "fecha_ultimo_pago": fecha_pago,
                "updated_at": datetime.utcnow(),
            }
        },
    )

    # Publicar evento
    import uuid
    from datetime import timezone
    await db.roddos_events.insert_one({
        "event_id": str(uuid.uuid4()),
        "event_type": "cuota.pagada",
        "source": "agente_loanbook",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "datos": {**resultado["evento_payload"], "banco": banco},
    })

    return {"ok": True, "desglose": resultado["evento_payload"]}


# ─────────────────────── Dispatcher map ───────────────────────────────────────

TOOL_HANDLERS: dict[str, Any] = {
    # Read-only (7)
    "consultar_loanbook": handle_consultar_loanbook,
    "listar_loanbooks": handle_listar_loanbooks,
    "consultar_mora": handle_consultar_mora,
    "calcular_liquidacion": handle_calcular_liquidacion,
    "consultar_inventario": handle_consultar_inventario,
    "consultar_cliente": handle_consultar_cliente,
    "resumen_cartera": handle_resumen_cartera,
    # Write (4)
    "registrar_apartado": handle_registrar_apartado,
    "registrar_pago_parcial": handle_registrar_pago_parcial,
    "registrar_entrega": handle_registrar_entrega,
    "registrar_pago_cuota": handle_registrar_pago_cuota,
}
