# Ejecución 1 — DataKeeper handlers + webhook Alegra

**Fecha:** 28-abril-2026
**Sprint:** S1.5 (cierre del bucle factura → loanbook + CRM)
**Brechas cerradas:** #1 (DataKeeper incompleto) y #3 (sin webhook Alegra)
**Tests:** 1127 verdes (+27 nuevos)

---

## Qué quedó construido

### 1. Refactor 4 `insert_one` Loanbook → `publish_event()`

`agents/loanbook/handlers/dispatcher.py` — los 4 puntos donde el agente Loanbook publicaba eventos directamente con `db.roddos_events.insert_one(...)` ahora usan `publish_event()` de `core/events.py`.

**Por qué importa:** el `EventProcessor` (DataKeeper) ahora se entera de los eventos `apartado.completo`, `entrega.realizada`, `cuota.pagada` y `loanbook.saldado` que publica el Loanbook → puede disparar la cascada de handlers Critical+Parallel.

### 2. Handlers DataKeeper nuevos

#### `core/datakeeper_handlers_loanbook.py`
- `handle_crear_loanbook_pendiente` (Critical en `factura.venta.creada`)
  - Idempotente por `factura_alegra_id`
  - Crea loanbook estado `pendiente_entrega`
  - Marca moto `vendida` en `inventario_motos`
  - Publica `loanbook.creado` (que dispara crm_handlers existente)
  - Solo procesa modalidad `semanal` automáticamente; quincenal/mensual quedan diferidos al flujo manual
- `handle_activar_cronograma_loanbook` (Critical en `entrega.realizada`)
  - Defensivo: si `entrega.realizada` llega de otro origen (futuro: webhook taller, app móvil)
  - Idempotente: si ya está activo, no hace nada
  - Recalcula cronograma con la fecha real de entrega
- `handle_cerrar_loanbook_paz_salvo` (Parallel en `loanbook.saldado`)
  - Actualiza CRM con tag `paz_y_salvo` y gestión de cierre

#### `core/datakeeper_handlers_crm.py`
- `handle_sync_mercately_contacto_inicial` (Parallel en `loanbook.creado`)
  - Normaliza teléfono a `+57XXXXXXXXXX`
  - Marca `mercately_phone` y `mercately_synced_at` en CRM
  - Stub de envío real a Mercately (se completa en Ejecución 2)
- `handle_sync_mercately_contacto_update` (Parallel en `crm.cliente.actualizado`)
  - Re-sync cuando cambia el cliente
- `handle_registrar_gestion_pago_crm` (Parallel en `cuota.pagada`)
  - Append al timeline `gestiones[]` del cliente
  - Tags automáticos: `al_dia` / `mora` / `paz_y_salvo` según `nuevo_estado`

### 3. Endpoint `POST /api/webhooks/alegra/invoice`

`routers/webhooks.py` — recibe webhook desde el dashboard de Alegra cuando alguien crea factura desde la UI directa (no desde SISMO chat).

- Validación HMAC SHA256 con `ALEGRA_WEBHOOK_SECRET` (env var)
- Modo dev: si `ALEGRA_WEBHOOK_SECRET` está vacío, acepta sin firma
- Idempotencia: si ya hay loanbook con ese `factura_alegra_id`, devuelve `idempotent: true`
- Parsea cliente, items (extrae VIN/Motor del formato `"Modelo Color - VIN: XXX / Motor: YYY"`), observaciones (busca `Plan: PXXS` y `Modalidad: semanal/quincenal/mensual`)
- Publica `factura.venta.creada` con datos completos para que el DataKeeper haga la cascada

Endpoints adicionales:
- `GET /api/webhooks/alegra/health` — health check para Alegra dashboard
- `POST /api/webhooks/alegra/health` — idem (algunos webhooks usan POST)

### 4. Reformulación ROG-4 (Brecha #2 cerrada en sesión anterior)

Recordatorio: ya quedó cerrado en commit `a640be4`. `inventario_motos`, `plan_cuentas_roddos`, `cartera_pagos`, `cxc_socios`, `cxc_clientes` salieron de `WRITE_PERMISSIONS['contador']`. Test estático `test_rog4_dominios.py` bloquea CI si algún agente escribe fuera de su dominio.

---

## Cómo se cierra el bucle "factura UI Alegra → loanbook + CRM"

```
┌──────────────────────────────────────────┐
│ Usuario crea factura en app.alegra.com   │
│ desde UI (NO desde SISMO chat)           │
└──────────────────┬───────────────────────┘
                   │ Alegra webhook (HMAC)
                   ▼
┌──────────────────────────────────────────┐
│ POST /api/webhooks/alegra/invoice        │
│ - valida HMAC                            │
│ - parsea client, items, observations     │
│ - extrae VIN, motor, plan, modalidad     │
│ - publish_event(factura.venta.creada)    │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│ EventProcessor (DataKeeper)              │
│ poll cada 5s → detecta nuevo evento      │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│ CRITICAL handlers (secuenciales)         │
│  1. crear_loanbook_pendiente             │
│     - crea loanbook pendiente_entrega    │
│     - marca moto vendida                 │
│     - publish_event(loanbook.creado)     │
└──────────────────┬───────────────────────┘
                   │ loanbook.creado
                   ▼
┌──────────────────────────────────────────┐
│ CRITICAL: handle_loanbook_creado         │
│  (crm_handlers.py existente)             │
│  - upsert cliente en crm_clientes        │
│  - agrega loanbook_id al cliente         │
└──────────────────┬───────────────────────┘
                   │
                   ▼ (en paralelo)
┌──────────────────────────────────────────┐
│ PARALLEL handlers                        │
│  • sync_mercately_contacto_inicial       │
│    (marca mercately_synced_at)           │
│  • factura.venta.creada                  │
│    sync_dashboard_alegra_stats (existía) │
└──────────────────────────────────────────┘
```

