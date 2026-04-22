"""
scripts/poblar_catalogos.py — Poblar catalogo_planes y catalogo_rodante en MongoDB.

Operación: UPSERT idempotente por plan_codigo / subtipo.
Puede ejecutarse N veces sin duplicar documentos.

Uso:
    cd backend
    python scripts/poblar_catalogos.py

    # Solo verificar sin escribir:
    python scripts/poblar_catalogos.py --dry-run

Requiere:
    - Variable MONGO_URL en .env
    - Variable DB_NAME en .env (default: sismo-prod)
"""

from __future__ import annotations

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import motor.motor_asyncio

# ─────────────────────── Config ───────────────────────────────────────────────

MONGO_URL = os.getenv("MONGO_URL", "")
DB_NAME   = os.getenv("DB_NAME", "sismo-prod")

if not MONGO_URL:
    print("❌ ERROR: MONGO_URL no está definida. Configura tu .env antes de continuar.")
    sys.exit(1)


# ─────────────────────── Datos maestros ───────────────────────────────────────

# 10 planes — fuente de verdad absoluta. Cualquier cambio aquí es el cambio oficial.
CATALOGO_PLANES = [
    {
        "plan_codigo": "P1S",
        "descripcion": "Contado (pago único)",
        "aplica_a": ["RDX", "RODANTE"],
        "cuotas_por_modalidad": {"semanal": 0},
        "multiplicador_precio": {"semanal": 1.0},
        "activo": True,
    },
    {
        "plan_codigo": "P2S",
        "descripcion": "2 semanas",
        "aplica_a": ["RODANTE"],
        "cuotas_por_modalidad": {"semanal": 2},
        "multiplicador_precio": {"semanal": 1.0},
        "activo": True,
    },
    {
        "plan_codigo": "P3S",
        "descripcion": "3 semanas",
        "aplica_a": ["RODANTE"],
        "cuotas_por_modalidad": {"semanal": 3},
        "multiplicador_precio": {"semanal": 1.0},
        "activo": True,
    },
    {
        "plan_codigo": "P4S",
        "descripcion": "4 semanas",
        "aplica_a": ["RODANTE"],
        "cuotas_por_modalidad": {"semanal": 4},
        "multiplicador_precio": {"semanal": 1.0},
        "activo": True,
    },
    {
        "plan_codigo": "P6S",
        "descripcion": "6 semanas",
        "aplica_a": ["RODANTE"],
        "cuotas_por_modalidad": {"semanal": 6},
        "multiplicador_precio": {"semanal": 1.0},
        "activo": True,
    },
    {
        "plan_codigo": "P12S",
        "descripcion": "12 semanas",
        "aplica_a": ["RODANTE"],
        "cuotas_por_modalidad": {"semanal": 12},
        "multiplicador_precio": {"semanal": 1.0},
        "activo": True,
    },
    {
        "plan_codigo": "P15S",
        "descripcion": "15 semanas",
        "aplica_a": ["RODANTE"],
        "cuotas_por_modalidad": {"semanal": 15},
        "multiplicador_precio": {"semanal": 1.0},
        "activo": True,
    },
    {
        "plan_codigo": "P39S",
        "descripcion": "39 semanas / 9 meses",
        "aplica_a": ["RDX"],
        "cuotas_por_modalidad": {"semanal": 39, "quincenal": 20, "mensual": 9},
        "multiplicador_precio": {"semanal": 1.0, "quincenal": 2.2, "mensual": 4.4},
        "activo": True,
    },
    {
        "plan_codigo": "P52S",
        "descripcion": "52 semanas / 12 meses",
        "aplica_a": ["RDX"],
        "cuotas_por_modalidad": {"semanal": 52, "quincenal": 26, "mensual": 12},
        "multiplicador_precio": {"semanal": 1.0, "quincenal": 2.2, "mensual": 4.4},
        "activo": True,
    },
    {
        "plan_codigo": "P78S",
        "descripcion": "78 semanas / 18 meses",
        "aplica_a": ["RDX"],
        "cuotas_por_modalidad": {"semanal": 78, "quincenal": 39, "mensual": 18},
        "multiplicador_precio": {"semanal": 1.0, "quincenal": 2.2, "mensual": 4.4},
        "activo": True,
    },
]

