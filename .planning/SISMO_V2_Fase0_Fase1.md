# SISMO V2 — Objetivo Primario

## Fase 0 + Fase 1: Especificación Ejecutable

RODDOS S.A.S. — Abril 2026

---

## Tesis

SISMO no avanza hasta que el dinero fluya correctamente. Cada peso que entra o sale de RODDOS debe quedar como un registro verificado en Alegra. Sin eso, el CFO está ciego, el RADAR no tiene ingresos que monitorear, y cualquier agente nuevo opera sobre datos incorrectos.

Fase 0 construye los cimientos que previenen los loops del pasado. Fase 1 construye las 9 capacidades del Agente Contador más el módulo Backlog operativo que hacen posible un P&L automático y correcto. Todo lo demás es Backlog de proyecto — se construye después, progresivamente.

**Criterio de éxito único:** El estado de resultados de RODDOS en Alegra refleja la realidad del negocio sin intervención manual.

---

## FASE 0 — Cimientos Arquitectónicos

Fase 0 no produce funcionalidad visible para el usuario. Produce la infraestructura interna que evita que los builds de Fase 1 generen los mismos problemas del pasado: identidades de agentes mezcladas, permisos que solo existen en el prompt, acciones sin verificación.

### C1. Router con threshold de confianza 0.70

**Qué es:** El router en `ai_chat.py` detecta el intent del mensaje del usuario y lo despacha al agente correcto. Hoy despacha siempre, sin importar qué tan ambiguo sea el mensaje.

**Qué cambia:** Si la confianza del router es menor a 0.70, en lugar de despachar al agente equivocado, le pregunta al usuario: "¿Esto es un tema contable, de cartera o financiero?" Una sola pregunta.

**Sin esto:** El CFO responde preguntas del Contador. El Contador responde preguntas del RADAR. Las identidades se mezclan y el usuario pierde confianza en el sistema.

**Criterio de aceptación:**
- Prompt "registra este gasto" llega al Contador con confianza ≥ 0.70
- Prompt "¿cuál es el P&L?" llega al CFO con confianza ≥ 0.70
- Prompt ambiguo "revisa esto" genera pregunta de clarificación, no despacho erróneo

---

### C2. System prompts diferenciados por agente

**Qué es:** Cada agente recibe su propio bloque de identidad como system message — no como contexto conversacional mezclado. El dict `SYSTEM_PROMPTS` en `ai_chat.py` tiene una entrada por agente con: identidad, dominio exclusivo, voz, herramientas permitidas y prohibidas.

**Qué cambia:** Hoy los agentes comparten contexto de forma parcial. Con system prompts diferenciados, el Contador sabe que es el Contador y solo responde dentro de su dominio. El CFO sabe que es analista — nunca ejecutor.

**Sin esto:** El agente con más contexto en memoria domina las respuestas. El CFO empieza a clasificar gastos. El Contador empieza a opinar sobre estrategia.

**Implementación:**
```
SYSTEM_PROMPTS = {
    'contador': SYSTEM_PROMPT_CONTADOR,
    'cfo':      SYSTEM_PROMPT_CFO,
    'radar':    SYSTEM_PROMPT_RADAR,
    'loanbook': SYSTEM_PROMPT_LOANBOOK,
}
```

**Criterio de aceptación:**
- Test: enviar prompt contable al CFO → el CFO rechaza y sugiere al Contador
- Test: enviar prompt analítico al Contador → el Contador rechaza y sugiere al CFO
- Cada agente se identifica correctamente cuando se le pregunta "¿quién eres?"

---

### C3. WRITE_PERMISSIONS en código — no en narrativa

**Qué es:** Una función `validate_write_permission(agent, collection)` que verifica en código si un agente tiene permiso de escritura en una colección o endpoint antes de ejecutar. Si no tiene permiso, lanza `PermissionError` — el LLM no puede razonar alrededor de una restricción en código.

