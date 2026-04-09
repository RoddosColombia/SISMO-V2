# Phase 2: Core Accounting Operations - Research

**Researched:** 2026-04-09
**Domain:** Handlers connecting Contador tool calls to Alegra API with retenciones automation
**Confidence:** HIGH

## Summary

Phase 2 implements 29 handlers that form the "missing middle" between Phase 1's tool definitions and actual Alegra operations. The ToolDispatcher class routes tool_name → handler function, passing AlegraClient, EventPublisher, and database via constructor injection. All write handlers follow a strict pattern: validate permissions → build Alegra payload → request_with_verify() → publish event → return alegra_id as auditable evidence. Read handlers (consultar_*) execute directly without confirmation.

The retenciones engine is a shared service (`backend/services/retenciones.py`) that calculates Arrendamiento (3.5%), Servicios (4%), Honorarios PN (10%), Honorarios PJ (11%), Compras 2.5% (base >$1.344.573), and ReteICA Bogotá (0.414%), with special handling for Auteco NIT 860024781 (autoretenedor — never ReteFuente). Handler→tool name mapping resolves differences between tool definitions in tools.py and handler function names in SISMO_V2_Phase2_CONTEXT.md.

**Primary recommendation:** Implement handlers in 7 waves as specified in CONTEXT.md. Start with ToolDispatcher + chat.py integration (Wave 1), then read-only consultas (Wave 2) to validate Alegra connectivity, then write handlers grouped by operational domain (Waves 3-6), concluding with integration tests (Wave 7).

---

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** PHASE2_CONTEXT.md (SISMO_V2_Phase2_CONTEXT.md) is the authoritative spec. The 29 handlers described there override any other interpretation.
- **D-02:** Conciliación bancaria (5 handlers with BBVA/Bancolombia/Davivienda parsers) is Phase 3 — too many edge cases for this phase.
- **D-03:** Backlog UI (BACK-02, BACK-03) remains in a later phase. Phase 2 only implements routing of movements to backlog.
- **D-04:** All handlers live in `backend/agents/contador/handlers/` organized by category: dispatcher.py, egresos.py, ingresos.py, facturacion.py, consultas.py, cartera.py, nomina.py.
- **D-05:** ToolDispatcher class receives tool_name + tool_input, dispatches to the correct handler. Injected with AlegraClient, db, EventPublisher via constructor.
- **D-06:** chat.py modified to connect tool_use blocks to ToolDispatcher. Write tools require ExecutionCard confirmation. Read tools (consultar_*) execute immediately without confirmation.
- **D-07:** Conciliación tools return "Disponible en Phase 3" instead of executing.
- **D-08:** Shared service at `backend/services/retenciones.py` with signature: `calcular_retenciones(tipo: str, monto: float, nit: str | None) -> dict`
- **D-09:** Autoretenedores hardcodeados — only Auteco NIT 860024781. If nit == "860024781" → retefuente = 0 always.
- **D-10:** ReteICA Bogota = 0.414% always applied.
- **D-11:** Compras ReteFuente 2.5% only if monto > $1.344.573.
- **D-12:** All write handlers import retenciones service — never calculate internally.
- **D-13:** validate_write_permission() BEFORE any write
- **D-14:** Build Alegra payload with correct entries (débito = crédito)
- **D-15:** Execute via alegra.request_with_verify() — POST → HTTP 200 → GET verify → return ID
- **D-16:** Publish event to bus AFTER successful write
- **D-17:** Return alegra_id as auditable evidence
- **D-18 through D-22:** tools.py, permissions.py, events.py, database.py, client.py MUST NOT be modified

### Claude's Discretion

- Error message formatting (within Spanish requirement)
- Background task implementation details for masiva handlers
- Anti-duplicate hash algorithm specifics
- Event payload structure beyond required fields

### Deferred Ideas (OUT OF SCOPE)

- Conciliación bancaria (5 handlers with BBVA/Bancolombia/Davivienda parsers) — Phase 3
- Backlog UI (page + badge + Causar modal) — later phase
- Nequi parser — format not documented
- Global66/Banco de Bogota parsers — format not documented

---

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EGRE-01 | User describes expense in natural language → motor matricial classifies → agent proposes complete journal entry with retenciones before executing | Wave 3: `handle_crear_causacion` / `handle_registrar_gasto` — direct Alegra POST with validated entries |
| EGRE-02 | Retenciones calculated automatically: Arrendamiento 3.5%, Servicios 4%, Honorarios PN 10%, Honorarios PJ 11%, Compras 2.5% (base >$1.344.573), ReteICA Bogota 0.414% | retenciones.py service implements all 5 types + ReteICA; handlers call it to build entries |
| EGRE-03 | Partner expenses (Andres CC 80075452, Ivan CC 80086601) routed to CXC socios — never classified as gasto operativo | Wave 4: `handle_registrar_cxc_socio` creates journal with CXC account (1305XX by partner) |
| EGRE-04 | Auteco NIT 860024781 identified as autoretenedor — ReteFuente never applied | retenciones.py: if nit == "860024781" → return retefuente_monto = 0 |
| CONC-04 | Individual movement classified via chat: user describes movement → agent classifies → proposes journal → user confirms → POST /journals with verification | Wave 1: dispatcher routes "causar_movimiento_bancario" to handler; Wave 3: handler calls request_with_verify() |
| NOMI-01 | Monthly payroll registered as individual journals per employee (Sueldos 5462 + Seguridad Social 5471) with anti-duplicate check per mes+empleado | Wave 6: `handle_registrar_nomina_mensual` — checks MongoDB journal cache before POST, publishes event after success |
| CXC-01 | Partner withdrawals registered as CXC journal (balance sheet), never as expense (P&L distortion prevention) | Wave 4: `handle_registrar_cxc_socio` / `handle_consultar_cxc_socios` |
| CXC-02 | Real-time CXC balance query per partner returns exact pending amount | Wave 4: `handle_consultar_cxc_socios` reads journals from Alegra GET /journals filtered by CXC account |
| FACT-01 | Invoice created in Alegra (POST /invoices) with item format "[Modelo] [Color] - VIN: [x] / Motor: [x]" — VIN and motor mandatory | Wave 5: `handle_crear_factura_venta_moto` — blocks if VIN/motor missing; exact format enforced in payload |
| FACT-02 | Successful invoice triggers cascade: inventario_motos → "vendida", loanbook created "pendiente_entrega", event "factura.venta.creada" published, WhatsApp Template 5 sent | Wave 5: handler updates MongoDB after Alegra POST succeeds, publishes event with alegra_id |
| FACT-03 | Invoice blocked if VIN missing, motor missing, or moto status != "disponible" | Wave 5: validation before Alegra POST |
| INGR-01 | Loan payment requires dual operation: POST /payments (against invoice) + POST /journals (income journal) — both verified with request_with_verify(), cuota marked paid only after BOTH succeed | Wave 4: `handle_registrar_pago_cuota` — executes both operations, marks cuota paid only if both return HTTP 200 |
| INGR-02 | Non-operational income (recovered motos, bank interest) registered as journal with correct account from plan_ingresos_roddos | Wave 4: `handle_registrar_ingreso_no_operacional` → POST /journals |
| BACK-01 | Unresolved movements (confidence < 0.70, Alegra errors, unclassifiable) inserted into backlog_movimientos with fecha, banco, descripcion, monto, razon_pendiente, intentos | Wave 1: ToolDispatcher error handler inserts to MongoDB (not Phase 2 scope yet — returns error) |
| PL-01 | CFO constructs P&L by reading directly from Alegra (GET /journals + /invoices + /payments + /categories) — never from MongoDB | Wave 2: `handle_consultar_estado_resultados` reads from Alegra |
| PL-02 | P&L separates devengado (Seccion A) from caja real (Seccion B); CXC socios excluded from P&L (balance sheet only); IVA cuatrimestral | Wave 2: `handle_consultar_estado_resultados` and `handle_consultar_balance_general` implement separation |

