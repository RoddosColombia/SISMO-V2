"""
scripts/validar_reglas_produccion.py — Validación de reglas de negocio vs producción.

Lee TODOS los loanbooks de MongoDB y los compara contra PLAN_CUOTAS.
Produce un reporte en consola antes de ejecutar cualquier reparación masiva.

REGLA: NO ejecutar /reparar-todos hasta que Andrés confirme que los números
del Excel son correctos. Este script es el paso previo de verificación.

Uso:
    cd backend
    python scripts/validar_reglas_produccion.py [--fix-dry-run]

    --fix-dry-run   Además del reporte, muestra qué cambiaría una reparación
                    (sin modificar nada en la DB)

Requiere:
    - Variable MONGO_URL en .env
    - Variables opcionales: DB_NAME (default: sismo-prod)
"""

from __future__ import annotations

import asyncio
import sys
import os
from datetime import date

# Agregar el directorio raíz al path para importar los módulos del backend
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import motor.motor_asyncio

from services.loanbook.reglas_negocio import PLAN_CUOTAS, get_num_cuotas, get_valor_total
from services.loanbook.auditor import auditar_loanbooks
from services.loanbook.reparador import reparar_loanbook

# ─────────────────────── Config ───────────────────────────────────────────────

MONGO_URL = os.getenv("MONGO_URL", "")
DB_NAME   = os.getenv("DB_NAME", "sismo-prod")

if not MONGO_URL:
    print("❌ ERROR: MONGO_URL no está definida. Configura tu .env antes de continuar.")
    sys.exit(1)


# ─────────────────────── Helpers de formato ───────────────────────────────────

def _cop(n: int | float) -> str:
    return f"${n:,.0f}"

def _pct(ok: int, total: int) -> str:
    if total == 0: return "0%"
    return f"{ok/total*100:.1f}%"

def _sep(char="─", width=70) -> None:
    print(char * width)


# ─────────────────────── Validación principal ─────────────────────────────────