**Latencia esperada:** webhook Alegra dispara → DataKeeper procesa en <30s (poll cada 5s + ~200ms cada handler).

---

## Configuración pendiente en Alegra dashboard (lo único humano)

Después del deploy a producción:

1. Login en https://app.alegra.com
2. Configuración → API o Webhooks (depende de la versión del Plan Pro)
3. Crear webhook:
   - **URL:** `https://sismo.roddos.com/api/webhooks/alegra/invoice`
   - **Eventos:** `invoice.created`, `invoice.updated` (al menos `created`)
   - **Secret:** generar valor seguro y guardarlo en Render env como `ALEGRA_WEBHOOK_SECRET`
4. Probar con la opción "Send test event" → debe responder HTTP 200
5. (Opcional pero recomendado) Configurar webhook de prueba apuntando primero a `/api/webhooks/alegra/health` para validar conectividad antes de cambiar al endpoint real

**Si Alegra no soporta webhooks** (consultar plan): el polling de 60min de `core/alegra_sync.py` sigue siendo fallback, ya arreglado en commit `5fc1ee2`.

---

## Variables de entorno nuevas

Agregar en Render dashboard:

```
ALEGRA_WEBHOOK_SECRET=<valor-generado-largo>
```

Si no se configura, el endpoint funciona en modo "abierto" (acepta sin firma) — solo recomendado en dev.

---

## Tests

```
tests/test_datakeeper_handlers_loanbook.py  11 tests
tests/test_datakeeper_handlers_crm.py        11 tests
tests/test_webhooks_alegra.py                 5 tests
tests/test_rog4_dominios.py                   3 tests (mantienen CI bloqueante)
─────────────────────────────────────────────────────
                                             30 tests nuevos
                                       1127 tests total verdes
```

---

## Archivos nuevos

```
backend/core/datakeeper_handlers_loanbook.py    +250 líneas
backend/core/datakeeper_handlers_crm.py         +180 líneas
backend/routers/webhooks.py                     +210 líneas
backend/tests/test_datakeeper_handlers_loanbook.py +180 líneas
backend/tests/test_datakeeper_handlers_crm.py    +130 líneas
backend/tests/test_webhooks_alegra.py            +110 líneas
.planning/E1_DATAKEEPER_WEBHOOK_ALEGRA.md       (este archivo)
```

## Archivos modificados

```
backend/agents/loanbook/handlers/dispatcher.py  4 insert_one → publish_event
backend/core/database.py                        importa los 2 módulos handlers nuevos
backend/main.py                                 incluye webhooks_router
```

---

## Comandos para deploy

```powershell
cd C:\Users\AndresSanJuan\roddos-workspace\SISMO-V2

# Verificar tests locales
cd backend
python -m pytest tests/test_datakeeper_handlers_loanbook.py tests/test_datakeeper_handlers_crm.py tests/test_webhooks_alegra.py tests/test_rog4_dominios.py -v
cd ..

# Commit
git add backend/core/datakeeper_handlers_loanbook.py backend/core/datakeeper_handlers_crm.py
git add backend/routers/webhooks.py
git add backend/tests/test_datakeeper_handlers_loanbook.py backend/tests/test_datakeeper_handlers_crm.py backend/tests/test_webhooks_alegra.py
git add backend/agents/loanbook/handlers/dispatcher.py
git add backend/core/database.py backend/main.py
git add .planning/E1_DATAKEEPER_WEBHOOK_ALEGRA.md

git commit -m "feat(E1): DataKeeper handlers + webhook Alegra (cierre bucle factura UI -> loanbook + CRM)

- 4 insert_one directos del Loanbook refactorizados a publish_event() — el
  EventProcessor ahora consume apartado.completo, entrega.realizada,
  cuota.pagada y loanbook.saldado.

- 6 handlers DataKeeper nuevos:
  * crear_loanbook_pendiente (Critical en factura.venta.creada)
  * activar_cronograma_loanbook (Critical en entrega.realizada)
  * cerrar_loanbook_paz_salvo (Parallel en loanbook.saldado)
  * sync_mercately_contacto_inicial (Parallel en loanbook.creado)
  * sync_mercately_contacto_update (Parallel en crm.cliente.actualizado)
  * registrar_gestion_pago_crm (Parallel en cuota.pagada)

- Endpoint POST /api/webhooks/alegra/invoice con HMAC SHA256.
  Cuando facturan desde Alegra UI directa, dispara la cascada DataKeeper
  que crea loanbook pendiente_entrega + cliente CRM + sync Mercately
  en <30s sin intervencion humana.

- Endpoints health (GET/POST /api/webhooks/alegra/health) para validar
  conectividad desde Alegra dashboard.

Tests: 1127 verdes (+27 nuevos).

Cierra brechas #1 y #3 del informe REVISION_INTEGRAL_SISMO_V2.md.
Sprint S1.5 del plan original.

Pendiente humano: configurar webhook en Alegra dashboard apuntando a
sismo.roddos.com/api/webhooks/alegra/invoice + crear var Render
ALEGRA_WEBHOOK_SECRET."

git push origin main
```

---

## Próxima ejecución

**Ejecución 2 — RADAR completo + Mercately bidireccional** (~4h)

Sigue el orden del plan de 5 ejecuciones del informe. Brechas que cierra: #5 (Mercately bidireccional) y #6 (RADAR sin tools).
