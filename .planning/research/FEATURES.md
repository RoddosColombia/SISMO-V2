# Feature Landscape: AI-Powered Accounting Automation for Motorcycle Dealership with In-House Financing

**Domain:** Automated journal entry and invoice generation for SMB with proprietary financing
**Context:** RODDOS S.A.S. — TVS dealership, ~$2-3M annual, financing plans P39S/P52S/P78S weekly
**Researched:** 2026-04-09
**Confidence:** MEDIUM (based on SISMO V1 validation + accounting automation SOTA + domain-specific constraints)

---

## Table Stakes Features

Features users expect. Missing = product feels incomplete or creates accounting liability.

| Feature | Why Expected | Complexity | Notes | Alegra Dependency |
|---------|--------------|------------|-------|------------------|
| **Expense Entry & Classification** | Cash leaves account; must be recorded. Core accountability. | Medium | Automated category suggestion, manual override, receipt attachment optional | POST /categories + POST /journals |
| **Invoice Generation with VIN Tracking** | Sale requires invoice (legal/tax). Finance product differentiator (VIN = asset tracking). | High | Auto-sequence, PDF generation, customer email, dual operation (invoice + journal) | POST /invoices + POST /journals |
| **Bank Reconciliation from Statements** | Validates cash position, prevents fraud, resolves discrepancies. Non-negotiable for lenders. | Medium | XLSX parser, deduplication, manual exception handling, bank code mapping | POST /journals (for exceptions) |
| **Payroll Journal Entry** | Employees must be paid; income recognition required. Reputational + legal risk if missed. | Medium | Employee list, gross calculation, retention deductions, monthly automation | POST /journals + /categories |
| **Accounts Receivable Tracking** | Financing is the business model. No tracking = no collection. | High | Loan payment registration (dual operation), aging, delinquency flags, partner tracking | POST /journals (payments) + /invoices (financing invoices) |
| **Payment Registration (Dual Operation)** | Each cuota payment = debt reduction (DR A/R) + income recognition (CR revenue). Single operation must create both journal entries. | High | Prevents orphaned transactions, reconciles to invoice, calculates interest component | POST /journals (2 entries atomic) |
| **P&L Construction from Alegra** | CFO cannot operate blind. Must know monthly profitability. | Medium | Aggregate from posted journals, category rollup, multi-period comparison, variance analysis | GET /journals + /categories (read-only aggregation) |
| **Backlog (Unprocessed Transaction Registry)** | Safety net for anything not yet posted to Alegra. SISMO V1 had 298 pending (BBVA 33, Bancolombia 188, Nequi 76). | Low | Visual queue, owner assignment, status (pending/disputed/resolved), audit trail | MongoDB collection, no Alegra write yet |
| **Non-Operational Income Recording** | Repossessed motos resold, bank interest, miscellaneous revenue. Critical for P&L accuracy. | Low | Category routing, manual verification, journal posting | POST /journals + /categories |
| **System of Record Integrity (Alegra Canonic)** | ROG-4: Every peso must be in Alegra. MongoDB is temp storage only. | Medium | Event sourcing (append-only roddos_events), idempotency tokens, audit trails | All Alegra writes must be audited |

---

## Differentiating Features

Features that set product apart. Not expected universally, but highly valued in fintech/dealership context.

