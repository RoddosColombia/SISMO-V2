# SISMO V2 — Plan de Ejecución

## Secuencia obligatoria: Fase 0 completa ANTES de cualquier tarea de Fase 1

---

## FASE 0 — Cimientos Arquitectónicos (6 tareas)

### F0-T1: System prompts diferenciados

CONTEXTO: Hoy los agentes comparten contexto parcialmente. El CFO respondió un prompt del Contador porque no tiene identidad diferenciada.

ACCIÓN:
1. Crear constantes SYSTEM_PROMPT_CONTADOR, SYSTEM_PROMPT_CFO, SYSTEM_PROMPT_RADAR, SYSTEM_PROMPT_LOANBOOK con los textos definidos en SISMO_V2_System_Prompts.md
2. Crear dict SYSTEM_PROMPTS en ai_chat.py que mapea agent_type → prompt
3. Modificar build_agent_prompt() para que use SYSTEM_PROMPTS[agent_type] + shared_context
4. Cada prompt es system message, no contexto conversacional

TEST:
- Enviar "registra este gasto" → el Contador responde, no el CFO
- Enviar "¿cuál es el P&L?" → el CFO responde, no el Contador
- Preguntar a cada agente "¿quién eres?" → responde con su identidad correcta

---

### F0-T2: Router con threshold 0.70

CONTEXTO: El router despacha siempre sin importar la confianza. Resultado: el agente equivocado responde prompts ambiguos.

ACCIÓN:
1. En process_chat(), después de detectar intent, verificar confidence score
2. Si confidence >= 0.70 → despachar al agente detectado
3. Si confidence < 0.70 → NO despachar. Responder al usuario: "¿Esto es un tema contable, de cartera o de análisis financiero?" (una sola pregunta)
4. El usuario responde → re-evaluar con el contexto adicional

TEST:
- Prompt claro "registra gasto arriendo" → despacho directo al Contador (confianza >= 0.70)
- Prompt ambiguo "revisa esto" → pregunta de clarificación, no despacho erróneo
- Prompt claro "¿quién debe pagar hoy?" → despacho directo al RADAR

---

### F0-T3: WRITE_PERMISSIONS en código

CONTEXTO: Los permisos solo existen en la narrativa del prompt. El LLM puede ignorarlos.

ACCIÓN:
1. Crear dict WRITE_PERMISSIONS en ai_chat.py (ver SISMO_V2_System_Prompts.md para el mapa completo)
2. Crear función validate_write_permission(agent_type, target, operation) que lanza PermissionError si no tiene permiso
3. Llamar validate_write_permission() ANTES de toda operación de escritura en MongoDB y Alegra
4. El PermissionError se captura y se muestra al usuario: "El agente CFO no tiene permiso de escritura en Alegra"

TEST:
- CFO intenta POST /journals → PermissionError
- RADAR intenta escribir en cartera_pagos → PermissionError
- Contador escribe en cartera_pagos → éxito
- Loanbook escribe en inventario_motos → éxito

---

### F0-T4: Tool Use nativo (Anthropic API)

CONTEXTO: Hoy el agente genera texto con acciones implícitas y ACTION_MAP las parsea. Es frágil.

ACCIÓN:
1. Definir las herramientas del Agente Contador como tools de Anthropic:
   - registrar_gasto(cuenta_id, monto, descripcion, banco, retenciones)
   - crear_factura_venta(cliente_nombre, cliente_cedula, moto_vin, plan, cuota_inicial)
   - registrar_pago_cuota(loanbook_id, cuota_numero, monto, banco, metodo_pago)
   - registrar_nomina(mes, año, empleados[])
   - registrar_cxc_socio(socio_cedula, monto, banco, descripcion)
   - registrar_ingreso_no_operacional(tipo, monto, banco, descripcion)
   - causar_movimiento_bancario(movimiento_id, cuenta_id, descripcion)
   - consultar_saldo_cxc(socio_cedula)
   - consultar_plan_cuentas()
2. Crear variable de entorno TOOL_USE_ENABLED (default: true)
3. Si TOOL_USE_ENABLED=false → fallback a ACTION_MAP existente
4. El agente llama tools con parámetros tipados en vez de generar texto para parsear

TEST:
- Gasto por chat → el agente llama registrar_gasto() con parámetros correctos
- Factura de moto → el agente llama crear_factura_venta() con VIN
- Feature flag false → sistema usa ACTION_MAP como antes

---

### F0-T5: Bus de eventos funcional

CONTEXTO: roddos_events existe pero su uso es inconsistente. No todas las escrituras publican eventos.

ACCIÓN:
1. Crear EventPublisher como servicio centralizado que publica eventos con el schema estándar:
   { event_id, event_type, source, correlation_id, timestamp, datos, alegra_id, accion_ejecutada }
2. Llamar EventPublisher.publish() después de TODA escritura exitosa en Alegra
3. El CFO consume eventos financieros → invalida cfo_cache
4. Los eventos son inmutables — append-only, nadie los modifica