**Qué cambia:** Hoy los permisos solo existen en la narrativa del system prompt. El LLM puede decidir ignorarlos si el contexto lo lleva en esa dirección. Con permisos en código, el CFO es *físicamente incapable* de escribir en Alegra.

**Mapa de permisos:**

| Agente | Colecciones con permiso de escritura | Endpoints Alegra |
|--------|--------------------------------------|-----------------|
| Contador | cartera_pagos, cxc_socios, cxc_clientes, plan_cuentas_roddos, inventario_motos | POST /journals, POST /invoices, POST /payments |
| CFO | cfo_informes, cfo_alertas | Solo GET |
| RADAR | crm_clientes, gestiones_cobranza | Ninguno |
| Loanbook | inventario_motos, loanbook | Ninguno |
| Todos | roddos_events (append-only) | — |

**Sin esto:** El CFO puede causar asientos si el LLM decide que es "urgente". El RADAR puede modificar loanbooks. Cualquier agente puede escribir donde no debe.

**Criterio de aceptación:**
- Test: CFO intenta POST /journals → PermissionError
- Test: RADAR intenta escribir en cartera_pagos → PermissionError
- Test: Contador escribe en cartera_pagos → éxito

---

### C4. Tool Use nativo (Anthropic API)

**Qué es:** Migración del patrón ACTION_MAP actual (el agente responde texto + acción detectada, luego el dispatcher la enruta) al patrón nativo de Tool Use de la API de Anthropic. En lugar de que el LLM genere texto con una acción implícita, el LLM llama explícitamente a una herramienta tipada con parámetros validados.

**Qué cambia:** El agente deja de "describir" lo que quiere hacer y pasa a "llamar" directamente la herramienta correcta con los parámetros correctos. Menos errores de parsing, menos ambigüedad, tipado fuerte en los inputs.

**Feature flag:** `TOOL_USE_ENABLED` en variables de entorno. Si es `false`, el sistema usa ACTION_MAP como fallback. Esto permite rollback sin riesgo.

**Sin esto:** El parsing de acciones desde texto natural sigue siendo frágil. El dispatcher tiene que adivinar la intención del agente a partir de texto generado.

**Criterio de aceptación:**
- Las 32 herramientas del Agente Contador están definidas como tools de Anthropic
- El agente llama `registrar_gasto(cuenta_id, monto, descripcion, retenciones)` en lugar de generar texto que dice "quiero registrar un gasto"
- Feature flag permite rollback a ACTION_MAP

---

### C5. Bus de eventos funcional

**Qué es:** La colección `roddos_events` en MongoDB opera como un append-only log. Cada agente publica eventos después de cada acción exitosa. Otros agentes consumen esos eventos para reaccionar.

**Qué cambia:** Hoy el bus existe pero su uso es inconsistente. Con Fase 0, cada escritura exitosa en Alegra genera un evento obligatorio. El CFO se entera de cada gasto causado. El RADAR se entera de cada pago registrado.

**Schema de evento (inmutable):**
```
{
  event_id:        UUID v4,
  event_type:      "gasto.causado" | "factura.venta.creada" | "pago.cuota.registrado" | ...,
  source:          "agente_contador" | "radar" | "cfo" | ...,
  correlation_id:  UUID del request original,
  timestamp:       ISO 8601 UTC,
  datos:           { payload específico del evento },
  alegra_id:       string | null,
  accion_ejecutada: "Journal arrendamiento $3.614.953 causado"
}
```

**Criterio de aceptación:**
- Toda escritura exitosa en Alegra genera un evento
- El CFO invalida su caché al consumir un evento financiero
- Los eventos son inmutables — nadie los modifica ni borra

---

### C6. request_with_verify() como patrón único

**Qué es:** Toda operación de escritura en Alegra sigue el mismo patrón: POST → esperar respuesta → GET de verificación → solo si HTTP 200, reportar éxito. Sin esta verificación, el registro no existe.

**Qué cambia:** Ya está implementado desde BUILD 21, pero Fase 0 lo formaliza como el único camino aceptable. Ninguna escritura en Alegra puede saltarse esta verificación.

