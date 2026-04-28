# REVISIÓN INTEGRAL SISMO V2 — Plan vs Realidad

**Fecha:** 28-abril-2026
**Autor:** Auditoría técnica integral
**Documentos fuente:** Plan_Fases_Definitivo, Informe_12Abr2026, Informe_Cierre_Phase5_5, Informe_Completo_Abr2026, arquitectura Loanbook (PDF)
**Repo verificado:** `C:\Users\AndresSanJuan\roddos-workspace\SISMO-V2` @ commit `a640be4`
**Producción:** sismo.roddos.com (Render)

---

## Resumen ejecutivo

SISMO V2 está en un estado intermedio razonable pero **no es todavía el orquestador que el plan describe**. Lo construido funciona en su dominio (Contador) pero los puentes entre dominios (DataKeeper, RADAR completo, CFO) están a medias o ausentes.

| Capa | Plan documentado | Estado real | Gap |
|---|---|---|---|
| Agente Contador | 36 tools, ROG-4 puro | **49 tools, ROG-4 puro** ✓ | +13 tools, sobrecubierto |
| Agente Loanbook | 11 tools, scheduler miércoles, waterfall ANZI | 11 tools, schema, waterfall, **sin scheduler** | Scheduler miércoles |
| Agente RADAR | 4 tools + dispatcher + cola priorizada | Solo `radar/alertas.py` con scheduler básico, **sin tools** | Tools, dispatcher, frontend |
| Agente CFO | 4 tools read-only + scheduler proactivo | **Skeleton vacío** (`__init__.py` único) | Todo |
| DataKeeper | 8 eventos × Critical+Parallel handlers | **4/8 eventos** + handlers básicos | Mitad de los handlers |
| CRM | Router + sync Mercately bidireccional | Router OK, **sync básico sin webhook** | Webhook bidireccional |
| Mercately | CRUD customers + webhook + T1-T5 | Solo `send_template`, 2 templates | CRUD + webhook + T1-T5 |
| ROG-4 estricto | `inventario_motos` fuera de permissions | **`inventario_motos` SIGUE en `WRITE_PERMISSIONS['contador']`** | P0 |
| Frontend | Login + Chat + Conciliación + Dashboard + Loanbook + CRM + Inventario + RADAR | 27 archivos `.tsx`, RADAR no verificado | Mayormente OK |
| Tests | 304 verdes (plan) | **1.094 verdes** | +257% (sobrecumplido) |

**Veredicto global:** Phase 5.5 y 6 ✅ completas y operativas. Phase 7 (Loanbook) ~75% (faltan piezas conectivas). Phase 8 (RADAR) ~25%. Phase 9 (CFO) ~5%. Phases 10-13 ~0%.

---

## Pregunta 1 — ¿Funcionan los flujos de información?

Reviso los 8 flujos críticos del plan, uno por uno, con evidencia del código y los logs de los últimos 26 horas:

### Flujo A — Causación de gasto desde chat
**Estado: ✅ FUNCIONA**

Usuario describe un gasto en chat → Claude clasifica + calcula retenciones → ExecutionCard → usuario aprueba → POST `/journals` Alegra → verifica HTTP 200 → publica `gasto.causado` en `roddos_events`.
Evidencia en logs prod del 27-abr 23:30: `POST /api/backlog/.../causar?cuenta_id=5332 → 200 OK`.

### Flujo B — Conciliación bancaria batch
**Estado: ✅ FUNCIONA con 5 parsers**

`Causar Automáticos (≥70%)` procesa el backlog completo en BackgroundTask. Verificado: 260 movimientos migrados de V1, plan-separe operativo (PS-2026-013, 014, 015). Parser Global66 agregado en T2 de Phase 5.5.

### Flujo C — Crear factura de venta de moto desde chat
**Estado: 🟡 BLOQUEADO HASTA HOY, ARREGLADO EN COMMIT `5fc1ee2`**

El handler `handle_registrar_compra_motos` y `crear_factura_venta` mandaban el código NIIF (`41350501`) en lugar del ID interno Alegra (`5442`) → Alegra respondía `1008 — No se encontró la cuenta contable`. **Hoy se corrigió.** Aún sin probar end-to-end con factura real.

