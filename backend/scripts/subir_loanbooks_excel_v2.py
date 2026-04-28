"""scripts/subir_loanbooks_excel_v2.py - Re-import limpio con formato canonico.

Crea los 14 loanbooks faltantes usando los datos del Loan Tape oficial
(loanbook_roddos_2026-04-28.xlsx) con estructura ANIDADA que el frontend
espera + capital_plan + tasa_ea + saldo_capital y saldo_intereses separados.

Reemplaza al script v1 que creaba docs en formato plano.

Uso:
    cd /opt/render/project/src/backend
    python3 scripts/subir_loanbooks_excel_v2.py --dry-run
    python3 scripts/subir_loanbooks_excel_v2.py --ejecutar
    python3 scripts/subir_loanbooks_excel_v2.py --marcar-entrega-jueves --ejecutar
"""
from __future__ import annotations
import argparse, asyncio, os, sys, json
from datetime import datetime, timezone, timedelta, date

_THIS = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_THIS)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from motor.motor_asyncio import AsyncIOMotorClient

CAPITAL_PLAN = {"RAIDER 125": 7_800_000, "TVS Raider 125": 7_800_000,
                "SPORT 100": 5_750_000, "TVS Sport 100": 5_750_000}

ALEGRA_IDS_ENTREGA_JUEVES = {
    "FE474","FE475","FE476","FE477","FE478","FE479",
    "FE480","FE481","FE482","FE483",
}
FECHA_ENTREGA_JUEVES = "2026-04-30"

