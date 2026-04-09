# Architecture Patterns — AI Agent Orchestration with ERP Integration

**Project:** SISMO V2 — Multi-Agent Orchestrator for RODDOS S.A.S.
**Domain:** Financial automation, ERP integration, agent coordination
**Researched:** 2026-04-09
**Confidence Level:** HIGH (derived from SISMO V2 Phase 0 specification + established multi-agent patterns)

---

## Executive Summary

SISMO V2 implements a **permission-isolated, event-driven multi-agent system** where 4 specialized AI agents (Contador, CFO, RADAR, Loanbook) coordinate through a MongoDB append-only event bus. Only the Contador agent writes to the external ERP (Alegra); all other agents read-only. This architecture prevents the identity-mixing and permission-bypass problems that plagued V1.

The system follows three foundational patterns:
1. **Single-writer principle** — One agent (Contador) owns all Alegra writes
2. **Event-driven communication** — Agents communicate via immutable log (roddos_events), not direct calls
3. **Code-enforced permissions** — WRITE_PERMISSIONS validated at runtime, not in prompts

---

## System Components

### Component 1: Router — Intent Dispatch Layer

**Purpose:** Receive user requests; route to correct agent with confidence threshold

**Responsibility:**
- Analyze user prompt intent (NLP classification)
- Validate confidence ≥ 0.70
- If confidence < 0.70: ask clarification ("Is this accounting, credit, or finance?")
- Route confirmed request to agent dispatcher

**Input:** User message (plain text)
**Output:** Agent ID + routed message + correlation_id (UUID)

**Communicates With:**
- Anthropic Claude API (intent classification)
- Agent Dispatcher (routed request)
- Shared State (session context)

**Technology:**
- Python FastAPI endpoint `/ai-chat/route`
- Prompt-based intent classifier (Anthropic)
- Threshold comparison logic

**Build Dependency:** Must exist before any agent can be tested. No agent receives requests without routing.

---

### Component 2: Agent Dispatcher — Identity Container

**Purpose:** Instantiate agents with isolated system prompts and permission boundaries

**Responsibility:**
- Receive routed request from Router
- Load agent-specific system prompt (SYSTEM_PROMPTS[agent_type])
- Initialize permission validator (WRITE_PERMISSIONS[agent_type])
- Call Anthropic Tool Use API with agent identity
- Collect tool calls from agent
- Validate each tool call against WRITE_PERMISSIONS
- Raise PermissionError if agent attempts unauthorized action
- Pass authorized tool calls to Tool Executor
- Collect results and return to agent
- Publish events to bus after successful actions

**Input:** Agent type, routed message, correlation_id, user identity
**Output:** Tool calls (validated), agent response, events (published)

**Communicates With:**
- Router (receives routed request)
- Anthropic Tool Use API (calls agent LLM)
- Tool Executor (validated tool calls)
- Permission Validator (checks before execution)
- Event Publisher (publishes success events)

**Technology:**
- Python FastAPI handler
- Anthropic SDK (Tool Use native interface)
- Feature flag for fallback (TOOL_USE_ENABLED)
- Simple dict-based permission enforcement

**Build Dependency:** Core orchestration. Depends on Router (input), Tool Executor (actions), Tool definitions (Anthropic schema). Phase 0 completion criteria.

---

### Component 3: Tool Executor — Action Runner

**Purpose:** Execute validated tool calls against MongoDB and Alegra API

**Responsibility:**
- Receive tool name + parameters from Dispatcher
- Validate parameters against tool schema
- For Alegra writes: call request_with_verify()
  - POST operation
  - Verify HTTP 200/201
  - GET to confirm creation
  - Only on verification success: return ID
- For MongoDB operations:
  - Enforce append-only for roddos_events
  - Standard write for other collections
  - Index management
- Handle retries (exponential backoff for 429/503)
- Return result or error to Dispatcher

**Input:** Tool name, parameters dict
**Output:** Result dict (with IDs) or error object

