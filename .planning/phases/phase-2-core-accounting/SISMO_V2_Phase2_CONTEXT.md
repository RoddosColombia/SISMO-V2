SISMO V2 — GSD Phase 2: Core Accounting Operations (Egresos + Ingresos)
Repo: RoddosColombia/SISMO-V2 | Branch: main
Objetivo: Implementar 29 handlers que conectan las tools del Agente Contador con Alegra real
NOTA: Los 5 handlers de conciliación bancaria (parsers BBVA/Bancolombia/Davivienda) quedan
para Phase 3 dedicada — son el componente con más edge cases y merecen su propio ciclo de tests.

════════════════════════════════════════════════════════════════
CONTEXTO — LO QUE YA EXISTE (NO TOCAR)
════════════════════════════════════════════════════════════════

Phase 1 entregó la arquitectura completa con 76/76 tests en main:

  backend/agents/contador/tools.py    — 34 herramientas Anthropic Tool Use (7 categorías)
  backend/agents/chat.py              — process_chat() con SSE streaming + Tool Use loop
  backend/agents/prompts.py           — SYSTEM_PROMPTS dict (4 agentes diferenciados)
  backend/core/router.py              — Intent router (0.70 threshold + keyword rules + sticky)
  backend/core/permissions.py         — WRITE_PERMISSIONS en código (PermissionError)
  backend/core/events.py              — EventPublisher (append-only roddos_events)
  backend/core/database.py            — AsyncIOMotorClient + FastAPI Depends() DI
  backend/services/alegra/client.py   — AlegraClient + request_with_verify()
  backend/routers/chat.py             — POST /api/chat (SSE) + POST /api/chat/approve-plan
  backend/tests/                      — 76 tests (permisos, eventos, alegra, tools, router, infra)

Flujo actual funcionando:
  Usuario escribe mensaje → router detecta intent → despacha al Contador
  → Claude razona con Tool Use → propone herramienta + parámetros
  → usuario confirma via ExecutionCard → FALTA: handler ejecuta contra Alegra
  → Alegra retorna ID → usuario ve evidencia

Lo que FALTA es el paso del medio: los HANDLERS que reciben la tool call
del LLM y la ejecutan contra Alegra real via request_with_verify().

════════════════════════════════════════════════════════════════
REGLAS INAMOVIBLES — LEER ANTES DE ESCRIBIR CÓDIGO
════════════════════════════════════════════════════════════════

ROG-1: NUNCA reportar éxito sin verificar HTTP 200 en Alegra.
       Toda escritura usa AlegraClient.request_with_verify().
       El juez es Alegra, no el agente.

ROG-4: Alegra es la fuente canónica de verdad contable.
       MongoDB es cache operativo temporal, NUNCA fuente contable.
       Todo dato contable se construye EN Alegra y se lee DESDE Alegra.

ENDPOINTS CORRECTOS:
  - Comprobantes: POST /journals y GET /journals — NUNCA /journal-entries (da 403)
  - Plan de cuentas: GET /categories — NUNCA /accounts (da 403)
  - Fechas: formato yyyy-MM-dd — NUNCA ISO-8601 con timezone

PLAN DE CUENTAS — IDs REALES ALEGRA (nunca hardcodear, pero estos son los de referencia):
  Sueldos 510506 = 5462 | Honorarios = 5470 | Seguridad social = 5471
  Arrendamientos 512010 = 5480 | Servicios públicos = 5484 | Teléfono = 5487
  Mantenimiento = 5490 | Transporte = 5491 | Publicidad = 5500
  Gastos Generales = 5493 (FALLBACK CORRECTO — NUNCA 5495)
  ReteFuente practicada = 236505 | ReteICA practicada = 236560
  Comisiones bancarias = 5508 | Seguros = 5510 | Intereses = 5533