**El patrón:**
1. POST al endpoint correcto (/journals, /invoices, /payments)
2. Verificar HTTP 200/201 en la respuesta
3. GET al mismo registro para confirmar que existe
4. Si el GET no confirma → el registro no se creó → retry o escalar
5. Solo después de la verificación → reportar éxito con el ID de Alegra

**Sin esto:** El agente reporta "gasto registrado" cuando en realidad Alegra no lo creó. Fue el bug más costoso del proyecto: 176 journals duplicados.

**Criterio de aceptación:**
- Ningún endpoint de escritura en Alegra funciona sin request_with_verify()
- Si Alegra retorna error, el usuario ve un mensaje en español explicando qué pasó
- El ID de Alegra se retorna siempre como evidencia auditable

---

## FASE 1 — Agente Contador Completo

Fase 1 construye las 8 capacidades que le dan al Agente Contador la capacidad de capturar todo el flujo financiero de RODDOS. Cada capacidad produce journals o facturas verificadas en Alegra. La suma de todas las capacidades produce un P&L correcto.

### Capacidad 1: Egresos por chat

**Qué hace:** El usuario describe un gasto en lenguaje natural. El agente clasifica, calcula retenciones y propone el asiento completo antes de ejecutar.

**Flujo:**
1. Usuario: "Pagamos arriendo $3.614.953"
2. Agente clasifica → Arrendamientos (ID 5480)
3. Agente calcula → ReteFuente 3.5% = $126.523 + ReteICA 0.414% = $14.966
4. Agente propone → DÉBITO 5480 $3.614.953 / CRÉDITO ReteFte $126.523 / CRÉDITO ReteICA $14.966 / CRÉDITO Banco $3.473.464
5. Usuario confirma
6. POST /journals → request_with_verify() → ID retornado
7. Evento al bus → CFO invalida caché

**Endpoint Alegra:** POST /journals

**Reglas críticas:**
- Motor matricial de 50+ reglas para clasificación automática
- Auteco NIT 860024781 = autoretenedor → NUNCA ReteFuente
- Máximo 1 pregunta por turno si falta información
- Plan de cuentas desde plan_cuentas_roddos — nunca ID hardcodeado
- Fallback: ID 5493 (Gastos Generales) — NUNCA 5495
- Gasto de socio (Andrés CC 80075452, Iván CC 80086601) = CXC socios, NUNCA gasto operativo

**Criterio de aceptación:**
- Gasto natural → asiento correcto con retenciones → ID Alegra verificado
- Arrendamiento con ReteFuente 3.5% y ReteICA 0.414% calculados automáticamente
- Gasto socio clasificado como CXC, no como gasto operativo

---

### Capacidad 2: Conciliación bancaria y procesamiento de movimientos

**Qué hace:** Dos vías de entrada para movimientos bancarios:
- **Masiva:** El usuario sube un extracto bancario en formato .xlsx. El sistema parsea, clasifica y causa.
- **Individual:** El usuario describe un movimiento por chat: "El débito de $450.000 en Bancolombia es el pago del seguro". El agente clasifica y causa.

En ambos casos, el motor matricial clasifica con confianza 0-1. Lo que no se logra causar automáticamente va al módulo Backlog.

**Flujo masivo (extracto):**
1. Usuario sube archivo .xlsx (BBVA, Bancolombia, Davivienda o Nequi)
2. Parser identifica el banco por formato de headers
3. Motor matricial clasifica cada movimiento con confianza 0-1
4. Movimientos con confianza ≥ 0.70 → causación automática
5. Movimientos con confianza < 0.70 → WhatsApp a CEO+CGO para aclaración
6. Si WhatsApp no resuelve → movimiento va al módulo Backlog
7. BackgroundTasks con job_id para el lote completo
8. Anti-duplicados en 3 capas: hash extracto + hash movimiento + GET Alegra

