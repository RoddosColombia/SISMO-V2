"""
scripts/fix_loanbooks_excel_v1_format.py - Convierte 14 loanbooks importados
del Excel V1 al formato canonico que espera el frontend.

Problema: subir_loanbooks_excel_v1.py creo docs con estructura PLANA
(cliente_nombre, moto_vin, fecha_factura, etc.) pero el frontend espera
estructura ANIDADA (cliente.nombre, moto.vin, fechas.factura, etc.).

Este script LEE cada doc con via=import_excel_v1, construye los campos
anidados que faltan, y hace update_one preservando los datos originales.

Idempotente: si el campo cliente.nombre ya existe, salta.

Uso:
    cd /opt/render/project/src/backend
    python3 scripts/fix_loanbooks_excel_v1_format.py --dry-run
    python3 scripts/fix_loanbooks_excel_v1_format.py --ejecutar

Sprint 2026-04-28 - Fix urgente para frontend.
"""
from __future__ import annotations
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

_THIS = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_THIS)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from motor.motor_asyncio import AsyncIOMotorClient


ESTADO_CREDITO_TO_FRONTEND = {
    "activo":             "Current",
    "mora":               "Early Delinquency",
    "saldado":            "Pagado",
    "pendiente_entrega":  "Pendiente Entrega",
}

PRODUCTO_TO_TIPO = {
    "RAIDER 125": "moto",
    "SPORT 100":  "moto",
    "COMPARENDO": "comparendo",
    "LICENCIA":   "licencia",
}


def _construir_campos_anidados(doc: dict) -> dict:
    """Construye los campos anidados que el frontend espera."""
    meta = doc.get("metadata_producto", {})
    moto_modelo = meta.get("moto_modelo", "")
    moto_vin = meta.get("moto_vin", "")
    moto_motor = meta.get("moto_motor", "")
    capital_plan = meta.get("moto_valor_origen", doc.get("monto_original", 0))
    excel_import = meta.get("excel_v1_import", {})
    saldo_excel = excel_import.get("saldo_excel", doc.get("monto_original", 0))
    cuotas_pagadas = excel_import.get("cuotas_pagadas_historicas", 0)
    cuotas_vencidas = excel_import.get("cuotas_vencidas_historicas", 0)
    valor_total = excel_import.get("valor_total_excel", 0)

    es_moto = moto_vin != "" and moto_vin is not None
    tipo_producto = PRODUCTO_TO_TIPO.get(moto_modelo, "moto" if es_moto else "comparendo")

    cliente_block = {
        "nombre":               doc.get("cliente_nombre", ""),
        "cedula":               doc.get("cliente_cedula", ""),
        "telefono":             doc.get("cliente_telefono", ""),
        "telefono_alternativo": meta.get("telefono_alternativo", "") or None,
    }

    moto_block = None
    if es_moto:
        moto_block = {
            "modelo": moto_modelo,
            "vin":    moto_vin,
            "motor":  moto_motor,
        }

    plan_block = {
        "codigo":        doc.get("plan_codigo", ""),
        "modalidad":     doc.get("modalidad_pago", "semanal"),
        "cuota_valor":   doc.get("cuota_periodica", 0),
        "cuota_inicial": doc.get("cuota_inicial", 0),
        "total_cuotas":  doc.get("total_cuotas", 0),
    }

    fechas_block = {
        "factura":       doc.get("fecha_factura"),
        "entrega":       doc.get("fecha_entrega"),
        "primera_cuota": doc.get("fecha_cuota_1"),
    }

    estado_credito = doc.get("estado_credito", "activo")
    estado_frontend = ESTADO_CREDITO_TO_FRONTEND.get(estado_credito, "Current")

    saldo_pendiente = saldo_excel if saldo_excel else doc.get("monto_original", 0)

    return {
        # --- Campos anidados que el frontend lee ---
        "tipo_producto":     tipo_producto,
        "cliente":           cliente_block,
        "moto":              moto_block,
        "plan":              plan_block,
        "fechas":            fechas_block,
        "estado":            estado_frontend,
        "valor_total":       valor_total or doc.get("monto_original", 0),
        "saldo_pendiente":   saldo_pendiente,
        "cuotas_pagadas":    cuotas_pagadas,
        "cuotas_vencidas":   cuotas_vencidas,
        "cuotas_total":      doc.get("total_cuotas", 0),
        "alegra_factura_id": doc.get("factura_alegra_id"),
        # Campos planos legacy que tambien lee el frontend
        "vin":               moto_vin or None,
        "modelo":            moto_modelo,
        "modalidad":         doc.get("modalidad_pago", "semanal"),
        "plan_codigo":       doc.get("plan_codigo", ""),
        "cuota_monto":       doc.get("cuota_periodica", 0),
        "num_cuotas":        doc.get("total_cuotas", 0),
        # Calculos contables (placeholders para que el frontend no rompa)
        "saldo_capital":     int(capital_plan * (1 - cuotas_pagadas / max(doc.get("total_cuotas", 1), 1))),
        "total_pagado":      cuotas_pagadas * doc.get("cuota_periodica", 0),
        "total_mora_pagada": 0,
        "total_anzi_pagado": 0,
        "anzi_pct":          0.02 if es_moto else 0.0,
        "fecha_entrega":     doc.get("fecha_entrega"),
        "fecha_primer_pago": doc.get("fecha_cuota_1"),
        "saldo_intereses":   max(int(valor_total - capital_plan), 0) if valor_total else 0,
        "score_riesgo":      None,
        "sub_bucket_semanal": None,
        "subtipo_rodante":   doc.get("subtipo_rodante"),
        "whatsapp_status":   "pending",
        "dpd":               0,
        "mora_acumulada_cop": 0,
        "capital_plan":      capital_plan,
        "cuota_estandar_plan": doc.get("cuota_periodica", 0),
        "proxima_cuota":     None if estado_credito == "saldado" else {
            "fecha": doc.get("fecha_cuota_1") or doc.get("fecha_factura"),
            "monto": doc.get("cuota_periodica", 0),
        },
        "acuerdo_activo_id": None,
        "fecha_vencimiento": None,
        "migrated_from_v1":  True,
        "created_at":        doc.get("fecha_creacion"),
        "updated_at":        datetime.now(timezone.utc),
    }


