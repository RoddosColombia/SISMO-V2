"""
Migrate backlog movements from SISMO V1 (sismo) to V2 (sismo-v2).

V1 collection: contabilidad_pendientes (277 pendiente, 21 descartado)
V1 fields: fecha, descripcion, monto, tipo (EGRESO/INGRESO), banco,
           backlog_hash, referencia_original, proveedor_extraido,
           cuenta_debito_sugerida, cuenta_credito_sugerida,
           confianza_motor, razon_baja_confianza, estado

V2 collection: backlog_movimientos
V2 fields: fecha, banco, descripcion, monto, tipo (debito/credito),
           razon_pendiente, intentos, estado

Usage:
    python -m scripts.migrate_backlog explore
    python -m scripts.migrate_backlog export
    python -m scripts.migrate_backlog import
"""
import asyncio
import hashlib
import os
import sys
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

V1_DB = "sismo"
V2_DB = "sismo-v2"
V1_COLLECTION = "contabilidad_pendientes"

# Normalize V1 banco names to V2 format
BANCO_NORMALIZE = {
    "bbva": "BBVA",
    "bancolombia": "Bancolombia",
    "nequi": "Nequi",
    "davivienda": "Davivienda",
    "global66": "Global66",
}


def _hash_movimiento(fecha: str, descripcion: str, monto: float, banco: str) -> str:
    raw = f"{fecha}|{descripcion}|{monto}|{banco}"
    return hashlib.md5(raw.encode()).hexdigest()


async def explore():
    """Show V1 collection stats."""
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[V1_DB]
    col = db[V1_COLLECTION]

    total = await col.count_documents({})
    pendiente = await col.count_documents({"estado": "pendiente"})
    descartado = await col.count_documents({"estado": "descartado"})

    print(f"\n=== V1 {V1_DB}.{V1_COLLECTION} ===")
    print(f"  Total: {total}")
    print(f"  Pendiente: {pendiente}")
    print(f"  Descartado: {descartado}")

    for banco in ["bbva", "bancolombia", "nequi", "davivienda"]:
        c = await col.count_documents({"estado": "pendiente", "banco": banco})
        if c > 0:
            print(f"  pendiente/{banco}: {c}")

    # Sample
    sample = await col.find_one({"estado": "pendiente"})
    if sample:
        sample["_id"] = str(sample["_id"])
        print(f"\n  Sample keys: {list(sample.keys())}")

    client.close()


async def export_summary():
    """Count V1 pendientes by banco."""
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[V1_DB]
    col = db[V1_COLLECTION]

    print(f"\n=== Export summary: {V1_DB}.{V1_COLLECTION} (pendiente only) ===")

    total = 0
    for banco in ["bbva", "bancolombia", "nequi", "davivienda"]:
        c = await col.count_documents({"estado": "pendiente", "banco": banco})
        if c > 0:
            print(f"  {BANCO_NORMALIZE.get(banco, banco)}: {c}")
            total += c
    print(f"  TOTAL: {total}")

    client.close()


async def import_to_v2():
    """Import V1 pendiente movements to V2 backlog_movimientos."""
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db_v1 = client[V1_DB]
    db_v2 = client[V2_DB]

    col_v1 = db_v1[V1_COLLECTION]
    col_v2 = db_v2["backlog_movimientos"]

    print(f"\n=== Importing: {V1_DB}.{V1_COLLECTION} -> {V2_DB}.backlog_movimientos ===")

    # Only import pendiente (not descartado)
    cursor = col_v1.find({"estado": "pendiente"})
    imported = 0
    skipped = 0
    errors = 0

    async for doc in cursor:
        try:
            fecha = str(doc.get("fecha") or "")
            descripcion = str(doc.get("descripcion") or "")
            monto = float(doc.get("monto") or 0)
            banco_raw = str(doc.get("banco") or "")
            banco = BANCO_NORMALIZE.get(banco_raw.lower(), banco_raw)
            tipo_v1 = str(doc.get("tipo") or "EGRESO")
            tipo = "debito" if tipo_v1.upper() == "EGRESO" else "credito"

            if not fecha and not descripcion:
                errors += 1
                continue

            # Anti-dup by hash
            mov_hash = _hash_movimiento(fecha, descripcion, monto, banco)
            existing = await col_v2.find_one({"_migration_hash": mov_hash})
            if existing:
                skipped += 1
                continue

            # Build V2 document
            v2_doc = {
                "fecha": fecha,
                "banco": banco,
                "descripcion": descripcion,
                "monto": abs(monto),
                "tipo": tipo,
                "razon_pendiente": str(doc.get("razon_baja_confianza") or "Importado de SISMO V1"),
                "intentos": 0,
                "estado": "pendiente",
                "fecha_ingreso_backlog": datetime.now(timezone.utc).isoformat(),
                "source": "migration_v1",
                "_migration_hash": mov_hash,
            }

            # Preserve V1 metadata
            if doc.get("referencia_original"):
                v2_doc["referencia"] = str(doc["referencia_original"])
            if doc.get("proveedor_extraido"):
                v2_doc["proveedor_v1"] = str(doc["proveedor_extraido"])
            if doc.get("confianza_motor"):
                v2_doc["confianza_v1"] = float(doc["confianza_motor"])
            if doc.get("cuenta_debito_sugerida"):
                v2_doc["clasificacion_sugerida"] = {
                    "cuenta_debito": str(doc["cuenta_debito_sugerida"]),
                    "cuenta_credito": str(doc.get("cuenta_credito_sugerida") or ""),
                }
            if doc.get("backlog_hash"):
                v2_doc["backlog_hash_v1"] = str(doc["backlog_hash"])

            await col_v2.insert_one(v2_doc)
            imported += 1

        except Exception as e:
            errors += 1
            print(f"  ERROR: {e}")

    print(f"\n  Imported: {imported}")
    print(f"  Skipped (dup): {skipped}")
    print(f"  Errors: {errors}")
    print(f"  Total processed: {imported + skipped + errors}")

    # Verify
    total_v2 = await col_v2.count_documents({"estado": "pendiente"})
    print(f"\n  V2 backlog_movimientos (pendiente): {total_v2}")

    client.close()


async def main():
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.migrate_backlog [explore|export|import]")
        return

    cmd = sys.argv[1]
    if cmd == "explore":
        await explore()
    elif cmd == "export":
        await export_summary()
    elif cmd == "import":
        await import_to_v2()
    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    asyncio.run(main())
