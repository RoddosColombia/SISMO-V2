"""
scripts/seed_repuestos.py — Seed inicial de inventario_repuestos.

Inserta 10 repuestos con stock=0 / estado="agotado".
ARGOS detectará precios de mercado; RODDOS decide qué importar.

Uso en Render Shell:
    cd /opt/render/project/src
    python3 scripts/seed_repuestos.py
"""

import os
import asyncio
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient

REPUESTOS_SEED = [
    {
        "sku": "REP-TVS-CDI-001",
        "nombre": "CDI TVS Sport 100",
        "categoria": "electrico",
        "marca_compatible": "TVS Sport 100",
        "precio_venta": 85_000,
        "precio_costo": 55_000,
        "stock": 0,
        "estado": "agotado",
        "proveedor": "Auteco",
    },
    {
        "sku": "REP-TVS-FILT-002",
        "nombre": "Filtro de aire TVS Sport 100",
        "categoria": "filtros",
        "marca_compatible": "TVS Sport 100",
        "precio_venta": 22_000,
        "precio_costo": 12_000,
        "stock": 0,
        "estado": "agotado",
        "proveedor": "Auteco",
    },
    {
        "sku": "REP-TVS-CADENA-003",
        "nombre": "Cadena de transmisión TVS Sport 100",
        "categoria": "transmision",
        "marca_compatible": "TVS Sport 100",
        "precio_venta": 48_000,
        "precio_costo": 30_000,
        "stock": 0,
        "estado": "agotado",
        "proveedor": "Auteco",
    },
    {
        "sku": "REP-TVS-PASTILLA-004",
        "nombre": "Pastillas de freno trasero TVS Sport 100",
        "categoria": "frenos",
        "marca_compatible": "TVS Sport 100",
        "precio_venta": 35_000,
        "precio_costo": 20_000,
        "stock": 0,
        "estado": "agotado",
        "proveedor": "Auteco",
    },
    {
        "sku": "REP-RAI-FILT-005",
        "nombre": "Filtro de aceite Raider 125",
        "categoria": "filtros",
        "marca_compatible": "Raider 125",
        "precio_venta": 18_000,
        "precio_costo": 10_000,
        "stock": 0,
        "estado": "agotado",
        "proveedor": "Auteco",
    },
    {
        "sku": "REP-RAI-BUJIA-006",
        "nombre": "Bujía Raider 125 (NGK)",
        "categoria": "encendido",
        "marca_compatible": "Raider 125",
        "precio_venta": 15_000,
        "precio_costo": 8_000,
        "stock": 0,
        "estado": "agotado",
        "proveedor": "NGK",
    },
    {
        "sku": "REP-RAI-CABLE-007",
        "nombre": "Cable del acelerador Raider 125",
        "categoria": "controles",
        "marca_compatible": "Raider 125",
        "precio_venta": 28_000,
        "precio_costo": 16_000,
        "stock": 0,
        "estado": "agotado",
        "proveedor": "Auteco",
    },
    {
        "sku": "REP-RAI-LLANTA-008",
        "nombre": "Llanta delantera Raider 125 (2.75-17)",
        "categoria": "llantas",
        "marca_compatible": "Raider 125",
        "precio_venta": 120_000,
        "precio_costo": 78_000,
        "stock": 0,
        "estado": "agotado",
        "proveedor": "Pirelli",
    },
    {
        "sku": "REP-UNI-ACEITE-009",
        "nombre": "Aceite motor 4T 10W-40 (1L)",
        "categoria": "lubricantes",
        "marca_compatible": "Universal",
        "precio_venta": 32_000,
        "precio_costo": 20_000,
        "stock": 0,
        "estado": "agotado",
        "proveedor": "Castrol",
    },
    {
        "sku": "REP-UNI-BATERIA-010",
        "nombre": "Batería sellada 12V 5Ah",
        "categoria": "electrico",
        "marca_compatible": "Universal",
        "precio_venta": 95_000,
        "precio_costo": 62_000,
        "stock": 0,
        "estado": "agotado",
        "proveedor": "Yuasa",
    },
]


async def run():
    mongo_url = os.environ.get("MONGO_URL")
    db_name   = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL y DB_NAME deben estar en el entorno.")
        return

    db = AsyncIOMotorClient(mongo_url)[db_name]

    ahora = datetime.now(timezone.utc).isoformat()
    insertados = 0
    omitidos   = 0

    for rep in REPUESTOS_SEED:
        existe = await db.inventario_repuestos.find_one({"sku": rep["sku"]})
        if existe:
            print(f"  OMITIDO (ya existe): {rep['sku']}")
            omitidos += 1
            continue

        doc = {**rep, "ultima_actualizacion": ahora, "creado_en": ahora}
        await db.inventario_repuestos.insert_one(doc)
        print(f"  INSERTADO: {rep['sku']} — {rep['nombre']}")
        insertados += 1

    print(f"\nSeed completado: {insertados} insertados, {omitidos} omitidos.")


if __name__ == "__main__":
    asyncio.run(run())
