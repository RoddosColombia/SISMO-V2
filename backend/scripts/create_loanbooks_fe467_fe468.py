"""
Create 2 loanbooks for motorcycle invoices FE467 + FE468 that were
billed directly in Alegra today (2026-04-15 and 2026-04-16).

Data from Alegra:
  FE467 (2026-04-15): Richard Jose Millan Grimont CC 6145958
                       TVS Sport 100, VIN 9FLT81000VDB62403, Motor RF5AT14A5361
  FE468 (2026-04-16): Samir Andres Garcia Venegas CC 1082969662
                       TVS Sport 100, VIN 9FLT81000VDB62417, Motor RF5AT17A5427
                       PROMO SIN CUOTA INICIAL

Rules:
  - estado: "pendiente_entrega" (cronograma se genera al registrar entrega)
  - cuotas: [] (vacío)
  - Anti-dup por VIN
  - Upsert CRM contact si no existe

Run:
  $env:MONGO_URL = "..."
  $env:DB_NAME = "sismo-v2"
  python -m scripts.create_loanbooks_fe467_fe468
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient


NEW_LOANBOOKS = [
    {
        "loanbook_id": "LB-2026-0027",
        "cedula": "6145958",
        "nombre": "Richard Jose Millan Grimont",
        "telefono": "573155237548",  # existente en CRM
        "email": None,
        "modelo": "TVS Sport 100",
        "vin": "9FLT81000VDB62403",
        "motor": "RF5AT14A5361",
        "factura": "FE467",
        "fecha_factura": "2026-04-15",
        "valor_total": 6_492_800,
        "cuota_inicial_default": 1_160_000,  # promedio Sport 100
        "notas": "Credito creado desde Alegra FE467; plan y cuota pendientes de definir en entrega",
    },
    {
        "loanbook_id": "LB-2026-0028",
        "cedula": "1082969662",
        "nombre": "Samir Andres Garcia Venegas",
        "telefono": "573024743216",
        "email": "venegasseleccion@gmail.com",
        "modelo": "TVS Sport 100",
        "vin": "9FLT81000VDB62417",
        "motor": "RF5AT17A5427",
        "factura": "FE468",
        "fecha_factura": "2026-04-16",
        "valor_total": 6_492_800,
        "cuota_inicial_default": 0,  # PROMO SIN CUOTA INICIAL
        "notas": "Credito creado desde Alegra FE468 con PROMO SIN CUOTA INICIAL; plan pendiente de definir",
    },
]


def _build_loanbook_doc(row: dict) -> dict:
    return {
        "loanbook_id": row["loanbook_id"],
        "tipo_producto": "moto",
        "cliente": {
            "nombre": row["nombre"],
            "cedula": row["cedula"],
            "telefono": row["telefono"],
            "telefono_alternativo": None,
        },
        "moto": {
            "modelo": row["modelo"],
            "vin": row["vin"],
            "motor": row["motor"],
        },
        "plan": {
            "codigo": None,  # se define al registrar entrega
            "modalidad": "semanal",  # default
            "cuota_valor": 0,
            "cuota_inicial": row["cuota_inicial_default"],
            "total_cuotas": 0,
        },
        "fechas": {
            "factura": row["fecha_factura"],
            "entrega": None,
            "primera_cuota": None,
        },
        "cuotas": [],
        "estado": "pendiente_entrega",
        "valor_total": row["valor_total"],
        "saldo_pendiente": row["valor_total"],
        "cuotas_pagadas": 0,
        "cuotas_vencidas": 0,
        "cuotas_total": 0,
        "alegra_factura_id": row["factura"],
        # Compat fields
        "vin": row["vin"],
        "modelo": row["modelo"],
        "modalidad": "semanal",
        "plan_codigo": None,
        "cuota_monto": 0,
        "num_cuotas": 0,
        "saldo_capital": row["valor_total"],
        "total_pagado": 0,
        "total_mora_pagada": 0,
        "total_anzi_pagado": 0,
        "anzi_pct": 0.02,
        "fecha_entrega": None,
        "fecha_primer_pago": None,
        "notas_migracion": row["notas"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "origen": "alegra_direct_invoice",
    }


async def run() -> None:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "sismo-v2")
    if not mongo_url:
        raise RuntimeError("MONGO_URL env var is required.")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    print(f"Connected to {db_name}")

    inserted_lbs = 0
    inserted_crm = 0
    updated_crm = 0

    for row in NEW_LOANBOOKS:
        # Anti-dup por VIN
        existing = await db.loanbook.find_one({"vin": row["vin"]})
        if existing:
            print(f"  SKIP {row['loanbook_id']} — VIN {row['vin']} ya existe como {existing['loanbook_id']}")
            continue

        doc = _build_loanbook_doc(row)
        await db.loanbook.insert_one(doc)
        inserted_lbs += 1
        print(f"  OK   {row['loanbook_id']} — {row['nombre']} ({row['factura']})")

        # Upsert CRM
        existing_crm = await db.crm_clientes.find_one({"cedula": row["cedula"]})
        if existing_crm:
            await db.crm_clientes.update_one(
                {"cedula": row["cedula"]},
                {
                    "$addToSet": {"loanbook_ids": row["loanbook_id"]},
                    "$set": {
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        # Enriquecer datos si vienen de Alegra y no existían
                        **({"email": row["email"]} if row["email"] and not existing_crm.get("email") else {}),
                    },
                    "$inc": {"loanbooks": 1},
                },
            )
            updated_crm += 1
        else:
            crm_doc = {
                "cedula": row["cedula"],
                "nombre": row["nombre"],
                "telefono": row["telefono"],
                "email": row["email"],
                "estado": "activo",
                "loanbook_ids": [row["loanbook_id"]],
                "loanbooks": 1,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            await db.crm_clientes.insert_one(crm_doc)
            inserted_crm += 1

    print(f"\nLoanbooks insertados: {inserted_lbs}")
    print(f"CRM insertados: {inserted_crm}")
    print(f"CRM actualizados: {updated_crm}")

    total_lb = await db.loanbook.count_documents({})
    pend = await db.loanbook.count_documents({"estado": "pendiente_entrega"})
    print(f"\nTotal loanbooks en MongoDB: {total_lb}")
    print(f"Pendiente entrega: {pend}")

    client.close()


if __name__ == "__main__":
    asyncio.run(run())