---

## Standard Stack

### Core Libraries (Phase 1 — Already Implemented)

| Library | Version | Purpose | Verified |
|---------|---------|---------|----------|
| FastAPI | 0.104+ | Web framework with SSE streaming | [VERIFIED: codebase] |
| Anthropic SDK | 0.7+ | Claude API + native Tool Use | [VERIFIED: codebase imports] |
| Motor (async MongoDB) | 3.3+ | Async MongoDB driver | [VERIFIED: codebase] |
| httpx | 0.25+ | Async HTTP client for Alegra API | [VERIFIED: client.py] |

### Alegra API Patterns (Phase 1 Established)

| Pattern | Endpoint | Method | Verified |
|---------|----------|--------|----------|
| Journals (CORRECT) | `/journals` | POST/GET/DELETE | [VERIFIED: client.py, tools.py] |
| Categories (CORRECT) | `/categories` | GET | [VERIFIED: client.py, tools.py] |
| Invoices | `/invoices` | POST/GET | [VERIFIED: tools.py] |
| Payments | `/payments` | POST/GET | [VERIFIED: tools.py] |
| Contacts | `/contacts` | GET | [VERIFIED: tools.py] |
| Bills | `/bills` | GET | [VERIFIED: tools.py] |
| Items | `/items` | GET | [VERIFIED: tools.py] |

**Critical Anti-patterns (NEVER use):**
- `/journal-entries` → returns HTTP 403 [CITED: tools.py line 14]
- `/accounts` → returns HTTP 403 [CITED: tools.py line 15]
- Account ID 5495 (deprecated fallback) → use 5493 instead [CITED: PHASE2_CONTEXT.md]
- ISO-8601 dates with timezone → use yyyy-MM-dd only [CITED: client.py line 8]

### New Files to Create (Phase 2)

| File | Lines | Purpose |
|------|-------|---------|
| `backend/agents/contador/handlers/__init__.py` | 3 | Module marker, re-export ToolDispatcher |
| `backend/agents/contador/handlers/dispatcher.py` | 80-100 | ToolDispatcher class + handler registration |
| `backend/agents/contador/handlers/consultas.py` | 150-200 | 8 read-only handlers (GET from Alegra) |
| `backend/agents/contador/handlers/egresos.py` | 250-350 | 7 expense handlers (POST /journals + retenciones) |
| `backend/agents/contador/handlers/ingresos.py` | 180-220 | 4 income + CXC handlers |
| `backend/agents/contador/handlers/facturacion.py` | 180-220 | 4 invoice handlers with VIN validation |
| `backend/agents/contador/handlers/cartera.py` | 100-120 | 2 portfolio handlers (read + query) |
| `backend/agents/contador/handlers/nomina.py` | 150-180 | 3 payroll + tax handlers |
| `backend/services/retenciones.py` | 80-120 | Declarative retenciones rules engine |

**Modification (existing file):**
- `backend/agents/chat.py` — Add lines ~15-30 to integrate ToolDispatcher into process_chat() tool_use block handling

---

## Architecture Patterns

### Handler Function Signature (All 29 handlers follow this)

```python
# Source: PHASE2_CONTEXT.md wave descriptions

async def handle_[operation_name](
    tool_input: dict,                          # From Claude tool_use.input
    alegra: AlegraClient,                      # Injected by ToolDispatcher
    db: AsyncIOMotorDatabase,                  # Injected by ToolDispatcher
    event_bus: EventPublisher,                 # Injected by ToolDispatcher
    user_id: str                               # From session context
) -> dict:
    """
    Handler returns: {"success": True/False, "alegra_id": "...", "message": "..."}
    """
```

**Every write handler flow (mandatory pattern):**

1. Call `validate_write_permission("contador", target_endpoint)` → raises PermissionError if not allowed
2. Build Alegra payload with correct account IDs, amounts, dates (yyyy-MM-dd format)
3. Call `alegra.request_with_verify(endpoint, method, payload)` → returns verified Alegra record with _alegra_id
4. Call `event_bus.publish(event_type, source, datos, alegra_id, accion_ejecutada)` → append-only event
5. Return dict with alegra_id and human-readable message

### ToolDispatcher Class Structure