RETENCIONES COLOMBIA 2026:
  Arrendamiento: ReteFuente 3.5%
  Servicios: ReteFuente 4%
  Honorarios PN: ReteFuente 10%
  Honorarios PJ: ReteFuente 11%
  Compras: ReteFuente 2.5% (base > $1.344.573)
  ReteICA Bogotá: 0.414%
  Auteco NIT 860024781 = AUTORETENEDOR → NUNCA aplicar ReteFuente
  IVA: cuatrimestral (ene-abr / may-ago / sep-dic) — NUNCA bimestral

BANCOS EN ALEGRA:
  Bancolombia = 111005 | BBVA = 111010 | Davivienda = 111015
  Banco de Bogotá = 111020 | Global66 = 11100507

SOCIOS:
  Andrés Sanjuan CC 80075452 | Iván Echeverri CC 80086601
  Sus gastos personales = CXC Socios — NUNCA gasto operativo

REGLAS TÉCNICAS:
  - BackgroundTasks + job_id para lotes > 10 registros
  - Anti-duplicados 3 capas: hash registro + verificación MongoDB + GET Alegra
  - Publicar evento al bus DESPUÉS de toda escritura exitosa en Alegra
  - validate_write_permission() ANTES de toda escritura
  - Máximo 1 pregunta por turno al usuario
  - Mostrar asiento propuesto ANTES de ejecutar — usuario confirma

════════════════════════════════════════════════════════════════
ARQUITECTURA DE HANDLERS — LO QUE SE DEBE CONSTRUIR
════════════════════════════════════════════════════════════════

Crear el directorio: backend/agents/contador/handlers/

Estructura final:
  backend/agents/contador/handlers/
    __init__.py           — re-export ToolDispatcher
    dispatcher.py         — ToolDispatcher: recibe tool_name + tool_input → despacha al handler correcto
    egresos.py            — 7 handlers de escritura (gastos → journals Alegra)
    ingresos.py           — 4 handlers (ingresos cuotas, no operacionales, CXC socios)
    facturacion.py        — 4 handlers (factura venta moto, notas crédito)
    consultas.py          — 8 handlers read-only (plan cuentas, journals, balance, P&L)
    cartera.py            — 2 handlers (pago cuota, consulta cartera)
    nomina.py             — 3 handlers (nómina mensual, obligaciones, retenciones)
    [NO INCLUIR conciliacion.py — va en Phase 3]

Patrón de CADA handler de escritura (ejemplo crear_causacion):

  async def handle_crear_causacion(
      tool_input: dict,
      alegra: AlegraClient,
      db: AsyncIOMotorDatabase,
      event_bus: EventPublisher,
      user_id: str
  ) -> dict:
      # 1. Validar permisos
      validate_write_permission("contador", "alegra_journals")

      # 2. Construir payload Alegra
      entries = []
      # DÉBITO: cuenta de gasto
      entries.append({
          "account": {"id": tool_input["cuenta_debito_id"]},
          "debit": tool_input["monto_bruto"]
      })
      # CRÉDITO: banco
      entries.append({
          "account": {"id": tool_input["cuenta_banco_id"]},
          "credit": tool_input["monto_neto"]
      })
      # CRÉDITO: ReteFuente (si aplica)
      if tool_input.get("retefuente_monto"):
          entries.append({
              "account": {"id": 236505},
              "credit": tool_input["retefuente_monto"]
          })
      # CRÉDITO: ReteICA (si aplica)
      if tool_input.get("reteica_monto"):
          entries.append({
              "account": {"id": 236560},
              "credit": tool_input["reteica_monto"]
          })

      payload = {
          "date": tool_input["fecha"],  # yyyy-MM-dd
          "observations": tool_input["descripcion"],
          "entries": entries
      }

      # 3. Ejecutar contra Alegra con verificación
      result = await alegra.request_with_verify("journals", "POST", body=payload)

      # 4. Publicar evento al bus
      await event_bus.publish(
          event_type="gasto.causado",
          source="agente_contador",
          datos={
              "alegra_id": result["_alegra_id"],
              "monto": tool_input["monto_bruto"],
              "cuenta": tool_input["cuenta_debito_id"],
              "descripcion": tool_input["descripcion"]
          }
      )

      # 5. Retornar con ID de Alegra como evidencia
      return {
          "success": True,
          "alegra_id": result["_alegra_id"],
          "message": f"Journal #{result['_alegra_id']} creado en Alegra. Gasto: {tool_input['descripcion']} por ${tool_input['monto_bruto']:,.0f}"
      }