async def main(args) -> None:
    mongo_url = os.environ.get("MONGO_URL", "")
    db_name = os.environ.get("DB_NAME", "")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL o DB_NAME no configurados")
        sys.exit(1)

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    contador = {"total": 0, "actualizados": 0, "ya_correctos": 0, "errores": []}

    try:
        async for doc in db.loanbook.find({"via": "import_excel_v1"}):
            contador["total"] += 1
            lb_id = doc.get("loanbook_id", "?")
            cliente_anidado = doc.get("cliente")

            # Idempotente: si ya tiene cliente.nombre, ya esta migrado
            if isinstance(cliente_anidado, dict) and cliente_anidado.get("nombre"):
                contador["ya_correctos"] += 1
                print(f"  {lb_id} ya tiene formato correcto, skip")
                continue

            try:
                campos_nuevos = _construir_campos_anidados(doc)
                if not args.ejecutar:
                    print(f"  {lb_id} DRY_RUN agregaria: {sorted(campos_nuevos.keys())[:8]}...")
                    contador["actualizados"] += 1
                    continue

                await db.loanbook.update_one(
                    {"_id": doc["_id"]},
                    {"$set": campos_nuevos},
                )
                contador["actualizados"] += 1
                print(f"  {lb_id} OK actualizado ({doc.get('cliente_nombre', '?')[:30]})")
            except Exception as exc:
                contador["errores"].append({"loanbook_id": lb_id, "error": str(exc)})
                print(f"  {lb_id} ERROR: {exc}")

        print(f"\n{'='*60}")
        print(f"RESUMEN ({'EJECUCION REAL' if args.ejecutar else 'DRY-RUN'}):")
        print(f"  Total docs import_excel_v1: {contador['total']}")
        print(f"  Ya correctos (skip):        {contador['ya_correctos']}")
        print(f"  Actualizados:               {contador['actualizados']}")
        if contador["errores"]:
            print(f"  ERRORES ({len(contador['errores'])}):")
            for e in contador["errores"]:
                print(f"    {e['loanbook_id']}: {e['error']}")
        print(f"{'='*60}")
        if not args.ejecutar:
            print("\nPara ejecutar real, correr con --ejecutar")
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ejecutar", action="store_true",
                        help="Aplica cambios reales. Sin esto es dry-run.")
    args = parser.parse_args()
    asyncio.run(main(args))