# 14 docs faltantes con datos exactos del Loan Tape oficial
EXCEL_ROWS = json.loads('''[
  {
    "codigo": "LB-2026-0033",
    "producto": "RDX",
    "cliente_nombre": "GENESIS DANIELA VARGAS",
    "cliente_cedula": "6849245",
    "cliente_telefono": "573228366769",
    "cliente_ciudad": "Bogota",
    "plan_codigo": "P39S",
    "modalidad_pago": "semanal",
    "fecha_factura": "2026-04-23",
    "fecha_entrega": null,
    "fecha_vencimiento": null,
    "moto_vin": "9FLT81004VDB62260",
    "moto_modelo": "SPORT 100",
    "moto_motor": "RF5AT17A5597",
    "moto_anio": 2027,
    "moto_cilindraje": 100,
    "moto_valor_origen": 4157461.0,
    "ltv": 0,
    "monto_original": 7956000.0,
    "cuota_inicial": 0.0,
    "cuota_periodica": 204000.0,
    "tasa_ea": 0.39,
    "total_cuotas": 39,
    "cuotas_pagadas": 0,
    "cuotas_vencidas": 0,
    "saldo_capital": 5750000.0,
    "saldo_intereses": 2206000.0,
    "mora_acumulada_cop": 0.0,
    "dpd": 0,
    "estado": "Current",
    "sub_bucket_semanal": null,
    "score_riesgo": null,
    "factura_alegra_id": "FE473",
    "vendedor": null,
    "whatsapp_status": "pending",
    "subtipo_rodante": null
  },
  {
    "codigo": "LB-2026-0034",
    "producto": "RDX",
    "cliente_nombre": "ANTONI LEVIT RICO",
    "cliente_cedula": "6998154",
    "cliente_telefono": "573239469837",
    "cliente_ciudad": "Bogota",
    "plan_codigo": "P39S",
    "modalidad_pago": "semanal",
    "fecha_factura": "2026-04-27",
    "fecha_entrega": null,
    "fecha_vencimiento": null,
    "moto_vin": "9FL25AF31VDD00259",
    "moto_modelo": "RAIDER 125",
    "moto_motor": "BF3AV17C4075",
    "moto_anio": 2027,
    "moto_cilindraje": 125,
    "moto_valor_origen": 5638974.0,
    "ltv": 0,
    "monto_original": 8190000.0,
    "cuota_inicial": 1460000.0,
    "cuota_periodica": 210000.0,
    "tasa_ea": 0.39,
    "total_cuotas": 39,
    "cuotas_pagadas": 0,
    "cuotas_vencidas": 0,
    "saldo_capital": 7800000.0,
    "saldo_intereses": 390000.0,
    "mora_acumulada_cop": 0.0,
    "dpd": 0,
    "estado": "pendiente_entrega",
    "sub_bucket_semanal": null,
    "score_riesgo": null,
    "factura_alegra_id": "FE474",
    "vendedor": null,
    "whatsapp_status": "pending",
    "subtipo_rodante": null
  },
  {
    "codigo": "LB-2026-0035",
    "producto": "RDX",
    "cliente_nombre": "JORGE SUAREZ",
    "cliente_cedula": "1067163281",
    "cliente_telefono": "573046627605",
    "cliente_ciudad": "Bogota",
    "plan_codigo": "P78S",
    "modalidad_pago": "semanal",
    "fecha_factura": "2026-04-27",
    "fecha_entrega": null,
    "fecha_vencimiento": null,
    "moto_vin": "9FL25AF31VDD00407",
    "moto_modelo": "RAIDER 125",
    "moto_motor": "BF3AV17C4365",
    "moto_anio": 2027,
    "moto_cilindraje": 125,
    "moto_valor_origen": 5638974.0,
    "ltv": 0,
    "monto_original": 11692200.0,
    "cuota_inicial": 1460000.0,
    "cuota_periodica": 149900.0,
    "tasa_ea": 0.39,
    "total_cuotas": 78,
    "cuotas_pagadas": 0,
    "cuotas_vencidas": 0,
    "saldo_capital": 7800000.0,
    "saldo_intereses": 3892200.0,
    "mora_acumulada_cop": 0.0,
    "dpd": 0,
    "estado": "pendiente_entrega",
    "sub_bucket_semanal": null,
    "score_riesgo": null,
    "factura_alegra_id": "FE475",
    "vendedor": null,
    "whatsapp_status": "pending",
    "subtipo_rodante": null
  },
  {
    "codigo": "LB-2026-0036",
    "producto": "RDX",
    "cliente_nombre": "DIEGO MOISES ROSARIO ",
    "cliente_cedula": "6226257",
    "cliente_telefono": "573145204952",
    "cliente_ciudad": "Bogota",
    "plan_codigo": "P39S",
    "modalidad_pago": "semanal",
    "fecha_factura": "2026-04-27",
    "fecha_entrega": null,
    "fecha_vencimiento": null,
    "moto_vin": "9FL25AF32VDD00285",
    "moto_modelo": "RAIDER 125",
    "moto_motor": "BF3AV18L3076",
    "moto_anio": 2027,
    "moto_cilindraje": 125,
    "moto_valor_origen": 5638974.0,
    "ltv": 0,
    "monto_original": 8190000.0,
    "cuota_inicial": 1460000.0,
    "cuota_periodica": 210000.0,
    "tasa_ea": 0.39,
    "total_cuotas": 39,
    "cuotas_pagadas": 0,
    "cuotas_vencidas": 0,
    "saldo_capital": 7800000.0,
    "saldo_intereses": 390000.0,
    "mora_acumulada_cop": 0.0,
    "dpd": 0,
    "estado": "pendiente_entrega",
    "sub_bucket_semanal": null,
    "score_riesgo": null,
    "factura_alegra_id": "FE476",
    "vendedor": null,
    "whatsapp_status": "pending",
    "subtipo_rodante": null
  },
  {
    "codigo": "LB-2026-0037",
    "producto": "RDX",
    "cliente_nombre": "MANUEL DAVID QUIROZ",
    "cliente_cedula": "1103216616",
    "cliente_telefono": "573249063599",
    "cliente_ciudad": "Bogota",
    "plan_codigo": "P39S",
    "modalidad_pago": "semanal",
    "fecha_factura": "2026-04-28",
    "fecha_entrega": null,
    "fecha_vencimiento": null,
    "moto_vin": "9FL25AF33VDD00425",
    "moto_modelo": "RAIDER 125",
    "moto_motor": "BF3AV11C4364",
    "moto_anio": 2027,
    "moto_cilindraje": 125,
    "moto_valor_origen": 5638974.0,
    "ltv": 0,
    "monto_original": 8190000.0,
    "cuota_inicial": 1460000.0,
    "cuota_periodica": 210000.0,
    "tasa_ea": 0.39,
    "total_cuotas": 39,
    "cuotas_pagadas": 0,
    "cuotas_vencidas": 0,
    "saldo_capital": 7800000.0,
    "saldo_intereses": 390000.0,
    "mora_acumulada_cop": 0.0,
    "dpd": 0,
    "estado": "pendiente_entrega",
    "sub_bucket_semanal": null,
    "score_riesgo": null,
    "factura_alegra_id": "FE477",
    "vendedor": null,
    "whatsapp_status": "pending",
    "subtipo_rodante": null
  },
  {
    "codigo": "LB-2026-0038",
    "producto": "RDX",
    "cliente_nombre": "MANUEL DAVID QUIROZ",
    "cliente_cedula": "1103216616",
    "cliente_telefono": "573249063599",
    "cliente_ciudad": "Bogota",
    "plan_codigo": "P52S",
    "modalidad_pago": "semanal",
    "fecha_factura": "2026-04-28",
    "fecha_entrega": null,
    "fecha_vencimiento": null,
    "moto_vin": "9FL25AF34VDD00434",
    "moto_modelo": "RAIDER 125",
    "moto_motor": "BF3AV11C4379",
    "moto_anio": 2027,
    "moto_cilindraje": 125,
    "moto_valor_origen": 5638974.0,
    "ltv": 0,
    "monto_original": 9354800.0,
    "cuota_inicial": 1460000.0,
    "cuota_periodica": 179900.0,
    "tasa_ea": 0.39,
    "total_cuotas": 52,
    "cuotas_pagadas": 0,
    "cuotas_vencidas": 0,
    "saldo_capital": 7800000.0,
    "saldo_intereses": 1554800.0,
    "mora_acumulada_cop": 0.0,
    "dpd": 0,
    "estado": "pendiente_entrega",
    "sub_bucket_semanal": null,
    "score_riesgo": null,
    "factura_alegra_id": "FE478",
    "vendedor": null,
    "whatsapp_status": "pending",
    "subtipo_rodante": null
  },
  {
    "codigo": "LB-2026-0039",
    "producto": "RDX",
    "cliente_nombre": "MANUEL DAVID QUIROZ",
    "cliente_cedula": "1103216616",
    "cliente_telefono": "573249063599",
    "cliente_ciudad": "Bogota",
    "plan_codigo": "P52S",
    "modalidad_pago": "semanal",
    "fecha_factura": "2026-04-28",
    "fecha_entrega": null,
    "fecha_vencimiento": null,
    "moto_vin": "9FL25AF35VDD00250",
    "moto_modelo": "RAIDER 125",
    "moto_motor": "BF3AV17C4056",
    "moto_anio": 2027,
    "moto_cilindraje": 125,
    "moto_valor_origen": 5638974.0,
    "ltv": 0,
    "monto_original": 9354800.0,
    "cuota_inicial": 1460000.0,
    "cuota_periodica": 179900.0,
    "tasa_ea": 0.39,
    "total_cuotas": 52,
    "cuotas_pagadas": 0,
    "cuotas_vencidas": 0,
    "saldo_capital": 7800000.0,
    "saldo_intereses": 1554800.0,
    "mora_acumulada_cop": 0.0,
    "dpd": 0,
    "estado": "pendiente_entrega",
    "sub_bucket_semanal": null,
    "score_riesgo": null,
    "factura_alegra_id": "FE479",
    "vendedor": null,
    "whatsapp_status": "pending",
    "subtipo_rodante": null
  },
  {
    "codigo": "LB-2026-0040",
    "producto": "RDX",
    "cliente_nombre": "EDUAR ROJAS",
    "cliente_cedula": "6554194",
    "cliente_telefono": "573003319158",
    "cliente_ciudad": "Bogota",
    "plan_codigo": "P39S",
    "modalidad_pago": "semanal",
    "fecha_factura": "2026-04-28",
    "fecha_entrega": null,
    "fecha_vencimiento": null,
    "moto_vin": "9FL25AF35VDD00426",
    "moto_modelo": "RAIDER 125",
    "moto_motor": "BF3AV15C4515",
    "moto_anio": 2027,
    "moto_cilindraje": 125,
    "moto_valor_origen": 5638974.0,
    "ltv": 0,
    "monto_original": 8190000.0,
    "cuota_inicial": 1460000.0,
    "cuota_periodica": 210000.0,
    "tasa_ea": 0.39,
    "total_cuotas": 39,
    "cuotas_pagadas": 0,
    "cuotas_vencidas": 0,
    "saldo_capital": 7800000.0,
    "saldo_intereses": 390000.0,
    "mora_acumulada_cop": 0.0,
    "dpd": 0,
    "estado": "pendiente_entrega",
    "sub_bucket_semanal": null,
    "score_riesgo": null,
    "factura_alegra_id": "FE480",
    "vendedor": null,
    "whatsapp_status": "pending",
    "subtipo_rodante": null
  },
  {
    "codigo": "LB-2026-0041",
    "producto": "RDX",
    "cliente_nombre": "LEONEL MEDRANO",
    "cliente_cedula": "5222231",
    "cliente_telefono": "573224113327",
    "cliente_ciudad": "Bogota",
    "plan_codigo": "P39S",
    "modalidad_pago": "semanal",
    "fecha_factura": "2026-04-28",
    "fecha_entrega": null,
    "fecha_vencimiento": null,
    "moto_vin": "9FL25AF37VDD00427",
    "moto_modelo": "RAIDER 125",
    "moto_motor": "BF3AV16C4476",
    "moto_anio": 2027,
    "moto_cilindraje": 125,
    "moto_valor_origen": 5638974.0,
    "ltv": 0,
    "monto_original": 8190000.0,
    "cuota_inicial": 1460000.0,
    "cuota_periodica": 210000.0,
    "tasa_ea": 0.39,
    "total_cuotas": 39,
    "cuotas_pagadas": 0,
    "cuotas_vencidas": 0,
    "saldo_capital": 7800000.0,
    "saldo_intereses": 390000.0,
    "mora_acumulada_cop": 0.0,
    "dpd": 0,
    "estado": "pendiente_entrega",
    "sub_bucket_semanal": null,
    "score_riesgo": null,
    "factura_alegra_id": "FE481",
    "vendedor": null,
    "whatsapp_status": "pending",
    "subtipo_rodante": null
  },
  {
    "codigo": "LB-2026-0042",
    "producto": "RDX",
    "cliente_nombre": "ROBINSON RONDON",
    "cliente_cedula": "4628305",
    "cliente_telefono": "573001758140",
    "cliente_ciudad": "Bogota",
    "plan_codigo": "P39S",
    "modalidad_pago": "semanal",
    "fecha_factura": "2026-04-28",
    "fecha_entrega": null,
    "fecha_vencimiento": null,
    "moto_vin": "9FL25AF39VDD00431",
    "moto_modelo": "RAIDER 125",
    "moto_motor": "BF3AV17C4482",
    "moto_anio": 2027,
    "moto_cilindraje": 125,
    "moto_valor_origen": 5638974.0,
    "ltv": 0,
    "monto_original": 8190000.0,
    "cuota_inicial": 1460000.0,
    "cuota_periodica": 210000.0,
    "tasa_ea": 0.39,
    "total_cuotas": 39,
    "cuotas_pagadas": 0,
    "cuotas_vencidas": 0,
    "saldo_capital": 7800000.0,
    "saldo_intereses": 390000.0,
    "mora_acumulada_cop": 0.0,
    "dpd": 0,
    "estado": "pendiente_entrega",
    "sub_bucket_semanal": null,
    "score_riesgo": null,
    "factura_alegra_id": "FE482",
    "vendedor": null,
    "whatsapp_status": "pending",
    "subtipo_rodante": null
  },
  {
    "codigo": "LB-2026-0043",
    "producto": "RDX",
    "cliente_nombre": "MARIMAR GARCIA",
    "cliente_cedula": "5196362",
    "cliente_telefono": "573004801153",
    "cliente_ciudad": "Bogota",
    "plan_codigo": "P52S",
    "modalidad_pago": "semanal",
    "fecha_factura": "2026-04-28",
    "fecha_entrega": null,
    "fecha_vencimiento": null,
    "moto_vin": "9FL25AF3XVDD00406",
    "moto_modelo": "RAIDER 125",
    "moto_motor": "BF3AV14C4321",
    "moto_anio": 2027,
    "moto_cilindraje": 125,
    "moto_valor_origen": 5638974.0,
    "ltv": 0,
    "monto_original": 9354800.0,
    "cuota_inicial": 1460000.0,
    "cuota_periodica": 179900.0,
    "tasa_ea": 0.39,
    "total_cuotas": 52,
    "cuotas_pagadas": 0,
    "cuotas_vencidas": 0,
    "saldo_capital": 7800000.0,
    "saldo_intereses": 1554800.0,
    "mora_acumulada_cop": 0.0,
    "dpd": 0,
    "estado": "pendiente_entrega",
    "sub_bucket_semanal": null,
    "score_riesgo": null,
    "factura_alegra_id": "FE483",
    "vendedor": null,
    "whatsapp_status": "pending",
    "subtipo_rodante": null
  },
  {
    "codigo": "LB-2026-0024",
    "producto": "RODANTE",
    "cliente_nombre": "Jose Altamiranda",
    "cliente_cedula": "1063146896",
    "cliente_telefono": "573004613796",
    "cliente_ciudad": "",
    "plan_codigo": "P15S",
    "modalidad_pago": "semanal",
    "fecha_factura": "2026-03-02",
    "fecha_entrega": "2026-03-05",
    "fecha_vencimiento": "2026-06-17",
    "moto_vin": null,
    "moto_modelo": null,
    "moto_motor": null,
    "moto_anio": null,
    "moto_cilindraje": null,
    "moto_valor_origen": 0,
    "ltv": 0,
    "monto_original": 1050000.0,
    "cuota_inicial": NaN,
    "cuota_periodica": 70000.0,
    "tasa_ea": 0.39,
    "total_cuotas": 15,
    "cuotas_pagadas": 6,
    "cuotas_vencidas": 0,
    "saldo_capital": 560000.0,
    "saldo_intereses": 0.0,
    "mora_acumulada_cop": 0.0,
    "dpd": 0,
    "estado": "Current",
    "sub_bucket_semanal": null,
    "score_riesgo": null,
    "factura_alegra_id": null,
    "vendedor": null,
    "whatsapp_status": "pending",
    "subtipo_rodante": "comparendo"
  },
  {
    "codigo": "LB-2026-0025",
    "producto": "RODANTE",
    "cliente_nombre": "Ronaldo Carcamo",
    "cliente_cedula": "1126257783",
    "cliente_telefono": "573026699546",
    "cliente_ciudad": "",
    "plan_codigo": "P15S",
    "modalidad_pago": "semanal",
    "fecha_factura": "2026-03-02",
    "fecha_entrega": "2026-03-05",
    "fecha_vencimiento": "2026-06-17",
    "moto_vin": null,
    "moto_modelo": null,
    "moto_motor": null,
    "moto_anio": null,
    "moto_cilindraje": null,
    "moto_valor_origen": 0,
    "ltv": 0,
    "monto_original": 1500000.0,
    "cuota_inicial": NaN,
    "cuota_periodica": 100000.0,
    "tasa_ea": 0.39,
    "total_cuotas": 15,
    "cuotas_pagadas": 6,
    "cuotas_vencidas": 0,
    "saldo_capital": 800000.0,
    "saldo_intereses": 0.0,
    "mora_acumulada_cop": 0.0,
    "dpd": 0,
    "estado": "Current",
    "sub_bucket_semanal": null,
    "score_riesgo": null,
    "factura_alegra_id": null,
    "vendedor": null,
    "whatsapp_status": "pending",
    "subtipo_rodante": "comparendo"
  },
  {
    "codigo": "LB-2026-0026",
    "producto": "RODANTE",
    "cliente_nombre": "Kedwyng Valladares",
    "cliente_cedula": "7136824",
    "cliente_telefono": "573207643317",
    "cliente_ciudad": "",
    "plan_codigo": "P39S",
    "modalidad_pago": "semanal",
    "fecha_factura": "2026-03-19",
    "fecha_entrega": "2026-03-25",
    "fecha_vencimiento": "2026-12-02",
    "moto_vin": null,
    "moto_modelo": null,
    "moto_motor": null,
    "moto_anio": null,
    "moto_cilindraje": null,
    "moto_valor_origen": 0,
    "ltv": 0,
    "monto_original": 1521000.0,
    "cuota_inicial": NaN,
    "cuota_periodica": 39000.0,
    "tasa_ea": 0.39,
    "total_cuotas": 39,
    "cuotas_pagadas": 4,
    "cuotas_vencidas": 0,
    "saldo_capital": 1326000.0,
    "saldo_intereses": 0.0,
    "mora_acumulada_cop": 0.0,
    "dpd": 0,
    "estado": "Current",
    "sub_bucket_semanal": null,
    "score_riesgo": null,
    "factura_alegra_id": null,
    "vendedor": null,
    "whatsapp_status": "pending",
    "subtipo_rodante": "licencia"
  }
]''')