### Flujo D — Pago de cuota manual desde frontend
**Estado: 🟡 ROTO HASTA HOY, ARREGLADO EN COMMIT `5fc1ee2`**

`POST /api/loanbook/{id}/registrar-pago` reventaba con `KeyError: 'monto'` (línea 893 de `loanbook.py`). 3 fallos consecutivos en LB-2026-0014 el 27-abr 21:21. Arreglado.

### Flujo E — `factura.venta.creada` → loanbook + CRM + Mercately
**Estado: ❌ NO FUNCIONA según el plan**

El plan exige que cuando se crea una factura de venta, el DataKeeper dispare:
- Critical: `crear_loanbook_pendiente`
- Parallel: `crear_contacto_crm`, `sync_mercately`, `whatsapp_cuota_inicial`

Real: en `core/event_handlers.py` solo está `handle_factura_creada_sync_dashboard` que invalida el dashboard cache. **No crea loanbook, no crea contacto CRM, no sincroniza Mercately, no manda WhatsApp.**

Detalle en pregunta 4 abajo.

### Flujo F — `pago.cuota.registrado` cascada
**Estado: ❌ NO IMPLEMENTADO**

El plan exige Critical (separar ANZI 2%, journal en Alegra, marcar cuota pagada) + Parallel (CRM, Mercately tags, cache CFO, WhatsApp confirmación). Hoy: cero handlers para `pago.cuota.registrado`. El pago se registra solo en MongoDB.

### Flujo G — Cobranza miércoles
**Estado: 🟡 PARCIAL**

`agents/radar/alertas.py` tiene scheduler miércoles 08:00 que usa templates Mercately (`MERCATELY_TEMPLATE_COBRO_ID`, `MERCATELY_TEMPLATE_MORA_ID`), escribe en colección `radar_alertas` cada envío con estado. **Pero:**
- Solo 2 templates (cobro y mora) en lugar de T1-T5 del plan
- No hay tools del agente RADAR (cero `tools.py` en `agents/radar/`)
- No recibe respuestas (sin webhook Mercately → SISMO)
- No frontend RadarPage

### Flujo H — Detección automática facturas Alegra UI → SISMO
**Estado: ❌ ROTO HASTA HOY, ARREGLADO EN COMMIT `5fc1ee2`**

`core/alegra_sync.py` corre cada 60min `detect_and_sync_new_invoices`, pero:
1. Hasta hoy fallaba con HTTP 400 por `order_direction=DESC` no soportado. Logs: ~38 errores en 26h. Arreglado hoy.
2. Aun arreglado, **la lógica solo manda un mensaje al agente Loanbook con `auto_approve=True` esperando que cree el loanbook por chat** — frágil, no determinístico, no escalable.
3. **Polling de 60min es inaceptable** para un sistema que pretende reaccionar en tiempo real.

---

## Pregunta 2 — ¿Replantear flujos por Firecrawl?

**Sí. Pero no de forma drástica.** Firecrawl no debe ser camino primario por 4 razones:

1. **Latencia**: 10-30 segundos por operación vs 200-500ms de la API REST. Para 10 motos en lote eso es 5+ minutos vs 5 segundos.
2. **Costo**: créditos Firecrawl proporcionales al tiempo de sesión + uso del modelo `spark-1-pro`. ~$0.05-0.20 por operación contra $0.001 por API call.
3. **Idempotencia más difícil**: si el agente IA del browser se equivoca de cliente o duplica un ítem, el rollback es caro.
4. **Verificación más opaca**: hay que parsear URL final + título + texto en lugar de leer un JSON limpio.

### Modelo propuesto: 2 carriles

| Carril | Cuándo se usa | Tool del Contador |
|---|---|---|
| **Carril A — API REST** (primario) | Default. Rápido, barato, idempotente. | `crear_factura_venta`, `registrar_compra_motos`, `registrar_compra_proveedor` |
| **Carril B — Firecrawl Agent** (fallback) | Si Alegra responde 401/403/422 con `bot detection` o `code 1008` → fallback automático en el handler | Mismas tools, fallback transparente |

**Ya está parcialmente implementado** en `handle_registrar_compra_motos` (lines 538-562 facturacion.py) — la API se intenta primero, si falla cae a Firecrawl.