Patrón del ToolDispatcher:

  class ToolDispatcher:
      def __init__(self, alegra: AlegraClient, db: AsyncIOMotorDatabase, event_bus: EventPublisher):
          self.alegra = alegra
          self.db = db
          self.event_bus = event_bus
          self._handlers = {
              # EGRESOS
              "crear_causacion": handle_crear_causacion,
              "crear_causacion_masiva": handle_crear_causacion_masiva,
              "registrar_gasto_periodico": handle_registrar_gasto_periodico,
              "crear_nota_debito": handle_crear_nota_debito,
              "registrar_retenciones": handle_registrar_retenciones,
              "crear_asiento_manual": handle_crear_asiento_manual,
              "anular_causacion": handle_anular_causacion,
              # INGRESOS
              "registrar_ingreso_cuota": handle_registrar_ingreso_cuota,
              "registrar_ingreso_no_operacional": handle_registrar_ingreso_no_operacional,
              "registrar_cxc_socio": handle_registrar_cxc_socio,
              "consultar_cxc_socios": handle_consultar_cxc_socios,
              # FACTURACIÓN
              "crear_factura_venta_moto": handle_crear_factura_venta_moto,
              "consultar_facturas": handle_consultar_facturas,
              "anular_factura": handle_anular_factura,
              "crear_nota_credito": handle_crear_nota_credito,
              # CONCILIACIÓN BANCARIA → Phase 3 (no implementar aquí)
              # CONSULTAS ALEGRA
              "consultar_plan_cuentas": handle_consultar_plan_cuentas,
              "consultar_journals": handle_consultar_journals,
              "consultar_balance": handle_consultar_balance,
              "consultar_estado_resultados": handle_consultar_estado_resultados,
              "consultar_pagos": handle_consultar_pagos,
              "consultar_contactos": handle_consultar_contactos,
              "consultar_items": handle_consultar_items,
              "consultar_movimiento_cuenta": handle_consultar_movimiento_cuenta,
              # CARTERA
              "registrar_pago_cuota": handle_registrar_pago_cuota,
              "consultar_cartera": handle_consultar_cartera,
              # NÓMINA E IMPUESTOS
              "registrar_nomina_mensual": handle_registrar_nomina_mensual,
              "consultar_obligaciones_tributarias": handle_consultar_obligaciones_tributarias,
              "calcular_retenciones": handle_calcular_retenciones,
              # CATÁLOGO
              "consultar_catalogo_roddos": handle_consultar_catalogo_roddos,
          }

      async def dispatch(self, tool_name: str, tool_input: dict, user_id: str) -> dict:
          handler = self._handlers.get(tool_name)
          if not handler:
              return {"success": False, "error": f"Handler no encontrado: {tool_name}"}
          try:
              return await handler(
                  tool_input=tool_input,
                  alegra=self.alegra,
                  db=self.db,
                  event_bus=self.event_bus,
                  user_id=user_id
              )
          except PermissionError as e:
              return {"success": False, "error": f"Sin permiso: {str(e)}"}
          except Exception as e:
              return {"success": False, "error": f"Error ejecutando {tool_name}: {str(e)}"}

Conexión con chat.py:
  En process_chat(), cuando Claude retorna un tool_use block:
    1. Extraer tool_name y tool_input del response
    2. Si la tool es de ESCRITURA → mostrar al usuario via ExecutionCard → esperar confirmación
    3. Al confirmar → dispatcher.dispatch(tool_name, tool_input, user_id)
    4. Retornar resultado al usuario con alegra_id como evidencia
    5. Si la tool es de LECTURA (consultar_*) → ejecutar inmediatamente sin confirmación
    6. Si la tool es de CONCILIACIÓN BANCARIA → retornar "Disponible en Phase 3"

