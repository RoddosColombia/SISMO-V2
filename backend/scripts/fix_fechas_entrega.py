"""
scripts/fix_fechas_entrega.py — Corrige fechas de entrega y regenera cronogramas.

Origen: Excel V1 (importación original). Las 23 fechas reales de entrega
difieren de las que quedaron en MongoDB, lo que causa que la Regla del
Miércoles calcule fechas incorrectas para toda la tabla de cuotas.

Proceso idempotente:
  1. Para cada loanbook en FECHAS_CORRECTAS verifica si la fecha ya es correcta.
  2. Si ya es correcta → SKIP.
  3. Si difiere → actualiza fecha_entrega + recalcula primer_pago + regenera cuotas.
  4. Solo escribe si --apply está en argv.

Uso:
  python -m scripts.fix_fechas_entrega            # dry-run (ver qué cambiaría)
  python -m scripts.fix_fechas_entrega --apply    # aplicar cambios
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta

# ─────────────────────────────────────────────────────────────────────────────
# TABLA DE VERDAD — extraída de Excel V1
# Formato: { "loanbook_id": "YYYY-MM-DD" }
# ─────────────────────────────────────────────────────────────────────────────
FECHAS_CORRECTAS: dict[str, str] = {
    # Fuente: Excel V1 — fechas reales de entrega confirmadas
    "LB-2026-0001": "2026-03-05",
    "LB-2026-0002": "2026-03-05",
    "LB-2026-0003": "2026-03-05",
    "LB-2026-0004": "2026-03-05",
    "LB-2026-0005": "2026-03-05",
    "LB-2026-0006": "2026-03-10",
    "LB-2026-0007": "2026-03-24",
    "LB-2026-0008": "2026-03-24",
    "LB-2026-0009": "2026-03-10",
    "LB-2026-0010": "2026-03-19",
    "LB-2026-0011": "2026-03-25",
    "LB-2026-0012": "2026-03-21",
    # LB-2026-0013 no está en Excel V1 — omitido intencionalmente
    "LB-2026-0014": "2026-03-27",
    "LB-2026-0015": "2026-03-27",
    "LB-2026-0016": "2026-03-27",
    "LB-2026-0017": "2026-03-28",
    "LB-2026-0018": "2026-03-28",
    "LB-2026-0019": "2026-04-08",
    "LB-2026-0020": "2026-04-10",
    "LB-2026-0021": "2026-04-10",
    "LB-2026-0022": "2026-04-10",
    "LB-2026-0023": "2026-04-10",
}


def _regenerar_cuotas(
    lb: dict,
    fecha_entrega: date,
    primer_pago: date,
) -> list[dict]:
    """Re-genera el cronograma de cuotas respetando los pagos ya realizados."""
    from services.loanbook.reglas_negocio import DIAS_ENTRE_CUOTAS

    modalidad = lb.get("modalidad") or lb.get("modalidad_pago") or "semanal"
    dias = DIAS_ENTRE_CUOTAS.get(modalidad, 7)
    cuotas_actuales: list[dict] = lb.get("cuotas") or []
    num_cuotas = len(cuotas_actuales)

    nuevas_cuotas: list[dict] = []
    for i, cuota in enumerate(cuotas_actuales):
        fecha_nueva = primer_pago + timedelta(days=dias * i)
        cuota_nueva = {
            **cuota,
            "fecha_programada": fecha_nueva.isoformat(),
        }
        # Si la cuota no tiene fecha_programada, la ponemos. Si ya está pagada
        # respetamos los campos de pago existentes (fecha_pago, monto_pagado, etc.)
        nuevas_cuotas.append(cuota_nueva)

    return nuevas_cuotas


async def _main(apply: bool) -> None:
    import os
    import sys

    # Agregar backend/ al path para imports
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from motor.motor_asyncio import AsyncIOMotorClient
    from core.datetime_utils import now_iso_bogota
    from services.loanbook.reglas_negocio import primer_miercoles_cobro

    mongo_url = os.environ.get("MONGO_URL") or os.environ.get("MONGODB_URL")
    db_name = os.environ.get("DB_NAME") or os.environ.get("MONGODB_DB", "sismo_v2")
    if not mongo_url:
        print("ERROR: Variable de entorno MONGO_URL no definida.")
        print("  Ejecutar con: MONGO_URL='mongodb+srv://...' DB_NAME='sismo_v2' python -m scripts.fix_fechas_entrega")
        sys.exit(1)
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    mode = "APPLY" if apply else "DRY-RUN"
    print(f"\n{'='*60}")
    print(f"fix_fechas_entrega — modo {mode}")
    print(f"{'='*60}")

    skip = corrected = errors = 0

    for lb_id, fecha_str in FECHAS_CORRECTAS.items():
        fecha_correcta = date.fromisoformat(fecha_str)

        lb = await db.loanbook.find_one(
            {"$or": [{"loanbook_id": lb_id}, {"loanbook_codigo": lb_id}]}
        )
        if not lb:
            print(f"  SKIP  {lb_id} — no encontrado en MongoDB")
            skip += 1
            continue

        # Leer fecha_entrega actual (puede ser string o date)
        fecha_actual_raw = lb.get("fecha_entrega")
        if isinstance(fecha_actual_raw, str):
            try:
                fecha_actual = date.fromisoformat(fecha_actual_raw[:10])
            except ValueError:
                fecha_actual = None
        elif hasattr(fecha_actual_raw, "date"):
            # datetime object
            fecha_actual = fecha_actual_raw.date()
        elif isinstance(fecha_actual_raw, date):
            fecha_actual = fecha_actual_raw
        else:
            fecha_actual = None

        if fecha_actual == fecha_correcta:
            print(f"  OK    {lb_id} — fecha ya correcta ({fecha_correcta})")
            skip += 1
            continue

        primer_pago = primer_miercoles_cobro(fecha_correcta)
        nuevas_cuotas = _regenerar_cuotas(lb, fecha_correcta, primer_pago)

        print(
            f"  FIX   {lb_id} — "
            f"entrega: {fecha_actual} → {fecha_correcta} | "
            f"primer_pago: {primer_pago} | "
            f"cuotas: {len(nuevas_cuotas)}"
        )

        if apply:
            try:
                await db.loanbook.update_one(
                    {"_id": lb["_id"]},
                    {
                        "$set": {
                            "fecha_entrega": fecha_correcta.isoformat(),
                            "fecha_primer_pago": primer_pago.isoformat(),
                            "cuotas": nuevas_cuotas,
                            "updated_at": now_iso_bogota(),
                            "fix_fechas_aplicado": True,
                        }
                    },
                )
                corrected += 1
            except Exception as exc:
                print(f"  ERROR {lb_id} — {exc}")
                errors += 1
        else:
            corrected += 1  # contamos como "corregiría"

    client.close()

    print(f"\nResumen: {corrected} {'corregidos' if apply else 'a corregir'} | {skip} OK/no encontrados | {errors} errores")
    if not apply and corrected:
        print("  → Volver a correr con --apply para aplicar los cambios.")


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    asyncio.run(_main(apply))