def _next_wednesday(d: date) -> date:
    """Devuelve d si es miercoles, o el proximo miercoles."""
    days_ahead = 2 - d.weekday()
    if days_ahead < 0:
        days_ahead += 7
    elif days_ahead == 0:
        return d
    return d + timedelta(days=days_ahead)


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:10]).date()
    except Exception:
        return None


def _generar_cuotas(row: dict) -> list[dict]:
    """Genera cuotas[] con regla del miercoles, marcando las pagadas."""
    cuotas = []
    fecha_entrega = _parse_date(row["fecha_entrega"])
    if not fecha_entrega:
        return cuotas

    # Primera cuota = primer miercoles >= fecha_entrega + (segun modalidad)
    modalidad = row["modalidad_pago"]
    if modalidad == "semanal":
        salto = 7
    elif modalidad == "quincenal":
        salto = 14
    elif modalidad == "mensual":
        salto = 28
    else:
        salto = 7

    primera = _next_wednesday(fecha_entrega + timedelta(days=salto))
    cuotas_pagadas = row.get("cuotas_pagadas", 0)

    for i in range(1, row["total_cuotas"] + 1):
        fecha = primera + timedelta(days=salto * (i - 1))
        cuotas.append({
            "numero":         i,
            "monto":          int(row["cuota_periodica"]),
            "fecha":          fecha.isoformat(),
            "estado":         "pagada" if i <= cuotas_pagadas else "pendiente",
            "fecha_pago":     fecha.isoformat() if i <= cuotas_pagadas else None,
            "mora_acumulada": 0,
        })
    return cuotas