════════════════════════════════════════════════════════════════
WAVES DE IMPLEMENTACIÓN — 7 WAVES EN ORDEN OBLIGATORIO
════════════════════════════════════════════════════════════════
(Conciliación bancaria = Phase 3 separada)

WAVE 1: INFRAESTRUCTURA (dispatcher + conexión chat.py)
  - Crear backend/agents/contador/handlers/__init__.py
  - Crear backend/agents/contador/handlers/dispatcher.py con ToolDispatcher
  - Modificar backend/agents/chat.py para conectar tool_use blocks al dispatcher
  - Distinguir tools de escritura (requieren confirmación) vs lectura (ejecución directa)
  - Tests: dispatcher despacha correctamente, tool desconocida retorna error, PermissionError manejado
  - Commit: "phase2-wave1: ToolDispatcher + chat.py integration"

WAVE 2: CONSULTAS (8 handlers read-only — sin riesgo, validan la conexión Alegra)
  - Crear backend/agents/contador/handlers/consultas.py
  - 8 handlers:
    consultar_plan_cuentas → GET /categories
    consultar_journals → GET /journals (limit=50, filtro local por fecha)
    consultar_balance → GET /balance (parámetros: date_from, date_to)
    consultar_estado_resultados → GET /income-statement
    consultar_pagos → GET /payments
    consultar_contactos → GET /contacts
    consultar_items → GET /items
    consultar_movimiento_cuenta → GET /journals filtrado por account_id
  - NINGUNO de estos escribe en Alegra — ejecución directa sin ExecutionCard
  - NUNCA usar GET /accounts — usar GET /categories
  - Tests: cada handler retorna datos, manejo de error Alegra, formato de respuesta
  - Commit: "phase2-wave2: 8 consultas read-only handlers"

WAVE 3: EGRESOS (7 handlers de escritura — el core contable)
  - Crear backend/agents/contador/handlers/egresos.py
  - 7 handlers:
    crear_causacion → POST /journals (gasto individual con retenciones automáticas)
      REGLAS: ReteFuente según tipo, ReteICA 0.414%, Auteco sin ReteFuente
      PAYLOAD: date yyyy-MM-dd, observations, entries[débito gasto + créditos banco/retenciones]
      DESPUÉS: event_bus.publish("gasto.causado")

    crear_causacion_masiva → BackgroundTasks + job_id (lotes > 10)
      REGLAS: anti-dup 3 capas, lotes de 10, job_id en MongoDB
      DESPUÉS: event_bus.publish("causacion_masiva.completada") con resumen

    registrar_gasto_periodico → POST /journals (arriendo, servicios, etc.)
      REGLAS: mismas retenciones, validar que no esté duplicado en el período

    crear_nota_debito → POST /journals (ajuste débito)

    registrar_retenciones → POST /journals (retenciones de período)
      REGLAS: IVA cuatrimestral, ReteICA acumulada, ReteFuente por tipo

    crear_asiento_manual → POST /journals (asiento libre con entries custom)
      REGLAS: validar que entries balancea (total débito = total crédito)

    anular_causacion → DELETE /journals/{id} (con confirmación obligatoria del usuario)
      REGLAS: primero GET para verificar que existe, luego DELETE, luego GET para confirmar eliminación
      DESPUÉS: event_bus.publish("causacion.anulada")

  - TODAS usan request_with_verify() para escritura
  - TODAS publican evento al bus después de éxito
  - TODAS requieren confirmación del usuario via ExecutionCard antes de ejecutar
  - Tests: payload correcto para cada tipo, retenciones calculadas, anti-dup funciona, evento publicado
  - Commit: "phase2-wave3: 7 egresos handlers con retenciones automáticas"