**Flujo individual (chat):**
1. Usuario: "El débito de $450.000 en Bancolombia del 15 de marzo es el pago del seguro anual"
2. Agente clasifica → Seguros (ID 5510)
3. Agente propone asiento con retenciones si aplican
4. Usuario confirma → POST /journals → verificar

**Tres destinos posibles para cada movimiento (nunca /dev/null):**
- **Causado:** confianza ≥ 0.70 o aclarado por chat/WhatsApp → journal en Alegra
- **Pendiente WhatsApp:** confianza < 0.70 → pregunta enviada, esperando respuesta
- **Backlog:** sin respuesta de WhatsApp, error de Alegra, o clasificación imposible → módulo Backlog para causación manual

**Endpoint Alegra:** POST /journals (masivo, en lotes de 10)

**Formatos de extracto:**
| Banco | Headers row | Columnas clave |
|-------|------------|----------------|
| Bancolombia | 15 (sheet "Extracto") | FECHA (d/m), DESCRIPCIÓN, VALOR |
| BBVA | 14 | FECHA DE OPERACIÓN (DD-MM-YYYY), CONCEPTO, IMPORTE (COP) |
| Davivienda | skiprows=4 | Fecha, Descripción, Valor, Naturaleza (C/D) |
| Nequi | — | (formato pendiente de documentar) |

**Reglas críticas:**
- SIEMPRE .xlsx — nunca CSV
- BackgroundTasks + job_id obligatorio (lotes > 10)
- Anti-duplicados: hash MD5 por extracto (Capa 1) + hash MD5 por movimiento (Capa 2) + GET Alegra post-POST (Capa 3)
- Retry con exponential backoff para errores 429/503 de Alegra
- Ningún movimiento se descarta silenciosamente — va a causado (≥70%) o pendiente (<70%)

**Criterio de aceptación:**
- Extracto de 100 movimientos procesado en < 60 segundos
- Cero duplicados al subir el mismo extracto dos veces
- Movimientos ambiguos generan notificación WhatsApp, no causación incorrecta

---

### Capacidad 3: Nómina mensual

**Qué hace:** Registra la nómina mensual discriminada por empleado como journals individuales en Alegra. Anti-duplicados por mes + empleado.

**Flujo:**
1. Usuario indica nómina del mes (o el sistema la sugiere al inicio de mes)
2. Agente propone el desglose: empleado, salario, retenciones SGSSS
3. Usuario confirma
4. Un journal por empleado → POST /journals → verificar

**Datos de referencia (actualizables):**
- Enero 2026: Alexa $3.220.000 + Luis $3.220.000 + Liz $1.472.000
- Febrero 2026: Alexa $4.500.000 + Liz $2.200.000

**Endpoint Alegra:** POST /journals

**Reglas críticas:**
- Anti-duplicados: verificar por mes + nombre empleado antes de causar
- Cuenta: Sueldos 510506 (ID 5462)
- Seguridad social en cuenta separada (ID 5471)
- Si el empleado ya fue registrado ese mes → bloquear y avisar

**Criterio de aceptación:**
- Nómina de febrero causada correctamente con 2 empleados
- Intentar causar febrero dos veces → bloqueo por anti-duplicados
- Cada empleado tiene su journal individual, no un lote agrupado

---

### Capacidad 4: CXC socios

**Qué hace:** Los retiros y gastos personales de Andrés (CC 80075452) e Iván (CC 80086601) se registran como Cuentas por Cobrar a socios — nunca como gastos operativos. El saldo es consultable en tiempo real.

**Flujo:**
1. Usuario: "Andrés retiró $620.000 de BBVA para gastos personales"
2. Agente pregunta: "¿Es anticipo de nómina o gasto personal?"
3. Usuario: "Gasto personal, va como CXC"
4. Agente: DÉBITO CXC Andrés / CRÉDITO Banco BBVA
5. POST /journals → verificar → actualizar saldo en cxc_socios

**Endpoint Alegra:** POST /journals