| Feature | Value Proposition | Complexity | Implementation Notes | Competitive Advantage |
|---------|-------------------|------------|----------------------|-----------------------|
| **AI-Powered Expense Categorization** | Reduces manual classification time from 5m to 30s per transaction. Learns from corrections. | Medium-High | Claude API analyzes vendor + amount + description → category suggestion + retention calculation. Feature flag for rollback. | Cashflow speed — decisions made faster |
| **Automatic Retention Calculation (2026 Colombia Rules)** | Removes 80% of retention mistakes. Auto-routes to liability account. | Medium | Lookup table: arrendamiento 3.5%, servicios 4%, honorarios PN 10%, PJ 11%, compras 2.5% (base >$1.344.573), ReteICA Bogotá 0.414%, Auteco carve-out | Compliance + tax savings |
| **Dual-Operation Atomicity (Payment → A/R + Income)** | One click posts payment correctly. Prevents split-brain state where payment is recorded but income isn't. | High | Transactional journal posting; if either journal fails, rollback both. Idempotency token prevents duplicates. | Trust in data — no manual reconciliation loops |
| **Backlog Module with Visual Queue** | Unprocessed transactions visible at a glance. Liz (operations) can see bottleneck. | Low | React component showing pending count by source (BBVA, Bancolombia, Nequi), owner assignment, dispute reason | Operational transparency |
| **Partner-Specific CXC Routing** | Andrés (CC 80075452) and Iván (CC 80086601) receivables NEVER enter gasto operativo. Automatic partner detection. | Low | Hardcoded list of partner accounts, routing rule (if counterparty in partners → CXC socios, not gasto) | Prevents P&L distortion from partner advances |
| **Bank Statement Deduplication (3-Layer)** | SISMO V1 had duplicate transaction bugs. 3-layer check: (1) Alegra journal exists, (2) MongoDB backlog has it, (3) Bank stmt hash match. | Medium | Hash on (date, amount, description), query Alegra /journals, query MongoDB backlog, decision tree | Prevents ghost transactions + reconciliation failures |
| **Batch Bank Import (XLSX) with Exception Handling** | Upload entire month at once; system flags ambiguities for human decision. | Medium | Parser for XLSX (bank-specific format), flagging logic for: unmapped banks, negative amounts, duplicates, amounts >threshold | Accounting team efficiency |
| **Interest Component Extraction (Finance)** | Separates principal from interest on each cuota payment. Interest = taxable income. | Medium-High | Payment amount - (principal remaining × factor) = interest. Requires loan book state. | Financial accuracy + tax deduction legitimacy |
| **Multi-Period P&L with Trend** | Not just this month — see YTD, compare to budget, trend analysis. | Low-Medium | Aggregate by category, compare periods, calculate growth %, highlight variance | CFO planning capability |
| **Confidence Score on AI Suggestions** | Claude returns confidence 0.0-1.0 on each categorization. Threshold 0.70 routes to human review. | Low | Router rejects confidence < 0.70, sends to backlog for manual entry | Risk management — catches edge cases |

---

## Anti-Features

Things to explicitly NOT build. Scope killer or creates false sense of completeness.

| Anti-Feature | Why Avoid | What to Do Instead | Consequence of Building | Priority |
|--------------|-----------|-------------------|------------------------|----|
| **Multi-ERP Support** | Alegra is THE source of truth (ROG-4). Supporting Siigo, Contableduria.io, or Zoho creates sync nightmares. | Commit to Alegra. If client needs different ERP, build separate integration layer (future work). | Doubles complexity, adds versioning nightmares, data conflicts between systems | DO NOT BUILD IN V2 |
| **Global66 / Banco de Bogotá Parsers** | No documented format for either. Reverse-engineering is fragile. Maintenance burden grows. | Manual backlog entry for now. When format is documented, implement parser as Phase 2 extension. | Wasted time on fragile parsers, support burden. Better to wait for documentation. | DEFER INDEFINITELY |
| **Mobile App (Native)** | Web + mobile responsive = 80% of utility with 20% of complexity. Native = versioning, push notifications, offline sync = massive scope. | Build responsive web. PWA if time allows. Revisit native only if web can't deliver UX. | Doubles team, slows iterations, maintenance nightmare for 3-person team | WEB-FIRST ONLY |
| **Predictive Analytics / Forecasting** | Tempting but requires 12+ months of clean historical data. RODDOS has no clean history (V1 data is suspect). | Post-V2: Once 6-12 months of V2 data accrues, add forecasting as Phase 3. | False confidence in predictions, CFO makes bad decisions, credibility erosion | PHASE 3+ ONLY |
| **Automated Loan Origination** | Lending decisions have legal/compliance surface area. Automating = liability. | Keep loan entry manual (approval by human). Automate only payment registration. | Regulatory exposure, customer disputes, hidden liability | NEVER BUILD |
| **Expense Approval Workflow (Multi-Level)** | Adds complexity: who approves? When? At what amount? For a 3-person company, this is premature. | Single-step: AI categorization + manual override. If escalation needed, async comment field. | Workflow states explode, decision logic becomes tangled, slows operations | PHASE 2+ (IF NEEDED) |
| **Historical Data Migration from V1** | V1 data is suspect (duplicates, orphaned transactions, inconsistent retention calculations). Bulk migration = bulk corruption. | Clean break. V2 starts 2026-01-01 fresh. V1 data archived for reference only (read-only). | Inherits V1 bugs, audit failures, reconciliation nightmares. Trust erosion. | DO NOT DO |
| **Customer Portal / Self-Service Invoice** | Adds frontend complexity. RODDOS doesn't have public-facing invoicing. Internal use only. | Admin-only interface. If customers need invoices later, email PDF from admin. | Feature bloat, UX complexity, customer privacy exposure | DO NOT BUILD |
| **Bulk Expense Categorization Override** | Tempting for "fix all at once" but creates audit blind spots. Can't undo systematically. | Override one at a time. Each override updates AI model (implicit feedback). | Can't trace why batch was changed. Cascading errors. | NEVER BUILD |
| **Real-Time Webhooks to Customer Systems** | RODDOS has no downstream systems. Interesting but not required. | HTTP APIs are sufficient. Webhooks = delivery guarantees, retry logic, dead-letter queues. | Operational complexity, support burden, undocumented failure modes | PHASE 3+ IF NEEDED |