**Communicates With:**
- Alegra API (external, write-verify loop)
- MongoDB (operational data + event bus)
- Dispatcher (receives tool calls, returns results)

**Technology:**
- Python async Motor (MongoDB)
- aiohttp or httpx (Alegra API, including request_with_verify)
- Retry logic with exponential backoff
- Error translation to Spanish user messages

**Build Dependency:** Depends on Alegra API credentials, MongoDB connection. request_with_verify() is non-negotiable before any write succeeds.

---

### Component 4: Permission Validator — Code-Enforced Boundary

**Purpose:** Prevent agents from writing where not permitted (code-level, not prompt-level)

**Responsibility:**
- Receive agent type + target (collection/endpoint) + operation
- Look up WRITE_PERMISSIONS[agent_type][operation][target]
- Raise PermissionError if not found
- Short-circuit before Tool Executor runs

**Input:** Agent type, target (e.g., "cartera_pagos", "POST /journals"), operation type
**Output:** Boolean (authorized) or PermissionError

**Communicates With:**
- Dispatcher (validates before tool call)

**Technology:**
- Python function with dict lookup
- Raises PermissionError (not recoverable by LLM)

**Build Dependency:** Must be in place before Dispatcher. Cannot be bypassed.

**WRITE_PERMISSIONS Structure:**

```
contador:
  mongodb: [cartera_pagos, cxc_socios, cxc_clientes, plan_cuentas_roddos, inventario_motos, roddos_events]
  alegra: [POST /journals, POST /invoices, POST /payments, DELETE /journals, GET /categories, GET /journals]

cfo:
  mongodb: [cfo_informes, cfo_alertas, roddos_events]
  alegra: [GET /journals, GET /invoices, GET /payments, GET /categories, GET /bills]

radar:
  mongodb: [crm_clientes, gestiones_cobranza, roddos_events]
  alegra: []

loanbook:
  mongodb: [inventario_motos, loanbook, roddos_events]
  alegra: []
```

All agents can append to `roddos_events` (read-only except append).

---

### Component 5: Event Bus (roddos_events) — Append-Only Log

**Purpose:** Enable agent-to-agent communication without direct calls

**Responsibility:**
- Accept immutable event records from agents
- Prevent modification/deletion of published events
- Serve as source-of-truth for agent interactions
- Enable other agents to react to state changes

**Input:** Event objects (from Tool Executor after success)
**Output:** Event log (to agents and external readers)

**Schema (immutable, all required):**
```
{
  event_id:        UUID v4 (unique, generated by system)
  event_type:      string (enum: gasto.causado, factura.venta.creada, pago.cuota.registrado, etc.)
  source:          string (agent_contador, cfo, radar, loanbook)
  correlation_id:  UUID (links to original user request)
  timestamp:       ISO 8601 UTC
  datos:           {} (event-specific payload)
  alegra_id:       string | null (ID returned by Alegra, if applicable)
  accion_ejecutada: string (human-readable summary in Spanish)
}
```

**Communicates With:**
- Tool Executor (publishes events after success)
- All agents (read events for reaction/state invalidation)

**Technology:**
- MongoDB collection with immutable TTL (never delete, expire after policy)
- Unique index on event_id
- Timestamp-based ordering

**Build Dependency:** Integral to Phase 0. Must be in place before any multi-agent coordination.

---

### Component 6: Alegra API Adapter — Write-Verify Layer

**Purpose:** Ensure all Alegra writes are verified before claiming success

**Responsibility:**
- Execute POST to Alegra endpoint (journals, invoices, payments)
- Check HTTP 200/201 immediately
- If error: translate to Spanish, return error
- If success: GET same record to confirm it exists
- Only after GET 200: return created ID to agent

**Input:** Endpoint, method, payload, verification query
**Output:** Created ID or error

**Communicates With:**
- Tool Executor (called by request_with_verify())
- Alegra API (external)

**Technology:**
- Python aiohttp with retry logic
- Basic auth (API token from env)
- Error message translation
- GET-after-POST pattern (mandatory)