**Reglas críticas:**
- NUNCA causar retiros de socio como gasto operativo — distorsiona el P&L
- CXC va al balance general, no al estado de resultados
- Saldo consultable: "¿Cuánto debe Andrés?" → respuesta con monto exacto

**Criterio de aceptación:**
- Retiro de socio causado como CXC, no como gasto
- Saldo consultable: "¿Cuánto debe Andrés?" → "$X.XXX.XXX pendiente"
- Abonos reducen el saldo correctamente

---

### Capacidad 5: Facturación directa en Alegra

**Qué hace:** El Agente Contador crea facturas de venta de motos directamente en Alegra via POST /invoices. Esto es el corazón del flujo de ingresos — sin factura no hay venta, sin venta no hay loanbook, sin loanbook no hay cartera.

**Flujo:**
1. Usuario: "Facturar TVS Raider 125 Negro a Juan Pérez CC 1234567, plan P52S"
2. Agente valida: moto existe en inventario_motos con estado "disponible"
3. Agente valida: VIN y motor presentes (obligatorios)
4. Agente construye factura con formato obligatorio en el ítem:
   `"TVS Raider 125 Negro Nebulosa - VIN: 9FL25AF31VDB95058 / Motor: BF3AT18C2356"`
5. Agente muestra vista previa completa: cliente, moto, plan, cuota inicial, cuota semanal
6. Usuario confirma
7. POST /invoices → request_with_verify() → ID factura retornado
8. Cascada automática:
   - inventario_motos: moto → "vendida"
   - loanbook: nuevo registro en estado "pendiente_entrega"
   - roddos_events: "factura.venta.creada"
   - CFO: caché invalidado
   - WhatsApp: Template 5 al cliente (cuota inicial)

**Endpoint Alegra:** POST /invoices

**Datos del ítem (obligatorios):**
| Campo | Valor | Si falta |
|-------|-------|---------|
| VIN | Número de chasis real | Bloqueo total — no facturar |
| Motor | Número de motor real | Bloqueo total — no facturar |
| Formato ítem | "[Modelo] [Color] - VIN: [x] / Motor: [x]" | El polling no detecta el VIN |
| Plan | P39S, P52S, P78S | No se puede crear loanbook |
| Cliente | Nombre + cédula | No se crea contacto en Alegra |

**Planes de crédito (desde catalogo_planes en MongoDB — nunca hardcodeados):**
| Plan | Cuotas | Cuota semanal Sport | Cuota semanal Raider |
|------|--------|--------------------|--------------------|
| P39S | 39 | $175.000 | $210.000 |
| P52S | 52 | $160.000 | $179.900 |
| P78S | 78 | $130.000 | $149.900 |

**Multiplicadores por frecuencia:** Semanal ×1.0 (base), Quincenal ×2.2, Mensual ×4.4

**Reglas críticas:**
- VIN y motor son campos obligatorios — sin ellos NO se factura
- El formato del ítem es exacto — sin él el polling no puede sincronizar
- La moto debe estar en estado "disponible" — si está en otro estado, bloqueo total
- Auteco NIT 860024781 = autoretenedor → nunca ReteFuente en compras
- Al crear la factura, la moto pasa a "vendida" inmediatamente
- El loanbook se crea en estado "pendiente_entrega" — sin fechas de cuota aún

**Criterio de aceptación:**
- Factura de venta creada en Alegra con VIN en el ítem → ID retornado
- Moto cambia a "vendida" en inventario
- Loanbook creado en "pendiente_entrega"
- Intentar facturar moto ya vendida → bloqueo
- Intentar facturar sin VIN → bloqueo
- Evento "factura.venta.creada" publicado en el bus

---

### Capacidad 6: Ingresos por cuotas de cartera — asiento contable obligatorio

**Qué hace:** Cada pago de cuota genera DOS operaciones en Alegra — no una. Primero el payment contra la factura de venta (Alegra sabe que le pagaron), luego el journal de ingreso (el P&L ve el recaudo). Sin el journal, el pago existe pero no aparece en el estado de resultados.

