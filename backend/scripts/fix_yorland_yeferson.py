"""
Fix data for LB-2026-0020 (Yorland) and LB-2026-0021 (Yeferson).

YORLAND BERROCAL (LB-2026-0020):
  pendiente_entrega → activo. Entregada 13-abr-2026. Primera cuota 21-abr (mie).
  P52S quincenal = 26 cuotas cada 14 días desde 2026-04-21.

YEFERSON BENJUMES (LB-2026-0021):
  pendiente_entrega → activo. Entregada 10-abr-2026.
  EXCEPCION: paga los jueves (dia_cobro_especial="jueves").
  Primera cuota 17-abr-2026 (jueves). Cuota #1 YA PAGADA el 16-abr puntual.
  P39S semanal = 39 cuotas cada 7 días desde 2026-04-17.

Run:
  $env:MONGO_URL = "..."
  $env:DB_NAME = "sismo-v2"
  python -m scripts.fix_yorland_yeferson
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorClient


def _build_cuotas_array(
    first_date: date,
    dias_intervalo: int,
    num_cuotas: int,
    cuota_monto: int,
    pagadas: int,
    fecha_pago_primera: str | None = None,
) -> list[dict]:
    """Build cuotas array. First `pagadas` cuotas marked as paid."""
    cuotas = []
    for i in range(1, num_cuotas + 1):
        fecha = first_date + timedelta(days=dias_intervalo * (i - 1))
        if i <= pagadas:
            cuotas.append({
                "numero": i, "monto": cuota_monto, "estado": "pagada",
                "fecha": fecha.isoformat(),
                "fecha_pago": fecha_pago_primera if i == 1 else fecha.isoformat(),
                "mora_acumulada": 0,
            })
        else:
            cuotas.append({
                "numero": i, "monto": cuota_monto, "estado": "pendiente",
                "fecha": fecha.isoformat(),
                "fecha_pago": None,
                "mora_acumulada": 0,
            })
    return cuotas


async def fix_yorland(db) -> None:
    """LB-2026-0020: pendiente_entrega → activo, entrega 13-abr (Mon), quincenal.
    First Wednesday >= entrega+7 = 2026-04-22 (Wed). (Spec said 21-abr but that's Tuesday.)
    """
    first = date(2026, 4, 22)  # Wednesday
    assert first.weekday() == 2, "Primera cuota Yorland debe ser miércoles"
    cuota_monto = 395_780
    num_cuotas = 26
    cuotas = _build_cuotas_array(first, 14, num_cuotas, cuota_monto, pagadas=0)

    update = {
        "estado": "activo",
        "fechas.entrega": "2026-04-13",
        "fechas.primera_cuota": first.isoformat(),
        "fecha_entrega": "2026-04-13",
        "fecha_primer_pago": first.isoformat(),
        "cuotas": cuotas,
        "cuotas_pagadas": 0,
        "cuotas_vencidas": 0,
        "total_pagado": 0,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    result = await db.loanbook.update_one({"loanbook_id": "LB-2026-0020"}, {"$set": update})
    print(f"  LB-2026-0020 Yorland: matched={result.matched_count}, modified={result.modified_count}")


async def fix_yeferson(db) -> None:
    """LB-2026-0021: entrega 10-abr (Fri), dia_cobro_especial=jueves.
    Primera cuota 2026-04-16 (Thu) — pagada a tiempo el mismo día.
    (Spec said 17-abr pero eso es viernes; Yeferson paga jueves.)
    """
    first = date(2026, 4, 16)  # Thursday
    assert first.weekday() == 3, "16-abr-2026 debe ser jueves"
    cuota_monto = 210_000
    num_cuotas = 39
    cuotas = _build_cuotas_array(
        first, 7, num_cuotas, cuota_monto,
        pagadas=1,
        fecha_pago_primera="2026-04-16",
    )

    update = {
        "estado": "activo",
        "fechas.entrega": "2026-04-10",
        "fechas.primera_cuota": first.isoformat(),  # 2026-04-16
        "fecha_entrega": "2026-04-10",
        "fecha_primer_pago": first.isoformat(),
        "dia_cobro_especial": "jueves",
        "cuotas": cuotas,
        "cuotas_pagadas": 1,
        "cuotas_vencidas": 0,
        "total_pagado": cuota_monto,
        "saldo_pendiente": (num_cuotas - 1) * cuota_monto,
        "saldo_capital": (num_cuotas - 1) * cuota_monto,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    result = await db.loanbook.update_one({"loanbook_id": "LB-2026-0021"}, {"$set": update})
    print(f"  LB-2026-0021 Yeferson: matched={result.matched_count}, modified={result.modified_count}")


async def run() -> None:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "sismo-v2")
    if not mongo_url:
        raise RuntimeError("MONGO_URL env var is required.")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    print(f"Connected to {db_name}")

    print("\n=== Fixing Yorland (LB-2026-0020) ===")
    await fix_yorland(db)

    print("\n=== Fixing Yeferson (LB-2026-0021) ===")
    await fix_yeferson(db)

    # Verify
    print("\n=== Verification ===")
    for lb_id in ("LB-2026-0020", "LB-2026-0021"):
        doc = await db.loanbook.find_one({"loanbook_id": lb_id})
        if doc:
            print(f"  {lb_id}: estado={doc['estado']}, entrega={doc.get('fecha_entrega')}, "
                  f"primera_cuota={doc.get('fecha_primer_pago')}, "
                  f"pagadas={doc.get('cuotas_pagadas')}, "
                  f"dia_especial={doc.get('dia_cobro_especial', '—')}")

    client.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(run())
