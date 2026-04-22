"""
scripts/migrar_loanbooks_a_schema_dual.py — Migración idempotente al schema dual RDX/RODANTE.

Qué hace:
  1. Backup de los documentos actuales en backups/loanbooks_pre_B1_{timestamp}.json
  2. Para cada loanbook sin `producto` → agrega `producto='RDX'`
  3. Si no tiene `metadata_producto` → lo construye desde campos sueltos (vin, modelo, motor, placa)
  4. Agrega campos nuevos con defaults si no existen:
     saldo_intereses=0.0, subtipo_rodante=None, score_riesgo=None,
     whatsapp_status='pending', sub_bucket_semanal=None,
     fecha_vencimiento=None, acuerdo_activo_id=None
  5. Crea las 4 nuevas colecciones con sus índices (idempotente)

Seguridad:
  - Idempotente: ya que cada campo se setea con $set y solo si no existe ($setOnInsert no aplica
    aquí, pero usamos lógica explícita para no sobreescribir datos existentes)
  - Backup antes de tocar nada
  - Modo --dry-run: muestra qué haría, sin escribir

Uso:
  cd backend
  python scripts/migrar_loanbooks_a_schema_dual.py --dry-run   # verificar
  python scripts/migrar_loanbooks_a_schema_dual.py             # ejecutar

Requiere:
  - MONGO_URL en .env
  - DB_NAME en .env (default: sismo-prod)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import motor.motor_asyncio

# ─────────────────────── Config ───────────────────────────────────────────────

MONGO_URL = os.getenv("MONGO_URL", "")
DB_NAME   = os.getenv("DB_NAME", "sismo-prod")

if not MONGO_URL:
    print("❌ MONGO_URL no está definida. Configura tu .env antes de continuar.")
    sys.exit(1)

BACKUP_DIR = Path(__file__).parent.parent / "backups"


# ─────────────────────── Helpers ──────────────────────────────────────────────

def _sep(char: str = "─", width: int = 60) -> None:
    print(char * width)


def _build_metadata_rdx(lb: dict) -> dict:
    """Construye metadata_producto para RDX desde campos sueltos del documento."""
    # Intenta extraer desde campo moto subdocumento o top-level
    moto = lb.get("moto") or {}

    vin = lb.get("vin") or moto.get("vin") or ""
    modelo = lb.get("modelo") or moto.get("modelo") or ""
    motor = lb.get("motor") or moto.get("motor")
    placa = lb.get("placa") or moto.get("placa")

    meta: dict = {
        "moto_vin":    vin,
        "moto_modelo": modelo,
    }
    if motor:
        meta["moto_motor"] = motor
    if placa:
        meta["moto_placa"] = placa

    return meta


def _inferir_subtipo(lb: dict) -> str | None:
    """Infiere el subtipo RODANTE desde tipo_producto o modelo del loanbook legacy."""
    tipo = lb.get("tipo_producto", "").lower()
    modelo = (lb.get("modelo") or "").upper()

    if tipo == "moto":
        return None  # RDX, no RODANTE
    if tipo == "comparendo" or "COMPARENDO" in modelo:
        return "comparendo"
    if tipo == "licencia" or "LICENCIA" in modelo:
        return "licencia"
    if tipo == "soat" or "SOAT" in modelo:
        return "soat"
    if tipo == "repuestos" or "REPUESTO" in modelo:
        return "repuestos"
    return None  # default RDX


def _inferir_producto(lb: dict) -> str:
    """Infiere el producto desde tipo_producto o campos existentes."""
    tipo = lb.get("tipo_producto", "").lower()
    if tipo in ("comparendo", "licencia", "soat", "repuestos"):
        return "RODANTE"
    return "RDX"  # default


# ─────────────────────── JSON serializer para backup ─────────────────────────

class _MongoEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        try:
            from bson import ObjectId
            if isinstance(obj, ObjectId):
                return str(obj)
        except ImportError:
            pass
        return super().default(obj)


# ─────────────────────── Lógica principal ─────────────────────────────────────

async def migrar(dry_run: bool = False) -> None:
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
    db     = client[DB_NAME]

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    print()
    _sep("═")
    print(f"  MIGRACIÓN B1 — SCHEMA DUAL RDX/RODANTE")
    print(f"  DB: {DB_NAME}")
    if dry_run:
        print("  MODO: DRY-RUN (sin escrituras)")
    _sep("═")

    # ── 1. BACKUP ─────────────────────────────────────────────────────────────
    print()
    _sep()
    print("  PASO 1 — Backup loanbooks")
    _sep()

    docs = await db.loanbook.find({}).to_list(length=None)
    total = len(docs)
    print(f"  Encontrados: {total} loanbooks")

    if not dry_run:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup_path = BACKUP_DIR / f"loanbooks_pre_B1_{ts}.json"
        # Serializar ObjectId como strings
        docs_serializable = json.loads(
            json.dumps(docs, cls=_MongoEncoder)
        )
        backup_path.write_text(
            json.dumps(docs_serializable, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  ✅ Backup escrito: {backup_path}")
    else:
        print(f"  [DRY-RUN] Backup se escribiría en backups/loanbooks_pre_B1_{ts}.json")

    # ── 2. MIGRAR DOCUMENTOS ───────────────────────────────────────────────────
    print()
    _sep()
    print("  PASO 2 — Migrar documentos loanbook")
    _sep()

    migrados = 0
    ya_migrados = 0
    parciales = 0

    for lb in docs:
        lb_id = lb.get("loanbook_id") or str(lb.get("_id", "?"))

        # Determinar si ya tiene los campos nuevos
        tiene_producto       = "producto" in lb
        tiene_metadata       = "metadata_producto" in lb
        tiene_saldo_int      = "saldo_intereses" in lb
        tiene_score          = "score_riesgo" in lb
        tiene_wp_status      = "whatsapp_status" in lb
        tiene_sub_bucket     = "sub_bucket_semanal" in lb
        tiene_fecha_venc     = "fecha_vencimiento" in lb
        tiene_acuerdo        = "acuerdo_activo_id" in lb
        tiene_subtipo        = "subtipo_rodante" in lb

        necesita_migracion = not all([
            tiene_producto, tiene_metadata, tiene_saldo_int,
            tiene_score, tiene_wp_status, tiene_sub_bucket,
            tiene_fecha_venc, tiene_acuerdo, tiene_subtipo,
        ])

        if not necesita_migracion:
            ya_migrados += 1
            print(f"  [SKIP]   {lb_id:20} — ya migrado")
            continue

        # Construir patch
        patch: dict = {}

        if not tiene_producto:
            producto = _inferir_producto(lb)
            patch["producto"] = producto
        else:
            producto = lb["producto"]

        if not tiene_subtipo:
            subtipo = _inferir_subtipo(lb)
            patch["subtipo_rodante"] = subtipo
        else:
            subtipo = lb.get("subtipo_rodante")

        if not tiene_metadata:
            if producto == "RDX":
                meta = _build_metadata_rdx(lb)
                patch["metadata_producto"] = meta
            else:
                # RODANTE: metadata vacía por ahora — requiere relleno manual
                patch["metadata_producto"] = {}
                print(f"  ⚠️  {lb_id} es RODANTE/{subtipo} — metadata_producto quedará vacía, requiere revisión")

        if not tiene_saldo_int:
            patch["saldo_intereses"] = 0.0

        if not tiene_score:
            patch["score_riesgo"] = None

        if not tiene_wp_status:
            patch["whatsapp_status"] = "pending"

        if not tiene_sub_bucket:
            patch["sub_bucket_semanal"] = None

        if not tiene_fecha_venc:
            # Inferir desde ultima cuota si existe
            cuotas = lb.get("cuotas", [])
            if cuotas:
                ultima_fecha = cuotas[-1].get("fecha")
                patch["fecha_vencimiento"] = ultima_fecha
            else:
                patch["fecha_vencimiento"] = None

        if not tiene_acuerdo:
            patch["acuerdo_activo_id"] = None

        if dry_run:
            print(f"  [UPDATE] {lb_id:20} — patch keys: {list(patch.keys())}")
            parciales += 1
        else:
            filter_q = {"loanbook_id": lb_id} if "loanbook_id" in lb else {"_id": lb["_id"]}
            await db.loanbook.update_one(filter_q, {"$set": patch})
            migrados += 1
            print(f"  [UPDATE] {lb_id:20} — ✅ {list(patch.keys())}")

    if dry_run:
        print()
        print(f"  → {parciales} se migrarían, {ya_migrados} ya migrados")
    else:
        print()
        print(f"  → {migrados} migrados, {ya_migrados} ya migrados")

        # Verificar C-08
        muestra = await db.loanbook.find_one(
            {"metadata_producto": {"$exists": True}, "saldo_intereses": {"$exists": True}},
            {"_id": 0, "loanbook_id": 1, "producto": 1, "metadata_producto": 1, "saldo_intereses": 1},
        )
        if muestra:
            print(f"  ✅ C-08: loanbook con metadata_producto y saldo_intereses: {muestra['loanbook_id']}")
        else:
            print("  ❌ C-08: ningún loanbook tiene metadata_producto y saldo_intereses — revisar")

    # ── 3. CREAR COLECCIONES E ÍNDICES ────────────────────────────────────────
    print()
    _sep()
    print("  PASO 3 — Colecciones e índices")
    _sep()

    _colecciones_indices = [
        # (nombre, campo_index, unique, sparse, descripcion)
        (
            "inventario_repuestos",
            [("referencia_sku", 1)],
            True, False,
            "C-04: SKU único",
        ),
        (
            "loanbook_acuerdos",
            [("loanbook_id", 1), ("created_at", -1)],
            False, False,
            "C-05: acuerdos por loanbook",
        ),
        (
            "loanbook_cierres",
            [("loanbook_codigo", 1)],
            True, False,
            "C-06: cierre único por loanbook",
        ),
        (
            "loanbook_modificaciones",
            [("loanbook_id", 1), ("ts", -1)],
            False, False,
            "C-07: modificaciones por loanbook+timestamp",
        ),
    ]

    for col_name, index_spec, unique, sparse, desc in _colecciones_indices:
        if dry_run:
            print(f"  [DRY-RUN] Crearía índice en {col_name}: {index_spec} (unique={unique}) — {desc}")
            continue

        # Crear colección si no existe (insertar + borrar doc centinela)
        existing_cols = await db.list_collection_names()
        if col_name not in existing_cols:
            # Motor crea la colección al crear el índice — no se necesita insertar
            pass

        try:
            await db[col_name].create_index(
                index_spec,
                unique=unique,
                sparse=sparse,
                background=True,
            )
            print(f"  ✅ {col_name}: índice {index_spec} (unique={unique}) — {desc}")
        except Exception as exc:
            print(f"  ⚠️  {col_name}: {exc}")

    if not dry_run:
        # Verificar C-04..C-07
        print()
        cols_existentes = await db.list_collection_names()
        for col in ["inventario_repuestos", "loanbook_acuerdos", "loanbook_cierres", "loanbook_modificaciones"]:
            # Motor crea la colección al crear el índice incluso sin documentos
            # Para verificar, usamos list_collection_names o count
            # Si no aparece aún en list_collection_names (colección vacía), se crea con insert+delete
            if col not in cols_existentes:
                await db[col].insert_one({"_centinela": True})
                await db[col].delete_one({"_centinela": True})
            count = await db[col].count_documents({})
            print(f"  ✅ C-0x: {col} existe ({count} documentos)")

    # ── 4. ÍNDICE NUEVO EN loanbook ───────────────────────────────────────────
    if not dry_run:
        print()
        _sep()
        print("  PASO 4 — Índices nuevos en colección loanbook")
        _sep()

        try:
            await db.loanbook.create_index([("producto", 1)], background=True)
            print("  ✅ Índice loanbook.producto")
        except Exception as exc:
            print(f"  ⚠️  {exc}")

        try:
            await db.loanbook.create_index([("subtipo_rodante", 1)], background=True, sparse=True)
            print("  ✅ Índice loanbook.subtipo_rodante (sparse)")
        except Exception as exc:
            print(f"  ⚠️  {exc}")

        try:
            await db.loanbook.create_index([("score_riesgo", 1)], background=True, sparse=True)
            print("  ✅ Índice loanbook.score_riesgo (sparse)")
        except Exception as exc:
            print(f"  ⚠️  {exc}")

    # ── 5. VERIFICACIÓN FINAL ─────────────────────────────────────────────────
    if not dry_run:
        print()
        _sep()
        print("  VERIFICACIÓN FINAL")
        _sep()

        total_lb = await db.loanbook.count_documents({})
        con_producto = await db.loanbook.count_documents({"producto": {"$exists": True}})
        con_metadata = await db.loanbook.count_documents({"metadata_producto": {"$exists": True}})
        con_saldo_int = await db.loanbook.count_documents({"saldo_intereses": {"$exists": True}})
        rdx_count = await db.loanbook.count_documents({"producto": "RDX"})
        rodante_count = await db.loanbook.count_documents({"producto": "RODANTE"})

        print(f"  Total loanbooks:       {total_lb}")
        print(f"  Con producto:          {con_producto}/{total_lb}")
        print(f"  Con metadata_producto: {con_metadata}/{total_lb}")
        print(f"  Con saldo_intereses:   {con_saldo_int}/{total_lb}")
        print(f"  RDX:                   {rdx_count}")
        print(f"  RODANTE:               {rodante_count}")

        if con_producto == total_lb and con_metadata == total_lb:
            print()
            print("  ✅ C-08: schema expandido en TODOS los loanbooks")
            print("  ✅ C-09: migración completa")
        else:
            faltantes = total_lb - con_producto
            print()
            print(f"  ⚠️  {faltantes} loanbooks aún sin campo `producto` — volver a ejecutar")

    print()
    _sep("═")
    if dry_run:
        print("  DRY-RUN completado. Ejecuta sin --dry-run para aplicar.")
    else:
        print("  MIGRACIÓN B1 completada.")
    _sep("═")
    print()

    client.close()


# ─────────────────────── Entrypoint ───────────────────────────────────────────

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    asyncio.run(migrar(dry_run=dry_run))