def _construir_doc(row: dict, ahora_iso: str) -> dict:
    """Construye doc loanbook con estructura canonica completa."""
    es_pendiente_entrega = row["factura_alegra_id"] in ALEGRA_IDS_ENTREGA_JUEVES

    # tipo_producto del frontend
    if row["producto"] == "RDX":
        tipo_producto = "moto"
    elif row["subtipo_rodante"]:
        tipo_producto = row["subtipo_rodante"]
    else:
        tipo_producto = "moto"

    # Mapeo estado canonico
    estado_excel = row.get("estado", "Current")

    # Cliente bloque anidado
    cliente_block = {
        "nombre":               row["cliente_nombre"],
        "cedula":               row["cliente_cedula"],
        "telefono":             row["cliente_telefono"],
        "telefono_alternativo": None,
    }

    # Moto bloque anidado (solo para RDX)
    moto_block = None
    if row["producto"] == "RDX" and row.get("moto_vin"):
        moto_block = {
            "modelo": row["moto_modelo"],
            "vin":    row["moto_vin"],
            "motor":  row["moto_motor"],
        }

    # Plan bloque anidado
    plan_block = {
        "codigo":        row["plan_codigo"],
        "modalidad":     row["modalidad_pago"],
        "cuota_valor":   int(row["cuota_periodica"]),
        "cuota_inicial": int(row["cuota_inicial"]),
        "total_cuotas":  row["total_cuotas"],
    }

    # Fechas bloque anidado
    fechas_block = {
        "factura":       row["fecha_factura"],
        "entrega":       None if es_pendiente_entrega else row["fecha_entrega"],
        "primera_cuota": None,
    }

    # Cuotas (vacio si pendiente_entrega)
    cuotas = [] if es_pendiente_entrega else _generar_cuotas(row)
    if cuotas:
        fechas_block["primera_cuota"] = cuotas[0]["fecha"]

    # Capital plan
    capital_plan = CAPITAL_PLAN.get(row.get("moto_modelo", ""), int(row["monto_original"]))
    if row["producto"] == "RODANTE":
        capital_plan = int(row["monto_original"])

    # Saldos: para pendiente_entrega usamos saldo_capital = capital_plan
    if es_pendiente_entrega:
        saldo_capital = capital_plan
        saldo_intereses = int(row["monto_original"]) - capital_plan
        saldo_pendiente = int(row["monto_original"])
    else:
        saldo_capital   = int(row["saldo_capital"])
        saldo_intereses = int(row["saldo_intereses"])
        saldo_pendiente = saldo_capital + saldo_intereses

    valor_total = int(row["cuota_inicial"]) + (int(row["cuota_periodica"]) * row["total_cuotas"])

    return {
        # IDs canonicos
        "loanbook_id":       row["codigo"],
        "tipo_producto":     tipo_producto,
        "producto":          row["producto"],
        "subtipo_rodante":   row.get("subtipo_rodante"),

        # Bloques anidados (frontend lee de estos)
        "cliente":           cliente_block,
        "moto":              moto_block,
        "plan":              plan_block,
        "fechas":            fechas_block,

        # Campos planos legacy (frontend tambien los lee)
        "modelo":            row.get("moto_modelo"),
        "vin":               row.get("moto_vin"),
        "modalidad":         row["modalidad_pago"],
        "modalidad_pago":    row["modalidad_pago"],
        "plan_codigo":       row["plan_codigo"],
        "cuota_monto":       int(row["cuota_periodica"]),
        "cuota_periodica":   int(row["cuota_periodica"]),
        "cuota_inicial":     int(row["cuota_inicial"]),
        "num_cuotas":        row["total_cuotas"],
        "total_cuotas":      row["total_cuotas"],
        "cuotas_total":      row["total_cuotas"],

        # Cuotas con regla miercoles
        "cuotas":            cuotas,

        # Saldos canonicos
        "saldo_capital":     saldo_capital,
        "saldo_intereses":   saldo_intereses,
        "saldo_pendiente":   saldo_pendiente,
        "valor_total":       valor_total,
        "monto_original":    int(row["monto_original"]),
        "capital_plan":      capital_plan,
        "cuota_estandar_plan": int(row["cuota_periodica"]),

        # Estado y mora
        "estado":            "Pendiente Entrega" if es_pendiente_entrega else estado_excel,
        "estado_credito":    "pendiente_entrega" if es_pendiente_entrega else "activo",
        "dpd":               row.get("dpd", 0),
        "mora_acumulada_cop": int(row.get("mora_acumulada_cop", 0)),
        "sub_bucket_semanal": row.get("sub_bucket_semanal"),
        "score_riesgo":      row.get("score_riesgo"),
        "anzi_pct":          0.02 if row["producto"] == "RDX" else 0.0,

        # Pagos
        "cuotas_pagadas":    row.get("cuotas_pagadas", 0),
        "cuotas_vencidas":   row.get("cuotas_vencidas", 0),
        "total_pagado":      row.get("cuotas_pagadas", 0) * int(row["cuota_periodica"]),
        "total_mora_pagada": 0,
        "total_anzi_pagado": 0,

        # Fechas planas
        "fecha_entrega":     None if es_pendiente_entrega else row["fecha_entrega"],
        "fecha_factura":     row["fecha_factura"],
        "fecha_primer_pago": cuotas[0]["fecha"] if cuotas else None,
        "fecha_vencimiento": row.get("fecha_vencimiento"),
        "fecha_entrega_programada": FECHA_ENTREGA_JUEVES if es_pendiente_entrega else None,

        # Auditoria
        "factura_alegra_id": row.get("factura_alegra_id"),
        "alegra_factura_id": row.get("factura_alegra_id"),
        "vendedor":          row.get("vendedor"),
        "whatsapp_status":   row.get("whatsapp_status", "pending"),
        "acuerdo_activo_id": None,
        "metadata_producto": {
            "moto_modelo": row.get("moto_modelo"),
            "moto_vin":    row.get("moto_vin"),
            "moto_motor":  row.get("moto_motor"),
            "moto_anio":   row.get("moto_anio"),
            "moto_cilindraje": row.get("moto_cilindraje"),
            "moto_valor_origen": row.get("moto_valor_origen", 0),
            "ltv":         row.get("ltv", 0),
        },

        # Timestamps
        "created_at":  ahora_iso,
        "updated_at":  ahora_iso,
        "migrated_from_v1": True,
        "via":         "import_excel_v2",
    }


