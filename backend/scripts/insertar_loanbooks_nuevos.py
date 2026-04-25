"""
scripts/insertar_loanbooks_nuevos.py — Inserta 4 loanbooks FE469-FE472.

Motos vendidas con facturas Alegra emitidas que no están en MongoDB.
Estado: pendiente_entrega (fecha_entrega aún no se conoce — se registra
manualmente desde la UI o via PUT /{id}/entrega).

Anti-dup: verifica loanbook_id Y vin antes de insertar. Si cualquiera existe,
SKIP sin modificar nada.

Idempotente: correr N veces produce el mismo resultado.

Ejecutar en Render Shell:
  python3 scripts/insertar_loanbooks_nuevos.py

O localmente con:
  $env:MONGO_URL = "mongodb+srv://..."
  $env:DB_NAME   = "sismo-prod"
  python -m scripts.insertar_loanbooks_nuevos
"""
from __future__ import annotations

import asyncio
import os
import sys

from motor.motor_asyncio import AsyncIOMotorClient

# Cuando se corre con python3 scripts/... en Render Shell el cwd es /opt/render/project/src
# y los imports de core/ ya están en el path.
# Cuando se corre localmente con python -m scripts.xxx también está en path.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.datetime_utils import now_iso_bogota  # noqa: E402  (después del sys.path)


# ─── Datos de los 4 loanbooks (fuente: facturas Alegra + Andrés) ──────────────

NUEVOS_LOANBOOKS = [
    {
        "loanbook_id":    "LB-2026-0029",
        "cliente": {
            "nombre":    "Toribio Rodriguez Salcedo",
            "cedula":    "19594484",
            "telefono":  "+573214383749",
            "ciudad":    "Bogotá",
        },
        "producto":       "RDX",
        "plan_codigo":    "P39S",
        "modalidad_pago": "semanal",
        "cuota_periodica": 204_000,
        "cuota_inicial":  0,
        "fecha_factura":  "2026-04-17",
        "factura_alegra_id": "FE469",
        "metadata_producto": {
            "moto_vin":        "9FLT81001VDB62264",
            "moto_modelo":     "TVS Sport 100",
            "moto_motor":      "RF5AT1XA5588",
            "moto_año":        2027,
            "moto_cilindraje": 100,
        },
        "notas_migracion": "Creado desde Alegra FE469 — fecha_entrega pendiente",
    },
    {
        "loanbook_id":    "LB-2026-0030",
        "cliente": {
            "nombre":    "Luis Alejandro Julio Romero",
            "cedula":    "1101879357",
            "telefono":  "+573232256737",
            "ciudad":    "Bogotá",
        },
        "producto":       "RDX",
        "plan_codigo":    "P39S",
        "modalidad_pago": "semanal",
        "cuota_periodica": 204_000,
        "cuota_inicial":  0,
        "fecha_factura":  "2026-04-17",
        "factura_alegra_id": "FE470",
        "metadata_producto": {
            "moto_vin":        "9FLT81003VDB62329",
            "moto_modelo":     "TVS Sport 100",
            "moto_motor":      "RF5AT11A5603",
            "moto_año":        2027,
            "moto_cilindraje": 100,
        },
        # Nota operativa: matricular a nombre de tercero
        "notas_migracion": (
            "Creado desde Alegra FE470 — fecha_entrega pendiente. "
            "MATRICULAR a nombre de Luis Angel Ortega Camacho CC 1005472601."
        ),
    },
    {
        "loanbook_id":    "LB-2026-0031",
        "cliente": {
            "nombre":    "Rafael Antonio Ssawk Baldovino",
            "cedula":    "1003077566",
            "telefono":  "+573115035599",
            "ciudad":    "Bogotá",
        },
        "producto":       "RDX",
        "plan_codigo":    "P39S",
        "modalidad_pago": "semanal",
        "cuota_periodica": 175_000,
        "cuota_inicial":  550_000,
        "fecha_factura":  "2026-04-20",
        "factura_alegra_id": "FE471",
        "metadata_producto": {
            "moto_vin":        "9FLT81006VDB62261",
            "moto_modelo":     "TVS Sport 100",
            "moto_motor":      "RF5AT14A5515",
            "moto_año":        2027,
            "moto_cilindraje": 100,
        },
        "notas_migracion": "Creado desde Alegra FE471 — fecha_entrega pendiente",
    },
    {
        "loanbook_id":    "LB-2026-0032",
        "cliente": {
            "nombre":    "Lina Fernanda Camacho Camargo",
            "cedula":    "1015443764",
            "telefono":  "+573044395444",
            "ciudad":    "Bogotá",
        },
        "producto":       "RDX",
        "plan_codigo":    "P78S",
        "modalidad_pago": "semanal",
        "cuota_periodica": 145_000,
        "cuota_inicial":  0,
        "fecha_factura":  "2026-04-23",
        "factura_alegra_id": "FE472",
        "metadata_producto": {
            "moto_vin":        "9FLT81001VDB62314",
            "moto_modelo":     "TVS Sport 100",
            "moto_motor":      "RF5AT16A5561",
            "moto_año":        2027,
            "moto_cilindraje": 100,
        },
        "notas_migracion": "Creado desde Alegra FE472 — fecha_entrega pendiente",
    },
]


# ─── Construcción del documento MongoDB ───────────────────────────────────────

