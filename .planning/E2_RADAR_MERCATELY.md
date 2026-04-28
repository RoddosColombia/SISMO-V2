# Ejecución 2 — RADAR completo + Mercately bidireccional

**Fecha:** 28-abril-2026
**Sprint:** S2
**Brechas cerradas:** #5 (Mercately solo manda) y #6 (RADAR sin tools)
**Tests:** 1153 verdes (+26 nuevos en E2)

---

## Lo que quedó construido

### 1. Mercately client ampliado — `services/mercately/client.py`

4 métodos nuevos sobre el `MercatelyClient` existente:

| Método | Propósito |
|---|---|
| `get_customer_by_phone(phone)` | R-MERCATELY: SIEMPRE consultar antes de POST/PATCH. Devuelve `{found, customer}`. |
| `create_customer(phone, first_name, last_name, email, id_number, tags)` | POST /customers — crea contacto. |
| `update_customer_tags(phone, add_tags, remove_tags)` | PATCH idempotente para mover tags `al_dia`/`mora`/`paz_y_salvo`. |
| `send_text(phone, message)` | Mensaje de texto libre dentro de ventana 24h post-respuesta cliente. |

Helper `get_mercately_client()` singleton para usar desde handlers sin reinstanciar.

### 2. Webhook entrante `POST /api/webhooks/mercately/inbound`

`routers/webhooks.py` — recibe respuestas WhatsApp de clientes a mensajes que SISMO envió:

- Validación HMAC `MERCATELY_WEBHOOK_SECRET` (modo dev sin firma si vacío)
- Busca cliente por `mercately_phone == phone_number`
- Append a `crm_clientes.gestiones[]` con `tipo='whatsapp_inbound'`
- Publica `cliente.respondio.whatsapp` para que RADAR decida siguiente acción
- Endpoint `GET /api/webhooks/mercately/health` para validar conectividad

> **NOTA 2026-04-28 (E2.5b):** Mercately **no expone webhooks** (verificado en
> `https://mercately.redocly.app/apis` y centro de soporte). El endpoint queda
> disponible por si Mercately publica webhooks en el futuro o para integración
> con un middleware (Zapier/n8n). El flujo bidireccional real corre vía
> **polling** — ver sección 5b.

### 5b. Inbound poller — `services/mercately/inbound_poller.py` (E2.5b)

Polling de 2 niveles cada 60 s que **simula el webhook que no existe**:

1. `GET /retailers/api/v1/whatsapp_conversations?page=1&results_per_page=100`
   → lista global con `last_interaction` por conversación.
2. Filtra conversaciones con `last_interaction > last_global_check`.
3. Para cada candidata: `GET /customers/{id}/whatsapp_conversations`
   → mensajes con `direction`, `content_text`, `created_time`.
4. Por cada mensaje `direction=inbound` con `created_time > last_seen`:
   - Append `crm_clientes.gestiones[]` (igual que el webhook).
   - Publica `cliente.respondio.whatsapp` con `via=polling`.
   - Audit en `mercately_inbound_audit`.
5. Persiste estado en `mercately_polling_state`:
   - `_id="global"` con `last_global_check_iso`
   - `_id="customer:{id}"` con `last_seen_msg_id` y `last_seen_iso`

Ventajas vs polling ingenuo (N queries por cliente):
- 1 sola request global por ciclo.
- Solo profundiza en conversaciones con actividad nueva.
- Idempotente — si SISMO se reinicia, no reprocesa mensajes ya vistos.
- Latencia inbound: máx 60 s (configurable con `MERCATELY_POLL_INTERVAL_S`).

Wiring en `core/database.py` lifespan:
```python
from services.mercately.inbound_poller import run_inbound_poller_loop
interval_s = int(os.getenv("MERCATELY_POLL_INTERVAL_S", "60"))
_mercately_inbound_poller_task = asyncio.create_task(
    run_inbound_poller_loop(get_db_sync, interval_s=interval_s)
)
```

### 3. Agente RADAR — 5 tools

`agents/radar/tools.py`:

