"""
loanbook_matcher.py — Motor de matching nombre → loanbook legacy

Integra pagos de créditos legacy que llegan al backlog bancario
con los registros en loanbook_legacy, usando fuzzy matching.

Alcance acotado:
  - SOLO lee loanbook_legacy (estado="activo")
  - Los loanbooks V2 activos tienen su propio flujo:
    evento cuota.pagada → DataKeeper → contabilidad_handlers.py
  - Este módulo NO toca loanbooks V2

Umbral: 82 (token_set_ratio de rapidfuzz).
  85 tiene demasiados falsos negativos para nombres colombianos abreviados.
  82 mantiene precisión aceptable con los datos de Roddos.
"""
import re
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase

try:
    from rapidfuzz import fuzz
    _RAPIDFUZZ_OK = True
except ImportError:
    _RAPIDFUZZ_OK = False

UMBRAL_SIMILITUD = 82

# Patrones para extraer el nombre del pagador desde la descripción bancaria
_NAME_PATTERNS = [
    re.compile(r"TRANSFIYA DE\s+(.+?)(?:\s+CC\s|\s*$)", re.IGNORECASE),
    re.compile(r"RECIBI POR BRE-B DE:?\s*(.+?)(?:\s+\d|\s*$)", re.IGNORECASE),
    re.compile(r"^DE\s+(.+?)(?:\s+CC\s|\s*$)", re.IGNORECASE),
    re.compile(r"CONSIG\s+(.+?)(?:\s+\d|\s*$)", re.IGNORECASE),
    re.compile(r"TRANSFERENCIA DE\s+(.+?)(?:\s+CC\s|\s*$)", re.IGNORECASE),
    re.compile(r"PAGO DE\s+(.+?)(?:\s+CC\s|\s*$)", re.IGNORECASE),
]


def extract_payer_name(descripcion: str) -> Optional[str]:
    """
    Extrae el nombre del pagador de una descripción de extracto bancario.
    Retorna el nombre en mayúsculas o None si no hay patrón reconocible.
    """
    if not descripcion:
        return None
    for pat in _NAME_PATTERNS:
        m = pat.search(descripcion)
        if m:
            nombre = m.group(1).strip().upper()
            if len(nombre) >= 3:
                return nombre
    return None


async def match_payer_to_loanbook(
    nombre: str,
    db: AsyncIOMotorDatabase,
) -> Optional[dict]:
    """
    Fuzzy-match un nombre de pagador contra loanbook_legacy (estado='activo').

    Args:
        nombre: Nombre del pagador extraído de la descripción bancaria (upper).
        db: Motor async database (sismo-v2).

    Returns:
        {
            "loanbook_id": str,      # codigo_sismo del crédito
            "nombre_cliente": str,
            "similarity_score": int, # 0-100
            "alegra_contact_id": str | None,
            "saldo_actual": float,
        }
        o None si ningún candidato supera el umbral.

    Raises:
        RuntimeError: si rapidfuzz no está instalado.
    """
    if not _RAPIDFUZZ_OK:
        raise RuntimeError(
            "rapidfuzz no está instalado. "
            "Agréguelo a requirements.txt: rapidfuzz>=3.0.0"
        )

    if not nombre or len(nombre) < 3:
        return None

    # Cargar créditos activos (solo campos necesarios para el match)
    docs = await db["loanbook_legacy"].find(
        {"estado": "activo"},
        {
            "codigo_sismo":      1,
            "nombre_completo":   1,
            "alegra_contact_id": 1,
            "saldo_actual":      1,
        },
    ).to_list(length=1000)

    if not docs:
        return None

    mejor_score = 0
    mejor_doc: Optional[dict] = None

    for doc in docs:
        nombre_doc = (doc.get("nombre_completo") or "").upper()
        if not nombre_doc:
            continue
        score = fuzz.token_set_ratio(nombre, nombre_doc)
        if score > mejor_score:
            mejor_score = score
            mejor_doc = doc

    if mejor_score < UMBRAL_SIMILITUD or mejor_doc is None:
        return None

    return {
        "loanbook_id":       mejor_doc.get("codigo_sismo", ""),
        "nombre_cliente":    mejor_doc.get("nombre_completo", ""),
        "similarity_score":  mejor_score,
        "alegra_contact_id": mejor_doc.get("alegra_contact_id"),
        "saldo_actual":      float(mejor_doc.get("saldo_actual", 0) or 0),
    }


async def match_from_description(
    descripcion: str,
    db: AsyncIOMotorDatabase,
) -> Optional[dict]:
    """
    Extrae el nombre del pagador de la descripción y luego hace el match.
    Convenience wrapper para usar directamente con backlog_movimientos.descripcion.

    Returns: mismo dict que match_payer_to_loanbook, o None.
    """
    nombre = extract_payer_name(descripcion)
    if not nombre:
        return None
    return await match_payer_to_loanbook(nombre, db)
