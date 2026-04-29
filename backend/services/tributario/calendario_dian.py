"""
services/tributario/calendario_dian.py — Calendario DIAN 2026 hardcoded.

RODDOS S.A.S.:
  - Régimen ordinario
  - Agente retenedor de fuente
  - Agente retenedor ReICA Bogotá
  - IVA cuatrimestral (regla CLAUDE.md: ene-abr / may-ago / sep-dic)
  - ReteFuente mensual
  - ReICA Bogotá bimestral
  - Renta anual 2025 (declaración 2026)

Fuente: calendario tributario DIAN 2026 oficial. Las fechas dependen del
último dígito del NIT del contribuyente (env var RODDOS_NIT_ULT_DIGITO).

Por defecto asume dígito 4. Configurar en Render con el real.

NOTA: ReICA Bogotá vence en SHD (Secretaría Distrital de Hacienda) — fechas
también según último dígito NIT.
"""
from __future__ import annotations
import os
from datetime import date
from typing import Literal, TypedDict

# Tipos
TipoObligacion = Literal[
    "iva_cuatrimestral",
    "retefuente_mensual",
    "reteiva_mensual",
    "reica_bogota_bimestral",
    "renta_anual",
    "informacion_exogena",
]

PeriodoStr = str  # ej "2026-C1" "2026-04" "2026-B1"


class Obligacion(TypedDict):
    tipo: TipoObligacion
    nombre: str
    periodo: PeriodoStr
    periodo_inicio: str  # ISO date
    periodo_fin: str  # ISO date
    fecha_vencimiento: str  # ISO date
    formulario_dian: str
    autoridad: str  # "DIAN" o "SHD" (Bogotá)


def _ult_digito_nit() -> int:
    """Lee dígito del NIT desde env. Default 4."""
    raw = os.getenv("RODDOS_NIT_ULT_DIGITO", "4")
    try:
        d = int(raw)
        if 0 <= d <= 9:
            return d
    except Exception:
        pass
    return 4


# ─────────────────────────────────────────────────────────────────────────────
# IVA CUATRIMESTRAL 2026 (DIAN - Decreto 2229/2023)
# Cuatrimestres: ene-abr / may-ago / sep-dic
# ─────────────────────────────────────────────────────────────────────────────

_IVA_CUATRIMESTRE_VENCIMIENTOS_2026: dict[int, list[str]] = {
    # último_dígito: [C1 vence, C2 vence, C3 vence (en 2027)]
    1: ["2026-05-12", "2026-09-08", "2027-01-12"],
    2: ["2026-05-13", "2026-09-09", "2027-01-13"],
    3: ["2026-05-14", "2026-09-10", "2027-01-14"],
    4: ["2026-05-15", "2026-09-11", "2027-01-15"],
    5: ["2026-05-19", "2026-09-12", "2027-01-19"],
    6: ["2026-05-20", "2026-09-15", "2027-01-20"],
    7: ["2026-05-21", "2026-09-16", "2027-01-21"],
    8: ["2026-05-22", "2026-09-17", "2027-01-22"],
    9: ["2026-05-26", "2026-09-18", "2027-01-26"],
    0: ["2026-05-27", "2026-09-19", "2027-01-27"],
}

_IVA_CUATRIMESTRES_RANGO = [
    ("2026-C1", "2026-01-01", "2026-04-30"),
    ("2026-C2", "2026-05-01", "2026-08-31"),
    ("2026-C3", "2026-09-01", "2026-12-31"),
]