TEST:
- Causar un gasto → evento gasto.causado aparece en roddos_events
- Crear factura → evento factura.venta.creada aparece
- Registrar pago → evento pago.cuota.registrado aparece
- CFO cache se invalida al detectar evento financiero

---

### F0-T6: request_with_verify() como patrón único

CONTEXTO: Ya está implementado desde BUILD 21. Fase 0 lo formaliza como el ÚNICO camino.

ACCIÓN:
1. Auditar TODO el código que hace POST/DELETE a Alegra
2. Verificar que CADA operación usa request_with_verify()
3. Si hay algún endpoint que no lo usa → corregir
4. El patrón: POST → verificar HTTP 200/201 → GET verificación → reportar con ID

TEST:
- No debe existir NINGÚN POST a Alegra que no pase por request_with_verify()
- Simular error de Alegra → el usuario ve mensaje en español, no código HTTP
- El ID de Alegra se retorna siempre como evidencia

---

## FASE 1 — Agente Contador Completo (9 capacidades + Backlog)

Cada capacidad se implementa como un tool de Anthropic (si F0-T4 está activo) o como un handler en ACTION_MAP (fallback).

### F1-C1: Egresos por chat

ACCIÓN:
1. Tool registrar_gasto() recibe: descripcion, monto, banco
2. Motor matricial clasifica → extrae cuenta de plan_cuentas_roddos
3. Calcula ReteFuente + ReteICA automáticamente según reglas
4. Propone asiento completo al usuario (DÉBITO cuenta / CRÉDITO retenciones / CRÉDITO banco)
5. Usuario confirma → POST /journals → request_with_verify()
6. Evento gasto.causado → CFO invalida caché

LÓGICA ESPECIAL:
- Si descripción menciona "Andrés" o "Iván" o CC 80075452/80086601 → preguntar: "¿Es gasto personal del socio?" → Si sí → CXC socios, no gasto operativo
- Si proveedor es Auteco NIT 860024781 → NUNCA ReteFuente
- Máximo 1 pregunta si falta info (ej: "¿es persona natural o jurídica?")

---

### F1-C2: Conciliación bancaria + movimientos individuales

ACCIÓN MASIVA (extracto):
1. Endpoint POST /api/conciliacion/cargar-extracto recibe .xlsx
2. Parser identifica banco por formato de headers
3. Motor matricial clasifica cada movimiento
4. Confianza >= 0.70 → cola de causación automática
5. Confianza < 0.70 → WhatsApp a CEO+CGO
6. Sin respuesta WhatsApp → movimiento va al Backlog
7. BackgroundTasks + job_id para el lote
8. Anti-duplicados 3 capas

ACCIÓN INDIVIDUAL (chat):
1. Tool causar_movimiento_bancario() recibe: descripcion, monto, banco, fecha
2. Motor matricial clasifica → propone asiento
3. Usuario confirma → POST /journals

---

### F1-C3: Nómina mensual

ACCIÓN:
1. Tool registrar_nomina() recibe: mes, año, lista de empleados con salario
2. Verifica anti-duplicados: ¿ya se registró nómina de [mes]/[año] para [empleado]?
3. Si ya existe → bloquear y avisar
4. Un journal por empleado: DÉBITO Sueldos (5462) + Seguridad Social (5471) / CRÉDITO Banco
5. POST /journals por cada empleado → request_with_verify()

---

### F1-C4: CXC socios

ACCIÓN:
1. Tool registrar_cxc_socio() recibe: socio_cedula, monto, banco, descripcion
2. Validar: CC 80075452 (Andrés) o CC 80086601 (Iván)
3. Asiento: DÉBITO CXC Socio / CRÉDITO Banco
4. POST /journals → request_with_verify()
5. Actualizar saldo en colección cxc_socios
6. Tool consultar_saldo_cxc() para consultas de saldo

---

### F1-C5: Facturación directa en Alegra

ACCIÓN:
1. Tool crear_factura_venta() recibe: cliente_nombre, cliente_cedula, moto_vin, plan, cuota_inicial
2. Validar moto en inventario_motos: estado == "disponible", VIN presente, motor presente
3. Si VIN o motor faltan → BLOQUEO TOTAL, no facturar
4. Construir factura con formato obligatorio: "[Modelo] [Color] - VIN: [x] / Motor: [x]"
5. Mostrar vista previa al usuario
6. POST /invoices → request_with_verify() → ID factura
7. Cascada: inventario_motos → "vendida", loanbook creado "pendiente_entrega", evento factura.venta.creada
8. WhatsApp Template 5 al cliente (cuota inicial)

---

### F1-C6: Ingresos por cuotas (doble operación)