def _build_doc(row: dict) -> dict:
    vin = row["metadata_producto"]["moto_vin"]
    ts  = now_iso_bogota()
    return {
        # Identidad
        "loanbook_id":       row["loanbook_id"],
        "estado":            "pendiente_entrega",
        "origen":            "alegra_direct_invoice",

        # Cliente
        "cliente":           row["cliente"],

        # Producto
        "producto":          row["producto"],
        "tipo_producto":     "moto",          # campo compat legado
        "plan_codigo":       row["plan_codigo"],
        "modalidad":         row["modalidad_pago"],
        "modalidad_pago":    row["modalidad_pago"],
        "cuota_periodica":   row["cuota_periodica"],
        "cuota_monto":       row["cuota_periodica"],   # campo compat legado
        "cuota_inicial":     row["cuota_inicial"],
        "anzi_pct":          0.02,

        # Metadata (schema B1 RDX)
        "metadata_producto": row["metadata_producto"],

        # Aliases de VIN para búsquedas legacy
        "vin":               vin,
        "modelo":            row["metadata_producto"]["moto_modelo"],

        # Cronograma — vacío hasta registrar entrega
        "cuotas":            [],
        "num_cuotas":        0,
        "cuotas_pagadas":    0,
        "cuotas_vencidas":   0,

        # Saldos — se calculan al generar cronograma en entrega
        "saldo_capital":     0,
        "saldo_pendiente":   0,
        "total_pagado":      0,
        "total_mora_pagada": 0,
        "total_anzi_pagado": 0,

        # Mora / DPD
        "dpd":               0,
        "mora_acumulada_cop": 0,
        "sub_bucket_semanal": None,

        # Fechas
        "fecha_factura":     row["fecha_factura"],
        "fecha_entrega":     None,     # se completa manualmente o via UI
        "fecha_primer_pago": None,     # se calcula al registrar entrega

        # Alegra
        "alegra_factura_id":    row["factura_alegra_id"],
        "factura_alegra_id":    row["factura_alegra_id"],  # alias compat

        # Score / scoring
        "score_riesgo":      None,
        "whatsapp_status":   "pending",
        "acuerdo_activo_id": None,

        # Notas
        "notas_migracion":   row["notas_migracion"],

        # Timestamps
        "created_at":        ts,
        "updated_at":        ts,
    }


def _build_crm_doc(row: dict, ts: str) -> dict:
    return {
        "cedula":       row["cliente"]["cedula"],
        "nombre":       row["cliente"]["nombre"],
        "telefono":     row["cliente"]["telefono"],
        "ciudad":       row["cliente"].get("ciudad"),
        "email":        None,
        "estado":       "activo",
        "loanbook_ids": [row["loanbook_id"]],
        "loanbooks":    1,
        "created_at":   ts,
        "updated_at":   ts,
    }


# ─── Main ─────────────────────────────────────────────────────────────────────

async def run() -> None:
    mongo_url = os.environ.get("MONGO_URL")
    db_name   = os.environ.get("DB_NAME", "sismo-prod")

    if not mongo_url:
        print("ERROR: Variable de entorno MONGO_URL no definida.")
        print("  Render Shell: las vars de entorno están disponibles automáticamente.")
        print("  Local: $env:MONGO_URL = 'mongodb+srv://...'")
        sys.exit(1)

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    print(f"\n{'='*60}")
    print(f"insertar_loanbooks_nuevos — DB: {db_name}")
    print(f"{'='*60}\n")

    insertados = 0
    saltados   = 0

    for row in NUEVOS_LOANBOOKS:
        lb_id  = row["loanbook_id"]
        nombre = row["cliente"]["nombre"]
        vin    = row["metadata_producto"]["moto_vin"]

        # Anti-dup capa 1: por loanbook_id
        existe_id = await db.loanbook.find_one({"loanbook_id": lb_id})
        if existe_id:
            print(f"  YA EXISTE  {lb_id} [{nombre}] — loanbook_id duplicado, sin cambios")
            saltados += 1
            continue

        # Anti-dup capa 2: por VIN
        existe_vin = await db.loanbook.find_one({"vin": vin})
        if existe_vin:
            print(
                f"  YA EXISTE  {lb_id} [{nombre}] — "
                f"VIN {vin} ya pertenece a {existe_vin.get('loanbook_id')}, sin cambios"
            )
            saltados += 1
            continue

        # Insertar loanbook
        doc = _build_doc(row)
        await db.loanbook.insert_one(doc)
        insertados += 1
        print(f"  CREADO     {lb_id} [{nombre}] — {row['factura_alegra_id']}")

        # Upsert CRM
        ts = now_iso_bogota()
        cedula = row["cliente"]["cedula"]
        existente_crm = await db.crm_clientes.find_one({"cedula": cedula})
        if existente_crm:
            await db.crm_clientes.update_one(
                {"cedula": cedula},
                {
                    "$addToSet": {"loanbook_ids": lb_id},
                    "$inc":      {"loanbooks": 1},
                    "$set":      {"updated_at": ts},
                },
            )
            print(f"             CRM actualizado para cédula {cedula}")
        else:
            crm_doc = _build_crm_doc(row, ts)
            await db.crm_clientes.insert_one(crm_doc)
            print(f"             CRM creado para cédula {cedula}")

    # Resumen
    print(f"\n{'─'*60}")
    print(f"Insertados : {insertados}")
    print(f"Saltados   : {saltados}")

    total_lb = await db.loanbook.count_documents({})
    pend_lb  = await db.loanbook.count_documents({"estado": "pendiente_entrega"})
    print(f"Total loanbooks en MongoDB     : {total_lb}")
    print(f"En estado pendiente_entrega    : {pend_lb}")

    client.close()


if __name__ == "__main__":
    asyncio.run(run())