### Lo que sí debe cambiar

1. **Eliminar las 3 tools redundantes** que confunden al LLM:
   - `crear_factura_venta` (API directa) — mantener
   - `crear_factura_venta_via_firecrawl` (vieja, rota) — **deprecar y remover**
   - `crear_factura_venta_alegra_agente` (V2 Firecrawl) — mantener solo como herramienta de mantenimiento manual

2. **Webhook Alegra → SISMO** (Alegra Plan Pro lo soporta) **reemplaza el polling** y elimina la dependencia de Firecrawl para detectar facturas creadas en Alegra UI por humanos.

3. **`fc.agent()` solo para casos donde no exista tool API**: por ejemplo "crear bodega Repuestos en Alegra" (no hay endpoint REST documentado para warehouses). Para items/bills/invoices la API REST funciona.

---

## Pregunta 3 — Auditoría tools del Contador

### Cobertura actual: 49 tools (vs 36 planeados)

Ordenadas por categoría:

| Categoría | # tools | Cobertura |
|---|---|---|
| Egresos (causaciones, gastos, ajustes) | 7 | Buena |
| Ingresos / CXC | 4 | Buena |
| Conciliación bancaria | 5 | Buena |
| Facturación + inventario | 12 | **Sobrecargado**: 3 tools redundantes |
| Consultas Alegra (read-only) | 8 | Buena |
| Cartera + catálogo | 3 | Buena |
| Nómina + impuestos | 5 | Buena |
| Compras a proveedores | 2 | Buena |
| Catálogo embebido | 1 | Buena |
| **V2 Firecrawl Agent (mías)** | 3 | Nuevo, transitorio |

### Reglas claras (✅)
- ROG-1: `request_with_verify()` con HTTP 200 + GET — implementado universalmente
- ROG-4: AlegraAccountsService con cache 5min + `cero find_one` a plan_cuentas — verificado
- Auteco autoretenedor — manejado
- Auxilio transporte exento si > 2 SMMLV — manejado en nómina
- Anti-dup 3 capas — implementado en conciliación

### Reglas borrosas (⚠️)
1. **Triple tool para facturar moto** confunde al LLM:
   - `crear_factura_venta` (API)
   - `crear_factura_venta_via_firecrawl` (vieja, **deprecar ya**)
   - `crear_factura_venta_alegra_agente` (V2 nueva)
   El system prompt dice "USAR SIEMPRE la V2" pero las 3 siguen expuestas.

2. **`registrar_pago_cuota` debería desaparecer**. Según el plan, el pago de cuota es flujo del Loanbook, no del Contador. El Loanbook publica `pago.cuota.registrado` y el DataKeeper invoca al Contador para crear el journal. Hoy hay tool directa en el Contador → duplicación de responsabilidad.

3. **Mezcla de cuentas en CXC socios**: el catálogo embebido (`tools.py` línea 980) lista `5329 CXC Socios y accionistas` pero también referencia `132505` (NIIF) sin aclarar cuál es el ID interno. **Coincide con el bug que arreglamos hoy** (NIIF vs Alegra ID).

### Gaps de tools (lo que falta)
- `consultar_obligaciones_proximas` — alertas de vencimiento ReteFuente, IVA, ICA. El plan lo menciona como Phase 7 pero no se implementó.
- `simular_pago_cuota` — read-only para que el RADAR muestre al cliente qué pasaría si paga X.
- `proyectar_flujo_caja_30d` — para CFO. No existe.
- `exportar_balance_a_excel` — para reportes de Iván/Andrés. No existe.

### Recomendación P0 (esta semana)
Limpieza de tools del Contador:
1. **Eliminar** `crear_factura_venta_via_firecrawl` (la vieja rota)
2. **Renombrar** `crear_factura_venta` → `crear_factura_venta_api` y dejar la V2 como `crear_factura_venta` (default)
3. **Mover** `registrar_pago_cuota` al agente Loanbook
4. **Agregar** las 4 tools faltantes (obligaciones, simular pago, flujo caja, balance excel)

---

## Pregunta 4 — ¿Por qué el DataKeeper no carga loanbook+CRM al facturar en Alegra?

