# SISMO V2 — Registro Canónico de Rutas

ARCHIVO VIVO — Actualizar con cada build, cada endpoint nuevo, cada colección nueva.
REGLA: Si no está en este archivo, no existe. Si vas a crear algo nuevo, primero verificar aquí que no exista ya.

Última actualización: Abril 2026 — Sprint v3 Reglas de Negocio (5b46ee8)

---

## 1. ALEGRA API — Endpoints permitidos

URL base: https://api.alegra.com/api/v1/
Auth: Basic Base64(contabilidad@roddos.com:17a8a3b7016e1c15c514)

| Método | Endpoint | Quién lo usa | Para qué | Estado |
|--------|----------|-------------|----------|--------|
| POST | /journals | Agente Contador | Crear comprobantes contables (gastos, ingresos, CXC) | ✅ Activo |
| GET | /journals | Contador + CFO | Leer journals existentes, verificar post-POST | ✅ Activo |
| GET | /journals/{id} | Contador | Verificación en request_with_verify() | ✅ Activo |
| DELETE | /journals/{id} | Contador | Anular causaciones incorrectas | ✅ Activo |
| POST | /invoices | Contador | Crear facturas de venta de motos | 🔴 Pendiente Fase 1 |
| GET | /invoices | CFO + Polling | P&L, sincronización de inventario | ✅ Activo |
| POST | /payments | Contador | Registrar pagos de cuotas | 🔴 Pendiente Fase 1 |
| GET | /payments | CFO + Polling | Sincronizar cartera | ✅ Activo |
| POST | /bills | Contador | Crear facturas de proveedor (DIAN) | ✅ Activo (simulación) |
| GET | /bills | CFO | Cuentas por pagar | ✅ Activo |
| GET | /categories | Contador + CFO | Plan de cuentas 233 NIIF | ✅ Activo |
| GET | /contacts | Contador | Verificar terceros (clientes/proveedores) | ✅ Activo |

PROHIBIDOS — NUNCA USAR:
| Método | Endpoint | Razón |
|--------|----------|-------|
| GET | /accounts | Da 403. Usar /categories en su lugar |
| POST | /journal-entries | Da 403. Usar /journals en su lugar |

---

## 2. ALEGRA — IDs de Cuentas (plan_cuentas_roddos)

Fuente: colección plan_cuentas_roddos en MongoDB. NUNCA hardcodear estos IDs en el código — siempre leer de la colección.

### 2A. Cuentas de gasto

| Categoría | Subcategoría | Cuenta Alegra | ID Alegra | Código NIIF |
|-----------|-------------|---------------|-----------|-------------|
| Personal | Salarios | Sueldos 510506 | 5462 | 510506 |
| Personal | Honorarios | Honorarios | 5470 | — |
| Personal | Seguridad social | Seguridad social | 5471 | — |
| Personal | Dotación | Dotaciones | 5472 | — |
| Operaciones | Arriendo | Arrendamientos 512010 | 5480 | 512010 |
| Operaciones | Servicios públicos | Servicios públicos | 5484 | — |
| Operaciones | Telefonía | Teléfono/Internet 513535 | 5487 | 513535 |
| Operaciones | Mantenimiento | Mantenimiento | 5490 | — |
| Operaciones | Transporte | Transporte | 5491 | — |
| Operaciones | Papelería | Útiles papelería 519530 | 5497 | 519530 |
| Marketing | Publicidad | Publicidad | 5500 | — |
| Marketing | Eventos | Eventos | 5501 | — |
| Impuestos | ICA | ICA | 5505 | — |
| Impuestos | ReteFuente | ReteFuente practicada | 236505 | 236505 |
| Impuestos | ReteICA | ReteICA practicada | 236560 | 236560 |
| Financiero | Intereses | Intereses 615020 | 5533 | 615020 |
| Financiero | Comisiones bancarias | Comisiones 530515 | 5508 | 530515 |
| Financiero | Seguros | Seguros | 5510 | — |
| Otros | Varios | Gastos Generales (FALLBACK) | 5493 | — |

⚠️ ID 5495 (Gastos de Representación) = PROHIBIDO. Causó 143 asientos incorrectos en enero 2026.

### 2B. Cuentas de banco