| Tool | Tipo | Función |
|---|---|---|
| `generar_cola_cobranza` | read-only | Cola priorizada por DPD × score, excluye contactados hoy (Ley 2300) |
| `registrar_gestion` | write | Append timeline CRM (llamada, WhatsApp manual, nota) |
| `registrar_promesa_pago` | write | PTP con fecha futura, monto, canal |
| `enviar_whatsapp_template` | write | T1-T5 con validaciones Ley 2300 (horario + max 1/día) |
| `consultar_estado_cliente` | read-only | Vista 360°: loanbooks + CRM + promesas + última gestión |

### 4. RadarToolDispatcher — `agents/radar/handlers/dispatcher.py`

- Patrón idéntico al ToolDispatcher del Contador
- ROG-4b puro: solo escribe en `crm_clientes`, `radar_alertas`, `roddos_events`
- Nunca toca Alegra ni loanbook
- Ley 2300 hard-coded: ventana L-V 7AM-7PM, Sáb 8AM-3PM, max 1 contacto/día por cédula
- Logging completo + `tool.error` events en excepciones (igual que Contador)

### 5. Schedulers martes + jueves

`agents/radar/alertas.py` extendido con 2 nuevas funciones:

- `enviar_recordatorios_martes(db)` + `run_radar_scheduler_martes(db)` — **martes 09:00 AM Bogotá**
  - Envía template T1 a clientes con cuota miércoles -1
  - Filtra contactados hoy
  - Audit en `radar_alertas` colección
- `enviar_alertas_mora_jueves(db)` + `run_radar_scheduler_jueves(db)` — **jueves 10:00 AM Bogotá**
  - DPD 1-6 → T3, DPD 7-29 → T4, DPD ≥30 → T5
  - Mora COP $2.000/día desde el día siguiente a la cuota
  - Tag automático `mora` al cliente

Ambos integrados en `core/database.py` lifespan junto al scheduler miércoles existente.

### 6. Wiring en `agents/chat.py`

```python
def _make_dispatcher(agent_type, db):
    if agent_type == "loanbook": return LoanToolDispatcher(db=db)
    if agent_type == "radar":    return RadarToolDispatcher(db=db)  # ← nuevo
    # default contador
```

`AGENT_TOOLS['radar']` ahora apunta a `RADAR_TOOLS` (5 tools) en lugar de lista vacía.

### 7. Templates Mercately T1-T5 (configurables)

```bash
# Variables de entorno nuevas (en Render dashboard)
MERCATELY_TEMPLATE_T1_RECORDATORIO_ID=<uuid>   # martes -2d
MERCATELY_TEMPLATE_T2_COBRO_HOY_ID=<uuid>      # miércoles
MERCATELY_TEMPLATE_T3_MORA_CORTA_ID=<uuid>     # mora 1-6d
MERCATELY_TEMPLATE_T4_MORA_MEDIA_ID=<uuid>     # mora 7-29d
MERCATELY_TEMPLATE_T5_ULTIMO_AVISO_ID=<uuid>   # mora ≥30d
MERCATELY_WEBHOOK_SECRET=<secret-largo>        # opcional pero recomendado
```

**Fallback automático:** si T1-T5 IDs no están configurados, usa los templates legacy `MERCATELY_TEMPLATE_COBRO_ID` y `MERCATELY_TEMPLATE_MORA_ID` que ya existían — código no rompe.

---

## Cómo se cierra el bucle "miércoles cobranza 100% remoto"