**Respuesta corta: porque NO está construido.** El DataKeeper que el plan describe (event_processor con 8 eventos × Critical+Parallel) no existe en producción.

### Lo que SÍ existe
- `core/event_processor.py` — infraestructura de procesamiento (registry, retry, DLQ) ✅
- `core/event_handlers.py` — solo 4 handlers registrados:
  - `gasto.causado` → invalida cfo_cache
  - `apartado.completo` → notificación interna
  - `test.ping` → testing
  - `factura.venta.creada` → **solo** `sync_alegra_invoice_stats` (actualiza dashboard)
- `routers/datakeeper.py` — endpoint admin para ver eventos
- `core/alegra_sync.py` — polling 60min de facturas Alegra UI

### Lo que el plan PIDE pero NO existe

| Evento | Critical (faltante) | Parallel (faltante) |
|---|---|---|
| `factura.venta.creada` | `crear_loanbook_pendiente` | `crear_contacto_crm`, `sync_mercately`, `whatsapp_cuota_inicial` |
| `moto.entregada` | `activar_cronograma_loanbook` | `actualizar_crm_credito`, `invalidar_cache_cfo`, `whatsapp_bienvenida` |
| `pago.cuota.registrado` | `separar_anzi_2%`, `crear_journal_alegra`, `marcar_cuota_pagada` | `actualizar_crm_pago`, `sync_mercately_tags`, `invalidar_cache_cfo`, `whatsapp_confirmacion` |
| `credito.saldado` | `cerrar_loanbook` | `actualizar_crm_cerrado`, `sync_mercately_pagado`, `invalidar_cache_cfo`, `whatsapp_paz_salvo` |
| `loanbook.modificado` | `recalcular_cronograma` | `actualizar_crm_acuerdo`, `sync_mercately_tags` |
| `crm.cliente.creado` | — | `sync_mercately_contacto` |
| `crm.cliente.actualizado` | — | `sync_mercately_contacto` |

### Por qué falla el caso "facturan en Alegra UI directo"

3 razones, en cascada:

1. **No hay webhook Alegra → SISMO.** Si alguien crea factura en `app.alegra.com`, SISMO se entera por **polling cada 60min** (`detect_and_sync_new_invoices`).
2. **El polling estaba roto** hasta hoy (HTTP 400 por `order_direction=DESC`). Arreglado en commit `5fc1ee2`.
3. **Aun arreglado el polling, la cascada no funciona**: la lógica actual de `detect_and_sync_new_invoices` solo invoca `process_system_event(message=..., agent_type="loanbook", auto_approve=True)` — manda un mensaje en lenguaje natural al agente Loanbook esperando que cree el loanbook. Esto es **inestable** (depende del LLM interpretar correctamente), **lento** (1 LLM call por factura), y **fragil** (no hay handlers determinísticos como en el plan).

### Solución correcta (P0)

```
┌─────────────────────────┐
│ Alegra POST /webhooks   │  ← config en Alegra dashboard
│ url: sismo.roddos.com   │
│      /api/webhooks/     │
│      alegra/invoice     │
└────────────┬────────────┘
             │ JSON con invoice_id
             ▼
┌─────────────────────────────────────────┐
│  POST /api/webhooks/alegra/invoice      │
│  - validar HMAC firma                    │
│  - GET /invoices/{id} para datos full    │
│  - publish_event("factura.venta.creada") │
└────────────┬────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────┐
│  EventProcessor (DataKeeper)            │
│  Critical:                              │
│    1. crear_loanbook_pendiente()        │  ← determinista, código Python
│  Parallel:                              │
│    a. crear_contacto_crm()              │
│    b. sync_mercately_contacto()         │
│    c. enviar_whatsapp_cuota_inicial()   │
└─────────────────────────────────────────┘
```

**Datakeeper NO está configurado correctamente.** Tiene la infraestructura (`event_processor.py`) pero le faltan los handlers reales del plan.

---

## Pregunta 5 — Arquitectura RADAR + Mercately