| Banco | ID Alegra | Cuenta NIIF | Uso principal |
|-------|-----------|-------------|---------------|
| Bancolombia | 111005 | 111005 | Recaudo cuotas semanales |
| BBVA | 111010 | 111010 | Pagos a proveedores |
| Davivienda | 111015 | 111015 | Operaciones generales |
| Banco de Bogotá | 111020 | 111020 | Operaciones generales |
| Global66 | 11100507 | — | Transferencias internacionales |

### 2C. Cuentas de ingreso (plan_ingresos_roddos)

| Tipo de ingreso | Cuenta Alegra | ID Alegra | Nota |
|----------------|---------------|-----------|------|
| Ingresos financieros | Ingresos financieros | TBD | Cuotas de cartera |
| Ventas especiales | Ventas motos recuperadas | TBD | Motos recuperadas |
| Otros ingresos | Otros ingresos no operacionales | TBD | Intereses bancarios, etc |

⚠️ IDs de plan_ingresos_roddos pendientes de confirmar en Alegra. Leer de MongoDB antes de usar.

---

## 3. MONGODB — Colecciones

### 3A. Colecciones operativas

| Colección | Agente dueño (escribe) | Agentes que leen | Propósito |
|-----------|----------------------|-----------------|-----------|
| loanbook | Agente Loanbook | Contador, RADAR, CFO | Créditos: cuotas, DPD, estado |
| inventario_motos | Agente Loanbook (mutex) | Contador, CFO | Estado de cada moto |
| cartera_pagos | Agente Contador | RADAR, CFO | Historial pagos confirmados |
| plan_cuentas_roddos | Agente Contador | Todos | IDs reales de cuentas Alegra (28 entradas) |
| plan_ingresos_roddos | Agente Contador | CFO | IDs de cuentas de ingreso Alegra |
| cxc_socios | Agente Contador | CFO | Retiros personales socios |
| cxc_clientes | Agente Contador | CFO | CXC clientes no-loanbook |
| crm_clientes | RADAR | Loanbook, CFO | Ficha 360° del cliente |
| gestiones_cobranza | RADAR | CFO | Historial gestiones de cobro |
| catalogo_motos | Admin (Settings) | Contador, Loanbook | Precios, cuotas, planes |
| catalogo_planes | Admin (Settings) | Loanbook, Contador | Planes P39S, P52S, P78S |
| proveedores_config | Admin | Contador | Autoretenedores y reglas especiales |

### 3B. Colecciones de sistema

| Colección | Propósito | Nota |
|-----------|-----------|------|
| roddos_events | Bus de eventos (append-only) | Todos publican, todos leen |
| agent_sessions | Historial conversacional por usuario | TTL 72h |
| agent_pending_topics | Temas pendientes por usuario | TTL 72h |
| agent_memory | Correcciones aprendidas del usuario | Permanente |
| agent_errors | Log de errores del agente | Permanente |
| users | Usuarios del sistema | Auth |
| audit_logs | Auditoría de acciones | Permanente |

### 3C. Colecciones CFO

| Colección | Propósito | Nota |
|-----------|-----------|------|
| cfo_cache | Indicadores cacheados | TTL invalidable por eventos |
| cfo_informes | Informes mensuales generados | Solo CFO escribe |
| cfo_alertas | Alertas activas | Solo CFO escribe |
| cfo_configuracion | Parámetros del CFO | Admin configura |
| cfo_deudas | Deudas productivas y no productivas | CFO lee |
| presupuesto | Presupuesto mensual | Admin configura |

### 3D. Colecciones de conciliación

| Colección | Propósito | Nota |
|-----------|-----------|------|
| conciliacion_extractos_procesados | Hash MD5 de extractos (anti-dup Capa 1) | Índice único en hash |
| conciliacion_movimientos_procesados | Hash MD5 por movimiento (anti-dup Capa 2) | Índice único en hash |
| conciliacion_jobs | Estado de jobs background | Sobrevive reinicios Render |
| conciliacion_reintentos | Cola de movimientos para reintento | Cada 5 min |
| backlog_movimientos | Movimientos pendientes de causar | 🔴 NUEVO en Fase 1 |

### 3E. Colecciones de integración

| Colección | Propósito | Nota |
|-----------|-----------|------|
| dian_facturas_procesadas | CUFEs procesados (anti-dup DIAN) | Índice único en CUFE |
| mercately_sessions | Sesiones de WhatsApp | — |
| mercately_config | Config de templates y API | — |
| alegra_credentials | Credenciales Alegra | — |
| sismo_knowledge | Knowledge Base Service | NO usar sismo_knowledge_base |

