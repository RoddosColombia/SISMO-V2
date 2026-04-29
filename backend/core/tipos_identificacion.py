"""
core/tipos_identificacion.py — Constantes canónicas de tipos de identificación
de clientes RODDOS.

PRINCIPAL: PPT (Permiso de Protección Temporal) — la mayoría de clientes
RODDOS son población migrante venezolana en Colombia.

Uso:
    from core.tipos_identificacion import TIPOS_VALIDOS, TIPO_DEFAULT

    cliente = {
        "tipo_identificacion": "PPT",
        "numero_identificacion": "12345678",
        ...
    }
"""

# Tipos válidos en orden de uso típico en RODDOS
TIPOS_VALIDOS: dict[str, str] = {
    "PPT":  "Permiso de Protección Temporal",        # ← principal RODDOS
    "CC":   "Cédula de Ciudadanía",
    "CE":   "Cédula de Extranjería",
    "PEP":  "Permiso Especial de Permanencia",       # legacy (anterior a PPT)
    "PP":   "Pasaporte",
    "TI":   "Tarjeta de Identidad",
    "NIT":  "Número de Identificación Tributaria",   # empresas
}

# Default cuando no se especifica
TIPO_DEFAULT = "CC"


def normalizar_tipo(tipo: str | None) -> str:
    """Normaliza un tipo de identificación. Si no es válido, devuelve TIPO_DEFAULT."""
    if not tipo:
        return TIPO_DEFAULT
    t = tipo.strip().upper()
    # Aliases comunes
    aliases = {
        "CEDULA":            "CC",
        "CÉDULA":            "CC",
        "CITIZENSHIP":       "CC",
        "CIUDADANIA":        "CC",
        "EXTRANJERIA":       "CE",
        "PASAPORTE":         "PP",
        "PASSPORT":          "PP",
        "PROTECCIÓN":        "PPT",
        "PROTECCION":        "PPT",
        "TEMPORAL":          "PPT",
        "PERMISO":           "PPT",
        "PERMANENCIA":       "PEP",
        "TARJETA":           "TI",
        "MENOR":             "TI",
        "EMPRESA":           "NIT",
        "EMPRESARIAL":       "NIT",
    }
    if t in aliases:
        return aliases[t]
    return t if t in TIPOS_VALIDOS else TIPO_DEFAULT


def descripcion(tipo: str) -> str:
    """Descripción legible del tipo."""
    return TIPOS_VALIDOS.get(normalizar_tipo(tipo), "Documento desconocido")