```
Martes 09:00 AM Bogota
   ↓
run_radar_scheduler_martes()
   ↓ filtra loanbooks con cuota = mañana (miércoles)
   ↓ filtra contactados hoy (Ley 2300)
   ↓
Mercately.send_template(T1, "Hola Juan, tu cuota de $X vence mañana 30 abr")
   ↓ exitoso → audit + gestión CRM
   ↓
══════════════════════════════════════
Miércoles 08:00 AM Bogota
   ↓
run_radar_scheduler() (existía) → T2 a clientes con cuota hoy
   ↓ exitoso → audit + gestión CRM
   ↓
Cliente paga (vía Loanbook agent o transferencia + conciliación)
   ↓ Loanbook publica cuota.pagada
   ↓
DataKeeper actualiza CRM con tag al_dia (handler S1.5)
══════════════════════════════════════
Jueves 10:00 AM Bogota
   ↓
run_radar_scheduler_jueves() → DPD máximo de cuotas no pagadas
   ↓ DPD 1-6 → T3, 7-29 → T4, ≥30 → T5
   ↓
Mercately.send_template(T3/T4/T5)
   ↓ tag mora al cliente
══════════════════════════════════════
Cliente responde por WhatsApp
   ↓ Mercately webhook
   ↓
POST /api/webhooks/mercately/inbound (HMAC)
   ↓ append crm_clientes.gestiones[whatsapp_inbound]
   ↓ publish cliente.respondio.whatsapp
   ↓
(Ejecucion 3+) RADAR agente decide siguiente acción
   o Andrés abre chat: "que dijo Juan ayer?" → RADAR consulta_estado_cliente
   ↓ ve la respuesta del cliente en el timeline
```

---

## Tests nuevos (26)

```
tests/test_radar_dispatcher.py       14 tests  (helpers + 5 tools)
tests/test_mercately_client_v2.py     8 tests  (CRUD + send_text + singleton)
tests/test_webhooks_mercately.py      4 tests  (inbound HMAC + idempotencia)
─────────────────────────────────────────────
                                     26 nuevos
                              1153 totales verdes
```

---

## Archivos nuevos

```
backend/agents/radar/tools.py                        ~135 líneas
backend/agents/radar/handlers/__init__.py             4 líneas
backend/agents/radar/handlers/dispatcher.py          ~390 líneas
backend/tests/test_radar_dispatcher.py               ~210 líneas
backend/tests/test_mercately_client_v2.py            ~110 líneas
backend/tests/test_webhooks_mercately.py             ~110 líneas
.planning/E2_RADAR_MERCATELY.md                      (este)
```

## Archivos modificados

```
backend/services/mercately/client.py     +120 líneas (CRUD + send_text + singleton)
backend/agents/radar/alertas.py          +250 líneas (2 schedulers extra)
backend/routers/webhooks.py              +120 líneas (mercately/inbound + health)
backend/agents/chat.py                   +6 líneas (RadarToolDispatcher wiring)
backend/agents/contador/tools.py         +1 línea (AGENT_TOOLS['radar'])
backend/core/database.py                 +35 líneas (2 schedulers extra en lifespan)
backend/tests/test_infrastructure.py     test ajustado (radar=5 tools)
backend/tests/test_tool_use.py           test ajustado (radar=5 tools)
```

---

## Configuración pendiente humana (Render + Mercately + Alegra dashboards)

### En Render dashboard (Settings → Environment)

```
MERCATELY_TEMPLATE_T1_RECORDATORIO_ID = <uuid Mercately>
MERCATELY_TEMPLATE_T2_COBRO_HOY_ID    = <uuid Mercately>
MERCATELY_TEMPLATE_T3_MORA_CORTA_ID   = <uuid Mercately>
MERCATELY_TEMPLATE_T4_MORA_MEDIA_ID   = <uuid Mercately>
MERCATELY_TEMPLATE_T5_ULTIMO_AVISO_ID = <uuid Mercately>
MERCATELY_WEBHOOK_SECRET              = <secret-largo-aleatorio>
```

Si no se configuran T1-T5 individualmente, el código usa fallbacks legacy (`MERCATELY_TEMPLATE_COBRO_ID` y `MERCATELY_TEMPLATE_MORA_ID`) — el sistema funciona pero todos los recordatorios usan el mismo template.

### En Mercately dashboard