WAVE 4: INGRESOS + CXC (4 handlers)
  - Crear backend/agents/contador/handlers/ingresos.py
  - 4 handlers:
    registrar_ingreso_cuota → POST /journals
      DÉBITO: Banco (cuenta según método pago)
      CRÉDITO: Ingresos financieros (cuenta del plan_ingresos_roddos)
      DESPUÉS: event_bus.publish("ingreso.cuota.registrado")

    registrar_ingreso_no_operacional → POST /journals
      Tipos: intereses bancarios, venta motos recuperadas, otros
      Cuentas desde plan_ingresos_roddos
      DESPUÉS: event_bus.publish("ingreso.no_operacional.registrado")

    registrar_cxc_socio → POST /journals
      DÉBITO: CXC Socio (1305XX según socio)
      CRÉDITO: Banco
      Validar: CC 80075452 = Andrés, CC 80086601 = Iván
      NUNCA registrar como gasto operativo
      DESPUÉS: event_bus.publish("cxc.socio.registrada")

    consultar_cxc_socios → GET /journals filtrado por cuenta CXC + cálculo de saldo
      Retorna: saldo pendiente por socio, historial de movimientos
      NO requiere confirmación (es lectura)

  - Tests: cada handler crea journal correcto, CXC nunca va como gasto, evento publicado
  - Commit: "phase2-wave4: 4 ingresos + CXC handlers"

WAVE 5: FACTURACIÓN (4 handlers)
  - Crear backend/agents/contador/handlers/facturacion.py
  - 4 handlers:
    crear_factura_venta_moto → POST /invoices
      FORMATO OBLIGATORIO del ítem: "[Modelo] [Color] - VIN: [chasis] / Motor: [motor]"
      VIN y motor son OBLIGATORIOS — bloquear si faltan
      DESPUÉS:
        - Actualizar inventario_motos en MongoDB: estado → "Vendida"
        - Crear loanbook en MongoDB: estado "pendiente_entrega"
        - event_bus.publish("factura.venta.creada")

    consultar_facturas → GET /invoices (filtros por fecha, cliente, estado)
      NO requiere confirmación

    anular_factura → POST /invoices/{id}/void (con confirmación obligatoria)
      DESPUÉS:
        - Actualizar inventario_motos: estado → "Disponible"
        - Actualizar loanbook: estado → "cancelado"
        - event_bus.publish("factura.venta.anulada")

    crear_nota_credito → POST /credit-notes
      DESPUÉS: event_bus.publish("nota_credito.creada")

  - Tests: VIN obligatorio, formato ítem correcto, inventario actualizado, loanbook creado
  - Commit: "phase2-wave5: 4 facturación handlers con VIN obligatorio"

WAVE 6: NÓMINA + IMPUESTOS + CARTERA + CATÁLOGO (6 handlers)
  - Crear backend/agents/contador/handlers/nomina.py
  - Crear backend/agents/contador/handlers/cartera.py
  - 6 handlers:
    registrar_nomina_mensual → POST /journals (1 journal por empleado)
      Anti-dup: verificar por mes+empleado antes de crear
      Discriminar: salario base, seguridad social, dotación
      DESPUÉS: event_bus.publish("nomina.registrada")

    consultar_obligaciones_tributarias → Cálculo local
      IVA cuatrimestral acumulado, ReteFuente acumulada, ReteICA acumulada
      Lee journals del período desde Alegra para calcular

    calcular_retenciones → Cálculo local
      Input: tipo operación + monto + NIT proveedor
      Output: ReteFuente, ReteICA, IVA, neto a pagar
      Verifica autoretenedores antes de calcular ReteFuente

    registrar_pago_cuota → POST /payments contra factura del loanbook
      Verificar que la cuota está pendiente en MongoDB loanbook
      DESPUÉS:
        - Actualizar cuota en loanbook: estado → "pagada"
        - event_bus.publish("pago.cuota.registrado")

    consultar_cartera → Lectura MongoDB loanbook + cálculo de saldos
      NO requiere confirmación

    consultar_catalogo_roddos → Retornar catálogo embebido (IDs, cuentas, reglas)
      NO requiere confirmación

  - Tests: anti-dup nómina, retenciones correctas, autoretenedor respetado, pago actualiza loanbook
  - Commit: "phase2-wave6: 6 nómina + cartera + catálogo handlers"

