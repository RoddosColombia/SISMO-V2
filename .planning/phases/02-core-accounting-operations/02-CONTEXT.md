# Phase 2: Core Accounting Operations - Context

**Gathered:** 2026-04-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement 29 handlers that connect the Contador's 34 tools to Alegra real. This is the "missing middle" — Phase 1 built the framework (tools, router, permissions, events, client), Phase 2 builds the handlers that execute tool calls against Alegra via request_with_verify(). Conciliación bancaria (5 handlers with parsers) excluded — goes to Phase 3.

**Scope absorbed from original roadmap Phases 3 and 4:**
- Facturación (FACT-01, FACT-02, FACT-03) — now in Phase 2 Wave 5
- Ingresos (INGR-01, INGR-02) — now in Phase 2 Wave 4
- Backlog routing (BACK-01) — partial, movement routing only
- P&L read-only (PL-01, PL-02) — Wave 2 consultas handles this

**Requirements covered:** EGRE-01 through EGRE-04, CONC-04, NOMI-01, CXC-01, CXC-02, FACT-01, FACT-02, FACT-03, INGR-01, INGR-02, BACK-01 (partial), PL-01, PL-02

</domain>

<decisions>
## Implementation Decisions

### Scope Alignment
- **D-01:** PHASE2_CONTEXT.md (SISMO_V2_Phase2_CONTEXT.md) is the authoritative spec. The 29 handlers described there are the scope of this phase, overriding the original GSD roadmap split.
- **D-02:** Conciliación bancaria (parsers BBVA/Bancolombia/Davivienda, batch processing, anti-dup hash) is Phase 3 — too many edge cases for this phase.
- **D-03:** Backlog UI (BACK-02, BACK-03) remains in a later phase. Phase 2 only implements the routing of movements to backlog (BACK-01 partial).

### Handler Architecture
- **D-04:** All handlers live in `backend/agents/contador/handlers/` organized by category: dispatcher.py, egresos.py, ingresos.py, facturacion.py, consultas.py, cartera.py, nomina.py.
- **D-05:** ToolDispatcher class receives tool_name + tool_input, dispatches to the correct handler. Injected with AlegraClient, db, EventPublisher via constructor.
- **D-06:** chat.py modified to connect tool_use blocks to ToolDispatcher. Write tools require ExecutionCard confirmation. Read tools (consultar_*) execute immediately without confirmation.
- **D-07:** Conciliación tools return "Disponible en Phase 3" instead of executing.

### Retenciones Engine
- **D-08:** Shared service at `backend/services/retenciones.py`. Receives: tipo_operacion (arriendo/servicios/honorarios_pn/honorarios_pj/compras), monto_bruto, nit_proveedor. Returns: {retefuente_tasa, retefuente_monto, reteica_tasa, reteica_monto, neto_a_pagar}.
- **D-09:** Autoretenedores hardcodeados — only Auteco NIT 860024781 for now. If nit == "860024781" -> retefuente = 0 always.
- **D-10:** ReteICA Bogota = 0.414% always applied.
- **D-11:** Compras ReteFuente 2.5% only if monto > $1.344.573.
- **D-12:** All write handlers import retenciones service — never calculate internally.

### Write Handler Pattern (every write handler follows this)
- **D-13:** validate_write_permission() BEFORE any write
- **D-14:** Build Alegra payload with correct entries (debito = credito)
- **D-15:** Execute via alegra.request_with_verify() — POST -> HTTP 200 -> GET verify -> return ID
- **D-16:** Publish event to bus AFTER successful write
- **D-17:** Return alegra_id as auditable evidence

### Files That MUST NOT Be Modified
- **D-18:** backend/agents/contador/tools.py — tool definitions are final (34 tools)
- **D-19:** backend/core/permissions.py — permission enforcement is final
- **D-20:** backend/core/events.py — event publisher is final
- **D-21:** backend/core/database.py — DI pattern is final
- **D-22:** backend/services/alegra/client.py — Alegra client is final

