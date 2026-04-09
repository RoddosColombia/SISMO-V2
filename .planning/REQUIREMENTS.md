# Requirements: SISMO V2

**Defined:** 2026-04-09
**Core Value:** Cada peso que entra o sale de RODDOS queda como un registro verificado en Alegra — el P&L refleja la realidad sin intervencion manual.

## SISMO V2 — Milestone 1 Requirements

Requirements for Fase 0 (cimientos) + Fase 1 (Agente Contador completo). Each maps to roadmap phases.

### Foundation

- [ ] **FOUND-01**: Router dispatches intent to correct agent with confidence >= 0.70; ambiguous prompts trigger single clarification question
- [ ] **FOUND-02**: Each agent (Contador, CFO, RADAR, Loanbook) has differentiated system prompt delivered as system message
- [ ] **FOUND-03**: WRITE_PERMISSIONS enforced in code — PermissionError raised if agent attempts write outside its permitted collections/endpoints
- [ ] **FOUND-04**: Anthropic Tool Use native with typed tool definitions; TOOL_USE_ENABLED feature flag for ACTION_MAP rollback
- [ ] **FOUND-05**: Event bus (roddos_events) publishes immutable event after every successful Alegra write
- [ ] **FOUND-06**: request_with_verify() is the only path for Alegra writes: POST -> verify HTTP 200/201 -> GET confirmation -> return Alegra ID

### Egresos

- [ ] **EGRE-01**: User describes expense in natural language -> motor matricial classifies -> agent proposes complete journal entry with retenciones before executing
- [ ] **EGRE-02**: Retenciones calculated automatically: Arrendamiento 3.5%, Servicios 4%, Honorarios PN 10%, Honorarios PJ 11%, Compras 2.5% (base >$1.344.573), ReteICA Bogota 0.414%
- [ ] **EGRE-03**: Partner expenses (Andres CC 80075452, Ivan CC 80086601) routed to CXC socios — never classified as gasto operativo
- [ ] **EGRE-04**: Auteco NIT 860024781 identified as autoretenedor — ReteFuente never applied

### Conciliacion Bancaria

- [ ] **CONC-01**: Upload .xlsx bank extract (Bancolombia, BBVA, Davivienda formats) -> parse by bank headers -> classify -> cause journals via BackgroundTasks with job_id
- [ ] **CONC-02**: Movements with confidence >= 0.70 auto-caused; confidence < 0.70 triggers WhatsApp notification, then routes to Backlog if unresolved
- [ ] **CONC-03**: Anti-duplicates enforced in 3 layers: hash MD5 per extract (Capa 1) + hash MD5 per movement (Capa 2) + GET Alegra post-POST (Capa 3)
- [ ] **CONC-04**: Individual movement classified via chat: user describes movement -> agent classifies -> proposes journal -> user confirms -> POST /journals with verification

### Nomina

- [ ] **NOMI-01**: Monthly payroll registered as individual journals per employee (Sueldos 5462 + Seguridad Social 5471) with anti-duplicate check per month+employee

### CXC Socios

- [ ] **CXC-01**: Partner withdrawals registered as CXC journal (balance sheet), never as expense (P&L distortion prevention)
- [ ] **CXC-02**: Real-time CXC balance query per partner returns exact pending amount

### Facturacion

- [ ] **FACT-01**: Invoice created in Alegra (POST /invoices) with item format "[Modelo] [Color] - VIN: [x] / Motor: [x]" — VIN and motor mandatory
- [ ] **FACT-02**: Successful invoice triggers cascade: inventario_motos -> "vendida", loanbook created "pendiente_entrega", event "factura.venta.creada" published, WhatsApp Template 5 sent
- [ ] **FACT-03**: Invoice blocked if VIN missing, motor missing, or moto status != "disponible"

### Ingresos

- [ ] **INGR-01**: Loan payment requires dual operation: POST /payments (against invoice) + POST /journals (income journal) — both verified with request_with_verify(), cuota marked paid only after both succeed
- [ ] **INGR-02**: Non-operational income (recovered motos, bank interest, other) registered as journal with correct account from plan_ingresos_roddos