---

## Feature Dependencies

```
Core Platform (Must Build First):
├─ System of Record Integrity (ROG-4: Alegra canonical)
│  └─ Event sourcing (roddos_events append-only)
│     └─ Audit trail on all writes
│
└─ Router + Agent Prompt System
   └─ Confidence scoring (threshold 0.70)
      └─ Routes to backlog if < 0.70

Expense Flow:
Expense Entry → AI Classification (confidence check) → Journal Posting (verify) → P&L aggregate

Invoice + Payment Flow:
Invoice Creation → VIN Registration → Payment Entry → Dual Journal Op (A/R debit + income credit) → P&L rollup

Bank Reconciliation Flow:
Bank Statement (XLSX) → Deduplication (3-layer) → Exception handling → Manual backlog entry OR auto-post if match

Payroll:
Employee list (static) → Monthly trigger → Journal auto-post (gross, deductions, net) → P&L includes labor cost

Non-Operational Income:
Manual entry → Category routing → Journal post → P&L separates from operations

P&L:
All journals (expenses, invoices, payments, payroll, non-op) → Alegra /journals aggregate → Category rollup → P&L report

Backlog Module:
Unmatched transactions → Visual queue → Owner assignment → Dispute resolution → Move to journal or discard
```

**Critical Ordering:**
1. **System integrity first** (ROG-4, event log, audit)
2. **Expense & Journal posting** (foundation for all accounting)
3. **Invoice + payment** (revenue + A/R tracking)
4. **Bank reconciliation** (cash validation)
5. **Payroll** (employee obligation)
6. **P&L** (aggregate from all above)
7. **Backlog** (safety net + transparency)
8. **AI confidence scoring** (feature flag gates all AI decisions)

---

## Complexity Matrix