```python
# Source: PHASE2_CONTEXT.md

class ToolDispatcher:
    def __init__(self, alegra: AlegraClient, db: AsyncIOMotorDatabase, event_bus: EventPublisher):
        """Injected via FastAPI Depends()"""
        self._handlers = {
            # 29 handlers map tool_name → handler function
            "crear_causacion": handle_crear_causacion,
            "consultar_plan_cuentas": handle_consultar_plan_cuentas,
            # ... etc
        }
    
    async def dispatch(self, tool_name: str, tool_input: dict, user_id: str) -> dict:
        """Route tool call to correct handler, catch exceptions"""
        handler = self._handlers.get(tool_name)
        if not handler:
            return {"success": False, "error": f"Handler no encontrado: {tool_name}"}
        try:
            return await handler(tool_input, alegra=self.alegra, db=self.db, event_bus=self.event_bus, user_id=user_id)
        except PermissionError as e:
            return {"success": False, "error": f"Sin permiso: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": f"Error ejecutando {tool_name}: {str(e)}"}
```

### chat.py Integration Point

**Current code (process_chat lines 86-127):**
- Yields text chunks as SSE
- Detects `block.type == 'tool_use'` in final_message.content
- Yields ExecutionCard (type: "tool_proposal")
- Persists pending_action to agent_sessions collection

**Phase 2 modification required:**
At line 127 (after yielding ExecutionCard), add integration point:
```python
# [Phase 2 Wave 1 addition]
# When ExecutionCard is approved, POST /api/chat/approve-plan calls dispatcher:
# await dispatcher.dispatch(tool_name, tool_input, user_id)
```

The dispatcher is injected into the chat route handler via FastAPI Depends(), allowing process_chat() to receive it as a parameter and call `dispatcher.dispatch()` when approving.

### Retenciones Service (Shared)

```python
# Source: PHASE2_CONTEXT.md D-08

async def calcular_retenciones(
    tipo: str,           # "arriendo" | "servicios" | "honorarios_pn" | "honorarios_pj" | "compras"
    monto: float,        # Monto bruto en COP
    nit: str | None      # NIT del proveedor (Auteco: "860024781")
) -> dict:
    """
    Returns: {
        "retefuente_tasa": 0.035,         # or 0 if autoretenedor
        "retefuente_monto": 126523,
        "reteica_tasa": 0.00414,
        "reteica_monto": 3528,
        "neto_a_pagar": 3740322,
        "autoretenedor": False,
    }
    """
```

**Rules hardcoded in function:**
- If nit == "860024781" → autoretenedor = True, retefuente_monto = 0
- ReteICA always 0.414%
- Compras ReteFuente 2.5% only if monto > 1344573 (else 0%)
- Arrendamiento/Servicios/Honorarios rates per CLAUDE.md

### Handler Organization by Wave

```
Wave 1 (Infrastructure)
  └─ ToolDispatcher + chat.py integration

Wave 2 (Read-only, 8 handlers)
  ├─ consultar_plan_cuentas → GET /categories
  ├─ consultar_journals → GET /journals
  ├─ consultar_balance → GET /balance
  ├─ consultar_estado_resultados → GET /income-statement
  ├─ consultar_pagos → GET /payments
  ├─ consultar_contactos → GET /contacts
  ├─ consultar_items → GET /items
  └─ consultar_movimiento_cuenta → GET /journals (filtered)

Wave 3 (Egresos/Expenses, 7 handlers)
  ├─ crear_causacion → POST /journals (core pattern test)
  ├─ crear_causacion_masiva → BackgroundTasks + job_id (lotes > 10)
  ├─ registrar_gasto_periodico → POST /journals (arriendo, servicios, etc.)
  ├─ crear_nota_debito → POST /journals (debit adjustment)
  ├─ registrar_retenciones → POST /journals (period retenciones)
  ├─ crear_asiento_manual → POST /journals (free-form with validation)
  └─ anular_causacion → DELETE /journals/{id}

Wave 4 (Ingresos/Income + CXC, 4 handlers)
  ├─ registrar_ingreso_cuota → POST /journals (loan payment)
  ├─ registrar_ingreso_no_operacional → POST /journals (interest, recovered motos)
  ├─ registrar_cxc_socio → POST /journals (partner withdrawal as CXC)
  └─ consultar_cxc_socios → GET /journals (filtered by CXC account)

Wave 5 (Facturación/Invoices, 4 handlers)
  ├─ crear_factura_venta_moto → POST /invoices (with VIN/motor validation)
  ├─ consultar_facturas → GET /invoices (read-only)
  ├─ anular_factura → POST /invoices/{id}/void (with inventory rollback)
  └─ crear_nota_credito → POST /credit-notes

Wave 6 (Nómina/Payroll + Cartera/Portfolio + Catálogo, 6 handlers)
  ├─ registrar_nomina_mensual → POST /journals (per employee with anti-dup)
  ├─ consultar_obligaciones_tributarias → Local calculation (IVA, ReteFuente, ReteICA)
  ├─ calcular_retenciones → Local calculation (retenciones service)
  ├─ registrar_pago_cuota → POST /payments + POST /journals (dual-op)
  ├─ consultar_cartera → MongoDB read (loanbooks)
  └─ consultar_catalogo_roddos → Return embedded catalog (no query)

Wave 7 (Integration + Smoke, 12 tests)
  └─ test_phase2_integration.py (12 test cases + static analysis)
```

### Tool Name → Handler Function Mapping

**Source file:** `backend/agents/contador/tools.py` (34 tool names)

Mapping resolution (PHASE2_CONTEXT.md dispatcher.py lines 174-212 vs tools.py):

