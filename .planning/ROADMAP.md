# ROADMAP: SISMO V2 — AI Agent Orchestrator for Accounting Automation

**Project:** SISMO V2  
**Defined:** 2026-04-09  
**Granularity:** Coarse (4 phases, clear dependencies)  
**Mode:** Interactive  

---

## Phases

- [ ] **Phase 1: Foundation & Architecture** - Build secure core infrastructure with verified writes, event bus, and agent permissions
- [ ] **Phase 2: Core Accounting Operations** - Automate expense recognition, bank reconciliation, payroll, and partner CXC
- [ ] **Phase 3: Revenue & Invoicing** - Enable invoice generation and payment tracking with dual-operation income recording
- [ ] **Phase 4: Operations & Financial Reporting** - Implement backlog safety net and automated P&L construction

---

## Phase Details

### Phase 1: Foundation & Architecture

**Goal:** Establish secure, verifiable infrastructure where all writes to Alegra follow verified path, permissions are enforced, events are immutable, and system can reliably route user intents to correct agents.

**Depends on:** Nothing (first phase)

**Requirements mapped:** FOUND-01, FOUND-02, FOUND-03, FOUND-04, FOUND-05, FOUND-06

**Success Criteria** (what must be TRUE):
1. Router successfully dispatches user intent to correct agent (Contador, CFO, RADAR, Loanbook) with confidence >= 0.70; ambiguous intents trigger single clarification question
2. Each agent receives its differentiated system prompt as system message in Claude API calls
3. Agent attempting to write to unauthorized collection raises PermissionError before Alegra call (WRITE_PERMISSIONS enforced)
4. Tool Use native from Anthropic API functions with typed tool definitions; TOOL_USE_ENABLED feature flag allows rollback to ACTION_MAP
5. Every successful write to Alegra is followed by immutable event published to roddos_events collection
6. All Alegra writes follow request_with_verify() pattern: POST with verification HTTP 200/201, GET confirmation, return Alegra ID -- no blind writes

**Plans:** 3 plans

Plans:
- [ ] 01-01-PLAN.md -- Project scaffold, database DI, intent router, system prompts, WRITE_PERMISSIONS, event bus
- [ ] 01-02-PLAN.md -- Alegra client with request_with_verify(), 32 Contador tools, SSE chat endpoint with Tool Use loop
- [ ] 01-03-PLAN.md -- Infrastructure test suite covering all FOUND-01 through FOUND-06 requirements

---

### Phase 2: Core Accounting Operations

**Goal:** Enable users to describe expenses naturally, reconcile bank statements, manage payroll, and track partner withdrawals -- all automatically classified, verified, and recorded to Alegra with correct retenciones and anti-duplicate protection.

**Depends on:** Phase 1

**Requirements mapped:** EGRE-01, EGRE-02, EGRE-03, EGRE-04, CONC-01, CONC-02, CONC-03, CONC-04, NOMI-01, CXC-01, CXC-02

**Success Criteria** (what must be TRUE):
1. User describes expense in natural language, agent classifies via motor matricial, proposes complete journal entry with correct retenciones calculated (Arrendamiento 3.5%, Servicios 4%, Honorarios PN 10%, Honorarios PJ 11%, Compras 2.5%, ReteICA 0.414%), user confirms before execution
2. Partner expenses (Andres CC 80075452, Ivan CC 80086601) always routed to CXC socios account, never classified as operating expense
3. Auteco NIT 860024781 recognized as autoretenedor -- ReteFuente never applied
4. User uploads bank extract .xlsx (Bancolombia, BBVA, Davivienda formats), system parses by headers, classifies movements with >= 0.70 confidence auto-caused via BackgroundTask; < 0.70 routes to WhatsApp and then Backlog if unresolved
5. Anti-duplicates enforced in 3 layers: MD5 hash per extract (Capa 1), MD5 hash per movement (Capa 2), GET Alegra post-POST verification (Capa 3)
6. Individual movements classified via chat: user describes, agent proposes journal, user confirms, POST /journals executes with verification
7. Monthly payroll registered as individual journals per employee (Sueldos 5462 + Seguridad Social 5471) with anti-duplicate check per month+employee
8. Partner CXC balance query returns exact pending amount per partner in real-time

**Plans:** TBD

**UI hint:** yes

---

### Phase 3: Revenue & Invoicing

**Goal:** Enable invoice creation with mandatory motorcycle details (VIN, motor), automatic inventory and loanbook tracking, and properly recorded loan payment income through dual-operation pattern.

**Depends on:** Phase 1, Phase 2

**Requirements mapped:** FACT-01, FACT-02, FACT-03, INGR-01, INGR-02

**Success Criteria** (what must be TRUE):
1. Invoice created in Alegra (POST /invoices) with item format "[Modelo] [Color] - VIN: [x] / Motor: [x]" -- VIN and motor mandatory; invoice blocked if missing or status != "disponible"
2. Successful invoice triggers cascade: inventario_motos status -> "vendida", loanbook created as "pendiente_entrega", event "factura.venta.creada" published, WhatsApp Template 5 sent
3. Loan payment requires dual operation: POST /payments (against invoice) + POST /journals (income journal) -- both verified with request_with_verify(), cuota marked paid only after BOTH succeed
4. Non-operational income (recovered motos, bank interest) registered as journal with correct account from plan_ingresos_roddos