### 3F. Colecciones RADAR

| Colección | Propósito | Nota |
|-----------|-----------|------|
| acuerdos_pago | Acuerdos de pago con clientes | FASE 8-A |
| scoring_historico | Historial de scores | Futuro |

---

## 4. FASTAPI — Endpoints Backend

Base URL producción: https://sismo-backend-40ca.onrender.com

### 4A. Chat y agentes

| Método | Ruta | Archivo | Propósito |
|--------|------|---------|-----------|
| POST | /api/chat | ai_chat.py | Chat con agente (SSE streaming) |
| POST | /api/chat/document | ai_chat.py | Chat con documento adjunto |
| POST | /api/chat/approve-plan | chat.py | Aprobar plan pendiente (ExecutionCard) |

### 4B. Loanbook

| Método | Ruta | Archivo | Propósito |
|--------|------|---------|-----------|
| GET | /api/loanbook | loanbook.py | Lista todos los loanbooks |
| POST | /api/loanbook | loanbook.py | Crear loanbook nuevo |
| GET | /api/loanbook/auditoria | loanbook.py | Auditoría estructural del portafolio (BUILD 1) |
| GET | /api/loanbook/export-excel | loanbook.py | Descarga portafolio .xlsx con 2 hojas y flags corrupción (v3-B) |
| GET | /api/loanbook/stats | loanbook.py | KPIs de cartera (totales, mora, recaudo) |
| POST | /api/loanbook/reparar-todos | loanbook.py | Reparar inconsistencias en todo el portafolio (BUILD 3) |
| GET | /api/loanbook/{id} | loanbook.py | Detalle de un loanbook |
| PUT | /api/loanbook/{id} | loanbook.py | Edición canónica con auto-derivación de plan (BUILD 4) |
| PUT | /api/loanbook/{id}/entrega | loanbook.py | Activación canónica: pendiente_entrega→activo + cronograma (BUILD 4) |
| PUT | /api/loanbook/{id}/pago | loanbook.py | Pago canónico con waterfall ANZI completo (BUILD 4) |
| POST | /api/loanbook/{id}/reparar | loanbook.py | Reparar inconsistencias de un crédito (BUILD 3) |
| POST | /api/loanbook/{id}/gestion | loanbook.py | Registrar gestión de cobro |
| POST | /api/loanbook/{id}/ptp | loanbook.py | Registrar promesa de pago |
| PATCH | /api/loanbook/{id} | loanbook.py | [DEPRECATED] Edición manual — usar PUT /{id} |
| PATCH | /api/loanbook/{id}/cuotas/{n} | loanbook.py | [DEPRECATED] Corrección manual de cuota (Sprint Cobranza) |
| POST | /api/loanbook/{id}/registrar-pago | loanbook.py | [DEPRECATED] Pago manual — usar PUT /{id}/pago |
| POST | /api/loanbook/{id}/registrar-entrega | loanbook.py | [DEPRECATED] Entrega manual — usar PUT /{id}/entrega |

### 4C. RADAR

| Método | Ruta | Archivo | Propósito |
|--------|------|---------|-----------|
| GET | /api/radar/queue | radar.py | Cola de cobranza priorizada |
| GET | /api/radar/portfolio-health | radar.py | KPIs de cartera |
| GET | /api/radar/semana | radar.py | Resumen semanal |
| GET | /api/radar/roll-rate | radar.py | Roll rate de cartera |
| GET | /api/radar/diagnostico | radar.py | Diagnóstico del sistema RADAR |
| POST | /api/radar/arranque | radar.py | Activar RADAR |

### 4D. CFO

| Método | Ruta | Archivo | Propósito |
|--------|------|---------|-----------|
| GET | /api/cfo/semaforo | cfo.py | Semáforo financiero 5 dimensiones |
| GET | /api/cfo/informe-mensual | cfo.py | Último informe generado |
| POST | /api/cfo/generar | cfo.py | Generar informe bajo demanda |
| GET | /api/cfo/plan-accion | cfo.py | Plan de acción del mes |
| GET | /api/cfo/alertas | cfo.py | Alertas activas priorizadas |

### 4E. CRM

| Método | Ruta | Archivo | Propósito |
|--------|------|---------|-----------|
| GET | /api/crm | crm.py | Lista CRM con filtros |
| GET | /api/crm/{id} | crm.py | Ficha 360° del cliente |
| PUT | /api/crm/{id}/datos | crm.py | Actualizar datos personales |
| POST | /api/crm/{id}/nota | crm.py | Agregar nota del cobrador |