### Lo que pide el plan
- 4 tools (`generar_cola`, `registrar_gestion`, `registrar_ptp`, `enviar_whatsapp`)
- Scheduler miércoles 07:00 con cola priorizada por `dpd × score`
- Templates T1-T5 con variables de CRM custom fields
- Cron martes 9AM (recordatorio) + jueves 10AM (mora)
- Webhook bidireccional Mercately → SISMO
- Frontend RadarPage mobile-first
- Ley 2300 (max 1 contacto/día)

### Lo que existe
- `agents/radar/alertas.py` con scheduler miércoles 08:00 (no 07:00)
- 2 templates Mercately (`COBRO_ID` y `MORA_ID`) — falta T3, T4, T5
- Colección `radar_alertas` con audit de envíos
- Endpoints `/api/radar/preview` (dry_run) y `/api/radar/enviar`
- Mercately client con `send_template()` (fila 65 `services/mercately/client.py`)

### Lo que falta
- **Tools del agente RADAR**: cero. `agents/radar/` solo tiene `alertas.py`. No hay `tools.py`, no hay `handlers/`. RADAR hoy no es agente IA, es solo un cron job.
- **Webhook bidireccional**: Mercately permite recibir respuestas de los clientes pero SISMO no expone endpoint que las reciba.
- **CRUD customers en Mercately**: solo `send_template`. Falta `GET /customers/{phone}` para verificar antes de enviar (el plan lo exige como `R-MERCATELY`).
- **Frontend RadarPage**: no verificado.
- **Templates T1-T5**: solo 2 de 5. El plan diseñó 5 niveles de fricción (T1=recordatorio amable → T5=último aviso pre-cobranza jurídica).

### Recomendación

**Sí, la arquitectura es correcta** (eventos + scheduler + cola priorizada + webhook), pero está **al 25% de implementación**. Para que funcione en producción:

1. **Templates T1-T5** declarados en Mercately + IDs en `.env`
2. **Tools del RADAR**: `generar_cola_cobranza`, `registrar_gestion_telefonica`, `registrar_promesa_pago`, `enviar_whatsapp_template`, `consultar_estado_cliente`
3. **Webhook entrante** `POST /api/webhooks/mercately/inbound` → registra mensaje en `crm_clientes.{cliente}.gestiones[]` + dispara evento `cliente.respondio.whatsapp`
4. **Cliente Mercately con `get_customer_by_phone`** (para R-MERCATELY)
5. **Cron martes 9AM (recordatorio)** y jueves 10AM (mora) — solo existe el del miércoles

---

## Pregunta 6 — ¿Contador puede contactar a Iván / Fabián / Andrés vía Mercately?

**Sí, técnicamente viable hoy mismo, con poco trabajo.**

Lo que ya tienes:
- `services/mercately/client.py` con `send_template()` y `MERCATELY_API_KEY` configurado
- Plantillas activas en Mercately (cobro, mora) — sirven de referencia para nuevas

Lo que falta para habilitarlo (estimado: medio día de trabajo):

### Implementación recomendada

```python
# backend/services/mercately/client.py — agregar al final

INTERNOS_TELEFONOS = {
    "andres":  os.getenv("WHATSAPP_ANDRES",  "+57XXXXXXXXXX"),
    "ivan":    os.getenv("WHATSAPP_IVAN",    "+57XXXXXXXXXX"),
    "fabian":  os.getenv("WHATSAPP_FABIAN",  "+57XXXXXXXXXX"),
}

# Templates con 1 parámetro: el mensaje
MERCATELY_TEMPLATE_INTERNO_INFO   = os.getenv("MERCATELY_TEMPLATE_INTERNO_INFO_ID")
MERCATELY_TEMPLATE_INTERNO_ALERTA = os.getenv("MERCATELY_TEMPLATE_INTERNO_ALERTA_ID")
MERCATELY_TEMPLATE_INTERNO_TASK   = os.getenv("MERCATELY_TEMPLATE_INTERNO_TASK_ID")

async def notificar_interno(persona: str, nivel: str, mensaje: str) -> dict:
    """nivel: 'info' | 'alerta' | 'task'."""
    tel = INTERNOS_TELEFONOS.get(persona.lower())
    if not tel:
        return {"ok": False, "error": f"Persona '{persona}' no configurada"}
    template_map = {"info": ..., "alerta": ..., "task": ...}
    return await send_template(
        phone=tel,
        template_id=template_map[nivel],
        params=[mensaje[:1024]],
    )
```

