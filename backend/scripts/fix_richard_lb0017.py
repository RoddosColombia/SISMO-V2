"""scripts/fix_richard_lb0017.py - Fix puntual LB-2026-0017 Richard Millan.

Problema: el Excel oficial tiene saldo_capital=7,800,000 mayor que monto_original=5,069,961.
Eso da saldo_intereses negativo (-2,730,039) que es matematicamente imposible.

Causa: Richard recibió descuento promocional. Se vendió a $6,529,961 (cuota_inicial
1,460,000 + 39 cuotas × 129,999 = 5,069,961). Pero capital_plan canónico Raider 125
es $7,800,000.

Fix: ajustar saldo_capital a 5,069,961 (= monto_original) y saldo_intereses a 0.

Uso:
    cd /opt/render/project/src/backend
    python3 scripts/fix_richard_lb0017.py --ejecutar
"""
import argparse, asyncio, os, sys
from datetime import datetime, timezone

_THIS = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_THIS)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from motor.motor_asyncio import AsyncIOMotorClient


async def main(args):
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ["DB_NAME"]]

    lb = await db.loanbook.find_one({"loanbook_id": "LB-2026-0017"})
    if not lb:
        print("ERROR: LB-2026-0017 no existe")
        return

    print(f"ANTES:")
    print(f"  cliente:           {lb.get('cliente_nombre') or (lb.get('cliente') or {}).get('nombre')}")
    print(f"  monto_original:    {lb.get('monto_original'):,}")
    print(f"  saldo_capital:     {lb.get('saldo_capital'):,}")
    print(f"  saldo_intereses:   {lb.get('saldo_intereses'):,}")
    print(f"  saldo_pendiente:   {lb.get('saldo_pendiente'):,}")
    print(f"  cuota_inicial:     {lb.get('cuota_inicial', 0):,}")

    # Para Richard: vendido con descuento. capital_plan=7.8M no aplica.
    monto_original = 5_069_961  # = total cuotas (sin cuota inicial)
    cuota_inicial = 1_460_000   # del Excel V1
    capital_real = monto_original  # capital efectivo = monto_original
    saldo_intereses = 0           # sin intereses adicionales

    update = {
        "saldo_capital":      capital_real,
        "saldo_intereses":    saldo_intereses,
        "saldo_pendiente":    monto_original,
        "monto_original":     monto_original,
        "valor_total":        monto_original,
        "capital_plan":       capital_real,
        "metadata_producto.descuento_promocional": 7_800_000 - capital_real,
        "updated_at":         datetime.now(timezone.utc).isoformat(),
        "fix_richard_lb0017": "2026-04-28: ajuste por descuento promocional",
    }

    print(f"\nDESPUES (DRY-RUN):")
    print(f"  saldo_capital:     {capital_real:,}")
    print(f"  saldo_intereses:   {saldo_intereses:,}")
    print(f"  saldo_pendiente:   {monto_original:,}")
    print(f"  capital_plan:      {capital_real:,}")
    print(f"  descuento:         {7_800_000 - capital_real:,}")

    if args.ejecutar:
        await db.loanbook.update_one(
            {"loanbook_id": "LB-2026-0017"},
            {"$set": update},
        )
        print(f"\n✓ Actualizado en MongoDB")
    else:
        print(f"\nPara ejecutar real, correr con --ejecutar")

    cli.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ejecutar", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args))
