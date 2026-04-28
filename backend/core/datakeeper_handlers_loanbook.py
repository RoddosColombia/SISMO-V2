"""
DataKeeper handlers para el dominio Loanbook.

Cada handler responde a un evento del bus y ejecuta una accion deterministica.
Sigue ROG-4b: solo escribe en colecciones de su dominio (loanbook,
inventario_motos vendida, apartados).

Eventos manejados:
- factura.venta.creada -> crear_loanbook_pendiente (Critical)
- entrega.realizada    -> activar_cronograma_loanbook (Critical) - migracion del flujo manual
- loanbook.saldado     -> cerrar_loanbook_paz_salvo (Parallel)

Sprint S1.5 - cierre del bucle factura -> loanbook automatico.
"""
from __future__ import annotations
import logging
from core.datetime_utils import today_bogota
from datetime import date, datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from core.event_handlers import on_event
from core.events import publish_event
from core.loanbook_model import (
    crear_loanbook,
    calcular_cronograma,
    MODALIDADES,
    VENTA_CONTADO,
)

logger = logging.getLogger("datakeeper.loanbook")


# ─────────────────────────────────────────────────────────────────────────────
# crear_loanbook_pendiente — Critical en factura.venta.creada
# ─────────────────────────────────────────────────────────────────────────────

