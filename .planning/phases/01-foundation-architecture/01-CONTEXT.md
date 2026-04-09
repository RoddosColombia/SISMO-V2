# Phase 1: Foundation & Architecture - Context

**Gathered:** 2026-04-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the secure, verifiable infrastructure that all agents depend on: intent router with confidence threshold, differentiated system prompts, code-enforced write permissions, Anthropic Tool Use native, append-only event bus, and request_with_verify() pattern for all Alegra writes. No user-facing features — pure backend infrastructure.

</domain>

<decisions>
## Implementation Decisions

### Router Strategy
- **D-01:** Keyword + rules first for confidence scoring. Deterministic rules map known patterns (gasto/factura -> Contador, P&L/semaforo -> CFO, cobranza/mora -> RADAR, loanbook/entrega -> Loanbook). LLM classifier only as fallback for ambiguous messages. Confidence threshold remains 0.70.
- **D-02:** Multi-intent messages trigger clarification. Router asks user to focus: "Puedo hacer una cosa a la vez — registrar el gasto primero?" Never auto-dispatches to two agents.
- **D-03:** Sticky session with override. Once dispatched to an agent, conversation stays with that agent. If router detects high-confidence intent for a different agent, asks user: "Esto parece un tema de [otro agente]. Quieres cambiar?"

### Tool Use Scope
- **D-04:** All 32 tools from V1's tool_executor.py are registered in Phase 0. Read definitions (names, parameters, descriptions) from `C:\Users\AndresSanJuan\roddos-workspace\SISMO\backend\tool_executor.py` in the V1 repo. Framework is built from scratch but tool definitions are extracted from V1.
- **D-05:** Only the Contador agent gets tools in Phase 0. CFO, RADAR, and Loanbook agents receive system prompts and identity only — their tools are added when their capabilities are implemented in later milestones.
- **D-06:** Write tool confirmation uses ExecutionCard UI — a React component with preview of the proposed journal (debits/credits/retenciones) + Confirm/Cancel buttons. More robust than text-based confirmation from V1.

### Project Structure
- **D-07:** Backend organized by feature/domain: `backend/agents/contador/`, `backend/agents/cfo/`, `backend/services/alegra/`, `backend/services/events/`, `backend/core/` (router, permissions, database). Each domain is a Python package.
- **D-08:** Dependency injection via FastAPI Depends(). MongoDB client, Alegra client, and EventPublisher injected into routers/services. More testeable than V1's global singletons.
- **D-09:** Monorepo: `SISMO-V2/backend/` + `SISMO-V2/frontend/` in the same repo. Deployed separately (Render for backend, Vercel for frontend).

### Test Strategy
- **D-10:** Alegra API tested with both mocks and sandbox. httpx mocks for unit tests (fast, deterministic). Real Alegra sandbox account for specific integration tests.
- **D-11:** Testing framework: pytest + httpx AsyncClient for FastAPI async testing.
- **D-12:** 22 smoke tests are semi-automated. Infrastructure tests (permissions, router, events, request_with_verify) are automated pytest. Full-flow tests (factura -> inventario -> loanbook, P&L construction) are manual verification checklists.

### Claude's Discretion
- Exact directory hierarchy within backend/ (beyond the domain-based pattern)
- Error handling patterns and retry logic implementation details
- Event schema validation approach (Pydantic model vs dict)
- Specific httpx mock patterns for Alegra responses

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### SISMO V2 Specifications
- `.planning/SISMO_V2_CLAUDE.md` — Master context: ROG rules, Alegra quirks, retention rates, account IDs, architecture constraints
- `.planning/SISMO_V2_Fase0_Fase1.md` — Phase 0 specification: 6 cimientos with acceptance criteria
- `.planning/SISMO_V2_Plan_Ejecucion.md` — Execution tasks F0-T1 through F0-T6 with concrete actions
- `.planning/SISMO_V2_System_Prompts.md` — System prompts for all 4 agents + WRITE_PERMISSIONS matrix
- `.planning/SISMO_V2_Registro_Canonico.md` — Canonical registry: all endpoints, collections, IDs, env vars

### V1 Source (read-only reference for tool definitions)
- `C:\Users\AndresSanJuan\roddos-workspace\SISMO\backend\tool_executor.py` — 32 tool definitions to extract for Anthropic Tool Use migration

### Research
- `.planning/research/ARCHITECTURE.md` — System component boundaries and data flow
- `.planning/research/PITFALLS.md` — Critical pitfalls from V1 with prevention strategies
- `.planning/research/STACK.md` — Technology recommendations and versions

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- No existing code in SISMO-V2 (greenfield). V1 tool definitions in `tool_executor.py` are the primary reusable reference.

### Established Patterns
- None yet — Phase 0 establishes the patterns all subsequent phases will follow.

### Integration Points
- Alegra API (https://api.alegra.com/api/v1/) — all write operations go through request_with_verify()
- MongoDB Atlas — async Motor driver, all collections documented in Registro Canonico
- Anthropic SDK — Tool Use API for agent tool invocation
- Frontend — SSE streaming for chat responses, ExecutionCard component for write confirmations

</code_context>

<specifics>
## Specific Ideas

- Tool definitions extracted from V1's tool_executor.py — NOT reimagined. Names, parameters, and descriptions stay consistent with V1 for continuity.
- ExecutionCard from V1 concept: React component that renders journal preview (debits, credits, retenciones) with Confirm/Cancel buttons. Agent sends tool_use response, frontend renders ExecutionCard, user clicks Confirm, frontend sends POST /api/chat/approve-plan.
- Router keywords should cover Spanish natural language patterns used by Andres, Ivan, and Liz (the three primary users).

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 01-foundation-architecture*
*Context gathered: 2026-04-09*
