# E2.5b — Comandos para commit + push (correr desde PowerShell)

```powershell
cd C:\Users\AndresSanJuan\roddos-workspace\SISMO-V2

# 1. Eliminar lock colgado (si existe)
if (Test-Path .git\index.lock) { Remove-Item .git\index.lock -Force }

# 2. Add solo archivos del polling Mercately
git add backend/services/mercately/client.py
git add backend/services/mercately/inbound_poller.py
git add backend/core/database.py
git add backend/tests/test_mercately_inbound_poller.py
git add .planning/E2_RADAR_MERCATELY.md
git add .planning/E2_5b_COMMIT_INSTRUCTIONS.md

# 3. Commit
git commit -m "feat(E2.5b): Mercately inbound polling (Mercately no expone webhooks)

Verificado en mercately.redocly.app/apis y centro de soporte: la API REST
de Mercately NO expone webhooks. El flujo bidireccional se cierra via
polling cada 60s.

Cambios:
- services/mercately/client.py: +list_whatsapp_conversations, +get_customer_messages
- services/mercately/inbound_poller.py: nuevo, scheduler 2-niveles
  - 1 GET global cada 60s a /whatsapp_conversations
  - Solo profundiza en conversaciones con last_interaction nuevo
  - Persiste estado en mercately_polling_state (global + per-customer)
  - Idempotente: no reprocesa msg_id ya visto
  - Audit en mercately_inbound_audit
  - Replica 1:1 la logica del webhook handler
- core/database.py: +get_db_sync helper, +scheduler en lifespan
- tests/test_mercately_inbound_poller.py: 9 tests (helpers, estado, ciclos)

Tests: 1214 verdes (+9 nuevos en E2.5b).
Latencia inbound: max 60s (configurable con MERCATELY_POLL_INTERVAL_S).

Pendiente humano: nada extra, solo necesita MERCATELY_API_KEY ya configurada.
El endpoint /api/webhooks/mercately/inbound queda disponible por compatibilidad
o para integracion futura con Zapier/n8n si Mercately publica webhooks."

# 4. Push
git push origin main
```

## Verificación post-deploy en Render

Una vez deployed (1-2 min):

```powershell
# 1. Health endpoint sigue OK
curl https://sismo.roddos.com/api/webhooks/mercately/health

# 2. Logs de Render — buscar arranque del poller
# En dashboard: Logs -> filtrar por "Mercately inbound poller"
# Esperado:
#   "Mercately inbound poller started (interval=60s)"
#   "Mercately inbound poller arrancado (interval=60s)"

# 3. Probar flujo end-to-end
# - Andres envia un WhatsApp manual desde su numero personal al WhatsApp Business
# - Esperar max 60s
# - En Render logs aparece:
#   "polling inbound — customer=NNN phone=573... cedula=... msg='...'"
# - En MongoDB Atlas: db.mercately_inbound_audit.find().sort({fecha:-1}).limit(1)
#   debe mostrar el mensaje recibido
```

## Si algo falla

1. **Poller no arranca:** Logs muestran "Mercately inbound poller failed to start" -> revisar import path.
2. **No detecta mensajes:** Verificar `MERCATELY_API_KEY` en Render. Verificar que existe la conversacion en Mercately con `last_interaction` reciente.
3. **Procesa pero no aparece en CRM:** El cliente quiza no esta sincronizado con `mercately_phone`. El audit log lo registra igual con `cliente_crm_encontrado: false`.
4. **Rate limit Mercately:** Aumentar interval a 120s con env var `MERCATELY_POLL_INTERVAL_S=120`.