WAVE 7: INTEGRACIÓN END-TO-END + SMOKE TEST
  - Crear backend/tests/test_phase2_integration.py
  - Tests de flujo completo:
    T1: Usuario describe gasto → dispatcher recibe → handler crea journal → evento publicado
    T2: Gasto con ReteFuente 3.5% → entries balancean (débito = créditos)
    T3: Gasto de socio → CXC, no gasto operativo
    T4: Factura venta moto sin VIN → BLOQUEO
    T5: Factura venta moto con VIN → inventario actualizado + loanbook creado
    T6: Consulta P&L → retorna datos sin error
    T7: Pago cuota → cuota marcada pagada + evento publicado
    T8: Nómina duplicada → anti-dup la bloquea
    T9: Causación masiva 15 registros → BackgroundTasks + job_id
    T10: Anular journal → DELETE verificado con GET posterior
    T11: Auteco → sin ReteFuente
    T12: STATIC ANALYSIS — ningún handler en handlers/ escribe datos contables en MongoDB
         (grep insert_one/update_one excluyendo roddos_events/inventario/loanbook = 0)
  - Verificar que los 76 tests de Phase 1 siguen pasando (regresión cero)
  - Commit: "phase2-wave7: 12 integration tests + smoke test"

════════════════════════════════════════════════════════════════
INSTRUCCIÓN PARA CLAUDE CODE — COPIAR EXACTO
════════════════════════════════════════════════════════════════

PASO 0 — ANTES DE EMPEZAR (OBLIGATORIO):
Verificar que .claude/CLAUDE.md contiene esta regla textual. Si no existe, AGREGARLA
como primera línea de la sección de reglas:

  REGLA MÁXIMA CONTABLE: Toda operación contable (gastos, ingresos, pagos, facturas,
  nómina, CXC) se ejecuta CONTRA ALEGRA via request_with_verify(). MongoDB es SOLO
  cache operativo y bus de eventos. Si estás escribiendo datos contables en MongoDB
  sin pasar por Alegra, ESTÁS MAL. PARA INMEDIATAMENTE.

  Escrituras MongoDB PERMITIDAS en handlers contables:
    - roddos_events (bus de eventos — append-only)
    - conciliacion_jobs (estado de background tasks)
    - inventario_motos (estado operativo de motos — no es dato contable)
    - loanbook (estado operativo del crédito — no es dato contable)
  Escrituras MongoDB PROHIBIDAS en handlers contables:
    - Cualquier colección que pretenda ser fuente de verdad de montos, journals,
      facturas, pagos, balances o cualquier dato que debe vivir en Alegra.

Lee el archivo .planning/SISMO_V2_Registro_Canonico.md y .claude/CLAUDE.md para contexto del proyecto.

Lee backend/agents/contador/tools.py para ver las 34 herramientas definidas.
Lee backend/agents/chat.py para ver el flujo actual de process_chat().
Lee backend/services/alegra/client.py para ver AlegraClient y request_with_verify().
Lee backend/core/permissions.py para ver WRITE_PERMISSIONS.
Lee backend/core/events.py para ver EventPublisher.

Ejecuta Phase 2 usando GSD. Las 7 waves ya están definidas arriba como el plan.
GSD maneja el context window automáticamente — cada tarea corre en subagente fresco.

  /gsd:discuss-phase 2   (si necesitas clarificar algo del plan antes de ejecutar)
  /gsd:execute-phase 2   (ejecuta las 7 waves con subagentes frescos)

Cada wave dentro de la ejecución GSD debe:
1. Implementar los handlers de esa categoría
2. Escribir tests que cubran el handler
3. Ejecutar pytest — TODOS los tests deben pasar (Phase 1 + Phase 2)
4. EJECUTAR GREP DE VERIFICACIÓN ANTI-MONGODB (ver abajo)
5. Commit atómico con mensaje descriptivo
6. Push a main

