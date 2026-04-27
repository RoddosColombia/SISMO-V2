"""
scripts/generar_api_key.py — Genera una API key read-only para integraciones externas.

Uso local:
    cd backend
    python scripts/generar_api_key.py

La key generada debe:
1. Copiarse como variable de entorno en el sistema cliente (ej: ARGOS → SISMO_API_KEY)
2. Registrarse en MongoDB producción via Render Shell (ver instrucciones impresas)
"""

import secrets

KEY = "sk-sismo-" + secrets.token_urlsafe(32)

print(f"\n{'='*60}")
print(f"API Key generada:")
print(f"  {KEY}")
print(f"{'='*60}")
print()
print("PASO 1 — Agregar en el sistema cliente:")
print(f"  SISMO_API_KEY={KEY}")
print()
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
    print('API key registrada en MongoDB:', KEY[:20], '...')

asyncio.run(run())
"
""")
print("PASO 3 — Verificar en ARGOS:")
print("  curl -H 'X-API-Key: <key>' https://sismo-backend-40ca.onrender.com/api/integraciones/cartera/resumen")
print()
