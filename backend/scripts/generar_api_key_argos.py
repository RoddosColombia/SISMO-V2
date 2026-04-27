"""
scripts/generar_api_key_argos.py — Genera una API key para ARGOS.

Uso local (solo genera la key, no toca MongoDB):
    cd backend
    python scripts/generar_api_key_argos.py

Después registrarla en MongoDB producción via Render Shell:
    ver PASO 2 impreso al final.
"""

import secrets

KEY = "sk-sismo-" + secrets.token_urlsafe(32)

print(f"\n{'='*60}")
print(f"API Key ARGOS generada:")
print(f"  {KEY}")
print(f"{'='*60}\n")

print("PASO 1 — Copiar en el entorno de ARGOS:")
print(f"  SISMO_API_KEY={KEY}\n")

print("PASO 2 — Registrar en MongoDB producción (Render Shell):")
print(f"""
python3 -c "
import os, asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timezone

KEY = '{KEY}'

async def run():
    db = AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
    await db.api_keys.insert_one({{
        'key': KEY,
        'name': 'ARGOS Integration',
        'scope': 'read_only',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'last_used_at': None,
        'active': True,
    }})
    print('OK — API key registrada:', KEY[:24], '...')

asyncio.run(run())
"
""")

print("PASO 3 — Verificar:")
print(f"  curl -H 'X-API-Key: {KEY[:24]}...' \\")
print("       https://sismo-backend-40ca.onrender.com/api/integraciones/repuestos\n")