def obligaciones_iva_2026() -> list[Obligacion]:
    digito = _ult_digito_nit()
    fechas = _IVA_CUATRIMESTRE_VENCIMIENTOS_2026[digito]
    return [
        {
            "tipo": "iva_cuatrimestral",
            "nombre": f"IVA {periodo}",
            "periodo": periodo,
            "periodo_inicio": ini,
            "periodo_fin": fin,
            "fecha_vencimiento": venc,
            "formulario_dian": "300",
            "autoridad": "DIAN",
        }
        for (periodo, ini, fin), venc in zip(_IVA_CUATRIMESTRES_RANGO, fechas)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# RETEFUENTE + RETEIVA MENSUAL 2026
# ─────────────────────────────────────────────────────────────────────────────

# Vencimientos mensuales DIAN 2026 (formulario 350)
# Fila por mes que se declara → fecha límite por dígito NIT
_RETEFUENTE_VENC_2026: dict[str, dict[int, str]] = {
    "2026-01": {1: "2026-02-09", 2: "2026-02-10", 3: "2026-02-11", 4: "2026-02-12",
                5: "2026-02-13", 6: "2026-02-16", 7: "2026-02-17", 8: "2026-02-18",
                9: "2026-02-19", 0: "2026-02-20"},
    "2026-02": {1: "2026-03-09", 2: "2026-03-10", 3: "2026-03-11", 4: "2026-03-12",
                5: "2026-03-13", 6: "2026-03-16", 7: "2026-03-17", 8: "2026-03-18",
                9: "2026-03-19", 0: "2026-03-20"},
    "2026-03": {1: "2026-04-08", 2: "2026-04-09", 3: "2026-04-10", 4: "2026-04-13",
                5: "2026-04-14", 6: "2026-04-15", 7: "2026-04-16", 8: "2026-04-17",
                9: "2026-04-20", 0: "2026-04-21"},
    "2026-04": {1: "2026-05-12", 2: "2026-05-13", 3: "2026-05-14", 4: "2026-05-15",
                5: "2026-05-19", 6: "2026-05-20", 7: "2026-05-21", 8: "2026-05-22",
                9: "2026-05-26", 0: "2026-05-27"},
    "2026-05": {1: "2026-06-09", 2: "2026-06-10", 3: "2026-06-11", 4: "2026-06-12",
                5: "2026-06-15", 6: "2026-06-16", 7: "2026-06-17", 8: "2026-06-18",
                9: "2026-06-19", 0: "2026-06-22"},
    "2026-06": {1: "2026-07-08", 2: "2026-07-09", 3: "2026-07-10", 4: "2026-07-13",
                5: "2026-07-14", 6: "2026-07-15", 7: "2026-07-16", 8: "2026-07-17",
                9: "2026-07-20", 0: "2026-07-21"},
    "2026-07": {1: "2026-08-11", 2: "2026-08-12", 3: "2026-08-13", 4: "2026-08-14",
                5: "2026-08-18", 6: "2026-08-19", 7: "2026-08-20", 8: "2026-08-21",
                9: "2026-08-24", 0: "2026-08-25"},
    "2026-08": {1: "2026-09-08", 2: "2026-09-09", 3: "2026-09-10", 4: "2026-09-11",
                5: "2026-09-14", 6: "2026-09-15", 7: "2026-09-16", 8: "2026-09-17",
                9: "2026-09-18", 0: "2026-09-21"},
    "2026-09": {1: "2026-10-07", 2: "2026-10-08", 3: "2026-10-09", 4: "2026-10-12",
                5: "2026-10-13", 6: "2026-10-14", 7: "2026-10-15", 8: "2026-10-16",
                9: "2026-10-19", 0: "2026-10-20"},
    "2026-10": {1: "2026-11-10", 2: "2026-11-11", 3: "2026-11-12", 4: "2026-11-13",
                5: "2026-11-16", 6: "2026-11-17", 7: "2026-11-18", 8: "2026-11-19",
                9: "2026-11-20", 0: "2026-11-23"},
    "2026-11": {1: "2026-12-09", 2: "2026-12-10", 3: "2026-12-11", 4: "2026-12-14",
                5: "2026-12-15", 6: "2026-12-16", 7: "2026-12-17", 8: "2026-12-18",
                9: "2026-12-21", 0: "2026-12-22"},
    "2026-12": {1: "2027-01-12", 2: "2027-01-13", 3: "2027-01-14", 4: "2027-01-15",
                5: "2027-01-19", 6: "2027-01-20", 7: "2027-01-21", 8: "2027-01-22",
                9: "2027-01-26", 0: "2027-01-27"},
}


def obligaciones_retefuente_2026() -> list[Obligacion]:
    digito = _ult_digito_nit()
    out = []
    for periodo, mapa in _RETEFUENTE_VENC_2026.items():
        anio, mes = periodo.split("-")
        anio_i, mes_i = int(anio), int(mes)
        ini = date(anio_i, mes_i, 1).isoformat()
        if mes_i == 12:
            fin = date(anio_i, 12, 31).isoformat()
        else:
            fin = (date(anio_i, mes_i + 1, 1) - __import__("datetime").timedelta(days=1)).isoformat()
        out.append({
            "tipo": "retefuente_mensual",
            "nombre": f"ReteFuente + ReteIVA {periodo}",
            "periodo": periodo,
            "periodo_inicio": ini,
            "periodo_fin": fin,
            "fecha_vencimiento": mapa[digito],
            "formulario_dian": "350",
            "autoridad": "DIAN",
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# ReICA BOGOTÁ BIMESTRAL 2026 (Secretaría Distrital de Hacienda)
# Bimestres: ene-feb / mar-abr / may-jun / jul-ago / sep-oct / nov-dic
# Vencimiento: aproximadamente el día 19 del mes siguiente al cierre del bimestre,
# ajustado por dígito de NIT.
# ─────────────────────────────────────────────────────────────────────────────

_REICA_BOG_VENC_2026: dict[str, dict[int, str]] = {
    "2026-B1": {1: "2026-03-13", 2: "2026-03-13", 3: "2026-03-16", 4: "2026-03-16",
                5: "2026-03-17", 6: "2026-03-17", 7: "2026-03-18", 8: "2026-03-18",
                9: "2026-03-19", 0: "2026-03-19"},
    "2026-B2": {1: "2026-05-15", 2: "2026-05-15", 3: "2026-05-18", 4: "2026-05-18",
                5: "2026-05-19", 6: "2026-05-19", 7: "2026-05-20", 8: "2026-05-20",
                9: "2026-05-21", 0: "2026-05-21"},
    "2026-B3": {1: "2026-07-14", 2: "2026-07-14", 3: "2026-07-15", 4: "2026-07-15",
                5: "2026-07-16", 6: "2026-07-16", 7: "2026-07-17", 8: "2026-07-17",
                9: "2026-07-20", 0: "2026-07-20"},
    "2026-B4": {1: "2026-09-15", 2: "2026-09-15", 3: "2026-09-16", 4: "2026-09-16",
                5: "2026-09-17", 6: "2026-09-17", 7: "2026-09-18", 8: "2026-09-18",
                9: "2026-09-21", 0: "2026-09-21"},
    "2026-B5": {1: "2026-11-13", 2: "2026-11-13", 3: "2026-11-16", 4: "2026-11-16",
                5: "2026-11-17", 6: "2026-11-17", 7: "2026-11-18", 8: "2026-11-18",
                9: "2026-11-19", 0: "2026-11-19"},
    "2026-B6": {1: "2027-01-15", 2: "2027-01-15", 3: "2027-01-18", 4: "2027-01-18",
                5: "2027-01-19", 6: "2027-01-19", 7: "2027-01-20", 8: "2027-01-20",
                9: "2027-01-21", 0: "2027-01-21"},
}

_REICA_BOG_RANGOS = [
    ("2026-B1", "2026-01-01", "2026-02-28"),
    ("2026-B2", "2026-03-01", "2026-04-30"),
    ("2026-B3", "2026-05-01", "2026-06-30"),
    ("2026-B4", "2026-07-01", "2026-08-31"),
    ("2026-B5", "2026-09-01", "2026-10-31"),
    ("2026-B6", "2026-11-01", "2026-12-31"),
]


def obligaciones_reica_bogota_2026() -> list[Obligacion]:
    digito = _ult_digito_nit()
    out = []
    for (periodo, ini, fin) in _REICA_BOG_RANGOS:
        out.append({
            "tipo": "reica_bogota_bimestral",
            "nombre": f"ReICA Bogotá {periodo}",
            "periodo": periodo,
            "periodo_inicio": ini,
            "periodo_fin": fin,
            "fecha_vencimiento": _REICA_BOG_VENC_2026[periodo][digito],
            "formulario_dian": "ICA-B",
            "autoridad": "SHD-Bogotá",
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# RENTA ANUAL 2025 (declaración en 2026, persona jurídica grande contribuyente
# o sociedad ordinaria). Vencimiento en abril-mayo según último dígito NIT.
# ─────────────────────────────────────────────────────────────────────────────

_RENTA_2025_VENC: dict[int, str] = {
    1: "2026-04-09", 2: "2026-04-13", 3: "2026-04-14", 4: "2026-04-15", 5: "2026-04-16",
    6: "2026-04-17", 7: "2026-04-20", 8: "2026-04-21", 9: "2026-04-22", 0: "2026-04-23",
}


def obligacion_renta_2025() -> Obligacion:
    digito = _ult_digito_nit()
    return {
        "tipo": "renta_anual",
        "nombre": "Declaración Renta y Complementarios 2025",
        "periodo": "2025",
        "periodo_inicio": "2025-01-01",
        "periodo_fin": "2025-12-31",
        "fecha_vencimiento": _RENTA_2025_VENC[digito],
        "formulario_dian": "110",
        "autoridad": "DIAN",
    }


# ─────────────────────────────────────────────────────────────────────────────
# API PÚBLICA
# ─────────────────────────────────────────────────────────────────────────────

def todas_obligaciones_2026() -> list[Obligacion]:
    return [
        *obligaciones_iva_2026(),
        *obligaciones_retefuente_2026(),
        *obligaciones_reica_bogota_2026(),
        obligacion_renta_2025(),
    ]


def obligaciones_proximas(
    desde: date | None = None,
    dias_adelante: int = 30,
) -> list[Obligacion]:
    """Devuelve obligaciones cuyo vencimiento está dentro del rango [desde, desde+días]."""
    from core.datetime_utils import today_bogota
    desde = desde or today_bogota()
    hasta = date.fromordinal(desde.toordinal() + dias_adelante)
    out = []
    for o in todas_obligaciones_2026():
        venc = date.fromisoformat(o["fecha_vencimiento"])
        if desde <= venc <= hasta:
            out.append({**o, "dias_restantes": (venc - desde).days})
    out.sort(key=lambda x: x["fecha_vencimiento"])
    return out