**Flujo:**
1. Pago recibido (informado por usuario o RADAR)
2. Agente identifica el loanbook y la cuota correspondiente
3. **Operación A:** POST /payments contra la factura de venta → request_with_verify()
4. **Operación B:** POST /journals → asiento de ingreso financiero → request_with_verify()
   - DÉBITO: Banco donde se recibió el pago (Bancolombia 111005, BBVA 111010, etc.)
   - CRÉDITO: Ingresos financieros (cuenta de plan_ingresos_roddos)
5. Ambas operaciones verificadas con HTTP 200
6. loanbook: cuota marcada como "pagada", saldo actualizado
7. Evento: "pago.cuota.registrado"
8. CFO invalida caché de recaudo

**Endpoints Alegra:** POST /payments + POST /journals (las dos)

**Reglas críticas:**
- Sin el journal, el payment existe pero el P&L NO refleja el ingreso — el CFO sigue ciego
- El pago se asocia a la factura de venta del loanbook (no es un journal suelto)
- La cuota se marca como pagada solo después de verificación de AMBAS operaciones
- Mora: $2.000 COP/día, empieza el jueves (día después del miércoles de vencimiento)

**Criterio de aceptación:**
- Pago de cuota genera payment + journal en Alegra → ambos IDs retornados
- El P&L refleja el ingreso financiero por la cuota pagada
- Cuota marcada como pagada en el loanbook
- Saldo del loanbook actualizado
- CFO ve el ingreso reflejado inmediatamente

---

### Capacidad 7: Ingresos no operacionales

**Qué hace:** Registra ingresos que no son de ventas de motos ni de cuotas: ventas de motos recuperadas, intereses bancarios, otros ingresos.

**Flujo:**
1. Usuario: "Recibimos $3.700.000 por venta de motos recuperadas a Motos del Trópico"
2. Agente clasifica → cuenta de plan_ingresos_roddos
3. Propone asiento → DÉBITO Banco / CRÉDITO Ingreso no operacional
4. POST /journals → verificar

**Endpoint Alegra:** POST /journals

**Cuentas de ingreso (desde plan_ingresos_roddos):**
- Ingresos financieros (intereses bancarios)
- Ventas especiales (motos recuperadas)
- Otros ingresos no operacionales

**Criterio de aceptación:**
- Ingreso no operacional causado en la cuenta correcta de plan_ingresos_roddos
- El P&L refleja el ingreso en "otros ingresos"

---

### Capacidad 8: Módulo Backlog operativo — la red de seguridad

**Qué es:** Un módulo en la interfaz de SISMO donde llegan todos los movimientos y transacciones que el Agente Contador no logró causar automáticamente. Es la garantía de que ningún movimiento se pierde — todo termina causado o en el Backlog esperando causación manual.

**Qué llega al Backlog:**
- Movimientos bancarios con confianza < 0.70 que no se resolvieron por WhatsApp
- Movimientos donde Alegra retornó error y los reintentos se agotaron
- Movimientos que el agente no pudo clasificar ni con la ayuda de Andrés
- Cualquier causación que falle en cualquier punto del proceso

**Flujo del Backlog:**
1. Movimiento llega al Backlog con: fecha, descripción, monto, banco de origen, razón de por qué no se causó
2. El módulo muestra una lista priorizada por antigüedad (los más viejos primero)
3. Badge en el menú lateral: "Backlog (298)" — el número es visible siempre
4. Liz (u otro operador) abre el movimiento → ve la descripción original del banco
5. El modal "Causar" permite: seleccionar cuenta contable, ajustar retenciones, confirmar
6. Al confirmar → POST /journals → request_with_verify() → movimiento sale del Backlog
7. Si falla de nuevo → vuelve al Backlog con el error actualizado

**Estado actual:** Liz está conciliando 298 movimientos pendientes (BBVA 33, Bancolombia 188, Nequi 76) de enero-febrero via el modal Causar. Este módulo formaliza y mejora ese flujo.

