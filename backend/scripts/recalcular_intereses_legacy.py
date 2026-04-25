"""
scripts/recalcular_intereses_legacy.py — Corregir saldo_intereses en loanbooks legacy.

Problema: LB-0001..LB-0008 (y otros) tienen saldo_intereses=0 porque:
  - capital_plan no estaba seteado, O
  - cuota_estandar_plan = cuota_periodica cuando debería ser la cuota del catálogo

Solución: Para cada loanbook activo con saldo_intereses=0:
  1. Determinar capital_plan por tipo de moto (Sport=5,750,000 / Raider=7,800,000)
  2. Aplicar cuota_estandar_plan correcta según plan_codigo + moto
  3. Recalcular con calcular_saldos()
  4. Actualizar MongoDB

Cuota estándar por plan y moto (fuente: Excel loanbook_roddos_2026-04-25.xlsx):
  P39S Sport  semanal = 175,000  |  P39S Raider semanal = 210,000
  P52S Sport  semanal = 160,000  |  P52S Raider semanal = 179,900
  P78S Sport  semanal = 130,000  |  P78S Raider semanal = 149,900

Idempotente: si saldo_intereses ya > 0, solo imprime y NO modifica.

Render Shell:
  cd /opt/render/project/src
  python3 scripts/recalcular_intereses_legacy.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from motor.motor_asyncio import AsyncIOMotorClient

# ─── Mapa cuota_estandar_plan por (plan_codigo, tipo_moto) ───────────────────
# tipo_moto: "sport" = Sport 100, "raider" = Raider 125

CUOTA_ESTANDAR_MAP: dict[tuple[str, str], int] = {
    ("P39S", "sport"):  175_000,
    ("P39S", "raider"): 210_000,
    ("P52S", "sport"):  160_000,
    ("P52S", "raider"): 179_900,
    ("P78S", "sport"):  130_000,
    ("P78S", "raider"): 149_900,
}

CAPITAL_SPORT  = 5_750_000
CAPITAL_RAIDER = 7_800_000

ESTADOS_TERMINALES = {"saldado", "castigado"}


def _tipo_moto(capital_plan: int) -> str | None:
    """Sport 100 → 'sport' | Raider 125 → 'raider' | otro → None (RODANTE)."""
    if capital_plan == CAPITAL_SPORT:
        return "sport"
    if capital_plan == CAPITAL_RAIDER:
        return "raider"
    return None


async def main() -> None:
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name   = os.environ.get("DB_NAME", "sismo-prod")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    from services.loanbook.reglas_negocio import calcular_saldos
    from core.datetime_utils import now_iso_bogota

    print(f"\n{'='*65}")
    print("RECALCULAR INTERESES LEGACY — diagnóstico + corrección")
    print(f"{'='*65}\n")

    # Traer todos los loanbooks activos (no terminales, no pendiente_entrega)
    cursor = db.loanbook.find({
        "estado": {"$nin": list(ESTADOS_TERMINALES) + ["pendiente_entrega"]},
    })
    lbs = await cursor.to_list(length=2000)
    print(f"Loanbooks activos encontrados: {len(lbs)}\n")

    modificados = 0
    saltados    = 0

    for lb in lbs:
        lb_id    = lb.get("loanbook_id", str(lb.get("_id", "?")))
        nombre   = lb.get("cliente_nombre", lb.get("nombre_cliente", ""))
        plan_cod = lb.get("plan_codigo") or (lb.get("plan") or {}).get("codigo") or ""
        cap_plan = int(lb.get("capital_plan", 0) or 0)

        si_actual = lb.get("saldo_intereses", 0) or 0

        # ── Diagnóstico ─────────────────────────────────────────────────────
        print(
            f"  {lb_id:<18} plan={plan_cod:<6} "
            f"capital_plan={cap_plan:>10,} "
            f"si_actual={si_actual:>10,}"
        )

        # Sin capital_plan → no podemos calcular interés
        if cap_plan == 0:
            print(f"    → SKIP: capital_plan=0 (RODANTE o legacy sin capital)")
            saltados += 1
            continue

        # Identificar tipo de moto
        tipo = _tipo_moto(cap_plan)
        if tipo is None:
            print(f"    → SKIP: capital_plan={cap_plan:,} no es Sport ni Raider (RODANTE)")
            saltados += 1
            continue

        # Buscar cuota_estandar correcta
        plan_upper = plan_cod.upper().replace(" ", "")
        cuota_std = CUOTA_ESTANDAR_MAP.get((plan_upper, tipo))
        if cuota_std is None:
            print(f"    → SKIP: plan {plan_cod}/{tipo} no tiene cuota_estandar en el mapa")
            saltados += 1
            continue

        # Parámetros del crédito
        num_cuotas  = (
            lb.get("num_cuotas", 0)
            or (lb.get("plan") or {}).get("total_cuotas", 0)
            or 0
        )
        cuota_monto = int(
            lb.get("cuota_periodica") or lb.get("cuota_monto")
            or (lb.get("plan") or {}).get("cuota_valor") or 0
        )
        cuotas_list  = lb.get("cuotas", [])
        cuotas_pag   = sum(1 for c in cuotas_list if c.get("estado") == "pagada")

        if num_cuotas <= 0 or cuota_monto <= 0:
            print(f"    → SKIP: num_cuotas={num_cuotas} cuota_monto={cuota_monto}")
            saltados += 1
            continue

        # Calcular saldos correctos
        saldos = calcular_saldos(
            capital_plan=cap_plan,
            total_cuotas=num_cuotas,
            cuota_periodica=cuota_monto,
            cuotas_pagadas=cuotas_pag,
            cuota_estandar_plan=cuota_std,
        )

        sc_nuevo = saldos["saldo_capital"]
        si_nuevo = saldos["saldo_intereses"]

        # Si saldo_intereses ya está correcto → no tocar
        if si_actual > 0 and abs(si_actual - si_nuevo) < 10_000:
            print(
                f"    → OK: si ya correcto ({si_actual:,}) — sin cambios"
            )
            saltados += 1
            continue

        # Actualizar
        print(
            f"    → ACTUALIZANDO: "
            f"sc {lb.get('saldo_capital', 0):,} → {sc_nuevo:,} | "
            f"si {si_actual:,} → {si_nuevo:,} | "
            f"cuota_std={cuota_std:,}"
        )

        await db.loanbook.update_one(
            {"loanbook_id": lb_id},
            {"$set": {
                "saldo_capital":      sc_nuevo,
                "saldo_intereses":    si_nuevo,
                "capital_plan":       cap_plan,
                "cuota_estandar_plan": cuota_std,
                "updated_at":         now_iso_bogota(),
            }},
        )
        modificados += 1

    print(f"\n{'='*65}")
    print(f"RESULTADO: {modificados} loanbooks actualizados, {saltados} saltados")
    print("Verificar con GET /api/loanbook/stats → cartera_total")
    print(f"{'='*65}\n")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
