# E2.5c — Refactor polling Mercately (estrategia phones activos)

## Resumen

El endpoint global `/whatsapp_conversations` de Mercately devuelve HTTP 500
("wrong number of arguments given 2, expected 0") — bug confirmado del lado
de Mercately. Pero el endpoint por-customer **SI funciona** y acepta phone
directamente en path.

Refactor del poller para usar la estrategia que SI funciona:
- Identifica phones activos en MongoDB (loanbook + crm + radar_alertas 24h)
- Para cada phone: GET /customers/{phone}/whatsapp_conversations
- Filtra direction=inbound y created_time > last_seen
- Procesa: append gestion CRM + publish event + audit

## Cambios

### `backend/services/mercately/client.py`
- `get_customer_by_phone`: cambio de query-style a path-style `/customers/{phone}`
  (el query-style devolvia los 82k customers sin filtrar)
- `list_whatsapp_conversations`: marcado DEPRECATED (endpoint global da 500)
- `get_whatsapp_conversations_by_phone`: helper nuevo, wrapper de
  `get_customer_messages` con phone normalizado

### `backend/services/mercately/inbound_poller.py`
- Reescritura completa con estrategia phones activos
- `_obtener_phones_activos`: 3 fuentes (loanbook, crm tags, radar_alertas)
- `poll_once`: itera phones (max 50/ciclo) y llama endpoint por-phone
- Backoff exponencial mantenido
- Estado per-phone en `mercately_polling_state` con `_id="phone:573..."`

### `backend/tests/test_mercately_inbound_poller.py`
- Reescritos para nueva firma (8 tests, todos verdes)
- Nuevo cursor mock `_Cursor` que soporta `.limit()` y `__aiter__`

## Tests

```
21 verdes en mercately + poller
81 verdes total en mercately/webhook/radar/rog4/notif (sin regresiones)
```

## Comandos commit + push (PowerShell)

```powershell
cd C:\Users\AndresSanJuan\roddos-workspace\SISMO-V2

if (Test-Path .git\index.lock) { Remove-Item .git\index.lock -Force }

git add backend/services/mercately/client.py
git add backend/services/mercately/inbound_poller.py
git add backend/tests/test_mercately_inbound_poller.py
git add .planning/E2_5c_COMMIT_INSTRUCTIONS.md

git commit -m "feat(E2.5c): refactor polling Mercately con estrategia phones activos

Diagnostico 2026-04-28 confirmo bug Mercately en endpoint global
/whatsapp_conversations (HTTP 500 'wrong number of arguments').
El endpoint por-customer /customers/{phone}/whatsapp_conversations SI
funciona y acepta phone directamente en path. Refactor del poller para
usar esa estrategia.

Cambios principales:

services/mercately/client.py:
- get_customer_by_phone usa path-style /customers/{phone} (query-style
  devolvia 82k customers sin filtrar)
- list_whatsapp_conversations marcado DEPRECATED (endpoint global roto)
- get_whatsapp_conversations_by_phone: helper nuevo con phone normalizado
- Auth confirmado: header api-key (lowercase)

services/mercately/inbound_poller.py:
- Reescritura completa con estrategia phones activos
- _obtener_phones_activos: 3 fuentes (loanbook DPD>=0/cuota proxima 7d,
  crm tags radar/mora, radar_alertas ultimas 24h)
- poll_once: itera max 50 phones por ciclo, llama endpoint por-phone
- Estado per-phone en mercately_polling_state (_id='phone:573...')
- Backoff exponencial mantenido (16x cuando todos fallan)

tests/test_mercately_inbound_poller.py:
- Reescritos para nueva firma (13 tests, todos verdes)
- Helper _Cursor para mockear find().limit().__aiter__()

Tests: 81 verdes en mercately/webhook/radar/rog4/notif sin regresiones.
Latencia inbound: max 60s (config MERCATELY_POLL_INTERVAL_S).
Phones por ciclo: max 50 (config MERCATELY_POLL_MAX_PHONES).
DPD lookahead: 7 dias (config MERCATELY_POLL_DPD_LOOKAHEAD)."

git push origin main
```

## Verificacion post-deploy en Render

Cuando termine el redeploy (1-2 min):

```bash
# 1. Health endpoint sigue OK
curl https://sismo.roddos.com/api/webhooks/mercately/health

# 2. En Render Logs, ya NO debe aparecer:
#    "polling list conversations falló: HTTP 500"
# En cambio, deberia aparecer cada 60s aprox:
#    "Mercately inbound poller arrancado (interval=60s)"
# Y si hay phones activos y mensajes:
#    "polling inbound phone=573... cedula=... msg=..."

# 3. Para probar end-to-end: enviar WhatsApp manual desde tu numero personal
#    a tu WhatsApp Business. Esperar max 60s. En logs:
#    "polling inbound phone=573102511280 cedula=... msg='tu mensaje'"
# En MongoDB:
#    db.mercately_inbound_audit.find().sort({fecha:-1}).limit(1)
#    db.crm_clientes.find({telefono: /3102511280$/}, {gestiones: 1})
```

## Configuracion env vars (opcional)

| Var | Default | Descripcion |
|-----|---------|-------------|
| `MERCATELY_POLL_INTERVAL_S` | 60 | Segundos entre ciclos |
| `MERCATELY_POLL_MAX_PHONES` | 50 | Max phones por ciclo |
| `MERCATELY_POLL_DPD_LOOKAHEAD` | 7 | Dias hacia adelante para "cuota proxima" |