1. Aprobar 5 templates con WhatsApp Business (3 parámetros cada uno: `{{1}}`=nombre, `{{2}}`=monto/dpd, `{{3}}`=fecha):
   - **T1 — Recordatorio amable:** `Hola {{1}}, te recordamos que tu cuota de {{2}} vence mañana {{3}}. ¿Necesitas ayuda? Avísanos.`
   - **T2 — Cobro hoy:** `Buenos días {{1}}, hoy {{3}} vence tu cuota de {{2}}. Puedes pagar por Bancolombia/Nequi.`
   - **T3 — Mora corta:** `{{1}}, tu cuota se venció hace {{2}} días. Mora acumulada: {{3}}. Te ayudamos a ponerte al día.`
   - **T4 — Mora media:** `{{1}}, tu crédito está en mora. {{2}} días de atraso, mora total {{3}}. Llámanos para acordar.`
   - **T5 — Último aviso:** `{{1}}, último aviso. Si no acuerdas pago en 48h iniciamos cobro jurídico. Mora: {{3}}.`
2. **NO HAY que configurar webhook entrante** — Mercately no los expone.
   El flujo inbound corre via polling automático cada 60s desde el backend
   (E2.5b). Solo necesitamos `MERCATELY_API_KEY` válida.
3. Probar enviando un WhatsApp manual al sistema desde tu propio número y
   esperar máx 60s. Verificar en logs Render: `Mercately inbound poller`.

### Verificación con curl

```bash
curl https://sismo.roddos.com/api/webhooks/mercately/health
# → {"ok":"true","service":"sismo.roddos.com","endpoint":"mercately-inbound-webhook"}
```

---

## Comandos commit + push

```powershell
cd C:\Users\AndresSanJuan\roddos-workspace\SISMO-V2

git add backend/services/mercately/client.py
git add backend/routers/webhooks.py
git add backend/agents/radar/tools.py
git add backend/agents/radar/handlers/__init__.py
git add backend/agents/radar/handlers/dispatcher.py
git add backend/agents/radar/alertas.py
git add backend/agents/chat.py
git add backend/agents/contador/tools.py
git add backend/core/database.py
git add backend/tests/test_radar_dispatcher.py
git add backend/tests/test_mercately_client_v2.py
git add backend/tests/test_webhooks_mercately.py
git add backend/tests/test_infrastructure.py
git add backend/tests/test_tool_use.py
git add .planning/E2_RADAR_MERCATELY.md

git commit -m "feat(E2): RADAR completo + Mercately bidireccional (sprint S2)

Cierra brechas #5 (Mercately solo manda) y #6 (RADAR sin tools).

Mercately client ampliado:
- get_customer_by_phone (R-MERCATELY antes de POST/PATCH)
- create_customer
- update_customer_tags (idempotente)
- send_text (ventana 24h)
- get_mercately_client() singleton

Webhook entrante:
- POST /api/webhooks/mercately/inbound con HMAC
- GET/POST /api/webhooks/mercately/health
- Append crm_clientes.gestiones[whatsapp_inbound]
- Publica cliente.respondio.whatsapp

Agente RADAR:
- 5 tools (generar_cola_cobranza, registrar_gestion, registrar_promesa_pago,
  enviar_whatsapp_template, consultar_estado_cliente)
- RadarToolDispatcher con permisos ROG-4b
- Validacion Ley 2300 (horario + max 1 contacto/dia)
- Templates T1-T5 configurables, fallback a legacy

Schedulers nuevos:
- run_radar_scheduler_martes (09:00 AM, T1 recordatorio -1d)
- run_radar_scheduler_jueves (10:00 AM, T3/T4/T5 segun DPD)
- Wiring en core/database.py lifespan

Tests: 1153 verdes (+26 nuevos)

Pendiente humano: configurar T1-T5 en Mercately + 6 env vars Render +
webhook entrante en Mercately dashboard."

git push origin main
```

---

## Próxima ejecución

**Ejecución 3 — Notificaciones internas + calendario tributario + cleanup tools** (~3h)

Brechas que cierra: tools faltantes Contador (`notificar_equipo`, `consultar_obligaciones_proximas`) + parte del orquestador (alertas tributarias automáticas para Fabián).
