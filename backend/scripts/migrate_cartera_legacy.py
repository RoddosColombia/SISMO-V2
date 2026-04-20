"""
migrate_cartera_legacy.py — BUILD 0.2 (V2)

Migra 59 créditos del Excel de scoring RODDOS a la colección
loanbook_legacy en sismo-v2.

Dedup por codigo_sismo = LG-{cedula}-{num_credito}.
Upsert idempotente: no destruye pagos_recibidos ni alegra_contact_id
si el documento ya existe.

Usage:
    python -m scripts.migrate_cartera_legacy --excel "ruta/al/archivo.xlsx"
    python -m scripts.migrate_cartera_legacy --excel "ruta/..." --dry-run

Requiere MONGO_URL en el entorno (Render env var o export local).
"""
import argparse
import asyncio
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne

V2_DB         = "sismo-v2"
COLLECTION    = "loanbook_legacy"
SHEET_NAME    = "Créditos Activos"
SKIPROWS      = 2       # fila 0: título, fila 1: resumen → fila 2: headers reales
ESTADO_FIJO   = "activo"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _s(val, default=None) -> str | None:
    """Safe str: NaN → default."""
    if val is None:
        return default
    if isinstance(val, float) and math.isnan(val):
        return default
    s = str(val).strip()
    return s or default


def _f(val, default=None) -> float | None:
    """Safe float."""
    if val is None:
        return default
    if isinstance(val, float) and math.isnan(val):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _i(val, default=None) -> int | None:
    """Safe int."""
    if val is None:
        return default
    if isinstance(val, float) and math.isnan(val):
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def parse_row(row: dict) -> dict | None:
    """
    Convierte una fila del Excel en un documento loanbook_legacy.
    Retorna None si la fila no es válida.
    """
    id_credito = _s(row.get("Id crédito"))
    if not id_credito:
        return None

    partes = id_credito.split("-")
    if len(partes) < 2:
        print(f"  [SKIP] Id sin guión: {id_credito!r}")
        return None

    cedula = partes[0].strip()
    num    = partes[1].strip()
    codigo = f"LG-{cedula}-{num}"

    nombre    = _s(row.get("Nombre"), "")
    apellidos = _s(row.get("Apellidos"), "")
    nombre_completo = f"{nombre} {apellidos}".strip() or "SIN NOMBRE"

    aliado       = _s(row.get("Aliado"), "Sin aliado")
    estado_excel = _s(row.get("Estado"), "En Mora")
    # Normalizar encoding roto en Windows ("Al DÃ­a" → "Al Día")
    if estado_excel and "Al D" in estado_excel and estado_excel != "Al Día":
        estado_excel = "Al Día"

    saldo_actual = _f(row.get("Saldo\nx Cobrar"), 0.0)

    return {
        "codigo_sismo":            codigo,
        "cedula":                  cedula,
        "numero_credito_original": num,
        "nombre_completo":         nombre_completo,
        "placa":                   _s(row.get("Placa")),
        "aliado":                  aliado,
        "estado":                  ESTADO_FIJO,
        "estado_legacy_excel":     estado_excel,
        "saldo_actual":            saldo_actual,
        "saldo_inicial":           saldo_actual,   # no disponible en Excel
        "score_total":             _f(row.get("Score Total")),
        "pct_on_time":             _f(row.get("% On Time")),
        "dias_mora_maxima":        _i(row.get("Días Máx")),
        "decision_historica":      _s(row.get("DECISIÓN")),
        "analisis_texto":          _s(row.get("Análisis")),
        "fecha_importacion":       datetime.now(timezone.utc),
        "updated_at":              datetime.now(timezone.utc),
    }


# ── Core ──────────────────────────────────────────────────────────────────────

async def run(excel_path: str, sheet: str, dry_run: bool) -> None:
    print(f"\n{'[DRY-RUN] ' if dry_run else ''}BUILD 0.2 (V2) — migrate_cartera_legacy")
    print(f"Excel  : {excel_path}")
    print(f"Sheet  : {sheet}")
    if not dry_run:
        print(f"DB     : {V2_DB}.{COLLECTION}")
    print()

    # ── 1. Leer + dedup Excel ─────────────────────────────────────────────────
    df = pd.read_excel(excel_path, sheet_name=sheet, skiprows=SKIPROWS)
    print(f"Filas brutas : {len(df)}")
    df = df.drop_duplicates(subset=["Id crédito"], keep="first")
    print(f"Tras dedup   : {len(df)}")

    # ── 2. Parsear ─────────────────────────────────────────────────────────────
    docs: list[dict] = []
    skipped = 0
    for _, row in df.iterrows():
        doc = parse_row(row.to_dict())
        if doc is None:
            skipped += 1
        else:
            docs.append(doc)

    print(f"Docs válidos : {len(docs)}  |  Skips: {skipped}")
    print()

    # ── 3. Dry-run preview ────────────────────────────────────────────────────
    if dry_run:
        def _safe(s: str, w: int = 28) -> str:
            return s[:w].encode("ascii", "replace").decode("ascii")

        for d in docs[:5]:
            print(
                f"  {d['codigo_sismo']} | {_safe(d['nombre_completo']):<28} "
                f"| {_safe(d['aliado'], 16):<16} | {d['estado_legacy_excel'][:8]:<8} "
                f"| ${d['saldo_actual']:>10,.0f}"
            )
        if len(docs) > 5:
            print(f"  ... y {len(docs) - 5} mas")
        print("\n[DRY-RUN] Nada escrito en MongoDB.")
        return

    # ── 4. Upsert a MongoDB ───────────────────────────────────────────────────
    mongo_url = os.environ["MONGO_URL"]
    client = AsyncIOMotorClient(mongo_url)
    col = client[V2_DB][COLLECTION]

    # Índice único
    await col.create_index("codigo_sismo", unique=True, background=True)

    ops = [
        UpdateOne(
            {"codigo_sismo": doc["codigo_sismo"]},
            {
                "$set": doc,
                "$setOnInsert": {
                    "pagos_recibidos":   [],
                    "alegra_contact_id": None,
                    "created_at":        datetime.now(timezone.utc),
                },
            },
            upsert=True,
        )
        for doc in docs
    ]

    result = await col.bulk_write(ops, ordered=False)
    client.close()

    print("Resultado MongoDB:")
    print(f"  Insertados  : {result.upserted_count}")
    print(f"  Actualizados: {result.modified_count}")
    print(f"  Total ops   : {len(ops)}")

    # Verificacion final
    client2 = AsyncIOMotorClient(mongo_url)
    total = await client2[V2_DB][COLLECTION].count_documents({})
    client2.close()
    print(f"  Total en coleccion: {total}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migra creditos legacy a sismo-v2")
    parser.add_argument("--excel",   required=True, help="Ruta al archivo .xlsx")
    parser.add_argument("--sheet",   default=SHEET_NAME, help="Nombre del sheet")
    parser.add_argument("--dry-run", action="store_true", help="Solo parsear, no escribir")
    args = parser.parse_args()

    asyncio.run(run(args.excel, args.sheet, args.dry_run))