Y en `tools.py` del Contador:

```python
{
  "name": "notificar_equipo",
  "description": "Envía un mensaje WhatsApp al equipo interno (Andrés/Iván/Fabián). "
                 "Usar para: alertas de causación importante, recordatorios fiscales, "
                 "errores Alegra que requieren intervención humana, confirmación "
                 "de pagos > 5M.",
  "input_schema": {
    "type": "object",
    "required": ["persona", "nivel", "mensaje"],
    "properties": {
      "persona": {"enum": ["andres","ivan","fabian"]},
      "nivel":   {"enum": ["info","alerta","task"]},
      "mensaje": {"type": "string", "maxLength": 1024},
    }
  }
}
```

### Casos útiles para empezar

| Caso | Persona | Nivel | Trigger |
|---|---|---|---|
| Causación CXC socio Andrés > $500.000 | Andrés | alerta | handler `registrar_cxc_socio` |
| Pago de cuota recibido > $1M | Iván | info | evento `pago.cuota.registrado` |
| Vencimiento ReteFuente en 3 días | Fabián | task | scheduler diario 8AM |
| 5+ errores `tool.error` en 1 hora | Andrés | alerta | scheduler hora |
| Alegra circuit breaker OPEN | Andrés + Iván | alerta | `_cb_publish_open_event` |

### Política anti-spam (importante)
Agregar tabla `whatsapp_internal_audit` que limite max 10 mensajes/día por persona y deduplique mensajes idénticos en ventana de 1h.

---

## Pregunta 7 — Roadmap orquestador IA backoffice

Para que SISMO sea **el orquestador completo** del backoffice de RODDOS, hay 7 brechas críticas y un plan de 8 semanas:

### Brechas críticas

| # | Brecha | Impacto si no se cierra |
|---|---|---|
| 1 | **DataKeeper handlers incompletos** (4/8) | Cascadas no ocurren → loanbook desincronizado, CRM sin contactos, WhatsApp sin disparar |
| 2 | **`inventario_motos` aún en WRITE_PERMISSIONS** | Viola ROG-4. Bug futuro: Contador modifica inventario en MongoDB sin pasar por Loanbook |
| 3 | **Webhook Alegra → SISMO ausente** | Polling 60min insuficiente. Facturas creadas desde Alegra UI tardan en propagarse |
| 4 | **CFO inexistente** | Cero P&L automatizado, cero alertas estratégicas, cero proyección de flujo |
| 5 | **Mercately solo `send_template`** | Sin webhook entrante = no se reciben respuestas de clientes |
| 6 | **RADAR sin tools** | Solo es scheduler. No es agente IA. No puede decidir cobranza |
| 7 | **Sin observabilidad** (Langfuse) | No saben costo de LLM por agente, dónde falla, latencias |

### Plan de 8 semanas para llegar a la visión completa

**Semana 1 (esta) — P0 cerrar lo crítico**
- Eliminar `inventario_motos` de `WRITE_PERMISSIONS['contador']`
- Corregir el `detect_and_sync_new_invoices` (ya hecho hoy)
- Implementar 6 handlers DataKeeper que faltan en `core/event_handlers.py`:
  - `crear_loanbook_pendiente` (factura.venta.creada)
  - `crear_contacto_crm` (factura.venta.creada)
  - `sync_mercately_contacto` (crm.cliente.creado/actualizado)
  - `activar_cronograma_loanbook` (moto.entregada)
  - `actualizar_crm_pago` (pago.cuota.registrado)
  - `cerrar_loanbook` (credito.saldado)

**Semana 2 — Webhook Alegra + Mercately bidireccional**
- Endpoint `POST /api/webhooks/alegra/invoice` con HMAC
- Configurar webhook en Alegra dashboard
- Endpoint `POST /api/webhooks/mercately/inbound`
- Cliente Mercately: agregar `get_customer_by_phone`, `create_customer`, `update_customer_tags`

**Semana 3 — Agente RADAR completo**
- Crear `agents/radar/tools.py` (4 tools)
- Crear `agents/radar/handlers/dispatcher.py`
- Templates T1-T5 declarados
- Scheduler martes (recordatorio) + jueves (mora)
- Frontend `RadarPage.tsx`

