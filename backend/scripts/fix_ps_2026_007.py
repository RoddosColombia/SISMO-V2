"""
One-shot fix: PS-2026-007 Manuel David Quiroz CC 1103216616.
Cuota inicial estaba en $1.350.000, debe ser $1.460.000 (estándar RODDOS).

Run:
  $env:MONGO_URL = "..."
  $env:DB_NAME = "sismo-v2"
  python -m scripts.fix_ps_2026_007
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient


async def run() -> None:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "sismo-v2")
    if not mongo_url:
        raise RuntimeError("MONGO_URL env var is required.")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    print(f"Connected to {db_name}")

    SEP_ID = "PS-2026-007"
    NEW_CUOTA = 1_460_000
    MOTIVO = "Corrección manual Andrés 17-abr-2026: cuota inicial estándar es $1.460.000"

    current = await db.plan_separe_separaciones.find_one({"separacion_id": SEP_ID})
    if not current:
        print(f"  {SEP_ID} no existe — abort")
        return

    old_cuota = current.get("moto", {}).get("cuota_inicial_requerida", 0) or 0
    pagado = current.get("total_abonado", 0) or 0
    print(f"  BEFORE: cuota_inicial={old_cuota:,.0f}  pagado={pagado:,.0f}")

    if old_cuota == NEW_CUOTA:
        print("  Nothing to fix — cuota_inicial ya es el esperado")
        return

    # Audit entry
    audit_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_email": "andres@roddos.com",
        "campos_modificados": [{
            "campo": "moto.cuota_inicial_requerida",
            "valor_anterior": old_cuota,
            "valor_nuevo": NEW_CUOTA,
        }],
        "motivo": MOTIVO,
        "source": "scripts.fix_ps_2026_007",
    }

    # Recalculate porcentaje on the fly (although compute_fields runs dynamically on read)
    new_pct = round((pagado / NEW_CUOTA) * 100, 2) if NEW_CUOTA else 0
    new_saldo = max(NEW_CUOTA - pagado, 0)

    await db.plan_separe_separaciones.update_one(
        {"separacion_id": SEP_ID},
        {
            "$set": {
                "moto.cuota_inicial_requerida": NEW_CUOTA,
                "saldo_pendiente": new_saldo,
                "porcentaje_pagado": new_pct,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            "$push": {"audit": audit_entry},
        },
    )

    # Verify via GET
    doc = await db.plan_separe_separaciones.find_one({"separacion_id": SEP_ID})
    m = doc.get("moto", {})
    audits = doc.get("audit", [])
    print(f"  AFTER:  cuota_inicial={m.get('cuota_inicial_requerida'):,.0f}  "
          f"saldo={doc.get('saldo_pendiente'):,.0f}  pct={doc.get('porcentaje_pagado')}%")
    print(f"  Audit entries: {len(audits)}")
    if audits:
        last = audits[-1]
        print(f"    last: {last['user_email']} - {last['motivo']}")
        for c in last.get("campos_modificados", []):
            print(f"      {c['campo']}: {c['valor_anterior']} -> {c['valor_nuevo']}")

    client.close()


if __name__ == "__main__":
    asyncio.run(run())