| Feature | Complexity | Build Time | Risk Level | MVP Priority | Notes |
|---------|-----------|-----------|----------|--------------|-------|
| Expense Entry & Classification | Medium | 1 week | Low | Phase 1 | Core daily operation |
| Invoice Generation | High | 2 weeks | Medium | Phase 1 | VIN tracking adds complexity |
| Bank Reconciliation (XLSX) | Medium | 1.5 weeks | Medium | Phase 1 | Parser fragility; manual fallback |
| Payroll Journal Entry | Medium | 1 week | Low | Phase 1 | Straightforward template |
| Accounts Receivable Tracking | High | 2 weeks | High | Phase 1 | Dual operations must be atomic |
| Payment Registration (Dual Op) | High | 1.5 weeks | High | Phase 1 | Blocking issue from SISMO V1 |
| P&L Construction | Medium | 1 week | Low | Phase 1 | Read-only aggregation from Alegra |
| Backlog Module | Low | 3 days | Low | Phase 1 | UI + MongoDB collection |
| Non-Operational Income | Low | 3 days | Low | Phase 1 | Special case handling |
| AI Expense Categorization | Medium-High | 2 weeks | Medium | Phase 1 (flagged) | Feature flag for rollback |
| Retention Calculation Auto | Medium | 1 week | Low | Phase 1 | Lookup table + rule engine |
| Deduplication (3-Layer) | Medium | 1 week | Medium | Phase 1 | Query performance + logic |
| Interest Extraction | Medium-High | 1.5 weeks | High | Phase 1 (defer if time-critical) | Loan book dependency |
| Partner CXC Routing | Low | 2 days | Low | Phase 1 | Hardcoded list, simple rule |
| Batch Import (XLSX) | Medium | 1 week | Medium | Phase 1 | Exception handling UX |
| Confidence Scoring | Low | 3 days | Low | Phase 1 | Wrapper around Claude |
| Multi-Period P&L | Low-Medium | 5 days | Low | Phase 1 (v2) | Optional for v1 |

---

## MVP Feature Set (Recommended for Phase 1)

**Build these first to establish accounting baseline:**

1. **Expense Entry with Manual Classification** (no AI initially, but prepare for it)
2. **Invoice Generation** (VIN mandatory, Alegra /invoices POST)
3. **Payment Registration** (dual operation: A/R debit + income credit, atomic)
4. **Bank Reconciliation** (XLSX parser + backlog routing for exceptions)
5. **Payroll Journal Auto-Post** (monthly template)
6. **P&L Aggregation** (read-only from Alegra)
7. **Backlog Visual Queue** (MongoDB + React component)
8. **Non-Operational Income** (special case category)

**Feature-Flagged (gate behind confidence threshold or team consensus):**
- AI expense categorization (route to backlog if confidence < 0.70)
- Automatic retention calculation (manual override available)
- 3-layer deduplication (start with 1-layer, expand if needed)

**Defer to Phase 2:**
- Interest extraction (requires loan book stability)
- Multi-period P&L trending (build baseline first)
- Batch XLSX import optimization (manual per-transaction + backlog for now)
- Advanced exception handling (simple rules first)

---

## Success Metrics by Feature

| Feature | Success Criteria | Measurement |
|---------|-----------------|--------------|
| Expense Entry | 100% of daily expenses recorded same-day | Daily count in backlog (goal: 0 by EOD) |
| Invoice Generation | 100% include VIN, zero posting failures | Alegra /invoices GET count matches recorded count |
| Payroll | Monthly posting by 5th of month, zero errors | Manual spot-check payroll journals |
| A/R Tracking | Payment registration matches invoice balance | Alegra GET /invoices outstanding vs MongoDB loan_book match |
| Bank Reconciliation | 95% of statement transactions auto-matched | Backlog exception ratio < 5% |
| P&L Accuracy | Month-end P&L matches Alegra journal sum | Compare report aggregate to Alegra /journals sum |
| Backlog | Cleared weekly (goal: 0 by Friday EOD) | Backlog count trend |
| Zero duplicates | No transaction appears twice in Alegra | Monthly audit of roddos_events vs Alegra journals |

---

## Sources

- SISMO V2 PROJECT.md (internal spec)
- Accounting automation SOTA (feature validation from training data)
- Colombian accounting regulations 2026 (retention rules, IVA schedule)
- RODDOS domain knowledge (dealership + financing specific requirements)

**Confidence Notes:**
- HIGH: Features explicitly called out in PROJECT.md (expense entry, invoice, payment, P&L)
- MEDIUM: Features inferred from financing use case (A/R tracking, payment atomicity, interest extraction)
- MEDIUM: AI features (confidence scoring, categorization) — rely on Claude capability knowledge + SISMO V1 validation
- MEDIUM: Anti-features — based on typical scope creep patterns + SISMO V1 historical decisions
