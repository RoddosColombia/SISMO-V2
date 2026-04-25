"""
scripts/registrar_entregas_abril.py — Activar 4 loanbooks entregados en abril 2026.

Loanbooks:
  LB-2026-0029  Toribio Rodriguez    entrega 2026-04-20  P39S Sport  cuota=204000 std=175000
  LB-2026-0030  Luis Alejandro Julio entrega 2026-04-20  P39S Sport  cuota=204000 std=175000
  LB-2026-0031  Rafael Ssawk         entrega 2026-04-23  P39S Sport  cuota=175000 std=175000
  LB-2026-0032  Lina Fernanda Camacho entrega 2026-04-27  P78S Sport  cuota=145000 std=130000

Idempotente: si el loanbook ya no está en estado pendiente_entrega, se salta.

Render Shell:
  cd /opt/render/project/src
  python3 scripts/registrar_entregas_abril.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from motor.motor_asyncio import AsyncIOMotorClient

# ─── Entregas confirmadas por Andrés Sanjuan ──────────────────────────────────

ENTREGAS = [
    {
        "loanbook_id": "LB-2026-0029",
        "fecha_entrega": date(2026, 4, 20),
        "cuota_estandar_plan": 175_000,   # P39S Sport 100 semanal
    },
    {
        "loanbook_id": "LB-2026-0030",
        "fecha_entrega": date(2026, 4, 20),
        "cuota_estandar_plan": 175_000,   # P39S Sport 100 semanal
    },
    {
        "loanbook_id": "LB-2026-0031",
        "fecha_entrega": date(2026, 4, 23),
        "cuota_estandar_plan": 175_000,   # P39S Sport 100 semanal
    },
    {
        "loanbook_id": "LB-2026-0032",
        "fecha_entrega": date(2026, 4, 27),
        "cuota_estandar_plan": 130_000,   # P78S Sport 100 semanal
    },
]


async def main() -> None:
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name   = os.environ.get("DB_NAME", "sismo-prod")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    from services.loanbook.reglas_negocio import (
        primer_miercoles_cobro,
        calcular_saldos,
    )
    from core.loanbook_model import calcular_cronograma
    from core.datetime_utils import now_iso_bogota

    print(f"\n{'='*60}")
    print("REGISTRAR ENTREGAS ABRIL 2026")
    print(f"{'='*60}\n")

    for entry in ENTREGAS:
        lb_id          = entry["loanbook_id"]
        fecha_entrega  = entry["fecha_entrega"]
        cuota_estandar = entry["cuota_estandar_plan"]

        lb = await db.loanbook.find_one({"loanbook_id": lb_id})
        if not lb:
            print(f"  {lb_id}: NO ENCONTRADO — saltando")
            continue

        estado_actual = lb.get("estado")
        if estado_actual != "pendiente_entrega":
            print(f"  {lb_id}: estado={estado_actual} — SALTANDO (no pendiente_entrega)")
            continue

        # Calcular primera cuota usando regla del miércoles Roddos
        fpc = primer_miercoles_cobro(fecha_entrega)

        # Parámetros del crédito
        modalidad   = lb.get("modalidad", "semanal")
        num_cuotas  = lb.get("num_cuotas", 0) or lb.get("cuotas_total", 0)
        cuota_monto = int(
            lb.get("cuota_periodica") or lb.get("cuota_monto") or 0
        )
        capital_plan = int(lb.get("capital_plan", 0) or 0)

        if num_cuotas <= 0:
            print(f"  {lb_id}: ERROR — num_cuotas={num_cuotas}, saltando")
            continue
        if cuota_monto <= 0:
            print(f"  {lb_id}: ERROR — cuota_monto={cuota_monto}, saltando")
            continue
        if capital_plan <= 0:
            print(f"  {lb_id}: ERROR — capital_plan={capital_plan}, saltando")
            continue

        # Generar fechas del cronograma
        fechas = calcular_cronograma(
            fecha_entrega=fecha_entrega,
            modalidad=modalidad,
            num_cuotas=num_cuotas,
            fecha_primer_pago=fpc,
        )

        cuotas = [
            {
                "numero": i + 1,
                "monto": cuota_monto,
                "estado": "pendiente",
                "fecha": f.isoformat(),
                "fecha_pago": None,
                "mora_acumulada": 0,
            }
            for i, f in enumerate(fechas)
        ]

        # Calcular saldo_capital y saldo_intereses
        saldos = calcular_saldos(
            capital_plan=capital_plan,
            total_cuotas=num_cuotas,
            cuota_periodica=cuota_monto,
            cuotas_pagadas=0,
            cuota_estandar_plan=cuota_estandar,
        )

        update_fields = {
            "estado":             "activo",
            "fecha_entrega":      fecha_entrega.isoformat(),
            "fecha_primer_pago":  fpc.isoformat(),
            "fechas.entrega":     fecha_entrega.isoformat(),
            "fechas.primera_cuota": fpc.isoformat(),
            "cuotas":             cuotas,
            "cuotas_pagadas":     0,
            "cuotas_total":       len(cuotas),
            "saldo_capital":      saldos["saldo_capital"],
            "saldo_pendiente":    saldos["saldo_capital"],
            "saldo_intereses":    saldos["saldo_intereses"],
            "capital_plan":       capital_plan,
            "cuota_estandar_plan": cuota_estandar,
            "updated_at":         now_iso_bogota(),
        }

        await db.loanbook.update_one(
            {"loanbook_id": lb_id},
            {"$set": update_fields},
        )

        nombre = lb.get("cliente_nombre", lb.get("nombre_cliente", ""))
        print(
            f"  {lb_id} [{nombre}]: ACTIVADO | "
            f"sc={saldos['saldo_capital']:,} | "
            f"si={saldos['saldo_intereses']:,} | "
            f"primera_cuota={fpc.isoformat()}"
        )

    client.close()
    print(f"\n{'='*60}")
    print("DONE — Verificar con GET /api/loanbook?estado=activo")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