**Semana 4 — Notificaciones internas + Calendario tributario**
- Tool `notificar_equipo` (pregunta 6)
- Scheduler diario 8AM que revisa calendario tributario y manda alertas
- Política anti-spam

**Semana 5-6 — Agente CFO MVP**
- 4 tools: `consultar_pl_mensual`, `consultar_balance`, `consultar_flujo_caja_90d`, `generar_alerta`
- System prompt + dispatcher
- Scheduler lunes 8AM resumen automático WhatsApp a Andrés
- Frontend `DashboardCFO.tsx` con Recharts

**Semana 7 — Observabilidad**
- Integrar Langfuse para tracing de cada agente
- Dashboard con costo LLM por operación
- Alertas P0: Alegra caído >30min, jobs fallidos >2, costo LLM >120%

**Semana 8 — DIAN + facturación electrónica**
- Conectar Alanube
- Causación nocturna automática (cron 11PM)
- Facturación electrónica venta motos con resolución DIAN

### Lo que NO hay que construir (ya está bien)

- Agente Contador con 49 tools — sobrecubre el plan
- Conciliación bancaria con 5 parsers + Causar Automáticos
- Memoria conversacional (chat_sessions con TTL 72h)
- AlegraAccountsService con cache 5min (ROG-4 puro)
- OCR de comprobantes vía Claude Vision
- Plan-separe operativo
- Auth JWT + 3 usuarios

### Métrica de éxito (cuando SISMO sea orquestador real)

Al cierre de la semana 8 podremos decir:
- Cuando facturen en Alegra UI → SISMO crea loanbook + CRM en <30s sin intervención
- Cada miércoles cobranza arranca 8AM, manda WhatsApp T1 a 100% al día, T3 a 7+ días mora, sin tocar nada
- El equipo recibe WhatsApp Lunes 8AM con P&L del mes anterior
- Andrés recibe alerta WhatsApp si: ReteFuente vence en 3 días, gasto socio >$500K, Alegra caído, costo LLM >120%
- Toda operación queda trazada en Langfuse con costo + latencia
- 0 fallas silenciosas — cada error queda en `tool.error` con traceback

---

## Anexo — Cosas raras encontradas en logs (posibles bugs latentes)

1. **Plan-separe abonos lentos (>7s)**: `POST /api/plan-separe/PS-2026-013/abono → 7185ms` (27-abr 16:37). Probable bloqueo esperando Alegra. Vale perfilar.

2. **`POST /api/chat/approve-plan` a 70 segundos**: log 27-abr 21:17. Probable timeout de Anthropic con tools chain larga.

3. **Cliente externo pega `/api/api/inventory/repuestos`** (api duplicado): n8n? script propio? ~3 hits/día desde `74.220.48.3`. Investigar quién hace la llamada y arreglar.

4. **Scanners de seguridad** (`/.env`, `/.git/config`, `phpinfo.php`): ~150 requests en 2 minutos desde varias IPs. Todos retornan 200 (SPA fallback con `index.html`). No leak real, pero ruido alto. Middleware `block_scanner_paths` reduciría esto en 95%.

5. **Doble deploy con frecuencia**: ~14 deploys en 26h. Algunos por push del usuario, otros por restart automático Render. Investigar si hay crashes silenciosos que provoquen restart.

---

## Bottom line

**Lo bueno:** la base contable está sólida (Contador 49 tools + ROG-4 + 1094 tests verdes + 5 parsers + Causar Automáticos + OCR). La arquitectura del plan es coherente y correcta.

**Lo malo:** la *conectividad* entre dominios (DataKeeper completo, RADAR completo, CFO, webhooks bidireccionales) es la mitad de lo que el plan describe. SISMO V2 hoy es un buen contador IA, pero no es todavía el orquestador integral.

**El plan de 8 semanas cierra el gap.** No requiere replanteo arquitectónico — el plan es correcto, falta ejecutarlo. La semana 1 (DataKeeper handlers + permissions.py + webhook Alegra) es la que más impacto tiene por unidad de esfuerzo.
