"""
scripts/subir_loanbooks_excel_v1.py — Sube loanbooks faltantes desde Excel V1.

Lee 43 filas del Excel RODDOS_Loanbooks_V1_para_completar.xlsx (datos embebidos
en este script para self-containment) y crea en MongoDB SOLO los que falten en
loanbook + crm_clientes.

Idempotente: si el factura_alegra_id ya existe en loanbook, salta.
Tambien busca por VIN como fallback para evitar duplicados.

Uso:

    cd /opt/render/project/src/backend

    # Dry run — muestra qué crearía, no toca la DB
    python3 scripts/subir_loanbooks_excel_v1.py --dry-run

    # Ejecutar — crea los faltantes
    python3 scripts/subir_loanbooks_excel_v1.py --ejecutar

    # Marcar entregas jueves para las 10 Raider 27-28abr
    python3 scripts/subir_loanbooks_excel_v1.py --marcar-entrega-jueves

Sprint 2026-04-28 — Backfill manual desde Excel.
"""
from __future__ import annotations
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Any

# Permite correr desde cualquier directorio con backend en path
_THIS = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_THIS)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from motor.motor_asyncio import AsyncIOMotorClient

# Capital_plan canonico segun CLAUDE.md
CAPITAL_PLAN = {
    "RAIDER 125": 7_800_000,
    "SPORT 100":  5_750_000,
}

# Cuota inicial sugerida (puede sobreescribirse con Excel)
CUOTA_INICIAL_DEFAULT = {
    "RAIDER 125": 1_460_000,
    "SPORT 100":  1_160_000,
}

# Las 10 Raider del 27-28 abril que entregan jueves 30 abril 2026
ALEGRA_IDS_ENTREGA_JUEVES = {
    "FE474", "FE475", "FE476",            # 27-abr (3)
    "FE477", "FE478", "FE479", "FE480",   # 28-abr (4)
    "FE481", "FE482", "FE483",            # 28-abr (3 mas) = 10 total
}
FECHA_ENTREGA_JUEVES = "2026-04-30"

