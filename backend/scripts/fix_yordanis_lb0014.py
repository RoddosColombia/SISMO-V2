"""scripts/fix_yordanis_lb0014.py - Fix puntual: Yordanis pagó viernes pero
el sistema lo muestra en mora.

LB-2026-0014 Yordanis Valentin Blanco
- DPD actual en DB: 1 (Early Delinquency)
- Realidad: pagó el viernes 25-abr, está al día
- Causa: pago no se registró en el sistema (cobrador no usó el agente)

Fix: marca próxima cuota pendiente como pagada con fecha viernes 25-abr,
recalcula saldo_pendiente, dpd=0, estado=Current.

Uso:
    cd /opt/render/project/src/backend
    python3 scripts/fix_yordanis_lb0014.py            # dry-run
    python3 scripts/fix_yordanis_lb0014.py --ejecutar
"""
import argparse, asyncio, os, sys
from datetime import datetime, timezone, date

_THIS = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_THIS)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from motor.motor_asyncio import AsyncIOMotorClient

LOANBOOK_ID = "LB-2026-0014"
FECHA_PAGO = "2026-04-25"  # viernes de la semana pasada


async def main(args):
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ["DB_NAME"]]

    lb = await db.loanbook.find_one({"loanbook_id": LOANBOOK_ID})
    if not lb:
        print(f"ERROR: {LOANBOOK_ID} no existe")
        return

    cliente = lb.get("cliente_nombre") or (lb.get("cliente") or {}).get("nombre", "?")
    cuota_periodica = (lb.get("cuota_periodica") or lb.get("cuota_monto")
                       or (lb.get("plan") or {}).get("cuota_valor", 0))

    print(f"Cliente:               {cliente}")
    print(f"ANTES:")
    print(f"  estado:              {lb.get('estado')}")
    print(f"  dpd:                 {lb.get('dpd')}")
    print(f"  saldo_pendiente:     {lb.get('saldo_pendiente'):,}")
    print(f"  cuotas_pagadas:      {lb.get('cuotas_pagadas')}")
    print(f"  cuotas_vencidas:     {lb.get('cuotas_vencidas')}")
    print(f"  mora_acumulada_cop:  {lb.get('mora_acumulada_cop', 0):,}")

    # Buscar primera cuota en estado pendiente o vencida
    cuotas = lb.get("cuotas") or []
    cuota_a_pagar = None
    for c in cuotas:
        if c.get("estado") in ("pendiente", "vencida"):
            cuota_a_pagar = c
            break

    if cuota_a_pagar:
        # Si la cuota no tiene monto (bug data), usar cuota_periodica del doc raiz
        monto_cuota = cuota_a_pagar.get("monto") or cuota_periodica or 0
        print(f"\nCUOTA A MARCAR PAGADA:")
        print(f"  numero:    {cuota_a_pagar.get('numero')}")
        print(f"  fecha:     {cuota_a_pagar.get('fecha')}")
        print(f"  monto:     {monto_cuota:,}  {'(usado cuota_periodica)' if not cuota_a_pagar.get('monto') else ''}")

    nuevo_saldo_pendiente = max(0, lb.get("saldo_pendiente", 0) - cuota_periodica)
    nuevas_cuotas_pagadas = (lb.get("cuotas_pagadas", 0) or 0) + 1
    nuevas_cuotas_vencidas = max(0, (lb.get("cuotas_vencidas", 0) or 0) - 1)

    print(f"\nDESPUES:")
    print(f"  estado:              Current (al_dia)")
    print(f"  dpd:                 0")
    print(f"  saldo_pendiente:     {nuevo_saldo_pendiente:,}")
    print(f"  cuotas_pagadas:      {nuevas_cuotas_pagadas}")
    print(f"  cuotas_vencidas:     {nuevas_cuotas_vencidas}")

    if not args.ejecutar:
        print(f"\nPara ejecutar real, --ejecutar")
        cli.close()
        return

    # Update root fields + array element
    update_set = {
        "estado":              "Current",
        "estado_credito":      "activo",
        "dpd":                 0,
        "mora_acumulada_cop":  0,
        "saldo_pendiente":     nuevo_saldo_pendiente,
        "saldo_capital":       max(0, lb.get("saldo_capital", 0) - cuota_periodica),
        "cuotas_pagadas":      nuevas_cuotas_pagadas,
        "cuotas_vencidas":     nuevas_cuotas_vencidas,
        "fecha_ultimo_pago":   FECHA_PAGO,
        "updated_at":          datetime.now(timezone.utc).isoformat(),
        "fix_yordanis_lb0014": f"2026-04-28: pago {FECHA_PAGO} no registrado por cobrador",
    }
    await db.loanbook.update_one({"loanbook_id": LOANBOOK_ID}, {"$set": update_set})

    if cuota_a_pagar:
        await db.loanbook.update_one(
            {"loanbook_id": LOANBOOK_ID, "cuotas.numero": cuota_a_pagar["numero"]},
            {"$set": {
                "cuotas.$.estado":     "pagada",
                "cuotas.$.fecha_pago": FECHA_PAGO,
                "cuotas.$.metodo":     "manual_fix",
                "cuotas.$.referencia": "Fix retroactivo - pago no registrado a tiempo",
            }},
        )

    # Publish event para que CRM/Contador/CFO se enteren
    from core.events import publish_event
    await publish_event(
        db=db,
        event_type="pago.cuota.recibido",
        source="scripts.fix_yordanis_lb0014",
        datos={
            "loanbook_id":     LOANBOOK_ID,
            "cliente_cedula":  lb.get("cliente_cedula") or (lb.get("cliente") or {}).get("cedula"),
            "monto":           int(cuota_periodica),
            "monto_capital":   int(cuota_periodica),
            "monto_interes":   0,
            "monto_mora":      0,
            "fecha_pago":      FECHA_PAGO,
            "metodo":          "manual_fix",
            "via":             "script_correctivo",
        },
        alegra_id=None,
        accion_ejecutada=f"Fix retroactivo Yordanis pago {FECHA_PAGO}",
    )

    print(f"\n✓ {LOANBOOK_ID} actualizado + evento pago.cuota.recibido publicado")
    cli.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ejecutar", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args))