### 4F. Inventario

| Método | Ruta | Archivo | Propósito |
|--------|------|---------|-----------|
| GET | /api/inventario | inventario.py | Lista motos con filtros |
| GET | /api/inventario/{vin} | inventario.py | Detalle de una moto |
| POST | /api/inventario | inventario.py | Agregar moto nueva |
| PUT | /api/inventario/{vin} | inventario.py | Actualizar estado de moto |

### 4G. Conciliación bancaria

| Método | Ruta | Archivo | Propósito |
|--------|------|---------|-----------|
| POST | /api/conciliacion/cargar-extracto | bank_reconciliation.py | Subir extracto .xlsx |
| GET | /api/conciliacion/estado/{job_id} | bank_reconciliation.py | Estado del job background |
| GET | /api/conciliacion/historial | bank_reconciliation.py | Historial de conciliaciones |
| POST | /api/conciliacion/reintentar/{id} | bank_reconciliation.py | Reintentar movimiento fallido |

### 4H. Gastos masivos

| Método | Ruta | Archivo | Propósito |
|--------|------|---------|-----------|
| POST | /api/gastos/cargar-csv | gastos.py | Subir CSV de gastos |
| GET | /api/gastos/plantilla | gastos.py | Descargar plantilla 7 columnas |
| GET | /api/gastos/estado/{job_id} | gastos.py | Estado del job background |
| POST | /api/gastos/preview | gastos.py | Vista previa antes de causar |
| POST | /api/gastos/confirmar | gastos.py | Confirmar y causar lote |

### 4I. Backlog operativo

| Método | Ruta | Archivo | Propósito |
|--------|------|---------|-----------|
| GET | /api/backlog | backlog.py | Lista movimientos pendientes | 🔴 NUEVO Fase 1 |
| GET | /api/backlog/count | backlog.py | Conteo para badge | 🔴 NUEVO Fase 1 |
| POST | /api/backlog/{id}/causar | backlog.py | Causar movimiento manual | 🔴 NUEVO Fase 1 |

### 4J. Ventas / Facturación

| Método | Ruta | Archivo | Propósito |
|--------|------|---------|-----------|
| POST | /api/ventas/crear-factura | ventas.py | Crear factura en Alegra con VIN | 🔴 NUEVO Fase 1 |

### 4K. Reportes

| Método | Ruta | Archivo | Propósito |
|--------|------|---------|-----------|
| GET | /api/reportes/resumen-dia | reportes.py | KPIs del día |
| GET | /api/reportes/semana | reportes.py | Resumen semanal cobros |
| GET | /api/reportes/loanbooks | reportes.py | Tabla para dashboard |

### 4L. Settings

| Método | Ruta | Archivo | Propósito |
|--------|------|---------|-----------|
| GET | /api/settings/catalogo-motos | settings.py | Catálogo de motos y precios |
| PUT | /api/settings/catalogo-motos | settings.py | Actualizar catálogo |
| GET | /api/settings/mercately | settings.py | Config Mercately |
| PUT | /api/settings/mercately | settings.py | Actualizar config WhatsApp |
| GET | /api/settings/cfo | settings.py | Config CFO |

### 4M. Auth e infraestructura

| Método | Ruta | Archivo | Propósito |
|--------|------|---------|-----------|
| POST | /api/auth/login | auth.py | Login → JWT 7 días |
| POST | /api/auth/register | auth.py | Registro de usuario |
| GET | /health | main.py | Health check |

### 4N. Webhooks entrantes