# 4 subtipos RODANTE — campos requeridos por cada uno
CATALOGO_RODANTE = [
    {
        "subtipo": "repuestos",
        "descripcion": "Microcrédito para repuestos de moto",
        "ticket_min": 50_000,
        "ticket_max": 500_000,
        "planes_validos": ["P1S", "P2S", "P3S", "P4S", "P6S", "P12S", "P15S"],
        "required_fields": [
            "referencia_sku",
            "cantidad",
            "valor_unitario",
            "descripcion_repuesto",
            "inventario_origen_id",
        ],
        "inventario": "inventario_repuestos",
        "activo": True,
    },
    {
        "subtipo": "soat",
        "descripcion": "Financiación SOAT — RODDOS paga aseguradora, financia al cliente",
        "ticket_min": 200_000,
        "ticket_max": 600_000,
        "planes_validos": ["P1S", "P2S", "P3S", "P4S", "P6S", "P12S", "P15S"],
        "required_fields": [
            "poliza_numero",
            "aseguradora",
            "cilindraje_moto",
            "vigencia_desde",
            "vigencia_hasta",
            "valor_soat",
            "placa_cubierta",
        ],
        "inventario": None,
        "activo": True,
    },
    {
        "subtipo": "comparendo",
        "descripcion": "Financiación pago comparendos — RODDOS paga Tránsito, financia al cliente",
        "ticket_min": 100_000,
        "ticket_max": 5_000_000,
        "planes_validos": ["P1S", "P2S", "P3S", "P4S", "P6S", "P12S", "P15S"],
        "required_fields": [
            "comparendo_numero",
            "entidad_emisora",
            "fecha_infraccion",
            "valor_comparendo",
            "codigo_infraccion",
        ],
        "inventario": None,
        "activo": True,
    },
    {
        "subtipo": "licencia",
        "descripcion": "Financiación licencia de conducción — RODDOS paga centro, financia al cliente",
        "ticket_min": 200_000,
        "ticket_max": 1_400_000,
        "planes_validos": ["P1S", "P2S", "P3S", "P4S", "P6S", "P12S", "P15S"],
        "required_fields": [
            "categoria_licencia",
            "centro_ensenanza_nombre",
            "centro_ensenanza_nit",
            "fecha_inicio_curso",
            "valor_curso",
        ],
        "inventario": None,
        "activo": True,
    },
]


# ─────────────────────── Helpers ──────────────────────────────────────────────

def _sep(char: str = "─", width: int = 60) -> None:
    print(char * width)


# ─────────────────────── Lógica principal ─────────────────────────────────────

async def poblar(dry_run: bool = False) -> None:
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
    db     = client[DB_NAME]

    print()
    _sep("═")
    print(f"  POBLAR CATÁLOGOS — DB: {DB_NAME}")
    if dry_run:
        print("  MODO: DRY-RUN (sin escrituras)")
    _sep("═")

    # ── catalogo_planes ───────────────────────────────────────────────────────
    print()
    _sep()
    print(f"  catalogo_planes — {len(CATALOGO_PLANES)} documentos")
    _sep()

    planes_insertados = 0
    planes_actualizados = 0

    for plan in CATALOGO_PLANES:
        codigo = plan["plan_codigo"]
        existing = await db.catalogo_planes.find_one({"plan_codigo": codigo})

        if dry_run:
            accion = "INSERT" if existing is None else "UPDATE"
            print(f"  [{accion}] {codigo:6} — {plan['descripcion']}")
            continue

        result = await db.catalogo_planes.update_one(
            {"plan_codigo": codigo},
            {"$set": plan},
            upsert=True,
        )
        if result.upserted_id:
            planes_insertados += 1
            print(f"  [INSERT] {codigo:6} — {plan['descripcion']}")
        else:
            planes_actualizados += 1
            print(f"  [UPDATE] {codigo:6} — {plan['descripcion']}")

    if not dry_run:
        total_planes = await db.catalogo_planes.count_documents({})
        print()
        print(f"  → {planes_insertados} insertados, {planes_actualizados} actualizados")
        print(f"  → Total en DB: {total_planes} documentos")
        assert total_planes == 10, f"Se esperaban 10 planes, hay {total_planes}"
        print("  ✅ catalogo_planes: 10/10 ✓")

    # ── catalogo_rodante ──────────────────────────────────────────────────────
    print()
    _sep()
    print(f"  catalogo_rodante — {len(CATALOGO_RODANTE)} documentos")
    _sep()

    rodante_insertados = 0
    rodante_actualizados = 0

    for subtipo_doc in CATALOGO_RODANTE:
        subtipo = subtipo_doc["subtipo"]
        existing = await db.catalogo_rodante.find_one({"subtipo": subtipo})

        if dry_run:
            accion = "INSERT" if existing is None else "UPDATE"
            print(f"  [{accion}] {subtipo:12} — {subtipo_doc['descripcion'][:45]}")
            continue

        result = await db.catalogo_rodante.update_one(
            {"subtipo": subtipo},
            {"$set": subtipo_doc},
            upsert=True,
        )
        if result.upserted_id:
            rodante_insertados += 1
            print(f"  [INSERT] {subtipo:12} — {subtipo_doc['descripcion'][:45]}")
        else:
            rodante_actualizados += 1
            print(f"  [UPDATE] {subtipo:12} — {subtipo_doc['descripcion'][:45]}")

    if not dry_run:
        total_rodante = await db.catalogo_rodante.count_documents({})
        print()
        print(f"  → {rodante_insertados} insertados, {rodante_actualizados} actualizados")
        print(f"  → Total en DB: {total_rodante} documentos")
        assert total_rodante == 4, f"Se esperaban 4 subtipos RODANTE, hay {total_rodante}"
        print("  ✅ catalogo_rodante: 4/4 ✓")

    # ── Índices ───────────────────────────────────────────────────────────────
    if not dry_run:
        await db.catalogo_planes.create_index("plan_codigo", unique=True)
        await db.catalogo_rodante.create_index("subtipo", unique=True)
        print()
        print("  ✅ Índices únicos creados (plan_codigo, subtipo)")

    print()
    _sep("═")
    if dry_run:
        print("  DRY-RUN completado. Ejecuta sin --dry-run para aplicar.")
    else:
        print("  POBLAR completado exitosamente.")
    _sep("═")
    print()

    client.close()


# ─────────────────────── Entrypoint ───────────────────────────────────────────

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    asyncio.run(poblar(dry_run=dry_run))