# Datos embebidos del Excel — 43 filas
EXCEL_ROWS: list[dict] = [
    {"n":1,"cliente":"Chenier Quintero","cedula":"1283367","telefono":"3015434981","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF31VDB95057","motor":"BF3AT13C2338","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-03-02","fecha_entrega":"2026-03-05","fecha_cuota_1":"2026-03-11","cuotas_pagadas":6,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":8275400.0,"estado":"activo","alegra_id":"FE444"},
    {"n":2,"cliente":"Jose altamiranda","cedula":"1063146896","telefono":"3004613796","tel_alt":"","modelo":"SPORT 100","vin":"9FL25AF22VDB95413","motor":"RF5AT18A5448","plan":"P78S","modalidad":"Semanal","cuota_valor":130000.0,"cuota_inicial":1160000.0,"fecha_factura":"2026-03-02","fecha_entrega":"2026-03-05","fecha_cuota_1":"2026-03-05","cuotas_pagadas":6,"cuotas_vencidas":0,"total_cuotas":78,"valor_total":10140000.0,"saldo":9360000.0,"estado":"activo","alegra_id":"FE448"},
    {"n":3,"cliente":"Ernesto Antonio Jaime","cedula":"6226605","telefono":"3005056127","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF31VDB95048","motor":"BF3AT15C2365","plan":"P78S","modalidad":"Semanal","cuota_valor":149900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-03-02","fecha_entrega":"2026-03-05","fecha_cuota_1":"2026-03-11","cuotas_pagadas":6,"cuotas_vencidas":0,"total_cuotas":78,"valor_total":11692200.0,"saldo":10792800.0,"estado":"activo","alegra_id":"FE445"},
    {"n":4,"cliente":"Ronaldo Carcamo","cedula":"1126257783","telefono":"3007878965","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF31VDB95055","motor":"BF3AT15C2378","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-03-02","fecha_entrega":"2026-03-05","fecha_cuota_1":"2026-03-11","cuotas_pagadas":3,"cuotas_vencidas":3,"total_cuotas":52,"valor_total":9354800.0,"saldo":8815100.0,"estado":"mora","alegra_id":"FE446"},
    {"n":5,"cliente":"Beatriz A Garcia","cedula":"5203668","telefono":"3145112233","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF31VDB95046","motor":"BF3AT15C2399","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-03-02","fecha_entrega":"2026-03-05","fecha_cuota_1":"2026-03-11","cuotas_pagadas":6,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":8275400.0,"estado":"activo","alegra_id":"FE447"},
    {"n":6,"cliente":"Alexis crespo","cedula":"598091","telefono":"3017654321","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF31VDB95058","motor":"BF3AT15C2401","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-03-02","fecha_entrega":"2026-03-05","fecha_cuota_1":"2026-03-11","cuotas_pagadas":6,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":8275400.0,"estado":"activo","alegra_id":"FE449"},
    {"n":7,"cliente":"Moises Ascanio","cedula":"199053959","telefono":"3209876543","tel_alt":"","modelo":"SPORT 100","vin":"9FL25AF22VDB95414","motor":"RF5AT18A5499","plan":"P78S","modalidad":"Semanal","cuota_valor":130000.0,"cuota_inicial":1160000.0,"fecha_factura":"2026-03-02","fecha_entrega":"2026-03-05","fecha_cuota_1":"2026-03-05","cuotas_pagadas":6,"cuotas_vencidas":0,"total_cuotas":78,"valor_total":10140000.0,"saldo":9360000.0,"estado":"activo","alegra_id":"FE450"},
    {"n":8,"cliente":"Kreyser Cabrices","cedula":"7711632","telefono":"3134567890","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF31VDB95043","motor":"BF3AT15C2455","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-03-02","fecha_entrega":"2026-03-05","fecha_cuota_1":"2026-03-11","cuotas_pagadas":6,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":8275400.0,"estado":"activo","alegra_id":"FE451"},
    {"n":9,"cliente":"Dora Maria Ospina","cedula":"20677811","telefono":"3145678901","tel_alt":"","modelo":"SPORT 100","vin":"9FL25AF22VDB95265","motor":"RF5AT18A5500","plan":"P52S","modalidad":"Semanal","cuota_valor":131000.0,"cuota_inicial":1160000.0,"fecha_factura":"2026-03-06","fecha_entrega":"2026-03-10","fecha_cuota_1":"2026-03-13","cuotas_pagadas":3,"cuotas_vencidas":3,"total_cuotas":52,"valor_total":6812000.0,"saldo":6157000.0,"estado":"mora","alegra_id":"FE452"},
    {"n":10,"cliente":"Sindy Bibiana Beltran","cedula":"1012415625","telefono":"3156789012","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF31VDB95987","motor":"BF3AT15C2511","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-03-13","fecha_entrega":"2026-03-19","fecha_cuota_1":"2026-03-25","cuotas_pagadas":5,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":8455300.0,"estado":"activo","alegra_id":"FE453"},
    {"n":11,"cliente":"Kedwyng Valladares","cedula":"7136824","telefono":"3167890123","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF31VDB95190","motor":"BF3AT15C2522","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-03-19","fecha_entrega":"2025-03-25","fecha_cuota_1":"2026-04-01","cuotas_pagadas":4,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":8635200.0,"estado":"activo","alegra_id":"FE456"},
    {"n":12,"cliente":"Manuel Andres Ovalles","cedula":"5898416","telefono":"3178901234","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF31VDB95997","motor":"BF3AT15C2533","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-03-16","fecha_entrega":"2026-03-21","fecha_cuota_1":"2026-03-25","cuotas_pagadas":5,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":8455300.0,"estado":"activo","alegra_id":"FE454"},
    {"n":13,"cliente":"Luis Rondon","cedula":"629080","telefono":"3189012345","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF31VDB95167","motor":"BF3AT15C2544","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-03-17","fecha_entrega":"2026-03-20","fecha_cuota_1":"2026-03-25","cuotas_pagadas":52,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":0.0,"estado":"completado","alegra_id":"FE455"},
    {"n":14,"cliente":"Yordanis Valentin Blanco","cedula":"2476679","telefono":"3190123456","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF31VDB95036","motor":"BF3AT15C2555","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-03-24","fecha_entrega":"2026-03-27","fecha_cuota_1":"2026-04-01","cuotas_pagadas":4,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":8635200.0,"estado":"activo","alegra_id":"FE457"},
    {"n":15,"cliente":"Ronald Gregory Galviz Soto","cedula":"4650762","telefono":"3201234567","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF31VDB95025","motor":"BF3AT15C2566","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-03-26","fecha_entrega":"2026-03-27","fecha_cuota_1":"2026-04-01","cuotas_pagadas":4,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":8635200.0,"estado":"activo","alegra_id":"FE459"},
    {"n":16,"cliente":"Jonathan José Martinez Evans","cedula":"6567354","telefono":"3212345678","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF33VDB95059","motor":"BF3AT15C2577","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-03-24","fecha_entrega":"2026-03-27","fecha_cuota_1":"2026-04-01","cuotas_pagadas":4,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":8635200.0,"estado":"activo","alegra_id":"FE461"},
    {"n":17,"cliente":"Richard José Millan Grimont","cedula":"6145958","telefono":"3223456789","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF22VDB95984","motor":"BF3AT15C2588","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-03-25","fecha_entrega":"2026-03-28","fecha_cuota_1":"2026-04-01","cuotas_pagadas":4,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":8635200.0,"estado":"activo","alegra_id":"FE458"},
    {"n":18,"cliente":"Isabella José Herrera Morales","cedula":"5273520","telefono":"3234567890","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF31VDB95022","motor":"BF3AT15C2599","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-03-25","fecha_entrega":"2026-03-28","fecha_cuota_1":"2026-04-01","cuotas_pagadas":4,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":8635200.0,"estado":"activo","alegra_id":"FE460"},
    {"n":19,"cliente":"Andres Eduardo Soto Fuenmayor","cedula":"4877690","telefono":"3245678901","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF31VDB95072","motor":"BF3AT15C2611","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-04-06","fecha_entrega":"2026-04-08","fecha_cuota_1":"2026-04-15","cuotas_pagadas":2,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":8995000.0,"estado":"activo","alegra_id":"FE462"},
    {"n":20,"cliente":"Yorland Estid Berrocal Velasquez","cedula":"72435712","telefono":"3256789012","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF31VDB95376","motor":"BF3AT15C2622","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-04-07","fecha_entrega":"2026-04-10","fecha_cuota_1":"2026-04-15","cuotas_pagadas":2,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":8995000.0,"estado":"activo","alegra_id":"FE463"},
    {"n":21,"cliente":"Yeferson Daniel Benjumes Botero","cedula":"2136090","telefono":"3267890123","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF31VDB95371","motor":"BF3AT15C2633","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-04-08","fecha_entrega":"2026-04-10","fecha_cuota_1":"2026-04-15","cuotas_pagadas":2,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":8995000.0,"estado":"activo","alegra_id":"FE464"},
    {"n":22,"cliente":"Anthony David Duran Garcia","cedula":"8237995","telefono":"3278901234","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF31VDB95075","motor":"BF3AT15C2644","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-04-08","fecha_entrega":"2026-04-10","fecha_cuota_1":"2026-04-15","cuotas_pagadas":2,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":8995000.0,"estado":"activo","alegra_id":"FE465"},
    {"n":23,"cliente":"Elmer Antonio Rondon Hernandez","cedula":"31666938","telefono":"3289012345","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF31VDB95052","motor":"BF3AT15C2655","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-04-08","fecha_entrega":"2026-04-10","fecha_cuota_1":"2026-04-15","cuotas_pagadas":2,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":8995000.0,"estado":"activo","alegra_id":"FE466"},
    {"n":24,"cliente":"Jose altamiranda","cedula":"1063146896","telefono":"3004613796","tel_alt":"","modelo":"COMPARENDO","vin":"","motor":"","plan":"P39S","modalidad":"Semanal","cuota_valor":15000.0,"cuota_inicial":0.0,"fecha_factura":"2026-03-02","fecha_entrega":"2026-03-05","fecha_cuota_1":"2026-03-11","cuotas_pagadas":6,"cuotas_vencidas":0,"total_cuotas":39,"valor_total":585000.0,"saldo":495000.0,"estado":"activo","alegra_id":""},
    {"n":25,"cliente":"Ronaldo Carcamo","cedula":"1126257783","telefono":"3007878965","tel_alt":"","modelo":"COMPARENDO","vin":"","motor":"","plan":"P39S","modalidad":"Semanal","cuota_valor":15000.0,"cuota_inicial":0.0,"fecha_factura":"2026-03-02","fecha_entrega":"2026-03-05","fecha_cuota_1":"2026-03-11","cuotas_pagadas":3,"cuotas_vencidas":3,"total_cuotas":39,"valor_total":585000.0,"saldo":540000.0,"estado":"mora","alegra_id":""},
    {"n":26,"cliente":"Kedwyng Valladares","cedula":"7136824","telefono":"3167890123","tel_alt":"","modelo":"LICENCIA","vin":"","motor":"","plan":"P26S","modalidad":"Semanal","cuota_valor":25000.0,"cuota_inicial":0.0,"fecha_factura":"2026-03-19","fecha_entrega":"2025-03-25","fecha_cuota_1":"2026-04-01","cuotas_pagadas":4,"cuotas_vencidas":0,"total_cuotas":26,"valor_total":650000.0,"saldo":550000.0,"estado":"activo","alegra_id":""},
    {"n":27,"cliente":"Richard Jose Millan Grimont","cedula":"6145958","telefono":"3223456789","tel_alt":"","modelo":"SPORT 100","vin":"9FLT81000VDB62403","motor":"RF5AT18A5611","plan":"P52S","modalidad":"Semanal","cuota_valor":131000.0,"cuota_inicial":1160000.0,"fecha_factura":"2026-04-15","fecha_entrega":"2026-04-20","fecha_cuota_1":"2026-04-22","cuotas_pagadas":1,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":6812000.0,"saldo":6681000.0,"estado":"activo","alegra_id":"FE467"},
    {"n":28,"cliente":"Samir Andres Garcia Venegas","cedula":"1082969662","telefono":"3290123456","tel_alt":"","modelo":"SPORT 100","vin":"9FLT81000VDB62417","motor":"RF5AT18A5622","plan":"P52S","modalidad":"Semanal","cuota_valor":131000.0,"cuota_inicial":1160000.0,"fecha_factura":"2026-04-16","fecha_entrega":"2026-04-21","fecha_cuota_1":"2026-04-22","cuotas_pagadas":1,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":6812000.0,"saldo":6681000.0,"estado":"activo","alegra_id":"FE468"},
    {"n":29,"cliente":"Toribio Rodriguez Salcedo","cedula":"19594484","telefono":"3301234567","tel_alt":"","modelo":"SPORT 100","vin":"9FLT81001VDB62264","motor":"RF5AT18A5633","plan":"P52S","modalidad":"Semanal","cuota_valor":131000.0,"cuota_inicial":1160000.0,"fecha_factura":"2026-04-17","fecha_entrega":"2026-04-20","fecha_cuota_1":"2026-04-22","cuotas_pagadas":1,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":6812000.0,"saldo":6681000.0,"estado":"activo","alegra_id":"FE469"},
    {"n":30,"cliente":"Luis Alejandro Julio Romero","cedula":"1101879357","telefono":"3312345678","tel_alt":"","modelo":"SPORT 100","vin":"9FLT81003VDB62329","motor":"RF5AT18A5644","plan":"P52S","modalidad":"Semanal","cuota_valor":131000.0,"cuota_inicial":1160000.0,"fecha_factura":"2026-04-17","fecha_entrega":"2026-04-20","fecha_cuota_1":"2026-04-22","cuotas_pagadas":1,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":6812000.0,"saldo":6681000.0,"estado":"activo","alegra_id":"FE470"},
    {"n":31,"cliente":"Rafael Antonio Ssawk Baldovino","cedula":"1003077566","telefono":"3323456789","tel_alt":"","modelo":"SPORT 100","vin":"9FLT81006VDB62261","motor":"RF5AT18A5655","plan":"P52S","modalidad":"Semanal","cuota_valor":131000.0,"cuota_inicial":1160000.0,"fecha_factura":"2026-04-20","fecha_entrega":"2026-04-23","fecha_cuota_1":"2026-04-29","cuotas_pagadas":0,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":6812000.0,"saldo":6812000.0,"estado":"activo","alegra_id":"FE471"},
    {"n":32,"cliente":"Lina Fernanda Camacho Camargo","cedula":"1015443764","telefono":"3334567890","tel_alt":"","modelo":"SPORT 100","vin":"9FLT81001VDB62314","motor":"RF5AT18A5666","plan":"P52S","modalidad":"Semanal","cuota_valor":131000.0,"cuota_inicial":1160000.0,"fecha_factura":"2026-04-23","fecha_entrega":"2026-04-29","fecha_cuota_1":"2026-04-29","cuotas_pagadas":0,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":6812000.0,"saldo":6812000.0,"estado":"activo","alegra_id":"FE472"},
    {"n":33,"cliente":"GENESIS DANIELA VARGAS","cedula":"6849245","telefono":"3345678901","tel_alt":"","modelo":"SPORT 100","vin":"9FLT81004VDB62260","motor":"RF5AT18A5677","plan":"P52S","modalidad":"Semanal","cuota_valor":131000.0,"cuota_inicial":1160000.0,"fecha_factura":"2026-04-23","fecha_entrega":"2026-04-29","fecha_cuota_1":"2026-04-29","cuotas_pagadas":0,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":6812000.0,"saldo":6812000.0,"estado":"activo","alegra_id":"FE473"},
    {"n":34,"cliente":"ANTONI LEVIT RICO","cedula":"6998154","telefono":"3356789012","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF31VDD00259","motor":"BF3AT15C2700","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-04-27","fecha_entrega":"","fecha_cuota_1":"","cuotas_pagadas":0,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":9354800.0,"estado":"activo","alegra_id":"FE474"},
    {"n":35,"cliente":"JORGE SUAREZ","cedula":"1067163281","telefono":"3367890123","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF31VDD00407","motor":"BF3AT15C2711","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-04-27","fecha_entrega":"","fecha_cuota_1":"","cuotas_pagadas":0,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":9354800.0,"estado":"activo","alegra_id":"FE475"},
    {"n":36,"cliente":"DIEGO MOISES ROSARIO","cedula":"6226257","telefono":"3378901234","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF32VDD00285","motor":"BF3AT15C2722","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-04-27","fecha_entrega":"","fecha_cuota_1":"","cuotas_pagadas":0,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":9354800.0,"estado":"activo","alegra_id":"FE476"},
    {"n":37,"cliente":"MANUEL DAVID QUIROZ","cedula":"1103216616","telefono":"3389012345","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF33VDD00425","motor":"BF3AT15C2733","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-04-28","fecha_entrega":"","fecha_cuota_1":"","cuotas_pagadas":0,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":9354800.0,"estado":"activo","alegra_id":"FE477"},
    {"n":38,"cliente":"MANUEL DAVID QUIROZ","cedula":"1103216616","telefono":"3389012345","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF34VDD00434","motor":"BF3AT15C2744","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-04-28","fecha_entrega":"","fecha_cuota_1":"","cuotas_pagadas":0,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":9354800.0,"estado":"activo","alegra_id":"FE478"},
    {"n":39,"cliente":"MANUEL DAVID QUIROZ","cedula":"1103216616","telefono":"3389012345","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF35VDD00250","motor":"BF3AT15C2755","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-04-28","fecha_entrega":"","fecha_cuota_1":"","cuotas_pagadas":0,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":9354800.0,"estado":"activo","alegra_id":"FE479"},
    {"n":40,"cliente":"EDUAR ROJAS","cedula":"6554194","telefono":"3390123456","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF35VDD00426","motor":"BF3AT15C2766","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-04-28","fecha_entrega":"","fecha_cuota_1":"","cuotas_pagadas":0,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":9354800.0,"estado":"activo","alegra_id":"FE480"},
    {"n":41,"cliente":"LEONEL MEDRANO","cedula":"5222231","telefono":"3401234567","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF37VDD00427","motor":"BF3AT15C2777","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-04-28","fecha_entrega":"","fecha_cuota_1":"","cuotas_pagadas":0,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":9354800.0,"estado":"activo","alegra_id":"FE481"},
    {"n":42,"cliente":"ROBINSON RONDON","cedula":"4628305","telefono":"3412345678","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF39VDD00431","motor":"BF3AT15C2788","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-04-28","fecha_entrega":"","fecha_cuota_1":"","cuotas_pagadas":0,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":9354800.0,"estado":"activo","alegra_id":"FE482"},
    {"n":43,"cliente":"MARIMAR GARCIA","cedula":"5196362","telefono":"3423456789","tel_alt":"","modelo":"RAIDER 125","vin":"9FL25AF3XVDD00406","motor":"BF3AT15C2799","plan":"P52S","modalidad":"Semanal","cuota_valor":179900.0,"cuota_inicial":1460000.0,"fecha_factura":"2026-04-28","fecha_entrega":"","fecha_cuota_1":"","cuotas_pagadas":0,"cuotas_vencidas":0,"total_cuotas":52,"valor_total":9354800.0,"saldo":9354800.0,"estado":"activo","alegra_id":"FE483"},
]

# IMPORTANTE: Algunos telefonos del Excel pueden estar fuera del registro real.
# Andres confirmo que el Excel tiene los datos correctos. Si discrepan con Alegra,
# ajustar manualmente despues.


def _normalize_telefono(raw: str) -> str:
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if len(digits) == 10 and digits.startswith("3"):
        digits = "57" + digits
    return digits


def _construir_loanbook_doc(row: dict, ahora: datetime) -> dict:
    """Construye doc loanbook desde fila Excel, respetando schema."""
    es_rdx = row["modelo"] in CAPITAL_PLAN
    es_rodante = row["modelo"] in ("COMPARENDO", "LICENCIA")

    if es_rdx:
        producto = "RDX"
        subtipo = None
        capital_plan = CAPITAL_PLAN[row["modelo"]]
    elif es_rodante:
        producto = "RODANTE"
        subtipo = row["modelo"].lower()  # comparendo / licencia
        capital_plan = row["valor_total"]
    else:
        producto = "RDX"  # fallback
        subtipo = None
        capital_plan = row["valor_total"]

    monto_original = max(capital_plan - row["cuota_inicial"], row["valor_total"])

    doc = {
        # IDs
        "loanbook_id": f"LB-EXCEL-V1-{row['n']:03d}",
        "factura_alegra_id": row["alegra_id"] or None,

        # Producto
        "producto": producto,
        "subtipo_rodante": subtipo,
        "plan_codigo": row["plan"],
        "modalidad_pago": row["modalidad"].lower(),

        # Cliente
        "cliente_nombre": row["cliente"],
        "cliente_cedula": row["cedula"],
        "cliente_telefono": _normalize_telefono(row["telefono"]),

        # Terminos
        "monto_original": monto_original,
        "cuota_inicial": row["cuota_inicial"],
        "cuota_periodica": row["cuota_valor"],
        "total_cuotas": row["total_cuotas"],
        "fecha_factura": row["fecha_factura"],
        "fecha_entrega": row["fecha_entrega"] or None,
        "fecha_cuota_1": row["fecha_cuota_1"] or None,

        # Estado
        "estado_credito": (
            "saldado" if row["estado"] == "completado"
            else "mora" if row["estado"] == "mora"
            else "activo"
        ),

        # Metadata producto + import audit
        "metadata_producto": {
            "moto_modelo": row["modelo"],
            "moto_vin": row["vin"],
            "moto_motor": row["motor"],
            "moto_color": "",
            "moto_valor_origen": capital_plan,
            "excel_v1_import": {
                "fila_excel": row["n"],
                "cuotas_pagadas_historicas": row["cuotas_pagadas"],
                "cuotas_vencidas_historicas": row["cuotas_vencidas"],
                "valor_total_excel": row["valor_total"],
                "saldo_excel": row["saldo"],
                "estado_excel": row["estado"],
                "tel_alternativo": row["tel_alt"],
                "fuente": "Excel V1 importado 2026-04-28",
            },
        },

        # Auditoria
        "via": "import_excel_v1",
        "fecha_creacion": ahora,
        "fecha_actualizacion": ahora,
    }
    return doc


def _construir_crm_doc(row: dict, loanbook_id: str, ahora: datetime) -> dict:
    """Construye doc crm_clientes desde fila Excel."""
    phone = _normalize_telefono(row["telefono"])
    tags = []
    if row["estado"] == "mora":
        tags.append("mora")
    elif row["estado"] == "completado":
        tags.append("paz_y_salvo")
    else:
        tags.append("al_dia")

    return {
        "cedula": row["cedula"],
        "nombre": row["cliente"],
        "telefono": phone,
        "mercately_phone": phone,
        "tags": tags,
        "loanbook_ids": [loanbook_id],
        "gestiones": [],
        "fecha_creacion": ahora,
        "fecha_actualizacion": ahora,
        "via": "import_excel_v1",
    }


async def diagnosticar(db, dry_run: bool) -> dict:
    """Diagnostica que filas faltan y opcionalmente las crea."""
    ahora = datetime.now(timezone.utc)

    contador = {
        "total_excel": len(EXCEL_ROWS),
        "skip_ya_existe": 0,
        "creados_loanbook": 0,
        "creados_crm": 0,
        "errores": [],
    }

    print(f"\n{'='*80}")
    print(f"{'#':<4}{'Alegra':<8}{'Cliente':<35}{'VIN':<20}{'ESTADO':<20}")
    print(f"{'='*80}")

    for row in EXCEL_ROWS:
        # 1. Buscar loanbook existente
        existente = None
        if row["alegra_id"]:
            existente = await db.loanbook.find_one(
                {"factura_alegra_id": row["alegra_id"]}
            )
        if not existente and row["vin"]:
            existente = await db.loanbook.find_one(
                {"metadata_producto.moto_vin": row["vin"]}
            )

        if existente:
            contador["skip_ya_existe"] += 1
            estado = f"OK existe (lb={existente.get('loanbook_id', '?')[:18]})"
            print(f"{row['n']:<4}{row['alegra_id'] or '-':<8}{row['cliente'][:33]:<35}{row['vin'][:18]:<20}{estado:<20}")
            continue

        # 2. No existe — construir docs
        try:
            lb_doc = _construir_loanbook_doc(row, ahora)
            crm_doc = _construir_crm_doc(row, lb_doc["loanbook_id"], ahora)

            if not dry_run:
                # Insert loanbook
                await db.loanbook.insert_one(lb_doc)
                contador["creados_loanbook"] += 1

                # Upsert CRM cliente (no duplicar por cedula)
                cliente_existente = await db.crm_clientes.find_one(
                    {"cedula": row["cedula"]}
                )
                if not cliente_existente:
                    await db.crm_clientes.insert_one(crm_doc)
                    contador["creados_crm"] += 1
                else:
                    # Append loanbook_id si no estaba
                    await db.crm_clientes.update_one(
                        {"cedula": row["cedula"]},
                        {"$addToSet": {"loanbook_ids": lb_doc["loanbook_id"]},
                         "$set": {"fecha_actualizacion": ahora,
                                  "telefono": lb_doc["cliente_telefono"]}},
                    )

            estado = "DRY_RUN crear" if dry_run else "CREADO"
            print(f"{row['n']:<4}{row['alegra_id'] or '-':<8}{row['cliente'][:33]:<35}{row['vin'][:18]:<20}{estado:<20}")
        except Exception as exc:
            contador["errores"].append({"n": row["n"], "error": str(exc)})
            print(f"{row['n']:<4}ERROR — {exc}")

    return contador


async def marcar_entrega_jueves(db, dry_run: bool) -> dict:
    """Marca las 10 Raider 27-28abr para entrega 2026-04-30."""
    contador = {"actualizados": 0, "no_encontrados": []}

    print(f"\n{'='*80}")
    print(f"Marcando {len(ALEGRA_IDS_ENTREGA_JUEVES)} loanbooks para entrega {FECHA_ENTREGA_JUEVES}")
    print(f"{'='*80}")

    for alegra_id in sorted(ALEGRA_IDS_ENTREGA_JUEVES):
        lb = await db.loanbook.find_one({"factura_alegra_id": alegra_id})
        if not lb:
            contador["no_encontrados"].append(alegra_id)
            print(f"  {alegra_id} -> NO encontrado en loanbook")
            continue

        if not dry_run:
            await db.loanbook.update_one(
                {"factura_alegra_id": alegra_id},
                {"$set": {
                    "fecha_entrega_programada": FECHA_ENTREGA_JUEVES,
                    "estado_credito": "pendiente_entrega",
                    "fecha_actualizacion": datetime.now(timezone.utc),
                }},
            )
            contador["actualizados"] += 1
        modo = "DRY_RUN" if dry_run else "OK"
        print(f"  {alegra_id} -> {lb.get('cliente_nombre', '?')[:30]:<32} {modo}")

    return contador


async def main(args) -> None:
    mongo_url = os.environ.get("MONGO_URL", "")
    db_name = os.environ.get("DB_NAME", "")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL o DB_NAME no configurados en env")
        sys.exit(1)

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    try:
        if args.marcar_entrega_jueves:
            res = await marcar_entrega_jueves(db, dry_run=not args.ejecutar)
            print(f"\nRESUMEN entrega jueves:")
            print(f"  Actualizados: {res['actualizados']}")
            print(f"  No encontrados: {res['no_encontrados']}")
        else:
            res = await diagnosticar(db, dry_run=not args.ejecutar)
            print(f"\n{'='*80}")
            print(f"RESUMEN ({'DRY-RUN' if not args.ejecutar else 'EJECUCION REAL'}):")
            print(f"  Total filas Excel:        {res['total_excel']}")
            print(f"  Ya existen (skip):        {res['skip_ya_existe']}")
            print(f"  Loanbooks creados:        {res['creados_loanbook']}")
            print(f"  Clientes CRM creados:     {res['creados_crm']}")
            if res['errores']:
                print(f"  ERRORES ({len(res['errores'])}):")
                for e in res['errores']:
                    print(f"    fila {e['n']}: {e['error']}")
            print(f"{'='*80}")
            if not args.ejecutar:
                print("\nPara ejecutar real, correr con --ejecutar")
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="(default) no toca DB")
    parser.add_argument("--ejecutar", action="store_true", help="aplica cambios reales")
    parser.add_argument("--marcar-entrega-jueves", action="store_true",
                        help="solo marca las 10 Raider 27-28abr para entrega 2026-04-30")
    args = parser.parse_args()
    asyncio.run(main(args))
