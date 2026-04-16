"""
Migrate 26 real RODDOS loanbooks into sismo-v2.

- Seeds catalogo_planes with P39S, P52S, P78S, P15S
- Inserts 26 loanbook documents (23 motos + 2 comparendos + 1 licencia)
- Upserts CRM contact per unique cedula with array of loanbook_ids

Anti-duplicados:
  - Loanbook: skip if one already exists with same VIN OR (cedula + plan_codigo + fecha_entrega)
  - CRM: upsert by cedula

Run:
  $env:MONGO_URL = "mongodb+srv://..."
  $env:DB_NAME = "sismo-v2"
  python -m scripts.migrate_loanbooks_v2
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date, datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorClient

# ═══════════════════════════════════════════
# catalogo_planes seed
# ═══════════════════════════════════════════

CATALOGO_PLANES = [
    {
        "codigo": "P39S",
        "nombre": "Plan 39 Semanas",
        "cuotas_base": 39,
        "anzi_pct": 0.02,
        "modelos": ["RAIDER 125", "SPORT 100", "APACHE 160"],
        "cuotas_modelo": {
            "RAIDER 125": 210_000,
            "SPORT 100": 160_000,
            "APACHE 160": 250_000,
        },
    },
    {
        "codigo": "P52S",
        "nombre": "Plan 52 Semanas",
        "cuotas_base": 52,
        "anzi_pct": 0.02,
        "modelos": ["RAIDER 125", "SPORT 100", "APACHE 160"],
        "cuotas_modelo": {
            "RAIDER 125": 179_900,
            "SPORT 100": 135_000,
            "APACHE 160": 220_000,
        },
    },
    {
        "codigo": "P78S",
        "nombre": "Plan 78 Semanas",
        "cuotas_base": 78,
        "anzi_pct": 0.02,
        "modelos": ["RAIDER 125", "SPORT 100", "APACHE 160"],
        "cuotas_modelo": {
            "RAIDER 125": 149_900,
            "SPORT 100": 130_000,
            "APACHE 160": 180_000,
        },
    },
    {
        "codigo": "P15S",
        "nombre": "Plan 15 Semanas",
        "cuotas_base": 15,
        "anzi_pct": 0.0,
        "modelos": ["COMPARENDO", "LICENCIA"],
        "cuotas_modelo": {},   # servicios no tienen precio por modelo
    },
]

# ═══════════════════════════════════════════
# Modalidad config (mirror of core.loanbook_model.MODALIDADES)
# ═══════════════════════════════════════════

MODALIDAD_DIAS = {"semanal": 7, "quincenal": 14, "mensual": 28}

# ═══════════════════════════════════════════
# 26 loanbook records (fuente: Excel RODDOS, correcciones verificadas)
# ═══════════════════════════════════════════

LOANBOOKS: list[dict] = [
    # ------ MOTOS -----------------------------------------------------------
    {
        "n": "0001", "nombre": "Chenier Quintero", "cedula": "1283367",
        "tel": "573015434981", "modelo": "RAIDER 125",
        "vin": "9FL25AF31VDB95057", "motor": "BF3AT13C2338",
        "plan": "P52S", "modalidad": "semanal", "cuota": 179_900,
        "inicial": 1_460_000, "factura": "2026-03-02", "entrega": "2026-03-05",
        "cuota1": "2026-03-11", "pagadas": 6, "vencidas": 0, "total": 52,
        "valor": 9_354_800, "saldo": 8_275_400, "estado": "activo",
        "alegra_factura": "FE444",
    },
    {
        "n": "0002", "nombre": "Jose Altamiranda", "cedula": "1063146896",
        "tel": "573004613796", "modelo": "SPORT 100",
        "vin": "9FL25AF22VDB95413", "motor": "RF5AT18A5448",
        "plan": "P78S", "modalidad": "semanal", "cuota": 130_000,
        "inicial": 1_160_000, "factura": "2026-03-02", "entrega": "2026-03-05",
        "cuota1": "2026-03-05", "pagadas": 6, "vencidas": 0, "total": 78,
        "valor": 10_140_000, "saldo": 9_360_000, "estado": "activo",
        "alegra_factura": "FE448",
    },
    {
        "n": "0003", "nombre": "Ernesto Antonio Jaime", "cedula": "6226605",
        "tel": "573005056127", "modelo": "RAIDER 125",
        "vin": "9FL25AF31VDB95048", "motor": "BF3AT15C2365",
        "plan": "P78S", "modalidad": "semanal", "cuota": 149_900,
        "inicial": 1_460_000, "factura": "2026-03-02", "entrega": "2026-03-05",
        "cuota1": "2026-03-11", "pagadas": 6, "vencidas": 0, "total": 78,
        "valor": 11_692_200, "saldo": 10_792_800, "estado": "activo",
        "alegra_factura": "FE445",
    },
    {
        "n": "0004", "nombre": "Ronaldo Carcamo", "cedula": "1126257783",
        "tel": "573026699546", "modelo": "RAIDER 125",
        "vin": "9FL25AF31VDB95055", "motor": "BF3AT18C2341",
        "plan": "P78S", "modalidad": "semanal", "cuota": 149_900,
        "inicial": 1_460_000, "factura": "2026-03-02", "entrega": "2026-03-05",
        "cuota1": "2026-03-11", "pagadas": 5, "vencidas": 1, "total": 78,
        "valor": 11_692_200, "saldo": 10_942_700, "estado": "mora",
        "alegra_factura": "FE446",
    },
    {
        "n": "0005", "nombre": "Beatriz A Garcia", "cedula": "5203668",
        "tel": "573204276869", "modelo": "RAIDER 125",
        "vin": "9FL25AF31VDB95046", "motor": "BF3AT13C2568",
        "plan": "P78S", "modalidad": "semanal", "cuota": 149_900,
        "inicial": 1_300_000, "factura": "2026-03-02", "entrega": "2026-03-05",
        "cuota1": "2026-03-11", "pagadas": 6, "vencidas": 0, "total": 78,
        "valor": 11_692_200, "saldo": 10_792_800, "estado": "activo",
        "alegra_factura": "FE447",
    },
    {
        "n": "0006", "nombre": "Alexis Crespo", "cedula": "598091",
        "tel": "573118580746", "modelo": "RAIDER 125",
        "vin": "9FL25AF31VDB95058", "motor": "BF3AT18C2356",
        "plan": "P52S", "modalidad": "semanal", "cuota": 179_900,
        "inicial": 1_460_000, "factura": "2026-03-02", "entrega": "2026-03-05",
        "cuota1": "2026-03-11", "pagadas": 6, "vencidas": 0, "total": 52,
        "valor": 9_354_800, "saldo": 8_275_400, "estado": "activo",
        "alegra_factura": "FE449",
    },
    {
        "n": "0007", "nombre": "Moises Ascanio", "cedula": "199053959",
        "tel": "573009550645", "modelo": "SPORT 100",
        "vin": "9FL25AF22VDB95414", "motor": "RF5AT1XA5494",
        "plan": "P39S", "modalidad": "quincenal", "cuota": 350_000,
        "inicial": 1_160_000, "factura": "2026-03-02", "entrega": "2026-03-05",
        "cuota1": "2026-03-24", "pagadas": 2, "vencidas": 0, "total": 21,
        "valor": 7_350_000, "saldo": 6_650_000, "estado": "activo",
        "alegra_factura": "FE450",
    },
    {
        "n": "0008", "nombre": "Kreyser Cabrices", "cedula": "7711632",
        "tel": "573152371345", "modelo": "RAIDER 125",
        "vin": "9FL25AF31VDB95043", "motor": "BF3AT15C2580",
        "plan": "P39S", "modalidad": "quincenal", "cuota": 420_000,
        "inicial": 1_460_000, "factura": "2026-03-02", "entrega": "2026-03-05",
        "cuota1": "2026-03-24", "pagadas": 2, "vencidas": 0, "total": 21,
        "valor": 8_820_000, "saldo": 7_980_000, "estado": "activo",
        "alegra_factura": "FE451",
    },
    {
        "n": "0009", "nombre": "Dora Maria Ospina", "cedula": "20677811",
        "tel": "573005472753", "tel2": "573028476052", "modelo": "SPORT 100",
        "vin": "9FL25AF22VDB95265", "motor": "RF5AT15A5593",
        "plan": "P78S", "modalidad": "semanal", "cuota": 130_000,
        "inicial": 1_160_000, "factura": "2026-03-06", "entrega": "2026-03-10",
        "cuota1": "2026-03-18", "pagadas": 4, "vencidas": 2, "total": 78,
        "valor": 10_140_000, "saldo": 9_620_000, "estado": "mora",
        "alegra_factura": "FE452",
    },
    {
        "n": "0010", "nombre": "Sindy Bibiana Beltran", "cedula": "1012415625",
        "tel": "573046344920", "modelo": "RAIDER 125",
        "vin": "9FL25AF31VDB95987", "motor": "BF3AV14L1853",
        "plan": "P52S", "modalidad": "semanal", "cuota": 179_900,
        "inicial": 1_460_000, "factura": "2026-03-13", "entrega": "2026-03-19",
        "cuota1": "2026-03-25", "pagadas": 4, "vencidas": 0, "total": 52,
        "valor": 9_354_800, "saldo": 8_635_200, "estado": "activo",
        "alegra_factura": "FE453",
    },
    {
        "n": "0011", "nombre": "Kedwyng Valladares", "cedula": "7136824",
        "tel": "573207643317", "modelo": "RAIDER 125",
        "vin": "9FL25AF31VDB95190", "motor": "BF3AV10L1705",
        "plan": "P39S", "modalidad": "semanal", "cuota": 210_000,
        "inicial": 1_460_000, "factura": "2026-03-19", "entrega": "2026-03-25",
        "cuota1": "2026-04-01", "pagadas": 3, "vencidas": 0, "total": 39,
        "valor": 8_190_000, "saldo": 7_560_000, "estado": "activo",
        "alegra_factura": "FE456",
    },
    {
        "n": "0012", "nombre": "Manuel Andres Ovalles", "cedula": "5898416",
        "tel": "573209003748", "modelo": "RAIDER 125",
        "vin": "9FL25AF31VDB95997", "motor": "BF3AV19L1950",
        "plan": "P52S", "modalidad": "quincenal", "cuota": 360_000,
        "inicial": 1_460_000, "factura": "2026-03-16", "entrega": "2026-03-21",
        "cuota1": "2026-04-06", "pagadas": 2, "vencidas": 0, "total": 26,
        "valor": 9_360_000, "saldo": 8_640_000, "estado": "activo",
        "alegra_factura": "FE454",
    },
    {
        "n": "0013", "nombre": "Luis Rondon", "cedula": "629080",
        "tel": "573102411685", "modelo": "RAIDER 125",
        "vin": "9FL25AF31VDB95167", "motor": "BF3AV11L0917",
        "plan": None, "modalidad": "contado", "cuota": 0,
        "inicial": 2_000_000, "factura": "2026-03-17", "entrega": "2026-03-20",
        "cuota1": None, "pagadas": 0, "vencidas": 0, "total": 0,
        "valor": 7_800_000, "saldo": 0, "estado": "saldado",
        "alegra_factura": None,
    },
    {
        "n": "0014", "nombre": "Yordanis Valentin Blanco", "cedula": "2476679",
        "tel": "573244080412", "modelo": "RAIDER 125",
        "vin": "9FL25AF31VDB95036", "motor": "BF3AT15C2406",
        "plan": "P78S", "modalidad": "semanal", "cuota": 149_900,
        "inicial": 1_460_000, "factura": "2026-03-24", "entrega": "2026-03-27",
        "cuota1": "2026-04-01", "pagadas": 3, "vencidas": 0, "total": 78,
        "valor": 11_692_200, "saldo": 11_242_500, "estado": "activo",
        "alegra_factura": "FE457",
    },
    {
        "n": "0015", "nombre": "Ronald Gregory Galviz Soto", "cedula": "4650762",
        "tel": "573507991099", "modelo": "RAIDER 125",
        "vin": "9FL25AF31VDB95025", "motor": "BF3AT15C2331",
        "plan": "P78S", "modalidad": "semanal", "cuota": 149_900,
        "inicial": 1_460_000, "factura": "2026-03-26", "entrega": "2026-03-27",
        "cuota1": "2026-04-01", "pagadas": 3, "vencidas": 0, "total": 78,
        "valor": 11_692_200, "saldo": 11_242_500, "estado": "activo",
        "alegra_factura": "FE459",
    },
    {
        "n": "0016", "nombre": "Jonathan Jose Martinez Evans", "cedula": "6567354",
        "tel": "573011264063", "modelo": "RAIDER 125",
        "vin": "9FL25AF33VDB95059", "motor": "BF3AT13C2342",
        "plan": "P39S", "modalidad": "semanal", "cuota": 210_000,
        "inicial": 1_460_000, "factura": "2026-03-24", "entrega": "2026-03-27",
        "cuota1": "2026-04-01", "pagadas": 3, "vencidas": 0, "total": 39,
        "valor": 8_190_000, "saldo": 7_560_000, "estado": "activo",
        "alegra_factura": "FE461",
    },
    {
        "n": "0017", "nombre": "Richard Jose Millan Grimont", "cedula": "6145958",
        "tel": "573155237548", "modelo": "RAIDER 125",
        "vin": "9FL25AF22VDB95984", "motor": "BF3AV11L1937",
        "plan": "P39S", "modalidad": "semanal", "cuota": 129_999,
        "inicial": 1_460_000, "factura": "2026-03-25", "entrega": "2026-03-28",
        "cuota1": "2026-04-01", "pagadas": 3, "vencidas": 0, "total": 39,
        "valor": 5_069_961, "saldo": 4_679_964, "estado": "activo",
        "alegra_factura": "FE458",
    },
    {
        "n": "0018", "nombre": "Isabella Jose Herrera Morales", "cedula": "5273520",
        "tel": "573507541578", "modelo": "RAIDER 125",
        "vin": "9FL25AF31VDB95022", "motor": "BF3AT14C2502",
        "plan": "P78S", "modalidad": "quincenal", "cuota": 329_780,
        "inicial": 1_460_000, "factura": "2026-03-25", "entrega": "2026-03-28",
        "cuota1": "2026-04-15", "pagadas": 1, "vencidas": 0, "total": 39,
        "valor": 12_861_420, "saldo": 12_531_640, "estado": "activo",
        "alegra_factura": "FE460",
    },
    {
        "n": "0019", "nombre": "Andres Eduardo Soto Fuenmayor", "cedula": "4877690",
        "tel": "573223257977", "modelo": "RAIDER 125",
        "vin": "9FL25AF31VDB95072", "motor": "BF3AV14L1887",
        "plan": "P78S", "modalidad": "quincenal", "cuota": 329_780,
        "inicial": 1_460_000, "factura": "2026-04-06", "entrega": "2026-04-08",
        "cuota1": "2026-04-15", "pagadas": 1, "vencidas": 0, "total": 39,
        "valor": 12_861_420, "saldo": 12_531_640, "estado": "activo",
        "alegra_factura": "FE462",
    },
    {
        "n": "0020", "nombre": "Yorland Estid Berrocal Velasquez", "cedula": "72435712",
        "tel": "573246300165", "modelo": "RAIDER 125",
        "vin": "9FL25AF31VDB95376", "motor": "BF3AV14L1412",
        "plan": "P52S", "modalidad": "quincenal", "cuota": 395_780,
        "inicial": 1_460_000, "factura": "2026-04-07", "entrega": "2026-04-10",
        "cuota1": "2026-04-15", "pagadas": 0, "vencidas": 0, "total": 26,
        "valor": 10_290_280, "saldo": 10_290_280, "estado": "pendiente_entrega",
        "alegra_factura": "FE463",
    },
    {
        "n": "0021", "nombre": "Yeferson Daniel Benjumes Botero", "cedula": "2136090",
        "tel": "573161067357", "modelo": "RAIDER 125",
        "vin": "9FL25AF31VDB95371", "motor": "BF3AV17L1441",
        "plan": "P39S", "modalidad": "semanal", "cuota": 210_000,
        "inicial": 1_460_000, "factura": "2026-04-08", "entrega": "2026-04-10",
        "cuota1": "2026-04-16", "pagadas": 0, "vencidas": 0, "total": 39,
        "valor": 8_190_000, "saldo": 8_190_000, "estado": "pendiente_entrega",
        "alegra_factura": "FE464",
    },
    {
        "n": "0022", "nombre": "Anthony David Duran Garcia", "cedula": "8237995",
        "tel": "573054510615", "modelo": "RAIDER 125",
        "vin": "9FL25AF31VDB95075", "motor": "BF3AV19L1754",
        "plan": "P39S", "modalidad": "semanal", "cuota": 210_000,
        "inicial": 1_460_000, "factura": "2026-04-08", "entrega": "2026-04-10",
        "cuota1": "2026-04-15", "pagadas": 1, "vencidas": 0, "total": 39,
        "valor": 8_190_000, "saldo": 7_980_000, "estado": "activo",
        "alegra_factura": "FE465",
    },
    {
        "n": "0023", "nombre": "Elmer Antonio Rondon Hernandez", "cedula": "31666938",
        "tel": "573175127527", "modelo": "RAIDER 125",
        "vin": "9FL25AF31VDB95052", "motor": "BF3AV11L1858",
        "plan": "P78S", "modalidad": "semanal", "cuota": 149_900,
        "inicial": 1_460_000, "factura": "2026-04-08", "entrega": "2026-04-10",
        "cuota1": "2026-04-15", "pagadas": 1, "vencidas": 0, "total": 78,
        "valor": 11_692_200, "saldo": 11_542_300, "estado": "activo",
        "alegra_factura": "FE466",
    },
    # ------ SERVICIOS FINANCIADOS (sin VIN, sin motor) ----------------------
    {
        "n": "0024", "nombre": "Jose Altamiranda", "cedula": "1063146896",
        "tel": "573004613796", "tipo_producto": "comparendo",
        "modelo": "COMPARENDO", "vin": None, "motor": None,
        "plan": "P15S", "modalidad": "semanal", "cuota": 70_000,
        "inicial": 0, "factura": "2026-03-02", "entrega": "2026-03-05",
        "cuota1": "2026-03-11", "pagadas": 6, "vencidas": 0, "total": 15,
        "valor": 1_050_000, "saldo": 630_000, "estado": "activo",
        "alegra_factura": None,
    },
    {
        "n": "0025", "nombre": "Ronaldo Carcamo", "cedula": "1126257783",
        "tel": "573026699546", "tipo_producto": "comparendo",
        "modelo": "COMPARENDO", "vin": None, "motor": None,
        "plan": "P15S", "modalidad": "semanal", "cuota": 100_000,
        "inicial": 0, "factura": "2026-03-02", "entrega": "2026-03-05",
        "cuota1": "2026-03-11", "pagadas": 5, "vencidas": 1, "total": 15,
        "valor": 1_500_000, "saldo": 1_000_000, "estado": "mora",
        "alegra_factura": None,
    },
    {
        "n": "0026", "nombre": "Kedwyng Valladares", "cedula": "7136824",
        "tel": "573207643317", "tipo_producto": "licencia",
        "modelo": "LICENCIA", "vin": None, "motor": None,
        "plan": "P39S", "modalidad": "semanal", "cuota": 39_000,
        "inicial": 0, "factura": "2026-03-19", "entrega": "2026-03-25",
        "cuota1": "2026-03-11", "pagadas": 3, "vencidas": 0, "total": 39,
        "valor": 1_521_000, "saldo": 1_404_000, "estado": "activo",
        "alegra_factura": None,
    },
]


# ═══════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════


def _build_cuotas(row: dict) -> list[dict]:
    """Build cuotas array based on pagadas + vencidas + total + modalidad + cuota1."""
    total = row["total"]
    pagadas = row["pagadas"]
    vencidas = row["vencidas"]
    cuota_monto = row["cuota"]
    modalidad = row["modalidad"]

    # Contado saldado: no cuotas
    if total == 0:
        return []

    cuota1_str = row["cuota1"]
    if not cuota1_str:
        return []

    dias = MODALIDAD_DIAS.get(modalidad, 7)
    first_date = date.fromisoformat(cuota1_str)
    entrega = date.fromisoformat(row["entrega"])
    fecha_pago_pagadas = entrega.isoformat()  # fake pago date = entrega (migración)

    cuotas = []
    for i in range(1, total + 1):
        fecha_cuota = first_date + timedelta(days=dias * (i - 1))
        if i <= pagadas:
            estado = "pagada"
            fecha_pago = fecha_pago_pagadas
            mora_acum = 0
        elif i <= pagadas + vencidas:
            estado = "vencida"
            fecha_pago = None
            mora_acum = 0  # set to 0; real mora will be computed on next payment
        else:
            estado = "pendiente"
            fecha_pago = None
            mora_acum = 0

        cuotas.append({
            "numero": i,
            "monto": cuota_monto,
            "estado": estado,
            "fecha": fecha_cuota.isoformat(),
            "fecha_pago": fecha_pago,
            "mora_acumulada": mora_acum,
        })

    return cuotas


def _build_loanbook_doc(row: dict) -> dict:
    """Build a MongoDB document for one loanbook record."""
    tipo = row.get("tipo_producto", "moto")
    serial_id = f"LB-2026-{row['n']}"

    moto_block = None
    if tipo == "moto":
        moto_block = {
            "modelo": row["modelo"],
            "vin": row["vin"],
            "motor": row["motor"],
        }

    cliente_block = {
        "nombre": row["nombre"],
        "cedula": row["cedula"],
        "telefono": row["tel"],
        "telefono_alternativo": row.get("tel2"),
    }

    plan_block = {
        "codigo": row["plan"],
        "modalidad": row["modalidad"],
        "cuota_valor": row["cuota"],
        "cuota_inicial": row["inicial"],
        "total_cuotas": row["total"],
    }

    fechas_block = {
        "factura": row["factura"],
        "entrega": row["entrega"],
        "primera_cuota": row["cuota1"],
    }

    cuotas = _build_cuotas(row)

    doc = {
        "loanbook_id": serial_id,
        "tipo_producto": tipo,
        "cliente": cliente_block,
        "moto": moto_block,
        "plan": plan_block,
        "fechas": fechas_block,
        "cuotas": cuotas,
        "estado": row["estado"],
        "valor_total": row["valor"],
        "saldo_pendiente": row["saldo"],
        "cuotas_pagadas": row["pagadas"],
        "cuotas_vencidas": row["vencidas"],
        "cuotas_total": row["total"],
        "alegra_factura_id": row.get("alegra_factura"),
        # Compat with existing loanbook queries/handlers
        "vin": row["vin"],
        "modelo": row["modelo"],
        "modalidad": row["modalidad"],
        "plan_codigo": row["plan"],
        "cuota_monto": row["cuota"],
        "num_cuotas": row["total"],
        "saldo_capital": row["saldo"],
        "total_pagado": row["valor"] - row["saldo"] if row["saldo"] is not None else 0,
        "total_mora_pagada": 0,
        "total_anzi_pagado": 0,
        "anzi_pct": 0.0 if row["plan"] == "P15S" else 0.02,
        "fecha_entrega": row["entrega"],
        "fecha_primer_pago": row["cuota1"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "migrated_from_v1": True,
    }
    return doc


# ═══════════════════════════════════════════
# Main
# ═══════════════════════════════════════════


async def seed_catalogo_planes(db) -> int:
    """Insert P39S, P52S, P78S, P15S if not present. Returns number inserted."""
    inserted = 0
    for plan in CATALOGO_PLANES:
        existing = await db.catalogo_planes.find_one({"codigo": plan["codigo"]})
        if existing:
            # Update to ensure latest seed (models, anzi_pct) without duplicating
            await db.catalogo_planes.update_one(
                {"codigo": plan["codigo"]},
                {"$set": plan},
            )
            continue
        await db.catalogo_planes.insert_one(plan)
        inserted += 1
    return inserted


async def migrate_loanbooks(db) -> dict:
    """Insert 26 loanbooks. Anti-dup by VIN or (cedula + plan + entrega)."""
    inserted = 0
    skipped = 0
    anomalias: list[str] = []

    for row in LOANBOOKS:
        # Anti-duplicate check: include tipo_producto so two credits of same client
        # (e.g. moto + licencia) at same date don't collide.
        tipo = row.get("tipo_producto", "moto")
        dup_query: dict = {"$or": []}
        if row.get("vin"):
            dup_query["$or"].append({"vin": row["vin"]})
        dup_query["$or"].append({
            "cliente.cedula": row["cedula"],
            "plan_codigo": row["plan"],
            "fecha_entrega": row["entrega"],
            "tipo_producto": tipo,
        })
        existing = await db.loanbook.find_one(dup_query)
        if existing:
            skipped += 1
            continue

        # Anomalía: saldo > valor
        if row["saldo"] > row["valor"]:
            anomalias.append(
                f"#{row['n']} {row['nombre']}: saldo {row['saldo']} > valor {row['valor']}"
            )

        doc = _build_loanbook_doc(row)
        await db.loanbook.insert_one(doc)
        inserted += 1

    return {"inserted": inserted, "skipped": skipped, "anomalias": anomalias}


async def migrate_crm_clientes(db) -> dict:
    """Upsert CRM contact per unique cedula. Aggregates loanbook_ids."""
    # Group by cedula
    by_cedula: dict[str, dict] = {}
    for row in LOANBOOKS:
        ced = row["cedula"]
        if ced not in by_cedula:
            by_cedula[ced] = {
                "cedula": ced,
                "nombre": row["nombre"],
                "telefono": row["tel"],
                "telefono_alternativo": row.get("tel2"),
                "loanbook_ids": [],
            }
        by_cedula[ced]["loanbook_ids"].append(f"LB-2026-{row['n']}")

    inserted = 0
    updated = 0
    for ced, data in by_cedula.items():
        # Determine overall estado: activo if at least one active; else last estado seen
        estados = [r["estado"] for r in LOANBOOKS if r["cedula"] == ced]
        if any(e == "mora" for e in estados):
            estado = "mora"
        elif any(e == "activo" for e in estados):
            estado = "activo"
        elif all(e == "saldado" for e in estados):
            estado = "saldado"
        else:
            estado = estados[0] if estados else "activo"

        doc = {
            **data,
            "estado": estado,
            "loanbooks": len(data["loanbook_ids"]),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        existing = await db.crm_clientes.find_one({"cedula": ced})
        if existing:
            await db.crm_clientes.update_one(
                {"cedula": ced},
                {"$set": doc},
            )
            updated += 1
        else:
            doc["created_at"] = doc["updated_at"]
            await db.crm_clientes.insert_one(doc)
            inserted += 1

    return {"inserted": inserted, "updated": updated, "total_clientes": len(by_cedula)}


async def run() -> None:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "sismo-v2")
    if not mongo_url:
        raise RuntimeError("MONGO_URL env var is required.")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    print(f"Connected to {db_name}")
    print("\n=== Seeding catalogo_planes ===")
    n_planes = await seed_catalogo_planes(db)
    print(f"  catalogo_planes: {n_planes} new (rest upserted)")

    print("\n=== Migrating loanbooks ===")
    lb_result = await migrate_loanbooks(db)
    print(f"  loanbooks inserted: {lb_result['inserted']}")
    print(f"  loanbooks skipped (duplicates): {lb_result['skipped']}")
    if lb_result["anomalias"]:
        print(f"  anomalias detectadas: {len(lb_result['anomalias'])}")
        for a in lb_result["anomalias"]:
            print(f"    - {a}")

    print("\n=== Upserting CRM clientes ===")
    crm_result = await migrate_crm_clientes(db)
    print(f"  clientes CRM inserted: {crm_result['inserted']}")
    print(f"  clientes CRM updated: {crm_result['updated']}")
    print(f"  total unique cedulas: {crm_result['total_clientes']}")

    print("\nMigration complete.")
    client.close()


if __name__ == "__main__":
    asyncio.run(run())