GREP DE VERIFICACIÓN ANTI-MONGODB — OBLIGATORIO DESPUÉS DE CADA WAVE:
Ejecutar estos 3 comandos. Si alguno encuentra violaciones, CORREGIR antes del commit:

  grep -rn "insert_one\|insert_many\|update_one\|replace_one" backend/agents/contador/handlers/ | grep -v "roddos_events\|conciliacion_jobs\|inventario_motos\|loanbook"

  Si retorna resultados → HAY UNA VIOLACIÓN. Un handler está escribiendo datos
  contables en MongoDB en lugar de en Alegra. Corregir: el dato debe ir a Alegra
  via request_with_verify() y solo después publicar evento al bus.

  grep -rn "journal-entries" backend/ → DEBE dar 0 resultados
  grep -rn "5495" backend/ → DEBE dar 0 resultados

REGLAS DURANTE LA EJECUCIÓN:
- NUNCA modificar tools.py (las definiciones ya están correctas)
- NUNCA modificar core/permissions.py, core/events.py, core/database.py
- NUNCA modificar services/alegra/client.py
- Solo AGREGAR archivos en handlers/ y MODIFICAR chat.py para conectar el dispatcher
- Si un test de Phase 1 se rompe → PARAR y diagnosticar antes de continuar
- Cada handler de escritura DEBE usar request_with_verify()
- Cada handler de escritura DEBE publicar evento al bus
- Cada handler de escritura DEBE requerir confirmación del usuario (excepto consultas)
- El DESTINO de toda operación contable es ALEGRA. MongoDB es solo cache/bus/estado operativo.

VERIFICACIÓN FINAL:
- pytest completo: 76 tests Phase 1 + N tests Phase 2 = TODOS GREEN
- grep -rn "journal-entries" backend/ → 0 resultados
- grep -rn "5495" backend/ → 0 resultados
- grep -rn "/accounts" backend/ → 0 resultados (solo /categories)

════════════════════════════════════════════════════════════════
REPORTE FINAL ESPERADO
════════════════════════════════════════════════════════════════

Al terminar Phase 2, reportar:

  [ ] Wave 1: ToolDispatcher + chat.py integration — N tests
  [ ] Wave 2: 8 consultas read-only — N tests
  [ ] Wave 3: 7 egresos con retenciones — N tests
  [ ] Wave 4: 4 ingresos + CXC — N tests
  [ ] Wave 5: 4 facturación con VIN — N tests
  [ ] Wave 6: 6 nómina + cartera + catálogo — N tests
  [ ] Wave 7: 12 integration tests + smoke

  Total tests: 76 (Phase 1) + N (Phase 2) = todos GREEN
  Total handlers: 29 (conciliación bancaria queda para Phase 3)
  Total commits: 7 (1 por wave)
  Regresiones: 0

  Archivos creados:
    backend/agents/contador/handlers/__init__.py
    backend/agents/contador/handlers/dispatcher.py
    backend/agents/contador/handlers/egresos.py
    backend/agents/contador/handlers/ingresos.py
    backend/agents/contador/handlers/facturacion.py
    backend/agents/contador/handlers/consultas.py
    backend/agents/contador/handlers/cartera.py
    backend/agents/contador/handlers/nomina.py
    backend/tests/test_phase2_integration.py

  Archivos modificados:
    backend/agents/chat.py (conectar dispatcher)

  VEREDICTO: Phase 2 COMPLETA cuando los 29 handlers están conectados,
  todos los tests pasan y Alegra puede recibir operaciones reales.

  SIGUIENTE: Phase 3 — Conciliación Bancaria (5 handlers)
    Parsers dedicados BBVA/Bancolombia/Davivienda/Nequi
    Motor matricial 50+ reglas con confianza 0-1
    Anti-duplicados hash MD5
    Flujo de movimientos ambiguos (<0.70 confianza)