**Build Dependency:** Critical for Fase 0 completion. Non-negotiable before any write-capable agent runs.

---

### Component 7: Tool Definitions (Anthropic Schema) — Agent Capabilities

**Purpose:** Define what each agent can ask to do (Tool Use native format)

**Responsibility:**
- Define 32+ tools for Contador (register_gasto, create_factura, register_pago, etc.)
- Define ~10 tools for CFO (generate_p_l, check_alert_threshold, etc.)
- Define ~8 tools for RADAR (register_gestion, send_whatsapp_reminder, etc.)
- Define ~6 tools for Loanbook (update_cuota_estado, calculate_schedule, etc.)
- Each tool has: name, description, required parameters, parameter types

**Input:** Agent type
**Output:** Tool list in Anthropic Tool Use schema

**Communicates With:**
- Dispatcher (loads tools for agent)
- Anthropic API (uses as system definition)

**Technology:**
- Python dataclasses or TypedDict for schema
- JSON serialization for Anthropic

**Build Dependency:** Tools defined for each agent before Dispatcher can call Anthropic API with that agent.

---

## Data Flow

### Flow 1: User Registers Expense (Contador Write)

```
User Message
    ↓
[Router] classify intent + confidence check
    ↓
If confidence >= 0.70: dispatch to contador
    ↓
[Dispatcher] load SYSTEM_PROMPT_CONTADOR + CONTADOR tools
    ↓
[Anthropic Tool Use] Contador reviews expense, calls tool: register_gasto(cuenta_id, monto, descripcion, retenciones)
    ↓
[Dispatcher] validate tool call against WRITE_PERMISSIONS[contador][mongodb] and [alegra]
    ↓
If authorized: route to [Tool Executor]
    ↓
[Tool Executor] calls request_with_verify():
    - POST /journals to Alegra
    - Verify HTTP 200
    - GET journal to confirm
    - Return ID on success
    ↓
[Tool Executor] on success:
    - Publish event: {event_type: "gasto.causado", source: "agente_contador", alegra_id: ID, ...}
    - Return result to Dispatcher
    ↓
[Dispatcher] returns result + ID to Contador
    ↓
[Contador] to user: "Gasto de $3.614.953 registrado. ID Alegra: J-12345"
    ↓
[CFO, RADAR, Loanbook] see event in roddos_events, invalidate caches as needed
```

**Duration:** ~2-3 seconds (Alegra + GET verification)
**Failure modes:** Alegra 4xx/5xx → error translated to Spanish, user sees specific problem

---

### Flow 2: CFO Generates P&L Report (Read-Only)

```
User Message: "¿Cuál es el P&L de marzo?"
    ↓
[Router] classify → confidence >= 0.70, route to cfo
    ↓
[Dispatcher] load SYSTEM_PROMPT_CFO + CFO tools (read-only)
    ↓
[Anthropic Tool Use] CFO calls: generate_p_l_report(start_date="2026-03-01", end_date="2026-03-31")
    ↓
[Dispatcher] validate tool against WRITE_PERMISSIONS[cfo]
    - No POST allowed → tools only read and write cfo_informes/cfo_alertas
    ↓
[Tool Executor] calls:
    - GET /journals from Alegra
    - GET /invoices from Alegra
    - GET /payments from Alegra
    - Read loanbook from MongoDB
    - Calculate: ingresos operacionales + ingresos financieros + gastos + retenciones
    - Separate Sección A (devengado) from Sección B (caja real)
    - Write report to cfo_informes collection
    ↓
[Dispatcher] return report to CFO
    ↓
[CFO] to user: formatted P&L table with numbers
```

**Duration:** ~1-2 seconds (all GET operations)
**Cache invalidation:** Triggered by events (gasto.causado, pago.cuota.registrado, etc.)

---

### Flow 3: RADAR Requests Pago, Contador Executes (Cross-Agent)