| Tool Name (tools.py) | Handler Name (handlers/) | Category | Notes |
|---------------------|--------------------------|----------|-------|
| crear_causacion | handle_crear_causacion | egresos | Direct mapping |
| registrar_gasto | handle_registrar_gasto* | egresos | *Might be renamed to crear_causacion in handlers |
| registrar_gasto_recurrente | handle_registrar_gasto_periodico | egresos | Renamed for clarity |
| anular_causacion | handle_anular_causacion | egresos | Direct mapping |
| causar_movimiento_bancario | handle_causar_movimiento_bancario | egresos | Direct mapping |
| registrar_ajuste_contable | handle_registrar_ajuste_contable | egresos | Not explicitly in Wave 3 spec |
| registrar_depreciacion | handle_registrar_depreciacion | egresos | Not explicitly in Wave 3 spec |
| registrar_pago_cuota | handle_registrar_pago_cuota | ingresos | Wave 4 |
| registrar_ingreso_no_operacional | handle_registrar_ingreso_no_operacional | ingresos | Wave 4 |
| registrar_abono_cxc | handle_registrar_cxc_socio | ingresos | Different function, same intent |
| registrar_ingreso_operacional | handle_registrar_ingreso_operacional | ingresos | Not in explicit Wave 4 spec |
| conciliar_extracto_bancario | Not implemented | conciliacion | Phase 3 |
| clasificar_movimiento | Not implemented | conciliacion | Phase 3 |
| enviar_movimiento_backlog | Not implemented | conciliacion | Phase 3 |
| causar_desde_backlog | Not implemented | conciliacion | Phase 3 |
| consultar_movimientos_pendientes | Not implemented | conciliacion | Phase 3 |
| crear_factura_venta | handle_crear_factura_venta_moto | facturacion | Wave 5 |
| consultar_inventario | Not a handler | operativo | MongoDB read only |
| actualizar_estado_moto | MongoDB write | operativo | Not Alegra, not handler |
| consultar_bills | handle_consultar_bills | consultas | GET /bills |
| consultar_plan_cuentas | handle_consultar_plan_cuentas | consultas | Wave 2 |
| consultar_journals | handle_consultar_journals | consultas | Wave 2 |
| consultar_facturas | handle_consultar_facturas | facturacion | Wave 5 |
| consultar_pagos | handle_consultar_pagos | consultas | Wave 2 |
| consultar_saldo_cxc | handle_consultar_cxc_socios | ingresos | Wave 4 |
| consultar_balance_general | handle_consultar_balance_general | consultas | Wave 2 |
| consultar_estado_resultados | handle_consultar_estado_resultados | consultas | Wave 2 |
| consultar_proveedores | handle_consultar_contactos | consultas | GET /contacts |
| consultar_cartera | handle_consultar_cartera | cartera | Wave 6 |
| consultar_recaudo_semanal | handle_consultar_cartera | cartera | Not in explicit spec |
| registrar_nomina | handle_registrar_nomina_mensual | nomina | Wave 6 |
| registrar_cxc_socio | handle_registrar_cxc_socio | ingresos | Wave 4 (CXC) |
| consultar_iva_cuatrimestral | handle_consultar_obligaciones_tributarias | nomina | Wave 6 |
| catalogo_cuentas_roddos | handle_consultar_catalogo_roddos | consultas | Embedded, no query |

