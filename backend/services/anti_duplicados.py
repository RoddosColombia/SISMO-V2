"""
Anti-duplicados 3 capas para conciliación bancaria.

Capa 1: hash MD5 del archivo completo → conciliacion_extractos_procesados
Capa 2: hash MD5 por movimiento (fecha|descripcion|monto) → conciliacion_movimientos_procesados
Capa 3: GET Alegra post-POST (handled by request_with_verify in AlegraClient)
"""
import hashlib
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase


def hash_extracto(file_bytes: bytes) -> str:
    """Capa 1: MD5 hash of entire file content."""
    return hashlib.md5(file_bytes).hexdigest()


def hash_movimiento(fecha: str, descripcion: str, monto: float) -> str:
    """Capa 2: MD5 hash of movement identity (fecha|descripcion|monto)."""
    key = f"{fecha}|{descripcion}|{monto:.2f}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()


async def check_extracto_duplicado(db: AsyncIOMotorDatabase, file_hash: str) -> bool:
    """Returns True if this extract was already processed."""
    doc = await db.conciliacion_extractos_procesados.find_one({"hash": file_hash})
    return doc is not None


async def check_movimiento_duplicado(db: AsyncIOMotorDatabase, mov_hash: str) -> bool:
    """Returns True if this movement was already processed."""
    doc = await db.conciliacion_movimientos_procesados.find_one({"hash": mov_hash})
    return doc is not None


async def registrar_extracto_procesado(
    db: AsyncIOMotorDatabase,
    file_hash: str,
    banco: str,
    movimientos: int,
) -> None:
    """Register extract as processed (Capa 1). MongoDB operational write — allowed."""
    await db.conciliacion_extractos_procesados.insert_one({
        "hash": file_hash,
        "banco": banco,
        "movimientos": movimientos,
        "fecha_procesado": datetime.now(timezone.utc).isoformat(),
    })


async def registrar_movimiento_procesado(
    db: AsyncIOMotorDatabase,
    mov_hash: str,
    alegra_id: str | None = None,
) -> None:
    """Register movement as processed (Capa 2). MongoDB operational write — allowed."""
    await db.conciliacion_movimientos_procesados.insert_one({
        "hash": mov_hash,
        "alegra_id": alegra_id,
        "fecha_procesado": datetime.now(timezone.utc).isoformat(),
    })
