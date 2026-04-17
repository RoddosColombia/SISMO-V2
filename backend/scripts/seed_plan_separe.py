"""
Seed 6 Plan Separe records (real operational data).

Regla: como es seed manual, NO genera journals en Alegra automáticamente.
El equipo Contabilidad debe registrar los journals históricos manualmente
via POST /api/plan-separe/{id}/abono cuando sea el momento, O ingresar el
journal directo en Alegra si ya estaba causado.

Los abonos aquí se marcan como "alegra_journal_id=null, pre_existente=true"
para que quede registro operacional sin duplicar contabilidad.

Run:
  $env:MONGO_URL = "..."
  $env:DB_NAME = "sismo-v2"
  python -m scripts.seed_plan_separe
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date, datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient


SEPARACIONES = [
    # (n, cc, tipo_doc, nombre, tel, pagado, estado_esperado)
    ("001", "6998154", "PPT", "Antony Rico", "",          1_460_000, "completada"),
    ("002", "6554194", "PPT", "Eduar Rojas", "",          1_460_000, "completada"),
    ("003", "1067163281", "CC", "Jorge Suarez", "",         500_000, "activa"),
    ("004", "5522635", "PPT", "Brandon Ramirez", "",        500_000, "activa"),
    ("005", "6226257", "PPT", "Diego Moises", "",           600_000, "activa"),
    ("006", "1103216616", "CC", "Manuel David", "",         600_000, "activa"),
]

CUOTA_INICIAL = 1_460_000
MODELO = "Raider 125 2027"
PRECIO_MOTO = 8_190_000
MATRICULA = 580_000


async def run() -> None:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "sismo-v2")
    if not mongo_url:
        raise RuntimeError("MONGO_URL env var is required.")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    print(f"Connected to {db_name}")

    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    skipped = 0

    for n, cc, tipo_doc, nombre, tel, pagado, estado in SEPARACIONES:
        sep_id = f"PS-2026-{n}"
        existing = await db.plan_separe_separaciones.find_one({"separacion_id": sep_id})
        if existing:
            print(f"  SKIP {sep_id} — ya existe")
            skipped += 1
            continue

        abonos = []
        if pagado > 0:
            abonos.append({
                "abono_id": str(uuid.uuid4()),
                "fecha": date.today().isoformat(),
                "monto": pagado,
                "banco": "bancolombia_2029",
                "banco_label": "Bancolombia 2029 (histórico)",
                "referencia": "SEED histórico",
                "registrado_por": "seed_plan_separe",
                "alegra_journal_id": None,
                "pre_existente": True,
                "timestamp": now,
            })

        doc = {
            "separacion_id": sep_id,
            "cliente": {
                "cc": cc,
                "tipo_documento": tipo_doc,
                "nombre": nombre,
                "telefono": tel,
            },
            "moto": {
                "modelo": MODELO,
                "precio_venta": PRECIO_MOTO,
                "cuota_inicial_requerida": CUOTA_INICIAL,
            },
            "abonos": abonos,
            "total_abonado": pagado,
            "saldo_pendiente": max(CUOTA_INICIAL - pagado, 0),
            "porcentaje_pagado": round((pagado / CUOTA_INICIAL) * 100, 2),
            "matricula_provision": MATRICULA,
            "estado": estado,
            "fecha_creacion": now,
            "fecha_100porciento": now if estado == "completada" else None,
            "alegra_invoice_id": None,
            "notas": "Migrado desde operación manual — abono no causado en Alegra (histórico)",
            "seed_source": "seed_plan_separe",
        }
        await db.plan_separe_separaciones.insert_one(doc)
        inserted += 1
        print(f"  OK   {sep_id} — {nombre} ({pagado:,.0f} / {estado})")

    total = await db.plan_separe_separaciones.count_documents({})
    print(f"\nInsertadas: {inserted}")
    print(f"Saltadas:   {skipped}")
    print(f"Total en MongoDB: {total}")
    client.close()


if __name__ == "__main__":
    asyncio.run(run())