**Plans:** TBD

**UI hint:** yes

---

### Phase 4: Operations & Financial Reporting

**Goal:** Provide safety net for unresolved movements and automatic P&L construction that reflects reality of business without manual intervention.

**Depends on:** Phase 1, Phase 2, Phase 3

**Requirements mapped:** BACK-01, BACK-02, BACK-03, PL-01, PL-02

**Success Criteria** (what must be TRUE):
1. Unresolved movements (confidence < 0.70, Alegra errors, unclassifiable) inserted into backlog_movimientos with fecha, banco, descripcion, monto, razon_pendiente, intentos
2. Backlog page displays visible badge count in sidebar, filterable by banco/fecha/razon, sortable by antiguedad
3. Manual "Causar" from Backlog: select cuenta + optional retenciones -> POST /journals -> request_with_verify() -> on success: movement exits Backlog; on failure: returns with updated error reason
4. CFO constructs P&L by reading directly from Alegra (GET /journals + /invoices + /payments + /categories) -- never from MongoDB
5. P&L separates devengado (Seccion A) from caja real (Seccion B); CXC socios excluded from P&L (balance sheet only); IVA cuatrimestral

**Plans:** TBD

**UI hint:** yes

---

## Progress

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 1 | Foundation & Architecture | 6 | Planned (3 plans ready) |
| 2 | Core Accounting Operations | 11 | Not started |
| 3 | Revenue & Invoicing | 5 | Not started |
| 4 | Operations & Financial Reporting | 5 | Not started |

**Total:** 4 phases, 27 requirements mapped, 3 plans created (Phase 1)

---

## Dependencies

```
Phase 1 (Foundation) --+
                       +--> Phase 2 (Core Accounting)
                       |         |
                       |    Phase 3 (Revenue) --+
                       |                        +--> Phase 4 (Operations & Reporting)
                       +------------------------+
```

**Execution order:** 1 -> 2 -> 3 -> 4

Phase 1 must complete before any other phase starts. Phase 2 can start once Phase 1 completes. Phase 3 depends on Phase 1 + 2. Phase 4 depends on all three prior phases (requires foundation, accounting ops, and revenue ops to be complete).

---

## Coverage Validation

**Requirement mapping:**

| Requirement | Category | Phase | Notes |
|-------------|----------|-------|-------|
| FOUND-01 | Foundation | 1 | Router with 0.70 confidence threshold |
| FOUND-02 | Foundation | 1 | Agent system prompts |
| FOUND-03 | Foundation | 1 | WRITE_PERMISSIONS enforcement |
| FOUND-04 | Foundation | 1 | Tool Use native + feature flag |
| FOUND-05 | Foundation | 1 | Event bus (roddos_events) |
| FOUND-06 | Foundation | 1 | request_with_verify() pattern |
| EGRE-01 | Egresos | 2 | Natural language expense -> classification -> journal |
| EGRE-02 | Egresos | 2 | Automatic retenciones calculation |
| EGRE-03 | Egresos | 2 | Partner expenses -> CXC socios |
| EGRE-04 | Egresos | 2 | Auteco autoretenedor handling |
| CONC-01 | Conciliacion Bancaria | 2 | Bank extract .xlsx upload and parsing |
| CONC-02 | Conciliacion Bancaria | 2 | Confidence-based auto-classification + Backlog |
| CONC-03 | Conciliacion Bancaria | 2 | 3-layer anti-duplicates |
| CONC-04 | Conciliacion Bancaria | 2 | Individual movement chat classification |
| NOMI-01 | Nomina | 2 | Monthly payroll journals per employee |
| CXC-01 | CXC Socios | 2 | Partner withdrawals as CXC (balance sheet) |
| CXC-02 | CXC Socios | 2 | Real-time CXC balance query |
| FACT-01 | Facturacion | 3 | Invoice creation with VIN + motor mandatory |
| FACT-02 | Facturacion | 3 | Invoice cascade (inventory, loanbook, event, WhatsApp) |
| FACT-03 | Facturacion | 3 | Invoice blocking rules |
| INGR-01 | Ingresos | 3 | Dual-operation loan payment (payment + journal) |
| INGR-02 | Ingresos | 3 | Non-operational income journals |
| BACK-01 | Backlog Operativo | 4 | Unresolved movement insertion to backlog |
| BACK-02 | Backlog Operativo | 4 | Backlog UI with filtering and sorting |
| BACK-03 | Backlog Operativo | 4 | Manual "Causar" from Backlog |
| PL-01 | P&L Automatico | 4 | CFO P&L read from Alegra (not MongoDB) |
| PL-02 | P&L Automatico | 4 | P&L sections (devengado/caja, CXC exclusion, IVA) |

**Total:** 27/27 requirements mapped
**Coverage:** 100%
**Orphaned:** 0

---

*Roadmap created: 2026-04-09*
*Phase 1 plans created: 2026-04-09*