### Backlog Operativo

- [ ] **BACK-01**: Unresolved movements (confidence < 0.70 unresolved, Alegra errors, unclassifiable) inserted into backlog_movimientos with fecha, banco, descripcion, monto, razon_pendiente, intentos
- [ ] **BACK-02**: Backlog page with visible badge count in sidebar, filterable by banco/fecha/razon, sortable by antiguedad
- [ ] **BACK-03**: Manual "Causar" from Backlog: select cuenta + optional retenciones -> POST /journals -> request_with_verify() -> on success: movement exits Backlog; on failure: returns with updated error

### P&L Automatico

- [ ] **PL-01**: CFO constructs P&L by reading directly from Alegra (GET /journals + /invoices + /payments + /categories) — never from MongoDB
- [ ] **PL-02**: P&L separates devengado (Seccion A) from caja real (Seccion B); CXC socios excluded from P&L (balance sheet only); IVA cuatrimestral

## Milestone 2+ Requirements

Deferred to future milestones. Tracked but not in current roadmap.

### RADAR Agent

- **RADAR-01**: Automated collection queue with priority scoring and daily generation
- **RADAR-02**: WhatsApp reminders via Mercately (Templates T1, T4)
- **RADAR-03**: Collection management history in gestiones_cobranza

### Loanbook Agent

- **LOAN-01**: Loanbook lifecycle: creation -> delivery -> active -> completed/defaulted
- **LOAN-02**: Cuota schedule generation from catalogo_planes (P39S, P52S, P78S)
- **LOAN-03**: DPD calculation and scoring (A+ to E)

### Integrations

- **INTG-01**: Alegra webhooks (12 events) replacing polling as primary sync
- **BANK-01**: Global66 and Banco de Bogota bank extract parsers

### Advanced Analytics

- **ADV-01**: Multi-period P&L trending and budget variance analysis
- **ADV-02**: Cash flow projection
- **ADV-03**: Risk concentration analysis

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Multi-tenancy | SISMO is exclusive to RODDOS S.A.S. |
| Mobile native app | Web-first, responsive later |
| Alternative ERPs | Alegra is canonical (ROG-4 immutable) |
| V1 data migration | Clean start — no legacy bug inheritance |
| AI forecasting/predictive | Need 12+ months of clean V2 data first |
| Self-service user signup | Internal tool, admin-provisioned users only |
| Global66/Banco de Bogota parsers | Format not documented yet |
| Interest extraction per cuota | Blocked on reliable Loanbook state — Phase 2+ |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FOUND-01 | TBD | Pending |
| FOUND-02 | TBD | Pending |
| FOUND-03 | TBD | Pending |
| FOUND-04 | TBD | Pending |
| FOUND-05 | TBD | Pending |
| FOUND-06 | TBD | Pending |
| EGRE-01 | TBD | Pending |
| EGRE-02 | TBD | Pending |
| EGRE-03 | TBD | Pending |
| EGRE-04 | TBD | Pending |
| CONC-01 | TBD | Pending |
| CONC-02 | TBD | Pending |
| CONC-03 | TBD | Pending |
| CONC-04 | TBD | Pending |
| NOMI-01 | TBD | Pending |
| CXC-01 | TBD | Pending |
| CXC-02 | TBD | Pending |
| FACT-01 | TBD | Pending |
| FACT-02 | TBD | Pending |
| FACT-03 | TBD | Pending |
| INGR-01 | TBD | Pending |
| INGR-02 | TBD | Pending |
| BACK-01 | TBD | Pending |
| BACK-02 | TBD | Pending |
| BACK-03 | TBD | Pending |
| PL-01 | TBD | Pending |
| PL-02 | TBD | Pending |

**Coverage:**
- Milestone 1 requirements: 27 total
- Mapped to phases: 0
- Unmapped: 27 (pending roadmap creation)

---
*Requirements defined: 2026-04-09*
*Last updated: 2026-04-09 after initial definition*
