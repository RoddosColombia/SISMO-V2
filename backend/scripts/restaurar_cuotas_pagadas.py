"""
restaurar_cuotas_pagadas.py — Restaura estado 'pagada' en cuotas[] de cada loanbook
leyendo los pagos reales de la colección cartera_pagos.

Problema: generar-cronogramas-todos regeneró el array cuotas[] desde cero con todas
las cuotas en estado 'pendiente', perdiendo el estado 'pagada' de cuotas ya cobradas.
Los registros de pago siguen intactos en cartera_pagos.

Estrategia:
  - Por cada loanbook con cuotas_pagadas > 0, buscar sus pagos en cartera_pagos
  - Ordenar pagos por fecha_pago ASC (pago más antiguo primero)
  - Marcar las cuotas en ese mismo orden (cuota 1, 2, 3...) como 'pagada'
  - Copiar fecha_pago, monto_pagado, metodo_pago desde el registro de pago

Idempotente: si la cuota ya tiene estado='pagada' y fecha_pago, no la sobreescribe.

Usage:
    DRY RUN (default — no escribe):
        python -m scripts.restaurar_cuotas_pagadas

    APLICAR:
        python -m scripts.restaurar_cuotas_pagadas --apply
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _pago_fecha_sort_key(pago: dict) -> str:
    """Key de ordenamiento: fecha_pago como ISO string (o '9999' si ausente)."""
    fp = pago.get("fecha_pago") or pago.get("fecha") or ""
    if isinstance(fp, datetime):
        return fp.isoformat()
    return str(fp)[:10] if fp else "9999-99-99"


def _float(val, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


# ─── Core ─────────────────────────────────────────────────────────────────────

async def restaurar(apply: bool = False) -> None:
    from motor.motor_asyncio import AsyncIOMotorClient

    mongo_url = os.environ.get("MONGO_URL")
    db_name   = os.environ.get("DB_NAME", "sismo-v2")

    if not mongo_url:
        print("ERROR: MONGO_URL no está definido en el entorno.", file=sys.stderr)
        sys.exit(1)

    client = AsyncIOMotorClient(mongo_url)
    db     = client[db_name]

    modo = "APLICANDO" if apply else "DRY RUN (usa --apply para escribir)"
    print(f"\n{'─'*60}")
    print(f"restaurar_cuotas_pagadas — {modo}")
    print(f"DB: {db_name}")
    print(f"{'─'*60}\n")

    # 1. Traer todos los loanbooks que declaran tener cuotas pagadas
    loanbooks = await db.loanbook.find(
        {"cuotas_pagadas": {"$gt": 0}}
    ).to_list(length=None)

    print(f"Loanbooks con cuotas_pagadas > 0: {len(loanbooks)}\n")

    reparados   = 0
    ya_ok       = 0
    sin_pagos   = 0
    total_cuotas_restauradas = 0

    for lb in loanbooks:
        lb_id    = lb.get("loanbook_id") or lb.get("loanbook_codigo") or str(lb["_id"])
        cuotas_pagadas_declaradas = lb.get("cuotas_pagadas", 0)
        cuotas   = lb.get("cuotas") or []

        # Contar cuántas cuotas ya tienen estado=pagada con fecha real
        ya_pagadas = [
            c for c in cuotas
            if c.get("estado") == "pagada" and c.get("fecha_pago")
        ]

        if len(ya_pagadas) >= cuotas_pagadas_declaradas:
            ya_ok += 1
            print(f"  {lb_id}: OK — {len(ya_pagadas)} cuotas ya tienen estado=pagada")
            continue

        # 2. Buscar pagos en cartera_pagos (OR en los tres campos de linkage)
        pagos = await db.cartera_pagos.find({
            "$or": [
                {"loanbook_id":    lb_id},
                {"loanbook_codigo": lb_id},
                {"credito_id":     lb_id},
            ]
        }).to_list(length=None)

        if not pagos:
            sin_pagos += 1
            print(
                f"  {lb_id}: ⚠  cuotas_pagadas={cuotas_pagadas_declaradas} "
                f"pero 0 registros en cartera_pagos"
            )
            continue

        # 3. Ordenar pagos más antiguos primero
        pagos_ordenados = sorted(pagos, key=_pago_fecha_sort_key)

        # 4. Construir updates — marcar cuotas 0..N-1 como pagadas
        updates: dict = {}
        cuotas_a_restaurar = 0

        for idx, pago in enumerate(pagos_ordenados):
            if idx >= len(cuotas):
                print(
                    f"  {lb_id}: ⚠  pago #{idx+1} no tiene cuota correspondiente "
                    f"(total cuotas={len(cuotas)}) — saltando"
                )
                break

            cuota = cuotas[idx]

            # No sobreescribir cuota que ya tiene estado correcto
            if cuota.get("estado") == "pagada" and cuota.get("fecha_pago"):
                continue

            fecha_pago  = pago.get("fecha_pago") or pago.get("fecha")
            monto_pagado = _float(pago.get("monto") or pago.get("monto_pagado"))
            metodo_pago  = pago.get("metodo_pago") or pago.get("banco") or "transferencia"

            # Normalizar fecha a string ISO si es datetime
            if isinstance(fecha_pago, datetime):
                fecha_pago = fecha_pago.date().isoformat()

            updates[f"cuotas.{idx}.estado"]       = "pagada"
            updates[f"cuotas.{idx}.fecha_pago"]   = fecha_pago
            updates[f"cuotas.{idx}.monto_pagado"] = monto_pagado or _float(cuota.get("monto"))
            updates[f"cuotas.{idx}.metodo_pago"]  = metodo_pago
            cuotas_a_restaurar += 1

        if not updates:
            ya_ok += 1
            print(f"  {lb_id}: OK — sin cambios necesarios")
            continue

        updates["updated_at"] = datetime.utcnow()

        print(
            f"  {lb_id}: restaurando {cuotas_a_restaurar} cuota(s) "
            f"[de {len(pagos_ordenados)} pago(s) encontrados]"
        )

        if apply:
            await db.loanbook.update_one({"_id": lb["_id"]}, {"$set": updates})

        reparados += 1
        total_cuotas_restauradas += cuotas_a_restaurar

    # ── Resumen ───────────────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"Resumen:")
    print(f"  Loanbooks procesados:   {len(loanbooks)}")
    print(f"  Ya correctos:           {ya_ok}")
    print(f"  Sin pagos en cartera:   {sin_pagos}")
    print(f"  A reparar:              {reparados}")
    print(f"  Cuotas a restaurar:     {total_cuotas_restauradas}")
    if not apply:
        print(f"\n[DRY RUN] Nada escrito. Corre con --apply para aplicar.")
    else:
        print(f"\n[APLICADO] {reparados} loanbooks actualizados en MongoDB.")
    print(f"{'─'*60}\n")

    client.close()


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    apply_flag = "--apply" in sys.argv
    asyncio.run(restaurar(apply=apply_flag))
