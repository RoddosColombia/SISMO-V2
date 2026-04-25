"""
scripts/agregar_capital_plan.py — Agrega capital_plan a catalogo_planes en MongoDB.

capital_plan = precio de venta base de la moto sin extras ni IVA.
Es el denominador de la fórmula de saldo_capital en calcular_saldos().

Valores verificados contra Excel loanbook_roddos_2026-04-25.xlsx:
  Raider 125    → 7_800_000
  TVS Sport 100 → 5_750_000

Para RODANTE: capital_plan = monto_original (el valor del repuesto/servicio).
Esos documentos no tienen moto_modelo — se deja sin tocar.

Idempotente: si ya existe el campo con el valor correcto, SKIP.

Ejecutar en Render Shell:
  python3 scripts/agregar_capital_plan.py

O localmente:
  $env:MONGO_URL = "mongodb+srv://..."
  $env:DB_NAME   = "sismo-prod"
  python -m scripts.agregar_capital_plan
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from motor.motor_asyncio import AsyncIOMotorClient
from core.datetime_utils import now_iso_bogota


# ─── Tabla de verdad: moto_modelo → capital_plan ─────────────────────────────
# Fuente: Excel loanbook_roddos_2026-04-25.xlsx
CAPITAL_POR_MODELO: dict[str, int] = {
    "Raider 125":    7_800_000,
    "TVS Sport 100": 5_750_000,
}


async def run() -> None:
    mongo_url = os.environ.get("MONGO_URL")
    db_name   = os.environ.get("DB_NAME", "sismo-prod")

    if not mongo_url:
        print("ERROR: Variable MONGO_URL no definida.")
        sys.exit(1)

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    print(f"\n{'='*60}")
    print(f"agregar_capital_plan — DB: {db_name}")
    print(f"{'='*60}\n")

    planes = await db.catalogo_planes.find({}).to_list(None)
    print(f"Total documentos en catalogo_planes: {len(planes)}\n")

    ok = skipped = sin_modelo = 0

    for plan in planes:
        plan_id  = plan.get("codigo") or plan.get("_id")
        modelo   = plan.get("moto_modelo") or plan.get("modelo")

        if not modelo:
            print(f"  SKIP  {plan_id} — sin moto_modelo (RODANTE o desconocido)")
            sin_modelo += 1
            continue

        capital = CAPITAL_POR_MODELO.get(modelo)
        if capital is None:
            print(f"  SKIP  {plan_id} [{modelo}] — modelo no está en tabla de verdad")
            sin_modelo += 1
            continue

        # Idempotente: si ya existe con el valor correcto, no tocar
        if plan.get("capital_plan") == capital:
            print(f"  OK    {plan_id} [{modelo}] — capital_plan={capital:,} ya correcto")
            skipped += 1
            continue

        await db.catalogo_planes.update_one(
            {"_id": plan["_id"]},
            {"$set": {
                "capital_plan": capital,
                "updated_at":   now_iso_bogota(),
            }},
        )
        prev = plan.get("capital_plan", "—")
        print(f"  FIX   {plan_id} [{modelo}] — capital_plan: {prev} → {capital:,}")
        ok += 1

    client.close()

    print(f"\n{'─'*60}")
    print(f"Actualizados : {ok}")
    print(f"Ya correctos : {skipped}")
    print(f"Sin modelo   : {sin_modelo}")


if __name__ == "__main__":
    asyncio.run(run())