```
[RADAR] detects payment in cartera_pagos (from external source)
    ↓
[RADAR] publishes event: {event_type: "pago.detectado", source: "radar", datos: {loanbook_id, monto, ...}}
    ↓
[Contador] subscribes to roddos_events, sees pago.detectado event
    ↓
[Contador] (via Tool Use) calls: register_pago(loanbook_id, monto, fecha)
    ↓
[Tool Executor] executes:
    - POST /payments to Alegra (against invoice)
    - POST /journals to Alegra (ingreso financiero)
    - request_with_verify() for both
    ↓
On success: publish event "pago.cuota.registrado" with both Alegra IDs
    ↓
[Loanbook] subscribes to event, updates cuota estado → "pagada"
    ↓
[CFO] subscribes to event, invalidates recaudo cache
```

**Pattern:** No direct agent-to-agent calls. All communication via roddos_events.

---

### Flow 4: Backlog Recovery (Fallback to Manual Causation)

```
[Contador] attempts to classify bank movement with confidence < 0.70
    ↓
Movement can't be caused automatically
    ↓
[Tool Executor] writes to backlog collection (not roddos_events, this is recoverable)
    ↓
[Dispatcher] publishes event: {event_type: "movimiento.pendiente_clasificacion", source: "agente_contador", datos: {movimiento, confianza: 0.45}}
    ↓
User (Liz) sees "Backlog (298)" badge in sidebar
    ↓
[Backlog Modal] shows movement details
    ↓
[Liz] manually selects cuenta contable
    ↓
[Contador] (via Tool Use) calls: causar_desde_backlog(backlog_id, cuenta_id)
    ↓
[Tool Executor] POST /journals → verify
    ↓
On success: move backlog item to archived, publish event
```

**Guarantee:** Zero movements lost. Everything either caused automatically or sits in Backlog until manual causation.

---

## Communication Patterns

### Pattern 1: Synchronous Tool Execution (Contador → Alegra)

**Used for:** Real-time accounting operations
**Latency:** ~2-3 seconds (Alegra response + verification GET)
**Failure handling:** Retry with exponential backoff (429/503), translate errors to Spanish

```
Contador tool call
  ↓
[Tool Executor] + [Alegra Adapter] → request_with_verify()
  ↓
Success: return ID, publish event
Error: return translated error, no event published
```

---

### Pattern 2: Asynchronous Event Consumption (Event Bus → Agents)

**Used for:** Multi-agent coordination, cache invalidation
**Latency:** ~100-500ms per event subscription
**Guarantee:** Immutable, ordered by timestamp

```
Event published to roddos_events
  ↓
All agents subscribed to event type see it
  ↓
Agent reacts (cache invalidation, state update)
  ↓
No direct agent-to-agent calls
```

---

### Pattern 3: Permission-Gated Tool Dispatch (Dispatcher → Permission Validator)

**Used for:** Every tool call
**Latency:** <1ms (dict lookup)
**Guarantee:** Non-bypassable; LLM cannot reason around PermissionError

```
Dispatcher receives tool call from Anthropic
  ↓
[Permission Validator] checks WRITE_PERMISSIONS[agent][operation][target]
  ↓
Not found: raise PermissionError immediately
Found: continue to Tool Executor
```

---

### Pattern 4: Confidence-Based Routing (Router → Agent)

**Used for:** Initial request dispatch
**Latency:** ~500ms (intent classification)
**Guarantee:** Ambiguous requests ask for clarification, not misdirected

```
User message → Router
  ↓
[Classifier] analyze intent, return confidence 0-1
  ↓
If confidence >= 0.70: dispatch to agent
If confidence < 0.70: ask user clarification question
```

---

## Component Boundaries

| Component | Owns | Reads | Writes | Communicates With |
|-----------|------|-------|--------|-------------------|
| Router | Intent classification | User message | roddos_events (append) | Dispatcher |
| Dispatcher | Agent instantiation, tool validation | WRITE_PERMISSIONS, agent prompts | — | Router, Anthropic, Tool Executor |
| Tool Executor | Action execution | MongoDB collections, Alegra endpoints | MongoDB (permitted), Alegra (via request_with_verify), roddos_events (append) | Dispatcher, MongoDB, Alegra |
| Permission Validator | Authorization logic | WRITE_PERMISSIONS dict | — | Dispatcher |
| Event Bus (roddos_events) | Event log | Append-only writes | Appends only, never update/delete | All agents |
| Alegra Adapter | Write-verify loop | HTTP responses | — | Tool Executor |
| Tool Definitions | Agent capability schema | — | — | Dispatcher, Anthropic |

