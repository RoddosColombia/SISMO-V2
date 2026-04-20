"""
cleanup_backlog_basura.py — BUILD 0.4 (V2)

Elimina 2 filas basura de backlog_movimientos:
  - Registros con fecha < 2026-01-01 (filas de encabezado/totales del Excel)
  - Registros cuya descripcion contiene "TOTALES" (case-insensitive)

Usage:
    python -m scripts.cleanup_backlog_basura [--dry-run]

Requiere MONGO_URL en el entorno.
"""
import argparse
import asyncio
import os
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

V2_DB   = "sismo-v2"
COL_BLG = "backlog_movimientos"

FILTER_BASURA = {
    "$or": [
        {"fecha": {"$lt": "2026-01-01"}},
        {"descripcion": {"$regex": "TOTALES", "$options": "i"}},
    ]
}


async def run(dry_run: bool) -> None:
    print(f"\n{'[DRY-RUN] ' if dry_run else ''}BUILD 0.4 (V2) — cleanup_backlog_basura")
    print(f"DB: {V2_DB}.{COL_BLG}\n")

    mongo_url = os.environ["MONGO_URL"]
    client = AsyncIOMotorClient(mongo_url)
    col = client[V2_DB][COL_BLG]

    # ── 1. Contar antes ───────────────────────────────────────────────────────
    total_antes = await col.count_documents({})
    print(f"Total antes  : {total_antes}  (esperado: 525)")

    # ── 2. Mostrar qué se eliminaría ──────────────────────────────────────────
    basura = await col.find(FILTER_BASURA, {"fecha": 1, "descripcion": 1, "_id": 0}).to_list(length=20)
    print(f"Filas basura : {len(basura)}")
    for b in basura:
        print(f"  fecha={b.get('fecha')}  desc={str(b.get('descripcion',''))[:60]}")

    if dry_run:
        print("\n[DRY-RUN] Nada eliminado.")
        client.close()
        return

    # ── 3. Eliminar ───────────────────────────────────────────────────────────
    result = await col.delete_many(FILTER_BASURA)
    print(f"\nEliminados   : {result.deleted_count}  (esperado: 2)")

    # ── 4. Contar después ─────────────────────────────────────────────────────
    total_post = await col.count_documents({})
    print(f"Total después: {total_post}  (esperado: 523)")

    # ── 5. Test-gate ──────────────────────────────────────────────────────────
    print()
    checks = [
        ("deleted_count == 2",          result.deleted_count == 2),
        ("total_post == 523",           total_post == 523),
        ("no fecha < 2026",             await col.count_documents({"fecha": {"$lt": "2026-01-01"}}) == 0),
        ("no descripcion TOTALES",      await col.count_documents({"descripcion": {"$regex": "TOTALES", "$options": "i"}}) == 0),
    ]
    all_pass = True
    for label, passed in checks:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {label}")
        if not passed:
            all_pass = False

    print()
    print("=" * 50)
    print(f"BUILD 0.4  {'ALL PASS' if all_pass else 'FAILED'}")
    print(f"  Antes    : {total_antes}")
    print(f"  Eliminados: {result.deleted_count}")
    print(f"  Despues  : {total_post}")
    print("=" * 50)

    client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Limpia filas basura del backlog")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar, no eliminar")
    args = parser.parse_args()
    asyncio.run(run(args.dry_run))