def _construir_crm(row: dict, loanbook_id: str, ahora) -> dict:
    estado_excel = row.get("estado", "Current")
    if "Delinquency" in estado_excel or "Default" in estado_excel:
        tag = "mora"
    elif estado_excel == "Pagado":
        tag = "paz_y_salvo"
    else:
        tag = "al_dia"
    return {
        "cedula":          row["cliente_cedula"],
        "nombre":          row["cliente_nombre"],
        "telefono":        row["cliente_telefono"],
        "mercately_phone": row["cliente_telefono"],
        "tags":            [tag],
        "loanbook_ids":    [loanbook_id],
        "gestiones":       [],
        "fecha_creacion":  ahora,
        "fecha_actualizacion": ahora,
        "via":             "import_excel_v2",
    }


async def main(args):
    mongo = os.environ.get("MONGO_URL", "")
    db_name = os.environ.get("DB_NAME", "")
    if not mongo or not db_name:
        print("ERROR: MONGO_URL o DB_NAME no configurados")
        sys.exit(1)

    cli = AsyncIOMotorClient(mongo)
    db = cli[db_name]
    ahora = datetime.now(timezone.utc)
    ahora_iso = ahora.isoformat()

    contador = {"total": len(EXCEL_ROWS), "skip": 0, "creados_lb": 0, "creados_crm": 0, "errores": []}
    print(f"\n{'='*100}")
    print(f"{'#':<4}{'codigo':<14}{'Alegra':<8}{'Cliente':<32}{'estado':<22}")
    print(f"{'='*100}")

    try:
        for i, row in enumerate(EXCEL_ROWS, 1):
            existente = await db.loanbook.find_one({"loanbook_id": row["codigo"]})
            if existente:
                contador["skip"] += 1
                print(f"{i:<4}{row['codigo']:<14}{row.get('factura_alegra_id') or '-':<8}{row['cliente_nombre'][:30]:<32}YA EXISTE skip")
                continue
            try:
                doc = _construir_doc(row, ahora_iso)
                crm = _construir_crm(row, row["codigo"], ahora)
                if args.ejecutar:
                    await db.loanbook.insert_one(doc)
                    contador["creados_lb"] += 1

                    cli_existente = await db.crm_clientes.find_one({"cedula": row["cliente_cedula"]})
                    if not cli_existente:
                        await db.crm_clientes.insert_one(crm)
                        contador["creados_crm"] += 1
                    else:
                        await db.crm_clientes.update_one(
                            {"cedula": row["cliente_cedula"]},
                            {"$addToSet": {"loanbook_ids": row["codigo"]},
                             "$set": {"fecha_actualizacion": ahora,
                                      "telefono": row["cliente_telefono"]}},
                        )
                modo = "CREADO" if args.ejecutar else "DRY_RUN"
                estado_msg = doc["estado"]
                print(f"{i:<4}{row['codigo']:<14}{row.get('factura_alegra_id') or '-':<8}{row['cliente_nombre'][:30]:<32}{estado_msg:<22}{modo}")
            except Exception as exc:
                contador["errores"].append({"codigo": row["codigo"], "error": str(exc)})
                print(f"{i:<4}{row['codigo']:<14}ERROR: {exc}")

        print(f"\n{'='*60}")
        print(f"RESUMEN ({'EJECUCION REAL' if args.ejecutar else 'DRY-RUN'}):")
        print(f"  Total filas:           {contador['total']}")
        print(f"  Ya existen (skip):     {contador['skip']}")
        print(f"  Loanbooks creados:     {contador['creados_lb']}")
        print(f"  Clientes CRM creados:  {contador['creados_crm']}")
        if contador["errores"]:
            print(f"  ERRORES ({len(contador['errores'])}):")
            for e in contador["errores"]:
                print(f"    {e['codigo']}: {e['error']}")
        print(f"{'='*60}")
        if not args.ejecutar:
            print("\nPara ejecutar real: python3 scripts/subir_loanbooks_excel_v2.py --ejecutar")
    finally:
        cli.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="(default) no toca DB")
    parser.add_argument("--ejecutar", action="store_true", help="aplica cambios reales")
    args = parser.parse_args()
    asyncio.run(main(args))