ACCIÓN:
1. Tool registrar_pago_cuota() recibe: loanbook_id, cuota_numero, monto, banco, metodo_pago
2. Identificar factura de venta del loanbook en Alegra
3. OPERACIÓN A: POST /payments contra la factura → request_with_verify()
4. OPERACIÓN B: POST /journals → asiento ingreso financiero → request_with_verify()
   - DÉBITO: Banco (111005/111010/111015/111020 según banco)
   - CRÉDITO: Ingresos financieros (cuenta de plan_ingresos_roddos)
5. AMBOS IDs verificados → marcar cuota como "pagada" en loanbook
6. Evento pago.cuota.registrado → CFO invalida caché

CRÍTICO: Sin el journal de la OPERACIÓN B, el payment existe pero el P&L no refleja el ingreso.

---

### F1-C7: Ingresos no operacionales

ACCIÓN:
1. Tool registrar_ingreso_no_operacional() recibe: tipo, monto, banco, descripcion
2. Clasificar: intereses bancarios, ventas motos recuperadas, otros
3. Cuenta correcta desde plan_ingresos_roddos
4. Asiento: DÉBITO Banco / CRÉDITO cuenta de ingreso correspondiente
5. POST /journals → request_with_verify()

---

### F1-C8: Módulo Backlog operativo

ACCIÓN BACKEND:
1. Crear colección backlog_movimientos en MongoDB:
   { movimiento_id, fecha, banco, descripcion, monto, tipo (debito/credito), razon_pendiente, intentos, fecha_ingreso_backlog, estado (pendiente/causado/error) }
2. Endpoint GET /api/backlog → lista movimientos pendientes (paginado, filtrable por banco/fecha)
3. Endpoint GET /api/backlog/count → conteo para el badge
4. Endpoint POST /api/backlog/{id}/causar → recibe cuenta_id → POST /journals → request_with_verify() → si éxito: estado="causado" → si falla: estado="error" + actualizar razon
5. Flujo automático: cuando conciliación tiene movimiento < 0.70 sin resolución → insertar en backlog_movimientos

ACCIÓN FRONTEND:
1. Componente BacklogPage.tsx en el menú lateral con badge de conteo
2. Tabla con: fecha, banco, descripción, monto, razón pendiente, intentos, acciones
3. Filtros: por banco, por rango de fechas, por razón
4. Botón "Causar" en cada fila → abre modal con: vista previa del movimiento + selector de cuenta + campos de retenciones opcionales + botón confirmar
5. Al confirmar → POST /api/backlog/{id}/causar → si éxito: fila desaparece de la lista

---

### F1-C9: P&L automático (resultado de todo lo anterior)

ACCIÓN:
1. El CFO consulta GET /journals + GET /invoices + GET /payments en Alegra
2. Separa: ingresos operacionales (ventas motos), ingresos financieros (cuotas), otros ingresos
3. Separa: gastos operativos, nómina, retenciones
4. CXC socios NO afecta P&L — va al balance
5. Calcula utilidad/pérdida
6. Invalidar cfo_cache antes de generar
7. Formato: Sección A (devengado) + Sección B (caja real) — nunca mezclar

---

## Smoke Test Final — 22 tests

No se declara SISMO V2 completo hasta que los 22 pasen:

EGRESOS (7):
1. Gasto por chat → journal Alegra con ID ✅/❌
2. Arrendamiento $3.614.953 → ReteFuente 3.5% + ReteICA 0.414% correctos ✅/❌
3. Extracto BBVA 20 movimientos → 0 duplicados, todos causados o en Backlog ✅/❌
4. Extracto Bancolombia 50 movimientos → background task con job_id ✅/❌
5. Movimiento individual por chat → journal correcto ✅/❌
6. Nómina febrero 2 empleados → anti-dup impide doble registro ✅/❌
7. Gasto socio Andrés → CXC, no gasto operativo ✅/❌

INGRESOS (6):
8. Factura moto TVS Raider → ID factura + VIN en ítem ✅/❌
9. Facturar sin VIN → bloqueo total ✅/❌
10. Facturar moto ya vendida → bloqueo total ✅/❌
11. Pago cuota → payment + journal ingreso (ambos IDs) ✅/❌
12. P&L refleja ingreso de cuota pagada ✅/❌
13. Ingreso no operacional → journal correcto ✅/❌

BACKLOG (4):
14. Movimiento confianza < 0.70 sin respuesta WhatsApp → en Backlog ✅/❌
15. Badge en menú "Backlog (N)" con conteo ✅/❌
16. Causar desde Backlog → journal Alegra → sale del Backlog ✅/❌
17. Fallo al causar → vuelve al Backlog con error ✅/❌

SISTEMA (5):
18. Router: prompt contable → Contador (confianza >= 0.70) ✅/❌
19. Router: prompt analítico → CFO (confianza >= 0.70) ✅/❌
20. CFO intenta POST /journals → PermissionError ✅/❌
21. Alegra caído → UI no se rompe, error en español ✅/❌
22. Evento publicado después de cada escritura ✅/❌