---

## Suggested Build Order

### Phase 0: Foundations (Completion Gates for Phase 1)

1. **Permission Validator** (1-2 days)
   - Define WRITE_PERMISSIONS dict
   - Implement validate_write_permission() function
   - Write unit tests: CFO cannot POST, Contador can POST

2. **Event Bus (roddos_events)** (1-2 days)
   - Create MongoDB collection schema
   - Immutable index + unique event_id
   - Append-only insert logic (no updates/deletes)

3. **Alegra Adapter** (2-3 days)
   - Implement request_with_verify() pattern
   - Error translation to Spanish
   - Retry logic with exponential backoff
   - Test against Alegra sandbox

4. **Router** (2-3 days)
   - Intent classifier (Anthropic prompt-based)
   - Confidence threshold (0.70)
   - Route to correct agent
   - Test: "registra gasto" → contador, "¿P&L?" → cfo

5. **Tool Definitions** (2-3 days)
   - Define Antropic Tool Use schema for Contador (32+ tools)
   - Define schema for CFO, RADAR, Loanbook
   - Validate against Anthropic API

6. **Dispatcher** (3-4 days)
   - Load system prompts by agent
   - Call Anthropic Tool Use API
   - Validate tool calls with Permission Validator
   - Route to Tool Executor
   - Publish events to bus

7. **Tool Executor** (3-4 days)
   - Execute MongoDB operations
   - Call Alegra Adapter
   - Handle retries
   - Return results or errors

**Phase 0 Complete When:**
- 22 smoke tests passing
- CFO cannot write to Alegra (PermissionError)
- Contador can write to Alegra via request_with_verify()
- Router routes ambiguous requests to clarification, not wrong agent
- All events published to roddos_events after success

---

### Phase 1: Agent Capabilities (Incremental, depend on Phase 0)

Each agent capability built independently:
1. Contador — 8 capabilities (egresos, conciliación, nómina, CXC, facturación, ingresos cuotas, ingresos no-operacionales, Backlog)
2. CFO — P&L report generation
3. RADAR — Gestiones de cobranza
4. Loanbook — Cronograma generation, estado updates

**Each capability:**
- Depends on Tool Executor + Alegra Adapter
- Defines new tools in Tool Definitions
- Adds to WRITE_PERMISSIONS
- Publishes new event types to roddos_events
- Tested with integration tests against Alegra sandbox

---

## Scalability Considerations

| Concern | At 100 users | At 10K users | At 1M users |
|---------|--------------|--------------|-------------|
| Agent instantiation (tool loading) | ~100ms / request | ~200ms / request | May require tool caching |
| Alegra API rate limits | <1 req/sec per agent | 10-100 req/sec total | Implement queue + batch operations |
| roddos_events log size | ~1K events/month | ~100K events/month | TTL policy, archive old events |
| Permission validation lookup | <1ms | <1ms | <1ms (dict lookup, no change) |
| Concurrent agent calls | 1-2 agents | 5-10 agents | May require queue/rate limiting |
| MongoDB indexes | ~10 total | ~20 total | Covered queries on event_id, timestamp |

**Recommendation:** Current architecture scales to 10-100K users without modification. Beyond that: implement event archival, Alegra API queue, tool caching.

---

## Failure Scenarios & Recovery

### Scenario 1: Alegra API returns 500

**What happens:**
- request_with_verify() gets 500 from POST
- Retry with exponential backoff (1s, 2s, 4s, 8s max)
- If all retries fail: return error to user in Spanish
- Tool Executor does NOT publish event (no success)
- Contador offers to save to Backlog

