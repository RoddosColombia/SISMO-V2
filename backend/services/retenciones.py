"""
Retenciones Colombia 2026 — pure function, no I/O.

Decisions applied (CONTEXT.md D-08 to D-12):
- D-09: Auteco NIT 860024781 = autoretenedor, retefuente always 0
- D-10: ReteICA Bogota 0.414% always applied
- D-11: Compras ReteFuente 2.5% only if monto > $1,344,573
- D-12: Handlers import this module — never calculate inline
"""

AUTORETENEDORES: frozenset[str] = frozenset({"860024781"})

TASAS_RETEFUENTE: dict[str, float] = {
    "arriendo": 0.035,
    "servicios": 0.04,
    "honorarios_pn": 0.10,
    "honorarios_pj": 0.11,
    "compras": 0.025,
}

RETEICA_BOGOTA: float = 0.00414
COMPRAS_BASE_MINIMA: float = 1_344_573.0


def calcular_retenciones(
    tipo: str,
    monto: float,
    nit: str | None = None,
) -> dict:
    """
    Calculate Colombian tax retentions for a given operation.

    Args:
        tipo: Operation type (arriendo, servicios, honorarios_pn, honorarios_pj, compras)
        monto: Gross amount in COP
        nit: Supplier NIT (if known). Autoretenedores get retefuente=0.

    Returns:
        dict with retefuente_tasa, retefuente_monto, reteica_tasa, reteica_monto, neto_a_pagar
    """
    es_autoretenedor = nit in AUTORETENEDORES if nit else False

    tasa_retefuente = TASAS_RETEFUENTE.get(tipo, 0.0)

    if es_autoretenedor:
        retefuente_monto = 0.0
        tasa_retefuente = 0.0
    elif tipo == "compras" and monto <= COMPRAS_BASE_MINIMA:
        retefuente_monto = 0.0
        tasa_retefuente = 0.0
    else:
        retefuente_monto = round(monto * tasa_retefuente, 2)

    reteica_monto = round(monto * RETEICA_BOGOTA, 2)
    neto_a_pagar = round(monto - retefuente_monto - reteica_monto, 2)

    return {
        "retefuente_tasa": tasa_retefuente,
        "retefuente_monto": retefuente_monto,
        "reteica_tasa": RETEICA_BOGOTA,
        "reteica_monto": reteica_monto,
        "neto_a_pagar": neto_a_pagar,
    }
