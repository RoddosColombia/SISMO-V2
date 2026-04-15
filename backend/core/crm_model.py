"""
CRM Model — Pure domain logic for client management.

NO MongoDB, NO FastAPI. Pure functions and data structures.
Clients are created automatically when a loanbook is created,
and managed via CRUD endpoints.
"""
from __future__ import annotations

from datetime import date

# Valid CRM client states
ESTADOS_CRM = ["activo", "inactivo", "mora", "saldado"]


def validar_telefono(telefono: str) -> bool:
    """
    Validate phone number format for Mercately (WhatsApp).
    Must be 57 + 10 digits = 12 digits total.
    """
    if not telefono or not telefono.isdigit():
        return False
    return telefono.startswith("57") and len(telefono) == 12


def crear_cliente_doc(
    cedula: str,
    nombre: str,
    telefono: str,
    email: str = "",
    direccion: str = "",
) -> dict:
    """
    Create a new CRM client document.

    Returns dict ready for MongoDB insert.
    """
    today = date.today().isoformat()
    return {
        "cedula": cedula,
        "nombre": nombre,
        "telefono": telefono,
        "email": email,
        "direccion": direccion,
        "fecha_registro": today,
        "loanbooks": [],
        "score": None,  # Set by Phase 8 RADAR
        "estado": "activo",
        "notas": "",
        "created_at": today,
        "updated_at": today,
    }