async def validar(fix_dry_run: bool = False) -> None:
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
    db     = client[DB_NAME]

    print()
    _sep("═")
    print(f"  VALIDACIÓN DE REGLAS DE NEGOCIO vs PRODUCCIÓN")
    print(f"  DB: {DB_NAME}  |  Fecha: {date.today().isoformat()}")
    _sep("═")

    # ── Cargar todos los loanbooks ────────────────────────────────────────────
    docs = await db.loanbook.find().to_list(length=5000)
    loanbooks = [{k: v for k, v in doc.items() if k != "_id"} for doc in docs]
    total = len(loanbooks)
    print(f"\n  Loanbooks en producción: {total}")

    # ── TABLA PLAN_CUOTAS vigente ─────────────────────────────────────────────
    print()
    _sep()
    print("  TABLA FIJA PLAN_CUOTAS (contrato de negocio)")
    _sep()
    print(f"  {'Plan':<8} {'Semanal':>10} {'Quincenal':>12} {'Mensual':>10}")
    _sep("-", 44)
    for plan, mods in PLAN_CUOTAS.items():
        sem = str(mods.get("semanal", "—"))
        qui = str(mods.get("quincenal") or "—")
        men = str(mods.get("mensual") or "—")
        print(f"  {plan:<8} {sem:>10} {qui:>12} {men:>10}")
    print()
    print("  REGLA: P39S quincenal=20 (no 18). P52S quincenal=26 (no 24).")

    # ── Auditoría completa ────────────────────────────────────────────────────
    audit = auditar_loanbooks(loanbooks)
    resumen = audit["resumen"]
    casos   = audit["casos"]

    print()
    _sep()
    print("  RESUMEN DE INCONSISTENCIAS DETECTADAS")
    _sep()
    print(f"  valor_total incorrecto         : {resumen['valor_total_incorrecto']:>4}")
    print(f"  num_cuotas incorrecto           : {resumen['total_cuotas_incorrecto_segun_plan']:>4}")
    print(f"  cuotas futuras pagadas (seed)   : {resumen['cuotas_pagadas_con_fecha_imposible']:>4}")
    print(f"  combinación no configurada      : {resumen['combinacion_no_configurada']:>4}")
    print(f"  cuotas con fecha_pago futura    : {resumen['cuotas_con_fecha_pago_futura']:>4}")

    total_issues = sum(resumen.values())
    print()
    if total_issues == 0:
        print("  ✅ Todo correcto. Producción está alineada con PLAN_CUOTAS.")
    else:
        print(f"  ⚠️  {total_issues} inconsistencias detectadas.")

    # ── Detalle num_cuotas incorrecto ─────────────────────────────────────────
    if casos["total_cuotas_incorrecto_segun_plan"]:
        print()
        _sep()
        print("  DETALLE — num_cuotas incorrecto según PLAN_CUOTAS")
        _sep()
        print(f"  {'ID':<16} {'Cliente':<22} {'Plan':<6} {'Modal':<11} {'DB':>6} {'Tabla':>7} {'Δ':>5}")
        _sep("-", 70)
        for c in casos["total_cuotas_incorrecto_segun_plan"]:
            delta = (c['total_cuotas_muestra'] or 0) - (c['total_cuotas_correcto'] or 0)
            print(
                f"  {c['loanbook_id']:<16} {c['cliente'][:21]:<22} "
                f"{c['plan_codigo']:<6} {c['modalidad']:<11} "
                f"{c['total_cuotas_muestra']:>6} {c['total_cuotas_correcto']:>7} "
                f"{delta:>+5}"
            )

    # ── Detalle valor_total incorrecto ────────────────────────────────────────
    if casos["valor_total_incorrecto"]:
        print()
        _sep()
        print("  DETALLE — valor_total incorrecto")
        _sep()
        print(f"  {'ID':<16} {'Cliente':<22} {'DB':>14} {'Tabla':>14} {'Δ':>12}")
        _sep("-", 70)
        for c in casos["valor_total_incorrecto"]:
            print(
                f"  {c['loanbook_id']:<16} {c['cliente'][:21]:<22} "
                f"{_cop(c['muestra']):>14} {_cop(c['deberia_ser']):>14} "
                f"{_cop(c['diferencia']):>12}"
            )

    # ── Detalle cuotas futuras pagadas ────────────────────────────────────────
    if casos["cuotas_pagadas_fecha_imposible"]:
        print()
        _sep()
        print("  DETALLE — cuotas futuras marcadas pagadas (seed corrupto)")
        _sep()
        for lb in casos["cuotas_pagadas_fecha_imposible"]:
            print(f"  {lb['loanbook_id']} — {lb['cliente']}:")
            for c in lb["cuotas"]:
                ref = "con_ref" if c.get("tiene_referencia") else "sin_ref"
                print(f"    cuota #{c['numero']:>3}  fecha={c['fecha']}  {ref}")

    # ── Combinaciones no configuradas ─────────────────────────────────────────
    if casos["combinacion_no_configurada"]:
        print()
        _sep()
        print("  DETALLE — combinación plan×modalidad no configurada en PLAN_CUOTAS")
        _sep()
        for c in casos["combinacion_no_configurada"]:
            print(f"  {c['loanbook_id']}  {c['plan_codigo']}×{c['modalidad']} → {c['motivo']}")

    # ── Dry-run de reparación ─────────────────────────────────────────────────
    if fix_dry_run:
        print()
        _sep("═")
        print("  DRY-RUN — Qué cambiaría una reparación masiva (sin tocar la DB)")
        _sep("═")

        lbs_con_problemas = 0
        for lb in loanbooks:
            resultado = reparar_loanbook(lb, dry_run=True)
            if resultado["tiene_problemas"]:
                lbs_con_problemas += 1
                print(f"\n  {lb.get('loanbook_id')} — {lb.get('cliente', {}).get('nombre', '?')}")
                for r in resultado["reparaciones"]:
                    tipo = r.get("tipo", "?")
                    if tipo == "num_cuotas_corregido":
                        print(f"    num_cuotas: {r['valor_anterior']} → {r['valor_nuevo']}")
                    elif tipo == "valor_total_corregido":
                        print(f"    valor_total: {_cop(r['valor_anterior'])} → {_cop(r['valor_nuevo'])}")
                    elif tipo == "cuota_seed_revertida":
                        print(f"    cuota #{r['cuota_numero']} fecha={r['fecha']}: pagada → pendiente (seed)")
                    elif tipo == "cuota_fecha_pago_futura_revertida":
                        print(f"    cuota #{r['cuota_numero']} fecha_pago={r['fecha_pago_registrada']}: revertida (fecha futura)")
                for m in resultado.get("requieren_revision_manual", []):
                    print(f"    ⚠️  cuota #{m['cuota_numero']} requiere revisión manual: {m['razon']}")

        print()
        if lbs_con_problemas == 0:
            print("  ✅ No hay nada que reparar.")
        else:
            print(f"  {lbs_con_problemas} loanbooks serían modificados.")
            print()
            print("  Para aplicar: POST /api/loanbook/reparar-todos?dry_run=false")
            print("  ⚠️  Confirmar con Andrés ANTES de ejecutar.")

    print()
    _sep("═")
    print()
    client.close()


# ─────────────────────── Entrypoint ───────────────────────────────────────────

if __name__ == "__main__":
    fix_dry_run = "--fix-dry-run" in sys.argv
    asyncio.run(validar(fix_dry_run=fix_dry_run))
