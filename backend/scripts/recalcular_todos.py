"""
scripts/recalcular_todos.py — Migración one-shot para BUILD 2 Sprint Estructural.

Recalcula num_cuotas, valor_total y saldo_capital en TODOS los loanbooks de
producción, usando PLANES_RODDOS como fuente canónica.

Uso:
    # Dry run (ver qué cambiaría, sin tocar nada):
    python scripts/recalcular_todos.py --dry-run

    # Aplicar cambios reales:
    python scripts/recalcular_todos.py

Variables de entorno requeridas:
    MONGO_URL   — URI de conexión a MongoDB
    DB_NAME     — nombre de la base de datos

Seguridad:
    - Solo sobreescribe: num_cuotas, valor_total, saldo_capital, total_pagado, plan.total_cuotas
    - NO toca: estado, cuotas, cliente, vin, modalidad, fechas, eventos
    - Idempotente — se puede correr múltiples veces sin riesgo
"""

import asyncio
import os
import sys
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

# Agregar el directorio padre al path para importar desde services/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.loanbook.state_calculator import patch_set_from_recalculo, PLANES_RODDOS


async def recalcular_todos(dry_run: bool = False) -> None:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")

    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL y DB_NAME son requeridos.")
        sys.exit(1)

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    docs = await db.loanbook.find().to_list(length=5000)
    print(f"{'[DRY RUN] ' if dry_run else ''}Analizando {len(docs)} loanbooks...")
    print()

    modificados = 0
    sin_plan = 0
    ya_correctos = 0

    for doc in docs:
        loanbook_id = doc.get("loanbook_id", str(doc.get("_id", "?")))
        plan_codigo = doc.get("plan_codigo") or doc.get("plan", {}).get("codigo")

        if not plan_codigo or plan_codigo not in PLANES_RODDOS:
            sin_plan += 1
            continue

        doc.pop("_id", None)
        patch = patch_set_from_recalculo(doc)

        # Solo campos estructurales
        campos = {k: v for k, v in patch.items()
                  if k in ("num_cuotas", "valor_total", "saldo_capital", "total_pagado", "plan")}

        # Detectar si algo cambió realmente
        hay_cambios = False
        diffs = {}
        for campo, valor_nuevo in campos.items():
            if campo == "plan":
                # Comparar solo total_cuotas dentro del subdoc
                old_tc = doc.get("plan", {}).get("total_cuotas")
                new_tc = valor_nuevo.get("total_cuotas") if isinstance(valor_nuevo, dict) else None
                if old_tc != new_tc:
                    hay_cambios = True
                    diffs["plan.total_cuotas"] = f"{old_tc} → {new_tc}"
            else:
                valor_viejo = doc.get(campo)
                if valor_viejo != valor_nuevo:
                    hay_cambios = True
                    diffs[campo] = f"{valor_viejo} → {valor_nuevo}"

        if not hay_cambios:
            ya_correctos += 1
            continue

        cliente_nombre = doc.get("cliente", {}).get("nombre", "?")
        print(f"  {'[WOULD UPDATE]' if dry_run else '[UPDATING]'} {loanbook_id} ({cliente_nombre})")
        for campo, diff in diffs.items():
            print(f"    {campo}: {diff}")

        if not dry_run:
            await db.loanbook.update_one(
                {"loanbook_id": loanbook_id},
                {"$set": {
                    **campos,
                    "recalculado_at": datetime.now(timezone.utc).isoformat(),
                }},
            )

        modificados += 1

    print()
    print("─" * 50)
    print(f"Total loanbooks: {len(docs)}")
    print(f"Ya correctos:    {ya_correctos}")
    print(f"Sin plan conocido: {sin_plan}")
    print(f"{'Serían modificados' if dry_run else 'Modificados'}:   {modificados}")

    if dry_run and modificados > 0:
        print()
        print("Para aplicar: python scripts/recalcular_todos.py")

    client.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv or "-n" in sys.argv
    asyncio.run(recalcular_todos(dry_run=dry))