| Método | Ruta | Archivo | Propósito |
|--------|------|---------|-----------|
| POST | /mercately/webhook | mercately.py | Recibir mensajes WhatsApp |
| POST | /api/webhooks/alegra | webhooks.py | Recibir eventos Alegra (12 tipos) |
| POST | /api/n8n/hooks/* | n8n_hooks.py | 9 endpoints n8n (BUILD 25) |
| POST | /api/webhooks/global66 | webhooks.py | Global66 con x-api-key |

---

## 5. FRONTEND — Rutas React

Base URL producción: https://sismo-bice.vercel.app

| Ruta | Componente | Propósito |
|------|-----------|-----------|
| /login | LoginPage.tsx | Autenticación |
| /chat | AgentChatPage.tsx | Chat con agente contador |
| /loanbook | LoanbookPage.tsx | Gestión de créditos |
| /loanbook/{id} | LoanbookDetailPage.tsx | Detalle de loanbook |
| /inventario | InventarioPage.tsx | Inventario de motos |
| /cargar-extracto | CargarExtractoPage.tsx | Subir extracto bancario |
| /radar | RadarPage.tsx | Cola de cobranza |
| /crm | CrmPage.tsx | CRM de clientes |
| /cfo | CfoPage.tsx | Dashboard CFO |
| /reportes | ReportesPage.tsx | Reportes y KPIs |
| /settings | SettingsPage.tsx | Configuración |
| /backlog | BacklogPage.tsx | Movimientos pendientes de causar | 🔴 NUEVO Fase 1 |

---

## 6. CRON JOBS / SCHEDULERS

Timezone: America/Bogota (UTC-5)
Motor: APScheduler en scheduler.py

| ID del job | Hora | Frecuencia | Función | Propósito |
|-----------|------|-----------|---------|-----------|
| calcular_dpd_todos | 06:00 AM | Diario | loanbook_service.calcular_dpd_todos() | DPD de cada loanbook |
| calcular_scores | 06:30 AM | Diario | loanbook_service.calcular_scores() | Scores A+ a E |
| generar_cola_cobranza | 07:00 AM | Diario | radar_service.generar_cola() | Cola priorizada RADAR |
| enviar_recordatorios_wa | 09:00 AM | Miércoles | mercately_service.enviar_recordatorios() | WhatsApp masivo cobro |
| resumen_semanal_cfo | 08:05 AM | Lunes | cfo_service.generar_resumen_semanal() | Resumen ejecutivo lunes |
| detectar_anomalias | 11:30 PM | Diario | cfo_service.detectar_anomalias() | Gastos inusuales, CXC vencida |
| dian_sync_diario | 11:00 PM | Diario | dian_service.sync_nocturno() | Causación facturas DIAN |
| alegra_polling_5min | Cada 5 min | Continuo | sincronizar_facturas_recientes() | Fallback webhooks Alegra |
| procesar_reintentos_alegra | Cada 5 min | Continuo | _procesar_reintentos_alegra() | Cola de reintentos 429/503 |
| alerta_mora_jueves | 10:00 AM | Jueves | mercately_service.alerta_mora() | Alerta mora D+1 |

---

## 7. WEBHOOKS ALEGRA (12 eventos configurados)

Estado: 🔴 0 de 12 activos en producción (URL incorrecta). Polling cada 5 min como fallback.

| Evento Alegra | Handler en SISMO | Qué hace |
|--------------|-----------------|----------|
| invoice.created | handle_invoice_created | Sincronizar inventario, detectar VIN |
| invoice.updated | handle_invoice_updated | Actualizar estado factura |
| invoice.deleted | handle_invoice_deleted | Revertir inventario → disponible |
| payment.created | handle_payment_created | Sincronizar cartera |
| bill.created | handle_bill_created | Registrar factura proveedor |
| journal.created | handle_journal_created | Log en roddos_events |
| journal.deleted | handle_journal_deleted | Log en roddos_events |
| contact.created | handle_contact_created | Sincronizar CRM |
| contact.updated | handle_contact_updated | Actualizar CRM |
| estimate.created | handle_estimate_created | Log |
| credit-note.created | handle_credit_note_created | Log |
| debit-note.created | handle_debit_note_created | Log |

---

## 8. MERCATELY — Templates WhatsApp

| Template | ID | Cuándo se envía | Variables |
|---------|----|-----------------|-----------|
| T1 | recordatorio_pago | Martes 9AM (previo al cobro) | nombre, cuota_numero, monto, fecha |
| T2 | confirmacion_entrega | Al entregar moto | nombre, modelo, vin |
| T3 | confirmacion_pago | Al registrar pago cuota | nombre, monto, saldo, proxima_fecha |
| T4 | alerta_mora | Jueves 10AM (D+1 sin pago) | nombre, dias_mora, monto_vencido |
| T5 | cuota_inicial | Al facturar venta | nombre, modelo, cuota_inicial, banco |

---

## 9. EVENTOS DEL BUS (roddos_events)

| event_type | Fuente | Quién reacciona |
|-----------|--------|----------------|
| factura.venta.creada | Contador | Inventario: moto→vendida, Loanbook: creado, RADAR: cuota inicial, WhatsApp T5 |
| moto.entregada | Contador | Loanbook: activo+cuotas, RADAR: cola activa, CFO: caché invalida |
| pago.cuota.registrado | Contador | Loanbook: cuota pagada, CFO: recaudo actualizado, WhatsApp T3 |
| gasto.causado | Contador | CFO: caché invalida |
| ingreso.causado | Contador | CFO: caché invalida |
| cxc.socio.registrada | Contador | CFO: activo corriente actualizado |
| mora.detectada | CFO cron | RADAR: prioridad sube, WhatsApp T4 |
| alegra.factura.detectada | Polling 5min | Inventario: sincronizado, CFO: caché invalida |
| dian.factura.causada | Cron 11pm | CFO: cuentas por pagar |
| inventario.moto.agregada | Polling | CFO: total disponibles |
| cleanup.journals.ejecutado | Contador | CFO: caché invalida |
| dian.sync.completado | Cron DIAN | Dashboard: badge sync |
| cfo.alerta.generada | CFO cron | Dashboard: badge alerta |
| factura.venta.anulada | Polling/webhook | Inventario: moto→disponible, Loanbook: cancelado |

---

## 10. VARIABLES DE ENTORNO

### Render (producción)

| Variable | Propósito | Nota |
|----------|-----------|------|
| MONGO_URL | Conexión MongoDB Atlas | mongodb+srv://sismo_admin:...@sismo-prod.rzebxlv.mongodb.net |
| DB_NAME | Nombre de la BD | sismo-prod |
| ALEGRA_EMAIL | Email Alegra | contabilidad@roddos.com |
| ALEGRA_TOKEN | Token API Alegra | 17a8a3b7016e1c15c514 |
| ANTHROPIC_API_KEY | API key Claude | Para el Agente Contador y otros agentes |
| N8N_API_KEY | API key n8n | Header X-N8N-Key |
| GLOBAL66_WEBHOOK_SECRET | Secret Global66 | Header x-api-key |
| MERCATELY_API_KEY | API key Mercately | ⚠️ Pendiente configurar |
| DIAN_MODO | Modo DIAN | "simulacion" o "alanube" |
| TOOL_USE_ENABLED | Feature flag Tool Use | true/false — rollback a ACTION_MAP |
| JWT_SECRET | Secret para JWT | Generado |

### Local (Windows PowerShell)

| Variable | Cómo setear |
|----------|------------|
| MONGO_URL | $env:MONGO_URL = "mongodb+srv://..." |
| DB_NAME | $env:DB_NAME = "sismo-prod" |

---

## 11. ARCHIVOS CLAVE DEL BACKEND

| Archivo | Propósito | Nota |
|---------|-----------|------|
| main.py | Entrypoint FastAPI, registro routers, CORS, middleware | Puerto 8000 |
| ai_chat.py | Router de agentes, SYSTEM_PROMPTS, process_chat() | Cerebro del sistema |
| accounting_engine.py | Motor matricial 50+ reglas, clasificación gastos | 78 cuentas Alegra |
| bank_reconciliation.py | Parsers 4 bancos, conciliación, retry logic | Anti-dup 3 capas |
| shared_state.py | Fuente única de verdad, caché 30s | Todos leen de aquí |
| event_bus.py | ELIMINADO en BUILD 24 — reemplazado por EventBusService | NO usar |
| database.py | Conexión MongoDB, patrón canónico | SIEMPRE leer primero |
| scheduler.py | APScheduler, cron jobs, timezone America/Bogota | Frágil en Render |
| auth.py | JWT 7 días, bcrypt, login/register | — |
| tool_executor.py | Ejecuta herramientas, confirm_pending_action() | Tool Use API |

---

## 12. PROTOCOLO DE ACTUALIZACIÓN

Cada vez que se crea algo nuevo en SISMO:
1. ANTES de crear: buscar en este archivo si ya existe
2. Si existe: usar la ruta/ID/colección existente
3. Si no existe: crear Y agregar a este archivo en el mismo commit
4. NUNCA hacer commit sin actualizar este archivo si se creó algo nuevo

El archivo vive en: .planning/SISMO_V2_Registro_Canonico.md

---

## 13. TABLA FIJA PLAN × MODALIDAD — PLAN_CUOTAS

**Fuente de verdad:** `backend/services/loanbook/reglas_negocio.py`

**REGLA INAMOVIBLE:** El número de cuotas es un contrato de negocio, NO una derivación matemática.
`round(39 / 2.2) = 18 ≠ 20`. Siempre usar la tabla, nunca la fórmula.

### 13A. Número de cuotas por plan × modalidad

| Plan | Semanal | Quincenal | Mensual | Observación |
|------|---------|-----------|---------|-------------|
| P15S | 15 | — | — | Comparendos/multas — solo semanal |
| P39S | 39 | 20 | 9 | Motos estándar ~9 meses |
| P52S | 52 | 26 | 12 | Motos estándar 1 año |
| P78S | 78 | 39 | 18 | Motos premium ~18 meses |

`None` = combinación no configurada → el auditor la reporta en `combinacion_no_configurada`.

### 13B. Multiplicadores de valor de cuota

| Modalidad | Factor vs cuota semanal | Días entre cobros |
|-----------|------------------------|-------------------|
| semanal | 1.0× | 7 días |
| quincenal | 2.2× | 14 días |
| mensual | 4.4× | 28 días |

### 13C. Constantes operativas

| Constante | Valor | Ubicación |
|-----------|-------|-----------|
| MORA_COP_POR_DIA | $2,000 COP/día | reglas_negocio.py |
| ANZI_PCT | 2% de cada pago | reglas_negocio.py |

### 13D. Regla fecha_pago

`fecha_pago > hoy` → HTTP 422 en todos los endpoints de pago (físicamente imposible).
Implementado en: `validar_fecha_pago()` → `PUT /{id}/pago`.

### 13E. Módulos que implementan esta tabla

| Módulo | Rol |
|--------|-----|
| `services/loanbook/reglas_negocio.py` | Fuente única — PLAN_CUOTAS + funciones puras |
| `services/loanbook/state_calculator.py` | Delega a `get_num_cuotas()` — recalcula campos derivados |
| `services/loanbook/auditor.py` | Detecta desviaciones vs tabla en el portafolio |
| `services/loanbook/reparador.py` | Corrige desviaciones via `recalcular_loanbook()` |
| `services/loanbook/excel_export.py` | Export .xlsx con comparación DB vs tabla |
| `frontend/src/pages/LoanDetailPage.tsx` | Espejo JS de PLAN_CUOTAS para live preview |

### 13F. Tests de cobertura

| Test | Archivo | Celdas verificadas |
|------|---------|-------------------|
| `test_P39S_quincenal_son_20` | test_reglas_negocio.py | P39S×quincenal=20 (el bug corregido) |
| `test_P52S_quincenal_son_26` | test_reglas_negocio.py | P52S×quincenal=26 |
| `test_valor_total_kreyser_P39S_quincenal` | test_reglas_negocio.py | 20×420k+1.46M=9.86M |
| `test_p52s_quincenal_tabla_fija_26` | test_state_calculator.py | recalcular_loanbook corrige a 26 |
| 58 tests total, todos GREEN | — | — |

---

## 14. BUILD B0 — Catálogos maestros en MongoDB (R-06)

**Branch:** `build/B1-schema-dual` (commit: f1e208d)
**Estado:** COMPLETO

### 14A. Cambios

| Archivo | Acción | Descripción |
|---------|--------|-------------|
| `services/loanbook/catalogo_service.py` | NUEVO | Cache en memoria de catálogos — `warm_catalogo()` async + lectura sync |
| `scripts/poblar_catalogos.py` | NUEVO | Pobla `catalogo_planes` (10 docs) y `catalogo_rodante` (4 docs) en MongoDB |
| `services/loanbook/reglas_negocio.py` | MODIFICADO | Eliminado `PLAN_CUOTAS` hardcoded → `_LazyPlanCuotas(dict)` proxy |
| `services/loanbook/state_calculator.py` | MODIFICADO | Eliminado `PLANES_RODDOS` hardcoded → `_LazyPlanesRoddos(dict)` proxy |
| `core/database.py` | MODIFICADO | `warm_catalogo(db)` en lifespan de FastAPI |
| `tests/conftest.py` | MODIFICADO | `seed_catalogos` fixture autouse session para tests unitarios |
| `tests/test_catalogo_service.py` | NUEVO | 48 tests del cache en memoria |

### 14B. Reglas implementadas

- **R-06:** `PLAN_CUOTAS` NUNCA hardcoded en Python. Solo fuente: `catalogo_planes` MongoDB.
- Los lazy dicts (`_LazyPlanCuotas`, `_LazyPlanesRoddos`) se auto-populan al primer acceso.
- `seed_for_tests()` permite tests unitarios sin MongoDB.

---

## 15. BUILD B1 — Schema dual RDX/RODANTE

**Branch:** `build/B1-schema-dual`
**Estado:** COMPLETO (pendiente ejecución en prod)

### 15A. Nuevos archivos

| Archivo | Descripción |
|---------|-------------|
| `models/__init__.py` | Paquete models |
| `models/loanbook_schema.py` | Pydantic schemas: 5 metadata classes + `LoanbookBase/Create/Update` |
| `scripts/migrar_loanbooks_a_schema_dual.py` | Migración idempotente — backup + expand schema + 4 colecciones |
| `services/loanbook/loanbook_service.py` | `registrar_acuerdo_pago()`, `registrar_cierre()`, `registrar_modificacion()` |
| `tests/test_loanbook_schema.py` | 52 tests del schema dual (todos GREEN) |

### 15B. Validaciones Pydantic (model_validator)

| Regla | Descripción | Error |
|-------|-------------|-------|
| R-06 | `plan_codigo` validado contra `catalogo_planes` en memoria | ValueError descriptivo |
| R-23 | RODANTE solo acepta `modalidad_pago='semanal'` | ValueError con "R-23" |
| — | RODANTE requiere `subtipo_rodante` | ValueError |
| — | RDX prohíbe `subtipo_rodante` | ValueError |
| P-07 | RODANTE+P78S/P52S/P39S rechazados | ValidationError |
| P-10 | RODANTE+quincenal/mensual rechazados | ValidationError |

### 15C. Metadata por producto/subtipo

| Producto/subtipo | Modelo Pydantic | Campos requeridos |
|-----------------|-----------------|-------------------|
| RDX | `MetadataRDX` | `moto_vin`, `moto_modelo` |
| RODANTE/repuestos | `MetadataRepuestos` | `referencia_sku`, `cantidad`, `valor_unitario`, `descripcion_repuesto` |
| RODANTE/soat | `MetadataSoat` | `poliza_numero`, `aseguradora`, `cilindraje_moto`, `vigencia_desde`, `vigencia_hasta`, `valor_soat`, `placa_cubierta` |
| RODANTE/comparendo | `MetadataComparendo` | `comparendo_numero`, `entidad_emisora`, `fecha_infraccion`, `valor_comparendo` |
| RODANTE/licencia | `MetadataLicencia` | `categoria_licencia`, `centro_ensenanza_nombre`, `centro_ensenanza_nit`, `fecha_inicio_curso`, `valor_curso` |

### 15D. Nuevos campos en documento loanbook

| Campo | Tipo | Default migración |
|-------|------|-------------------|
| `producto` | "RDX" \| "RODANTE" | inferido de `tipo_producto` |
| `subtipo_rodante` | enum \| null | inferido de `tipo_producto` |
| `metadata_producto` | dict | construido de campos sueltos (vin, modelo, motor, placa) |
| `saldo_intereses` | float | 0.0 |
| `score_riesgo` | enum \| null | null |
| `whatsapp_status` | enum | "pending" |
| `sub_bucket_semanal` | enum \| null | null |
| `fecha_vencimiento` | date \| null | última cuota |
| `acuerdo_activo_id` | str \| null | null |

### 15E. Nuevas colecciones

| Colección | Índice | Checklist |
|-----------|--------|-----------|
| `inventario_repuestos` | `referencia_sku` (unique) | C-04 |
| `loanbook_acuerdos` | `(loanbook_id, created_at)` | C-05 |
| `loanbook_cierres` | `loanbook_codigo` (unique) | C-06 |
| `loanbook_modificaciones` | `(loanbook_id, ts)` | C-07 |

### 15F. LTV auto-cálculo

Para `LoanbookCreate` con `producto='RDX'`:
```python
ltv = round(monto_original / moto_valor_origen, 3)
```
Solo cuando `moto_valor_origen > 0`. Campo `ltv` inyectado en `metadata_producto`.

### 15G. Tests

| Suite | Tests | Estado |
|-------|-------|--------|
| `test_loanbook_schema.py` | 52 | ✅ GREEN |
| `test_catalogo_service.py` | 48 | ✅ GREEN |
| Regresiones vs baseline | 0 | ✅ Sin regresión |