### 7 Waves (from PHASE2_CONTEXT.md)
- **D-23:** Wave 1: ToolDispatcher + chat.py integration
- **D-24:** Wave 2: 8 consultas read-only handlers
- **D-25:** Wave 3: 7 egresos handlers with retenciones
- **D-26:** Wave 4: 4 ingresos + CXC handlers
- **D-27:** Wave 5: 4 facturacion handlers with VIN
- **D-28:** Wave 6: 6 nomina + cartera + catalogo handlers
- **D-29:** Wave 7: 12 integration tests + smoke test

### Verification
- **D-30:** MANDATORY grep after every wave: `grep -rn "insert_one|insert_many|update_one|replace_one" backend/agents/contador/handlers/ | grep -v "roddos_events|conciliacion_jobs|inventario_motos|loanbook"` must return 0 lines.
- **D-31:** Phase 1 tests (76) must continue passing — zero regressions.
- **D-32:** No /journal-entries, no /accounts, no 5495 in any handler.

### Claude's Discretion
- Error message formatting (within Spanish requirement)
- Background task implementation details for masiva handlers
- Anti-duplicate hash algorithm specifics
- Event payload structure beyond required fields

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 2 Master Spec
- `.planning/phases/phase-2-core-accounting/SISMO_V2_Phase2_CONTEXT.md` — Authoritative 29-handler spec with wave breakdown, handler patterns, dispatcher design, and verification checklist

### SISMO V2 Specifications
- `.planning/SISMO_V2_CLAUDE.md` — ROG rules, Alegra quirks, retention rates, account IDs
- `.planning/SISMO_V2_Fase0_Fase1.md` — Fase 1 capability specs (egresos, facturacion, ingresos, nomina, CXC, P&L)
- `.planning/SISMO_V2_Plan_Ejecucion.md` — Execution tasks F1-C1 through F1-C9
- `.planning/SISMO_V2_System_Prompts.md` — System prompts with WRITE_PERMISSIONS
- `.planning/SISMO_V2_Registro_Canonico.md` — Canonical registry of endpoints, collections, IDs

### Phase 1 Code (read but do NOT modify)
- `backend/agents/contador/tools.py` — 34 tool definitions (names, params, descriptions)
- `backend/agents/chat.py` — process_chat() with SSE + Tool Use loop (MODIFY to connect dispatcher)
- `backend/services/alegra/client.py` — AlegraClient + request_with_verify()
- `backend/core/permissions.py` — validate_write_permission()
- `backend/core/events.py` — EventPublisher.publish()
- `backend/core/database.py` — get_db() DI

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- AlegraClient.request_with_verify() — all write handlers use this
- EventPublisher.publish() — all write handlers call this after success
- validate_write_permission("contador", target) — all handlers call this first
- CONTADOR_TOOLS in tools.py — tool names define the dispatcher routing

### Established Patterns
- FastAPI Depends() for DI — handlers receive alegra, db, event_bus via ToolDispatcher constructor
- request_with_verify pattern: POST -> verify HTTP 200 -> GET confirm -> return alegra_id
- Event schema: event_id, event_type, source, correlation_id, timestamp, datos, alegra_id

### Integration Points
- chat.py process_chat() — needs modification to route tool_use blocks to ToolDispatcher
- ExecutionCard — write tools send preview to frontend, wait for confirmation
- roddos_events — handlers publish events that CFO will consume

</code_context>

<specifics>
## Specific Ideas

- Handler naming follows the master spec (SISMO_V2_Phase2_CONTEXT.md) — dispatcher maps tool_name to handler function
- Retenciones service signature: `calcular_retenciones(tipo: str, monto: float, nit: str | None) -> dict`
- Anti-dup for nomina: check by mes + empleado nombre before creating journal
- Factura venta item format: "[Modelo] [Color] - VIN: [x] / Motor: [x]" — exact format, not approximate
- CXC socios: Andres CC 80075452, Ivan CC 80086601 — always CXC, never gasto operativo

</specifics>

<deferred>
## Deferred Ideas

- Conciliación bancaria (5 handlers with BBVA/Bancolombia/Davivienda parsers) — Phase 3
- Backlog UI (page + badge + Causar modal) — later phase
- Nequi parser — format not documented
- Global66/Banco de Bogota parsers — format not documented

</deferred>

---

*Phase: 02-core-accounting-operations*
*Context gathered: 2026-04-09*