**Recovery:** User retries, or Contador saves to Backlog for manual causation

---

### Scenario 2: GET verification fails after successful POST

**What happens:**
- POST /journals succeeds (201)
- GET /journals?id=X fails (404)
- Contador retries GET
- If GET still fails: return error "Registro creado en Alegra pero no se pudo verificar. ID: X"
- Do NOT publish event (verification failed)

**Recovery:** CFO manually verifies in Alegra UI, or Contador retries

---

### Scenario 3: Dispatcher receives unauthorized tool call

**What happens:**
- CFO tries to call "register_gasto" (not in CFO tools)
- Permission Validator checks WRITE_PERMISSIONS[cfo] — not found
- Raises PermissionError immediately
- LLM cannot recover from PermissionError
- Dispatcher returns error to CFO: "No tienes permiso de escritura en registros contables"

**Recovery:** User asks Contador instead, or clarifies request

---

### Scenario 4: roddos_events append fails (MongoDB write error)

**What happens:**
- Tool Executor publishes event to roddos_events
- Insert fails (disk full, connection error, etc.)
- Tool Executor returns error, but original action (journal in Alegra) was successful
- Inconsistency: Alegra has journal, roddos_events doesn't have event

**Prevention:** Implement two-phase commit or compensating transaction if events critical
**Current approach:** Events are durable but non-critical; agent can retry event publishing

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Direct Agent-to-Agent Calls

**What:** Contador calls RADAR.request_cobro() directly
**Why bad:** Creates circular dependencies, tight coupling, unpredictable state
**Instead:** Contador publishes event "pago.detectado", RADAR subscribes

---

### Anti-Pattern 2: Permissions Only in Prompts

**What:** System prompt says "CFO cannot write to Alegra" but no code enforcement
**Why bad:** LLM can reason around restrictions if context permits
**Instead:** WRITE_PERMISSIONS dict in code, PermissionError raises immediately

---

### Anti-Pattern 3: Alegra Writes Without Verification

**What:** POST succeeds, assume creation, don't GET to verify
**Why bad:** ~5% of Alegra requests fail silently; V1 had 176 duplicate journals
**Instead:** request_with_verify() always — POST + GET pattern mandatory

---

### Anti-Pattern 4: Mutable Event Log

**What:** Agent publishes event, then agent or admin deletes/modifies event
**Why bad:** Audit trail becomes unreliable; other agents miss state changes
**Instead:** roddos_events append-only; deletions forbidden by schema

---

### Anti-Pattern 5: No Correlation IDs

**What:** Request flows through system but no way to trace it end-to-end
**Why bad:** Debugging failures is impossible; can't link user action to Alegra ID to event
**Instead:** Every request gets UUID v4, passed through Router → Dispatcher → Tool Executor → Event

---

## Summary: Why This Architecture Works for SISMO

1. **Single Writer** (Contador) — Prevents simultaneous writes to Alegra, simplifies audit trail
2. **Event-Driven** — Agents coordinate without direct calls, enables async state replication
3. **Code Permissions** — PermissionError cannot be bypassed, unlike prompt-based rules
4. **Write-Verify Loop** — Ensures no silent failures; Alegra is source of truth
5. **Immutable Log** — roddos_events is audit trail; no events hidden or modified
6. **Correlation IDs** — Every user action traceable end-to-end

This prevents the V1 loops:
- Identity-mixing (Router assigns one agent per request)
- Permission bypass (code validates, not prompt)
- Duplicate journals (request_with_verify())
- Inconsistent data (Alegra is source of truth)
- Lost movements (Backlog catches anything automated can't handle)

---

## Sources & References

- SISMO V2 Phase 0 Specification (PROJECT.md, SISMO_V2_Fase0_Fase1.md)
- SISMO V2 System Prompts (SISMO_V2_System_Prompts.md)
- Anthropic Tool Use API documentation (native mode)
- Multi-agent architecture patterns (event-driven coordination)
- ERP integration best practices (write-verify, single writer)
- MongoDB immutable collections patterns
