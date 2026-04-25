"""
scripts/sync_legacy_saldos.py — Sync saldo_capital/saldo_intereses desde Excel.

Fuente de verdad: Excel loanbook_roddos_2026-04-25.xlsx (Hoja1).
Corrige total_cuotas, cuotas_pagadas, cuota_periodica, modalidad_pago,
cuota_estandar_plan, saldo_capital, saldo_intereses en 17 loanbooks legacy.

NO regenera cronogramas — solo actualiza campos de saldo y meta del crédito.

Idempotente: si los valores ya coinciden, imprime "OK (sin cambio)".

Render Shell:
  cd /opt/render/project/src
  python3 scripts/sync_legacy_saldos.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from motor.motor_asyncio import AsyncIOMotorClient

# ─── Datos canónicos desde Excel (fuente de verdad) ───────────────────────────
# Campos: loanbook_id, capital_plan, total_cuotas, cuotas_pagadas,
#         cuota_periodica, cuota_estandar_plan, modalidad_pago,
#         saldo_capital, saldo_intereses

CANONICAL: list[dict] = [
    # ── Quincenal ──────────────────────────────────────────────────────────────
    {
        "loanbook_id":       "LB-2026-0007",
        "capital_plan":       5_750_000,
        "total_cuotas":           20,
        "cuotas_pagadas":          3,
        "cuota_periodica":     350_000,
        "cuota_estandar_plan": 385_000,
        "modalidad_pago":    "quincenal",
        "saldo_capital":     4_887_500,
        "saldo_intereses":   1_657_500,
    },
    {
        "loanbook_id":       "LB-2026-0008",
        "capital_plan":       7_800_000,
        "total_cuotas":           20,
        "cuotas_pagadas":          3,
        "cuota_periodica":     420_000,
        "cuota_estandar_plan": 462_000,
        "modalidad_pago":    "quincenal",
        "saldo_capital":     6_630_000,
        "saldo_intereses":   1_224_000,
    },
    {
        "loanbook_id":       "LB-2026-0012",
        "capital_plan":       7_800_000,
        "total_cuotas":           26,
        "cuotas_pagadas":          2,
        "cuota_periodica":     360_000,
        "cuota_estandar_plan": 395_780,
        "modalidad_pago":    "quincenal",
        "saldo_capital":     7_200_000,
        "saldo_intereses":   2_298_720,
    },
    {
        "loanbook_id":       "LB-2026-0018",
        "capital_plan":       7_800_000,
        "total_cuotas":           39,
        "cuotas_pagadas":          1,
        "cuota_periodica":     329_780,
        "cuota_estandar_plan": 329_780,
        "modalidad_pago":    "quincenal",
        "saldo_capital":     7_600_000,
        "saldo_intereses":   4_931_640,
    },
    {
        "loanbook_id":       "LB-2026-0019",
        "capital_plan":       7_800_000,
        "total_cuotas":           39,
        "cuotas_pagadas":          1,
        "cuota_periodica":     329_780,
        "cuota_estandar_plan": 329_780,
        "modalidad_pago":    "quincenal",
        "saldo_capital":     7_600_000,
        "saldo_intereses":   4_931_640,
    },
    {
        "loanbook_id":       "LB-2026-0020",
        "capital_plan":       7_800_000,
        "total_cuotas":           26,
        "cuotas_pagadas":          1,
        "cuota_periodica":     395_780,
        "cuota_estandar_plan": 395_780,
        "modalidad_pago":    "quincenal",
        "saldo_capital":     7_500_000,
        "saldo_intereses":   2_394_500,
    },
    # ── Semanal Raider ─────────────────────────────────────────────────────────
    {
        "loanbook_id":       "LB-2026-0010",
        "capital_plan":       7_800_000,
        "total_cuotas":           52,
        "cuotas_pagadas":          4,
        "cuota_periodica":     179_900,
        "cuota_estandar_plan": 179_900,
        "modalidad_pago":    "semanal",
        "saldo_capital":     7_200_000,
        "saldo_intereses":   1_435_200,
    },
    {
        "loanbook_id":       "LB-2026-0011",
        "capital_plan":       7_800_000,
        "total_cuotas":           39,
        "cuotas_pagadas":          4,
        "cuota_periodica":     210_000,
        "cuota_estandar_plan": 210_000,
        "modalidad_pago":    "semanal",
        "saldo_capital":     6_999_384,
        "saldo_intereses":     344_316,
    },
    {
        "loanbook_id":       "LB-2026-0015",
        "capital_plan":       7_800_000,
        "total_cuotas":           78,
        "cuotas_pagadas":          3,
        "cuota_periodica":     149_900,
        "cuota_estandar_plan": 149_900,
        "modalidad_pago":    "semanal",
        "saldo_capital":     7_500_000,
        "saldo_intereses":   3_742_500,
    },
    {
        "loanbook_id":       "LB-2026-0016",
        "capital_plan":       7_800_000,
        "total_cuotas":           39,
        "cuotas_pagadas":          3,
        "cuota_periodica":     210_000,
        "cuota_estandar_plan": 210_000,
        "modalidad_pago":    "semanal",
        "saldo_capital":     7_199_538,
        "saldo_intereses":     354_162,
    },
    {
        "loanbook_id":       "LB-2026-0017",
        "capital_plan":       7_800_000,
        "total_cuotas":           39,
        "cuotas_pagadas":          3,
        "cuota_periodica":     129_999,   # cuota especial — std es 210000
        "cuota_estandar_plan": 210_000,
        "modalidad_pago":    "semanal",
        "saldo_capital":     7_199_538,
        "saldo_intereses":     354_162,
    },
    {
        "loanbook_id":       "LB-2026-0021",
        "capital_plan":       7_800_000,
        "total_cuotas":           39,
        "cuotas_pagadas":          2,
        "cuota_periodica":     210_000,
        "cuota_estandar_plan": 210_000,
        "modalidad_pago":    "semanal",
        "saldo_capital":     7_399_692,
        "saldo_intereses":     364_008,
    },
    {
        "loanbook_id":       "LB-2026-0022",
        "capital_plan":       7_800_000,
        "total_cuotas":           39,
        "cuotas_pagadas":          1,
        "cuota_periodica":     210_000,
        "cuota_estandar_plan": 210_000,
        "modalidad_pago":    "semanal",
        "saldo_capital":     7_599_846,
        "saldo_intereses":     373_854,
    },
    # ── Semanal Sport (cuota especial o estándar) ──────────────────────────────
    {
        "loanbook_id":       "LB-2026-0028",
        "capital_plan":       5_750_000,
        "total_cuotas":           39,
        "cuotas_pagadas":          0,
        "cuota_periodica":     204_000,   # cuota especial
        "cuota_estandar_plan": 175_000,
        "modalidad_pago":    "semanal",
        "saldo_capital":     5_750_000,
        "saldo_intereses":   1_069_750,
    },
    {
        "loanbook_id":       "LB-2026-0029",
        "capital_plan":       5_750_000,
        "total_cuotas":           39,
        "cuotas_pagadas":          0,
        "cuota_periodica":     204_000,   # cuota especial
        "cuota_estandar_plan": 175_000,
        "modalidad_pago":    "semanal",
        "saldo_capital":     5_750_000,
        "saldo_intereses":   1_069_750,
    },
    {
        "loanbook_id":       "LB-2026-0030",
        "capital_plan":       5_750_000,
        "total_cuotas":           52,
        "cuotas_pagadas":          0,
        "cuota_periodica":     182_000,   # cuota especial
        "cuota_estandar_plan": 160_000,
        "modalidad_pago":    "semanal",
        "saldo_capital":     5_750_000,
        "saldo_intereses":   2_570_000,
    },
    {
        "loanbook_id":       "LB-2026-0031",
        "capital_plan":       5_750_000,
        "total_cuotas":           39,
        "cuotas_pagadas":          0,
        "cuota_periodica":     175_000,
        "cuota_estandar_plan": 175_000,
        "modalidad_pago":    "semanal",
        "saldo_capital":     5_750_000,
        "saldo_intereses":   1_069_750,
    },
]

# Campos que el script sincroniza
SYNC_FIELDS = (
    "capital_plan",
    "total_cuotas",
    "cuotas_pagadas",
    "cuota_periodica",
    "cuota_estandar_plan",
    "modalidad_pago",
    "saldo_capital",
    "saldo_intereses",
)

ESTADOS_SKIP = {"saldado", "castigado"}


async def main() -> None:
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name   = os.environ.get("DB_NAME", "sismo-prod")
    client    = AsyncIOMotorClient(mongo_url)
    db        = client[db_name]

    from core.datetime_utils import now_iso_bogota

    print(f"\n{'='*65}")
    print("SYNC LEGACY SALDOS — fuente: Excel loanbook_roddos_2026-04-25")
    print(f"{'='*65}\n")

    sincronizados = 0
    sin_cambio    = 0
    no_encontrado = 0

    for canon in CANONICAL:
        lb_id = canon["loanbook_id"]
        lb    = await db.loanbook.find_one({"loanbook_id": lb_id})

        if not lb:
            print(f"  {lb_id}: NO ENCONTRADO")
            no_encontrado += 1
            continue

        # Comparar campos actuales contra canónicos
        diff: dict = {}
        for campo in SYNC_FIELDS:
            val_canon = canon[campo]
            val_actual = lb.get(campo)
            # Normalizar: ambos a int para campos numéricos
            if isinstance(val_canon, int) and val_actual is not None:
                val_actual = int(val_actual)
            if val_actual != val_canon:
                diff[campo] = (val_actual, val_canon)

        if not diff:
            sc = canon["saldo_capital"]
            si = canon["saldo_intereses"]
            print(
                f"  {lb_id}: OK (sin cambio) | "
                f"sc={sc:,} si={si:,}"
            )
            sin_cambio += 1
            continue

        # Construir $set con campos canónicos + timestamp
        set_doc = {campo: canon[campo] for campo in SYNC_FIELDS}
        set_doc["updated_at"] = now_iso_bogota()

        # Sincronizar también num_cuotas (alias de total_cuotas) si existe
        set_doc["num_cuotas"] = canon["total_cuotas"]

        await db.loanbook.update_one(
            {"loanbook_id": lb_id},
            {"$set": set_doc},
        )

        cambios_str = ", ".join(
            f"{c}: {v[0]} → {v[1]}" for c, v in diff.items()
        )
        sc = canon["saldo_capital"]
        si = canon["saldo_intereses"]
        total_lb = sc + si
        print(
            f"  {lb_id}: SYNC | "
            f"sc={sc:,} si={si:,} total={total_lb:,}"
        )
        if len(diff) <= 4:
            print(f"    cambios: {cambios_str}")
        sincronizados += 1

    # ── Suma total de cartera ─────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"RESULTADO: {sincronizados} sync, {sin_cambio} sin cambio, {no_encontrado} no encontrados")

    cursor = db.loanbook.find({
        "estado": {"$nin": list(ESTADOS_SKIP) + ["pendiente_entrega"]},
    })
    todos = await cursor.to_list(length=2000)

    cartera_total = sum(
        (lb.get("saldo_capital", 0) or 0) + (lb.get("saldo_intereses", 0) or 0)
        for lb in todos
        if lb.get("estado") not in ESTADOS_SKIP
        and lb.get("estado") != "pendiente_entrega"
    )

    print(f"\nCARTERA TOTAL (saldo_capital + saldo_intereses): ${cartera_total:,.0f}")
    print(f"Objetivo:                                        $256,694,850")
    diff_vs_objetivo = cartera_total - 256_694_850
    print(f"Diferencia:                                      ${diff_vs_objetivo:+,.0f}")
    print(f"{'='*65}\n")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