**Discrepancies to resolve (Claude's Discretion during Wave 1):**
1. `registrar_gasto` vs `crear_causacion` — may be same handler or split
2. `registrar_ajuste_contable` + `registrar_depreciacion` — appear in tools.py but not explicit in Wave 3 spec
3. `registrar_ingreso_operacional` — tools.py has it, not explicit in Wave 4 spec

**Recommendation:** Implement exactly as PHASE2_CONTEXT.md specifies (Wave descriptions are authoritative). Merge similar tools into single handlers if needed.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP requests to Alegra | Custom httpx calls | AlegraClient.request_with_verify() | 3-layer verification (POST + GET confirmation + ID validation) prevents partial writes; HTTP error handling translated to Spanish; timeout=30s enforced |
| Permission validation | if/else checks | validate_write_permission() + PermissionError | Centralized WRITE_PERMISSIONS dict prevents scattered permission checks; PermissionError is caught by dispatcher |
| Event publishing | Direct MongoDB insert | EventPublisher.publish() | Ensures immutability (insert_one only), adds correlation_id + timestamp, standardized schema across all event types |
| Retenciones calculation | Switch/if statements | retenciones.py service | Single source of truth for tax rates; Auteco exception hardcoded in one place; easier to audit for compliance |
| Account lookups | String IDs | GET /categories or embedded catalogo_cuentas_roddos | Alegra may change IDs; fallback to catalogo_cuentas_roddos for quick reference |
| Async database ops | sync pymongo | Motor AsyncIOMotor | FastAPI async context requires async drivers; Motor matches httpx async pattern |
| Payment confirmation | Single POST /payments | POST /payments + POST /journals (dual-op) | Payment alone doesn't record income; P&L missing the journal means the cuota payment is invisible to CFO P&L reads |

**Key insight:** Alegra is the source of truth (ROG-4). MongoDB writes are for operational state only (inventario_motos status, loanbook cuota tracking). All accounting truth lives in Alegra journals. Handlers are translators, not originators.

---

## Common Pitfalls

### Pitfall 1: Writing Accounting Data to MongoDB Instead of Alegra
**What goes wrong:** Handler calculates entries but stores in MongoDB collection instead of posting to Alegra. Later, CFO queries P&L but sees 0 because roddos_journals collection doesn't exist. Loss of audit trail, regulatory risk.

**Why it happens:** MongoDB feels "local" and fast; developer confusion about what "operational cache" means (MongoDB caches the STATUS of a moto, not the ACCOUNTING TRUTH).

**How to avoid:** REGLA MÁXIMA CONTABLE: All amounts, entries, journal balances MUST live in Alegra. MongoDB stores only: roddos_events (append-only), conciliacion_jobs (batch status), inventario_motos (status field only), loanbook (cuota tracking, not amounts). Every write handler MUST call request_with_verify().

**Prevention:** Grep after each handler: `grep -rn "insert_one|insert_many|update_one" backend/agents/contador/handlers/ | grep -v "roddos_events\|conciliacion_jobs\|inventario_motos\|loanbook"` must return 0.

**Warning signs:**
- Temptation to pre-calculate entries in MongoDB before Alegra POST
- Handler that saves to "journal_staging" collection
- MongoDB collection named anything like "journals", "facturas", "pagos"

### Pitfall 2: Using Deprecated Alegra Endpoints
**What goes wrong:** `/journal-entries` returns HTTP 403. `/accounts` returns HTTP 403. Code hangs or crashes during POST, user sees "Error 403" with no diagnosis.

**Why it happens:** Alegra legacy API docs mention these endpoints; they were valid in v0 but deprecated in v1.

**How to avoid:** ALWAYS use `/journals` (not `/journal-entries`), ALWAYS use `/categories` (not `/accounts`). These are hardcoded in tools.py and client.py.

**Prevention:** Grep: `grep -rn "journal-entries\|/accounts" backend/` must return 0.

**Warning signs:**
- Any reference to "deprecated API" in error message
- Allegra response: `{"error": "Forbidden", "message": "..."}`

### Pitfall 3: Building Entries Without Debit=Credit Balance
**What goes wrong:** Handler creates journal with entries that don't balance. Example: DEBIT 5480 (Arrendamiento) 3.614.953 but CREDIT Banco 3.600.000 (missing ReteFuente entry). Alegra rejects: HTTP 422 "Entries don't balance". User doesn't understand why it failed.

**Why it happens:** Manual entry construction is error-prone; easy to forget one arm of the debit-credit pair.

**How to avoid:** Every handler that builds entries MUST:
1. Sum all debit amounts (should be equal to sum of all credit amounts)
2. Log the entry list before calling request_with_verify()
3. Test with known-good payloads first

**Prevention:** Wave 2 (read-only handlers) validates that Alegra still responds. Wave 3 tests verify entries balance before POST.

**Warning signs:**
- HTTP 422 "Montos no balancean"
- Test failure with "suma débitos != suma créditos"
- Manual Excel calculation doesn't match handler output

### Pitfall 4: Forgetting to Publish Event After Alegra Success
**What goes wrong:** Handler calls request_with_verify() and returns alegra_id, but never publishes event. CFO queries roddos_events and sees no gasto.causado event. Later, Contador audit asks "did this journal actually get recorded?" and can't prove it.

**Why it happens:** Developer focuses on getting Alegra response and forgets the follow-up step.

**How to avoid:** ALWAYS publish event AFTER request_with_verify() succeeds. Pattern:
```python
result = await alegra.request_with_verify(...)
await event_bus.publish(event_type=..., source=..., datos=..., alegra_id=result["_alegra_id"], ...)
return {"success": True, "alegra_id": result["_alegra_id"], ...}
```

**Prevention:** Code review: every write handler MUST have one `event_bus.publish()` call.

**Warning signs:**
- roddos_events collection is empty after running handlers
- Manual test: handler returns success but event bus shows no event
- CFO queries roddos_events and wonders "where are the gasto events?"

### Pitfall 5: Retenciones Logic Scattered Across Handlers
**What goes wrong:** Handler A calculates ReteFuente 3.5%, Handler B calculates 4%. Later, tax law changes to 3.6% and developer must edit 7 handlers. One handler missed → inconsistency.

**Why it happens:** Duplicated logic feels "local" and fast; developer doesn't see the need for a shared service.

**How to avoid:** ALL retenciones calculations go through `retenciones.py`. No handler calculates percentages directly. D-12: All write handlers import retenciones service — never calculate internally.

**Prevention:** Grep: `grep -rn "0.035\|0.04\|0.10\|0.11\|0.025\|0.00414" backend/agents/contador/handlers/` must return 0 (only retenciones.py has percentages).

**Warning signs:**
- Multiple files with "# ReteFuente 3.5%" comment
- Excel-like calculations in handler code
- Different tax rates in different handlers for same operation type

### Pitfall 6: Missing Auteco Autoretenedor Check
**What goes wrong:** Gasto to Auteco NIT 860024781 calculates ReteFuente 3.5% when it should be 0% (autoretenedor). User thinks company saved on retenciones but Alegra shows the withholding anyway. Manual reconciliation required.

**Why it happens:** Autoretenedor logic feels like a special case; easy to forget if implemented outside the retenciones service.

**How to avoid:** retenciones.py checks: `if nit == "860024781": return retefuente_monto = 0`. Hardcoded, no exceptions.

**Prevention:** Test case: `test_auteco_no_retefuente()` calls handler with NIT 860024781 and verifies retefuente_monto == 0.

**Warning signs:**
- Auteco invoice shows ReteFuente deduction (should be 0)
- Alegra journal includes ReteFuente entry for NIT 860024781

### Pitfall 7: VIN/Motor Fields Treated as Optional in Facturación
**What goes wrong:** Invoice created without VIN or motor. Inventory updated to "vendida". Later, moto arrives at customer and dealer realizes they don't know the engine number (illegal in Colombia). Invoice voided, inventory rolled back, but loanbook already created. Cascading fix required.

**Why it happens:** LLM forgets to validate; invoice is "almost right" so handler proceeds.

**How to avoid:** FACT-01: VIN and motor are MANDATORY. Handler MUST check before Alegra POST:
```python
if not tool_input.get("moto_vin") or not tool_input.get("motor"):
    return {"success": False, "error": "VIN y motor son OBLIGATORIOS"}
```

**Prevention:** Test case: `test_factura_sin_vin_bloqueada()` verifies handler rejects. Phase 1 tests verify tools refuse missing fields.

**Warning signs:**
- Invoice in Alegra with item description "[Modelo] [Color] - VIN:  / Motor: " (blank VIN/motor)
- Inventory showing "vendida" but loanbook missing motor number

### Pitfall 8: Dual-Operation Payment Not Atomic
**What goes wrong:** INGR-01 requires POST /payments + POST /journals. Handler posts payment successfully, then POST /journals fails (wrong account ID). Payment recorded in Alegra, but no income journal, so P&L shows $0 income. Manual journal entry required to fix.

**Why it happens:** Async code is tricky; developer assumes both operations succeed, doesn't check both return codes.

**How to avoid:** INGR-01 pattern: both operations MUST succeed before marking cuota as paid.
```python
payment_result = await alegra.request_with_verify("payments", "POST", body=payment_payload)
journal_result = await alegra.request_with_verify("journals", "POST", body=income_journal_payload)
# Only if BOTH succeed: await db.loanbook.update_one(..., {"$set": {"status": "pagada"}})
```

**Prevention:** Test case: `test_pago_sin_journal_falla()` verifies handler returns error if either operation fails.

**Warning signs:**
- Payment exists in Alegra but no income journal
- Manual Journal entry required to balance P&L
- Cuota shows as "pagada" in MongoDB but Alegra journal missing

### Pitfall 9: Anti-Duplicate Logic Not 3-Layer
**What goes wrong:** Handler checks MongoDB for duplicate, doesn't find it. Posts to Alegra. Later, duplicate appears in Alegra (concurrent request, race condition). No protection.

**Why it happens:** Developer implements 1-layer (MongoDB check) and thinks it's sufficient. Alegra's own deduplication is not relied upon.

**How to avoid:** 3-layer anti-dup (CONC-03):
1. Hash the entire record + metadata (Layer 1: extract-level dedup)
2. Check MongoDB if hash exists (Layer 2: application-level dedup)
3. POST to Alegra, then GET to verify (Layer 3: Alegra-level confirmation via request_with_verify)

For nómina: check by mes + empleado nombre before POST.

**Prevention:** Test case: `test_duplicado_bloqueado()` submits same nómina twice, verifies second is rejected.

**Warning signs:**
- Duplicate journal entries in Alegra
- Same employee appears twice in nómina for same month

---

## Code Examples

Verified patterns from Phase 1 code and PHASE2_CONTEXT.md:

### Pattern 1: Write Handler Skeleton (Wave 3)

```python
# Source: PHASE2_CONTEXT.md, handle_crear_causacion pattern

async def handle_crear_causacion(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: EventPublisher,
    user_id: str
) -> dict:
    """Creates an accounting entry (journal) in Alegra."""
    
    # 1. Validate permissions
    validate_write_permission("contador", "POST /journals")
    
    # 2. Extract and validate input
    entries = tool_input.get("entries", [])
    date = tool_input.get("date")  # format: yyyy-MM-dd
    observations = tool_input.get("observations", "")
    
    # 3. Build Alegra payload
    payload = {
        "date": date,
        "observations": observations,
        "entries": [
            {
                "account": {"id": entry["id"]},
                "debit": entry.get("debit", 0),
                "credit": entry.get("credit", 0),
            }
            for entry in entries
        ]
    }
    
    # 4. Execute against Alegra with verification
    result = await alegra.request_with_verify("journals", "POST", body=payload)
    
    # 5. Publish event to bus
    await event_bus.publish(
        event_type="gasto.causado",
        source="agente_contador",
        datos={
            "entries_count": len(entries),
            "total_debit": sum(e.get("debit", 0) for e in entries),
            "observations": observations,
        },
        alegra_id=result["_alegra_id"],
        accion_ejecutada=f"Journal #{result['_alegra_id']} creado en Alegra"
    )
    
    # 6. Return with alegra_id as evidence
    return {
        "success": True,
        "alegra_id": result["_alegra_id"],
        "message": f"Journal #{result['_alegra_id']} creado. {observations}"
    }
```

### Pattern 2: Read-Only Handler (Wave 2)

```python
# Source: PHASE2_CONTEXT.md consultas handlers

async def handle_consultar_plan_cuentas(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: EventPublisher,
    user_id: str
) -> dict:
    """Query chart of accounts from Alegra — read-only."""
    
    # No permission check needed for read (GET is allowed)
    # No event publishing needed (no state change)
    
    try:
        categories = await alegra.get("categories")
        return {
            "success": True,
            "categories": categories,
            "message": f"Se encontraron {len(categories)} cuentas."
        }
    except AlegraError as e:
        return {
            "success": False,
            "error": str(e)
        }
```

### Pattern 3: Retenciones Service

```python
# Source: PHASE2_CONTEXT.md D-08

async def calcular_retenciones(
    tipo: str,           # "arriendo", "servicios", "honorarios_pn", "honorarios_pj", "compras"
    monto: float,        # Monto bruto en COP
    nit: str | None      # NIT del proveedor
) -> dict:
    """Calculate Colombian retenciones for an expense."""
    
    # Check if autoretenedor (Auteco)
    autoretenedor = nit == "860024781"
    
    # Determine retention rates by type
    rates = {
        "arriendo": 0.035,           # 3.5%
        "servicios": 0.04,            # 4%
        "honorarios_pn": 0.10,        # 10%
        "honorarios_pj": 0.11,        # 11%
        "compras": 0.025 if monto > 1344573 else 0,  # 2.5% if base > $1.344.573
    }
    
    retefuente_tasa = rates.get(tipo, 0)
    
    # If autoretenedor, never apply ReteFuente
    if autoretenedor:
        retefuente_tasa = 0
    
    retefuente_monto = monto * retefuente_tasa
    
    # ReteICA always 0.414% (Bogotá)
    reteica_tasa = 0.00414
    reteica_monto = monto * reteica_tasa
    
    # Net to pay
    neto_a_pagar = monto - retefuente_monto - reteica_monto
    
    return {
        "retefuente_tasa": retefuente_tasa,
        "retefuente_monto": retefuente_monto,
        "reteica_tasa": reteica_tasa,
        "reteica_monto": reteica_monto,
        "neto_a_pagar": neto_a_pagar,
        "autoretenedor": autoretenedor,
    }
```

### Pattern 4: ToolDispatcher Injection in FastAPI

```python
# Source: FastAPI Depends() pattern

from fastapi import Depends, FastAPI
from agents.contador.handlers import ToolDispatcher

app = FastAPI()

async def get_dispatcher(
    alegra: AlegraClient = Depends(get_alegra_client),
    db: AsyncIOMotorDatabase = Depends(get_db),
    event_bus: EventPublisher = Depends(get_event_publisher),
) -> ToolDispatcher:
    return ToolDispatcher(alegra, db, event_bus)

@app.post("/api/chat/approve-plan")
async def approve_tool_call(
    session_id: str,
    dispatcher: ToolDispatcher = Depends(get_dispatcher),
):
    # Retrieve pending_action from agent_sessions
    action = await db.agent_sessions.find_one({"session_id": session_id})
    tool_name = action["pending_action"]["tool_name"]
    tool_input = action["pending_action"]["tool_input"]
    
    # Dispatch to handler
    result = await dispatcher.dispatch(tool_name, tool_input, user_id=session_id)
    return result
```

### Pattern 5: Dual-Operation Handler (INGR-01)

```python
# Source: INGR-01 requirement + PHASE2_CONTEXT.md Wave 4

async def handle_registrar_pago_cuota(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: EventPublisher,
    user_id: str
) -> dict:
    """Register a loan payment: POST /payments + POST /journals (both must succeed)."""
    
    validate_write_permission("contador", "POST /payments")
    validate_write_permission("contador", "POST /journals")
    
    # Verify cuota exists in loanbook
    loanbook = await db.loanbook.find_one({"id": tool_input["loanbook_id"]})
    if not loanbook:
        return {"success": False, "error": "Loanbook no encontrado"}
    
    # Operation 1: Record payment in Alegra
    payment_payload = {
        "invoice": {"id": loanbook["alegra_invoice_id"]},
        "value": tool_input["monto"],
        "date": tool_input.get("fecha", date.today().isoformat()),
        "method": tool_input.get("metodo_pago", "transferencia"),
    }
    
    try:
        payment_result = await alegra.request_with_verify("payments", "POST", body=payment_payload)
    except AlegraError as e:
        return {"success": False, "error": f"Error en pago: {str(e)}"}
    
    # Operation 2: Record income journal in Alegra
    journal_payload = {
        "date": tool_input.get("fecha", date.today().isoformat()),
        "observations": f"Cuota #{tool_input['numero_cuota']} - {loanbook['customer_name']}",
        "entries": [
            {"account": {"id": 111005}, "debit": tool_input["monto"]},  # Banco
            {"account": {"id": 4105}, "credit": tool_input["monto"]},   # Ingreso financiero
        ]
    }
    
    try:
        journal_result = await alegra.request_with_verify("journals", "POST", body=journal_payload)
    except AlegraError as e:
        # Payment succeeded but journal failed — this is a problem
        # In production, would need to void the payment
        return {"success": False, "error": f"Error en journal: {str(e)}"}
    
    # Only mark cuota as paid if BOTH operations succeeded
    await db.loanbook.update_one(
        {"id": tool_input["loanbook_id"], "cuota": tool_input["numero_cuota"]},
        {"$set": {"status": "pagada"}}
    )
    
    # Publish event
    await event_bus.publish(
        event_type="pago.cuota.registrado",
        source="agente_contador",
        datos={
            "loanbook_id": tool_input["loanbook_id"],
            "numero_cuota": tool_input["numero_cuota"],
            "monto": tool_input["monto"],
            "payment_id": payment_result["_alegra_id"],
            "journal_id": journal_result["_alegra_id"],
        },
        alegra_id=journal_result["_alegra_id"],
        accion_ejecutada=f"Cuota #{tool_input['numero_cuota']} pagada. Payment #{payment_result['_alegra_id']}, Journal #{journal_result['_alegra_id']}"
    )
    
    return {
        "success": True,
        "alegra_id": journal_result["_alegra_id"],
        "message": f"Cuota #{tool_input['numero_cuota']} registrada: Payment #{payment_result['_alegra_id']}, Journal #{journal_result['_alegra_id']}"
    }
```

---

## State of the Art

| Old Approach | Current Approach (Phase 1) | Phase 2 Evolution | Impact |
|--------------|---------------------------|-------------------|--------|
| Custom HTTP handlers | AlegraClient.request_with_verify() | Unchanged — reused in all handlers | Verified writes prevent partial data; consistent error handling |
| Manual permission checks | validate_write_permission() + PermissionError | Unchanged — called before every write | Centralized enforcement; LLM cannot reason around it |
| Direct tool execution in chat.py | Tool Use loop + ExecutionCard approval | ToolDispatcher.dispatch() on approval | Handlers encapsulate business logic; cleaner separation of concerns |
| Event publishing scattered | EventPublisher.publish() to roddos_events | Unchanged — called after every write | Single source of truth for accounting events; CFO/RADAR consume events |
| Alegra account lookups | GET /categories OR embedded catalogo_cuentas_roddos | Both supported (for flexibility) | Catalogo as fallback if Alegra unavailable; handlers use embedded for quick reference |
| No handler layer | Phase 1: tools defined but not executed | Phase 2: 29 handlers implement operations | Business logic extraction from LLM; testability, reusability, maintainability |

**Deprecated/outdated (NEVER use):**
- `/journal-entries` endpoint — returns 403, use `/journals`
- `/accounts` endpoint — returns 403, use `/categories`
- Account ID 5495 — deprecated fallback, use 5493 (Gastos Generales)
- Custom retenciones logic per handler — centralize in retenciones.py service
- Synchronous HTTP requests — all must be async (httpx, Motor)

---

## Environment Availability

No external tools or services required beyond Phase 1 stack. All Alegra API endpoints are reachable via https://api.alegra.com/api/v1. MongoDB and httpx are already in requirements.

**Database availability:**
- MongoDB via MONGODB_URI env var (inherited from Phase 1)
- Alegra API credentials: ALEGRA_EMAIL, ALEGRA_TOKEN (inherited from Phase 1)

**No blocking dependencies identified.** All handlers use code + Alegra API only.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Tool names in tools.py match dispatcher handler names exactly (or need 1:1 mapping) | Tool Name Mapping table | If mismatch, dispatcher routing fails silently; handler not found error; user confused |
| A2 | request_with_verify() always adds "_alegra_id" key to returned dict | Code Examples | Handlers reference result["_alegra_id"] — if key missing, AttributeError |
| A3 | EventPublisher.publish() function signature matches calls in PHASE2_CONTEXT.md (event_type, source, datos, alegra_id, accion_ejecutada) | Pattern examples | If parameters wrong, event publishing fails; CFO has no audit trail |
| A4 | FastAPI Depends() and async/await patterns work with ToolDispatcher injection | Pattern examples | If dependency injection broken, handlers never called from chat.py |
| A5 | Alegra /journals POST returns {"id": ...} in response (not nested deeper) | Pattern 1 example | If ID nested in response, result["id"] will fail; handlers crash |
| A6 | Autoretenedor list contains only Auteco NIT 860024781 (not others) | Retenciones service | If other NITs added later without updating service, inconsistent behavior |

---

## Open Questions

1. **Tool Name Discrepancies**
   - What we know: tools.py has 34 tools, PHASE2_CONTEXT.md lists 29 handlers. The mapping table identifies ~5 tools not explicitly in wave specs (registrar_ajuste_contable, registrar_depreciacion, registrar_ingreso_operacional, consultar_recaudo_semanal, actualizar_estado_moto).
   - What's unclear: Should these extra tools be implemented as handlers, or are they deferred?
   - Recommendation: During Wave 1, clarify with user: implement only the 29 handlers from PHASE2_CONTEXT.md, or implement all 34 tool handlers? Phase 2 is scoped to 29 per D-01.

2. **BackgroundTasks + job_id Implementation**
   - What we know: Wave 3 mentions `crear_causacion_masiva` needs BackgroundTasks for lotes > 10 registros, with job_id stored in MongoDB.
   - What's unclear: FastAPI BackgroundTasks() vs celery vs simple job queue? How is job_id tracked in conciliacion_jobs collection?
   - Recommendation: Use FastAPI BackgroundTasks for simplicity (already in requirements). job_id in conciliacion_jobs collection tracks status.

3. **Loanbook Updates During Facturación**
   - What we know: Wave 5 says successful invoice triggers loanbook creation with status "pendiente_entrega".
   - What's unclear: Is loanbook ID auto-generated or derived from invoice ID? What fields in loanbook entry?
   - Recommendation: Document loanbook schema in Wave 0 or Wave 5 planning phase.

4. **Chat.py Integration Point**
   - What we know: Dispatcher must be called when ExecutionCard is approved.
   - What's unclear: Where exactly in the flow? Is it in a new endpoint like POST /api/chat/approve-plan, or inside process_chat() itself?
   - Recommendation: Wave 1 planning should clarify: new endpoint vs. modified process_chat().

---

## Security Domain

### Applicable ASVS Categories (from Phase 1 carried forward)

| ASVS Category | Applies | Phase 2 Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Not in scope — inherited from Phase 1 user session |
| V3 Session Management | No | Inherited from Phase 1 |
| V4 Access Control | Yes | validate_write_permission() enforced before every Alegra write; PermissionError raised; prevents unpermitted writes |
| V5 Input Validation | Yes | Handler input validation (VIN mandatory in facturacion, entries must balance in egresos, date format yyyy-MM-dd, monto > 0) |
| V6 Cryptography | Yes | HTTPS only (https://api.alegra.com/api/v1); HTTP credentials (ALEGRA_EMAIL, ALEGRA_TOKEN) never logged; environment variables only |
| V9 Communications | Yes | All Alegra API calls via HTTPS; httpx timeout=30s enforced |

### Known Threat Patterns for Alegra-Handler Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Unauthenticated API calls | Authentication | ALEGRA_EMAIL + ALEGRA_TOKEN in httpx auth parameter; rotated in Phase 1 |
| Partial writes (POST succeeds, GET verification fails) | Data Integrity | request_with_verify() enforces GET confirmation after POST; raises AlegraError if GET fails |
| Unbalanced entries in journals | Data Integrity | Handler validates debit == credit before POST; Alegra 422 response if entries don't balance |
| Unauthorized handler execution (e.g., CFO calling Contador handler) | Authorization | validate_write_permission() checks agent_type against WRITE_PERMISSIONS; PermissionError raised; handler never executes |
| Injection via tool_input (e.g., SQL-like in observations field) | Injection | Alegra API is REST JSON, not SQL; observations field treated as string literal; no dynamic query construction |
| Duplicate transactions (race condition) | Integrity | 3-layer anti-dup: hash check + MongoDB check + Alegra GET verification; concurrent requests protected by request_with_verify() verification step |
| Missing audit trail (no event published) | Non-repudiation | EventPublisher.publish() called after every write; roddos_events append-only (no delete/update); all events immutable |
| Retenciones miscalculation (tax evasion risk) | Compliance | Single retenciones.py service; rates hardcoded; Auteco exception hardcoded; easy to audit for compliance |

---

## Validation Architecture

Skipped: `workflow.nyquist_validation` is explicitly set to `false` in `.planning/config.json`. No automated test infrastructure required for Phase 2 validation.

---

## Sources

### Primary (HIGH confidence)

- CONTEXT.md (`.planning/phases/02-core-accounting-operations/02-CONTEXT.md`) — Authoritative user decisions and locked constraints
- SISMO_V2_Phase2_CONTEXT.md (`.planning/phases/phase-2-core-accounting/SISMO_V2_Phase2_CONTEXT.md`) — Spec for 29 handlers, 7 waves, ToolDispatcher design
- tools.py (`backend/agents/contador/tools.py`) — 34 tool definitions with exact input_schema and descriptions
- client.py (`backend/services/alegra/client.py`) — request_with_verify() implementation and Alegra endpoints
- chat.py (`backend/agents/chat.py`) — Tool Use loop and ExecutionCard pattern
- permissions.py (`backend/core/permissions.py`) — WRITE_PERMISSIONS enforcement
- events.py (`backend/core/events.py`) — EventPublisher.publish() signature and pattern
- REQUIREMENTS.md (`.planning/REQUIREMENTS.md`) — 16 Phase 2 requirements mapped to handlers
- CLAUDE.md (project) — ROG-1, ROG-4, retenciones rates, account IDs, Auteco exception

### Secondary (MEDIUM confidence)

- ROADMAP.md (`.planning/ROADMAP.md`) — Phase 2 success criteria and dependencies

---

## Metadata

**Confidence breakdown:**
- Standard Stack: HIGH — All Alegra endpoints, retenciones rates, account IDs verified against tools.py and client.py
- Architecture: HIGH — ToolDispatcher pattern, handler signature, request_with_verify() flow all specified in PHASE2_CONTEXT.md
- Pitfalls: HIGH — ROG rules from CLAUDE.md are explicit; common pitfalls derived from rules
- Tool Name Mapping: MEDIUM — Some discrepancies between tools.py (34) and PHASE2_CONTEXT.md (29 handlers); mapping table flags ambiguities for Wave 1 clarification

**Research date:** 2026-04-09  
**Valid until:** 2026-04-16 (7 days — Phase 2 is stable, no rapid changes expected)

---

*Phase: 02-core-accounting-operations*  
*Research completed: 2026-04-09*