@on_event("factura.venta.creada", critical=True)
async def handle_crear_loanbook_pendiente(event: dict, db: AsyncIOMotorDatabase) -> None:
    """
    Cuando el Contador (o webhook Alegra) emite factura.venta.creada con datos
    de venta de moto a credito, este handler crea el loanbook en estado
    pendiente_entrega y marca la moto como vendida.

    Idempotente: si ya existe loanbook con el mismo factura_alegra_id, salta.

    Despues publica loanbook.creado para que crm_handlers cree el cliente CRM.
    """
    datos = event.get("datos", {}) or {}

    factura_id = datos.get("alegra_invoice_id") or event.get("alegra_id") or datos.get("factura_id")
    if not factura_id:
        logger.warning("crear_loanbook_pendiente — factura sin alegra_id, saltando")
        return

    # Solo procesar facturas de venta de moto a credito (modalidad != contado)
    modalidad = (datos.get("modalidad") or datos.get("modo_pago") or "").lower()
    if modalidad in (VENTA_CONTADO, "", "contado"):
        logger.info(
            f"factura {factura_id} es contado/sin modalidad — no crea loanbook"
        )
        return

    if modalidad not in MODALIDADES:
        logger.warning(
            f"factura {factura_id} modalidad '{modalidad}' invalida — saltando"
        )
        return

    vin = (datos.get("vin") or datos.get("moto_vin") or "").strip().upper()
    if not vin:
        logger.warning(f"factura {factura_id} sin VIN — no crea loanbook")
        return

    # Idempotencia
    existing = await db.loanbook.find_one({"factura_alegra_id": str(factura_id)})
    if existing:
        logger.info(
            f"loanbook ya existe para factura {factura_id} (lb {existing.get('loanbook_id')}) — saltando"
        )
        return

    # quincenal/mensual requieren fecha_primer_pago. En pendiente_entrega
    # no la tenemos todavia, asi que para esos casos no creamos el loanbook
    # automaticamente — debe registrarse via apartar_moto manual del agente
    # Loanbook que pide la fecha. Solo automatizamos semanal por ahora.
    if modalidad != "semanal":
        logger.info(
            f"factura {factura_id} modalidad '{modalidad}' requiere fecha_primer_pago "
            "manual; creacion de loanbook diferida al flujo apartar_moto del agente Loanbook"
        )
        return

    # Lookup plan
    plan_codigo = datos.get("plan", "P52S")
    plan = await db.catalogo_planes.find_one({"plan_codigo": plan_codigo}) \
        or await db.catalogo_planes.find_one({"codigo": plan_codigo})
    if not plan:
        logger.error(
            f"factura {factura_id}: plan '{plan_codigo}' no existe en catalogo_planes — abortando"
        )
        raise ValueError(f"Plan {plan_codigo} no encontrado en catalogo_planes")

    # Normalizar nombres del plan: el modelo de loanbook usa 'codigo', muchos
    # docs viejos usan 'plan_codigo'. Aliasing para que crear_loanbook funcione.
    plan = dict(plan)
    plan.setdefault("codigo", plan.get("plan_codigo", plan_codigo))

    # Cliente
    cliente = {
        "nombre":   datos.get("cliente_nombre", ""),
        "cedula":   datos.get("cliente_cedula", ""),
        "telefono": datos.get("cliente_telefono", ""),
        "email":    datos.get("cliente_email", ""),
        "direccion": datos.get("cliente_direccion", ""),
    }

    # Modelo: para motos viene como "TVS Raider 125" / "TVS Sport 100"
    modelo = datos.get("modelo") or datos.get("moto_modelo") or "TVS Raider 125"

    # Para pendiente_entrega, fecha_entrega se setea como fecha de la factura
    # (placeholder); cuando se registre entrega real, se recalcula cronograma.
    fecha_factura_str = datos.get("fecha") or today_bogota().isoformat()
    try:
        fecha_entrega = date.fromisoformat(fecha_factura_str[:10])
    except Exception:
        fecha_entrega = today_bogota()

    try:
        lb = crear_loanbook(
            vin=vin,
            cliente=cliente,
            plan=plan,
            modelo=modelo,
            modalidad=modalidad,
            fecha_entrega=fecha_entrega,
            fecha_primer_pago=None,
        )
    except ValueError as e:
        logger.error(
            f"factura {factura_id}: crear_loanbook fallo: {e} — abortando"
        )
        raise

    # Anotar la factura para idempotencia futura
    lb["factura_alegra_id"] = str(factura_id)
    lb["origen_creacion"] = "datakeeper.factura.venta.creada"

    # B0.4: Patchear con capital_plan + saldos canonicos para que la cartera
    # total del frontend refleje correctamente. crear_loanbook() pone
    # saldo_capital = num_cuotas * cuota_monto que es plano (no separa).
    capital_plan_val = plan.get("capital_plan") or 0
    if not capital_plan_val:
        # Fallback: para Raider/Sport usar precios canonicos. Para RODANTE
        # usar cuota * num_cuotas (no hay capital separado).
        cuotas_modelo = plan.get("cuotas_modelo") or {}
        capital_plan_val = cuotas_modelo.get(modelo, lb["num_cuotas"] * lb["cuota_monto"])

    cuota_inicial_plan = plan.get("cuota_inicial", 0) or 0
    valor_total = lb["num_cuotas"] * lb["cuota_monto"]
    saldo_intereses = max(0, valor_total - capital_plan_val + cuota_inicial_plan)

    lb["capital_plan"] = capital_plan_val
    lb["cuota_estandar_plan"] = lb["cuota_monto"]
    lb["monto_original"] = valor_total
    lb["valor_total"] = valor_total
    lb["saldo_pendiente"] = valor_total  # = monto_original — lo que muestra cartera total
    lb["saldo_intereses"] = saldo_intereses
    lb["saldo_capital"] = capital_plan_val
    lb["cuota_inicial"] = cuota_inicial_plan
    lb["dpd"] = 0
    lb["mora_acumulada_cop"] = 0
    lb["cuotas_pagadas"] = 0
    lb["cuotas_vencidas"] = 0
    lb["cuotas_total"] = lb["num_cuotas"]
    lb["whatsapp_status"] = "pending"

    await db.loanbook.insert_one(lb)
    logger.info(
        f"loanbook creado: lb={lb['loanbook_id']} vin={vin} factura={factura_id} estado=pendiente_entrega"
    )

    # Marcar moto como vendida (mutex Loanbook)
    await db.inventario_motos.update_one(
        {"vin": vin},
        {"$set": {"estado": "vendida", "fecha_venta": fecha_entrega.isoformat(),
                  "factura_alegra_id": str(factura_id)}},
    )

    # Publicar loanbook.creado para que crm_handlers (Critical) cree el cliente
    await publish_event(
        db=db,
        event_type="loanbook.creado",
        source="datakeeper",
        datos={
            "loanbook_id": lb["loanbook_id"],
            "vin": vin,
            "factura_alegra_id": str(factura_id),
            "cliente": cliente,
            "plan_codigo": plan_codigo,
            "modelo": modelo,
            "modalidad": modalidad,
        },
        alegra_id=str(factura_id),
        accion_ejecutada=f"Loanbook creado desde factura {factura_id}",
        correlation_id=event.get("correlation_id"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# activar_cronograma_loanbook — Critical en entrega.realizada
# (puente: el flujo manual de registrar_entrega ya ejecuta esto, pero si en
# el futuro la entrega se registra desde otro canal, este handler se asegura
# de regenerar el cronograma con la fecha real de entrega)
# ─────────────────────────────────────────────────────────────────────────────

@on_event("entrega.realizada", critical=True)
async def handle_activar_cronograma_loanbook(event: dict, db: AsyncIOMotorDatabase) -> None:
    """
    Cuando se registra una entrega, asegurar que el loanbook este en estado
    activo con cronograma calculado. Idempotente: si ya esta activo, salta.

    NOTA: el flujo manual via agent.loanbook.registrar_entrega ya hace esto.
    Este handler es defensivo — en caso de que entrega.realizada se publique
    desde otro origen (futuro: webhook taller, app movil, etc.).
    """
    datos = event.get("datos", {}) or {}
    vin = (datos.get("vin") or "").strip().upper()
    if not vin:
        logger.warning("entrega.realizada sin VIN — saltando")
        return

    lb = await db.loanbook.find_one({"vin": vin})
    if not lb:
        logger.warning(f"entrega.realizada VIN {vin}: no existe loanbook — saltando")
        return

    if lb.get("estado") != "pendiente_entrega":
        # Ya activo o terminal — idempotente, nada que hacer
        return

    # Recalcular cronograma con la fecha real de entrega
    fecha_entrega_str = datos.get("fecha_entrega") or today_bogota().isoformat()
    try:
        fecha_entrega = date.fromisoformat(fecha_entrega_str[:10])
    except Exception:
        fecha_entrega = today_bogota()

    cuotas = lb.get("cuotas") or []
    fechas = calcular_cronograma(
        fecha_entrega=fecha_entrega,
        modalidad=lb["modalidad"],
        num_cuotas=len(cuotas),
        fecha_primer_pago=None,
    )
    for c, f in zip(cuotas, fechas):
        if c.get("fecha") is None:
            c["fecha"] = f.isoformat()

    await db.loanbook.update_one(
        {"vin": vin},
        {"$set": {
            "estado": "activo",
            "fecha_entrega": fecha_entrega.isoformat(),
            "cuotas": cuotas,
        }},
    )
    logger.info(f"loanbook {lb.get('loanbook_id')} activado con cronograma vin={vin}")


@on_event("loanbook.saldado", critical=False)
async def handle_cerrar_loanbook_paz_salvo(event: dict, db: AsyncIOMotorDatabase) -> None:
    """Marca cliente CRM con paz_y_salvo + registra gestion de cierre."""
    datos = event.get("datos", {}) or {}
    cedula = datos.get("cliente_cedula", "")
    vin = datos.get("vin", "")
    if not cedula:
        logger.warning("loanbook.saldado sin cedula - saltando CRM update")
        return
    await db.crm_clientes.update_one(
        {"cedula": cedula},
        {
            "$set": {"estado": "saldado"},
            "$addToSet": {"tags": "paz_y_salvo"},
            "$push": {
                "gestiones": {
                    "tipo": "cierre_credito",
                    "fecha": datetime.now(timezone.utc).isoformat(),
                    "vin": vin,
                    "loanbook_id": datos.get("loanbook_id"),
                    "nota": f"Credito saldado, paz y salvo - VIN {vin}",
                }
            },
        },
    )
    logger.info(f"CRM cliente {cedula} marcado paz_y_salvo - vin={vin}")