**Datos que muestra el Backlog por movimiento:**
| Campo | Ejemplo |
|-------|---------|
| Fecha del movimiento | 2026-01-15 |
| Banco de origen | Bancolombia |
| Descripción original | "PAGO PSE NEQUI 450000" |
| Monto | $450.000 |
| Tipo | Débito / Crédito |
| Razón de pendiente | "Confianza 0.45 — clasificación ambigua" |
| Intentos previos | 2 (WhatsApp sin respuesta + retry fallido) |
| Fecha de ingreso al Backlog | 2026-01-16 |

**Reglas críticas:**
- El Backlog debe tener un badge visible en el menú lateral — siempre
- Los movimientos más antiguos tienen prioridad visual
- Al causar desde el Backlog, se aplica el mismo request_with_verify() que en causación automática
- El movimiento solo sale del Backlog cuando tiene un ID de Alegra verificado
- Bug conocido: `pago_pse_nequi` en accounting_engine.py carece de `cuenta_debito` → movimientos Nequi caen al Backlog innecesariamente. Corregir en Fase 1.

**Criterio de aceptación:**
- Módulo visible en el menú con badge de conteo
- Movimiento no causado automáticamente → aparece en el Backlog
- Causar desde el Backlog → journal en Alegra con ID verificado
- Movimiento causado sale del Backlog
- Filtros: por banco, por fecha, por razón de pendiente

---

### Capacidad 9: P&L automático

**Qué hace:** El CFO Estratégico construye el estado de resultados leyendo directamente de Alegra. Esta capacidad es el *resultado* de las 7 anteriores — si alguna falta, el P&L tiene agujeros.

**Flujo:**
1. CFO consulta GET /journals + GET /invoices + GET /payments en Alegra
2. Separa ingresos operacionales (ventas motos), ingresos financieros (cuotas), otros ingresos
3. Separa gastos operativos, nómina, retenciones
4. CXC socios NO afecta P&L — va al balance
5. Calcula utilidad/pérdida del período
6. Compara devengado (Alegra) vs caja (extractos bancarios) — nunca los mezcla

**Endpoints Alegra:** GET /journals, GET /invoices, GET /payments, GET /categories

**Reglas críticas:**
- IVA es cuatrimestral: ene-abr / may-ago / sep-dic — nunca bimestral
- Separar siempre devengado (Sección A) de caja real (Sección B)
- Invalidar cfo_cache antes de generar informe
- CXC socios → balance general, nunca estado de resultados

**Criterio de aceptación:**
- P&L del mes muestra ingresos + gastos con desglose correcto
- CXC socios NO aparece en gastos
- El P&L cuadra con los journals y facturas reales en Alegra
- CFO puede generar el informe sin intervención manual

---

## Reglas de Oro — Prevención de Loops

Estas reglas existen porque cada una fue aprendida después de un incidente costoso. Violarlas es volver a los mismos loops que nos arrastraron al fracaso antes.

| # | Regla | El incidente que la originó |
|---|-------|-----------------------------|
| ROG-1 | Nunca reportar éxito sin HTTP 200 en Alegra | El agente reportó éxito falso → 176 journals duplicados |
| ROG-2 | Sin atajos. Cada build deja el sistema mejor | Shortcuts generaron deuda técnica acumulada |
| ROG-3 | Todo funciona desde SISMO — no scripts externos | PowerShell parches que no se integraron |
| R4 | Endpoint correcto: /journals — NO /journal-entries | /journal-entries da 403. Costó un build descubrirlo |
| R5 | BackgroundTasks + job_id para lotes > 10 | Timeout silencioso reportó éxito falso |
| R6 | Anti-duplicados 3 capas | 176 duplicados costaron horas de limpieza |
| R7 | IVA cuatrimestral — NO bimestral | Error frecuente en cálculos tributarios |
| R9 | VIN y motor obligatorios en toda factura de moto | Sin VIN el inventario no se actualiza |
