---
phase: 02-core-accounting-operations
plan: "02"
subsystem: consultas
tags: [consultas, wave2, read-only, alegra-get, categories, journals, balance]
dependency_graph:
  requires: [02-01-PLAN.md (ToolDispatcher with Wave 2 lazy import)]
  provides: [consultas.py with 8 read-only handlers]
  affects: [backend/agents/contador/handlers/dispatcher.py (auto-registers via try/except)]
tech_stack:
  added: []
  patterns: [alegra.get()-for-reads, {success,data,count}-return-shape, try-except-error-envelope]
key_files:
  created:
    - backend/agents/contador/handlers/consultas.py
    - backend/tests/test_phase2_wave2.py
  modified: []
decisions:
  - "Used alegra.get() not request_with_verify() for all GETs — AlegraClient.request_with_verify() only handles POST/PUT/DELETE; get() is the correct read path per client.py L120"
  - "EventPublisher type hint replaced with Any — core.events only exports publish_event() function, not an EventPublisher class; handlers don't call publish_event (read-only, no side effects)"
  - "GET /categories enforced throughout — never /accounts (403 per CLAUDE.md ROG rule)"
metrics:
  duration_minutes: 12
  completed_date: "2026-04-09"
  tasks_completed: 1
  tasks_total: 1
  files_created: 2
  files_modified: 0
---

# Phase 02 Plan 02: 8 Consultas Read-Only Handlers Summary

**One-liner:** 8 GET-only Alegra handlers (categories/journals/balance/income-statement/payments/contacts/items) with zero MongoDB writes, enforcing /categories over /accounts throughout.

## What Was Built

### Task 1 — 8 consultas handlers + 9 tests (commit `1b44864`)

**`backend/agents/contador/handlers/consultas.py`:**
- `handle_consultar_plan_cuentas`: GET /categories (enforces ROG rule — never /accounts)
- `handle_consultar_journals`: GET /journals with optional date_from/date_to params, default limit=50
- `handle_consultar_balance`: GET /balance with start-date/end-date params
- `handle_consultar_estado_resultados`: GET /income-statement with optional date params
- `handle_consultar_pagos`: GET /payments with optional date filter params
- `handle_consultar_contactos`: GET /contacts with optional name filter
- `handle_consultar_items`: GET /items (no params)
- `handle_consultar_movimiento_cuenta`: GET /journals with required account_id param + optional dates

All handlers follow the uniform return shape:
- Success: `{"success": True, "data": ..., "count": N}`
- Error: `{"success": False, "error": "..."}`

Zero MongoDB writes in the entire file (verified by static test + grep).

**`backend/tests/test_phase2_wave2.py`:**
- 9 tests, all GREEN
- TDD red-green cycle confirmed (all 9 failed before consultas.py was created)
- Uses `AsyncMock` for all alegra.get() calls — no real Alegra calls
- Test 9 is a static analysis check: reads consultas.py source and asserts zero insert_one/update_one/insert_many/replace_one occurrences

**ToolDispatcher integration:** dispatcher.py (Wave 1) already had the try/except lazy import block for Wave 2 consultas. Creating consultas.py causes ToolDispatcher to auto-register all 8 handlers on next initialization — no changes to dispatcher.py needed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Used alegra.get() instead of request_with_verify() for GETs**
- **Found during:** Implementation start — reading client.py
- **Issue:** Plan's interface spec showed `alegra.request_with_verify("categories", "GET")`, but AlegraClient.request_with_verify() only handles POST/PUT/DELETE writes. Calling it with "GET" raises ValueError("Metodo no soportado: GET").
- **Fix:** All 8 handlers use `alegra.get(endpoint, params=...)` — the correct read method at client.py L120
- **Files modified:** backend/agents/contador/handlers/consultas.py
- **Commit:** 1b44864

**2. [Rule 3 - Blocking] Replaced EventPublisher type hint with Any**
- **Found during:** First pytest run — ImportError on `from core.events import EventPublisher`
- **Issue:** core.events only exports the `publish_event()` function; no EventPublisher class exists. The plan's interface spec used EventPublisher as a type hint but it was aspirational, not real.
- **Fix:** `from typing import Any` — all handler signatures use `event_bus: Any`. Read-only handlers never call publish_event() anyway (no side effects to publish).
- **Files modified:** backend/agents/contador/handlers/consultas.py
- **Commit:** 1b44864

## Test Results

```
tests/test_phase2_wave2.py — 9/9 PASSED
tests/ full suite       — 147/148 PASSED
```

The 1 pre-existing failure (`test_no_journal_entries_in_tool_definitions` in test_infrastructure.py) predates this plan. tools.py is immutable per CLAUDE.md; the test checks for "NUNCA usar /journal-entries" text in the crear_causacion description, which contains that exact warning string. This was documented in the Wave 1 SUMMARY and is out of scope here.

## Verification Checks (Post-Wave)

```
grep -rn "insert_one|insert_many|update_one|replace_one" backend/agents/contador/handlers/
→ 0 lines (CLEAN)

grep -rn "/accounts" backend/agents/contador/handlers/
→ 0 results (using /categories)

grep -rn "journal-entries" backend/agents/contador/handlers/
→ 0 results (CLEAN)
```

## Known Stubs

None — all 8 handlers are fully wired to real Alegra GET endpoints. The `event_bus` parameter is accepted but not used (read-only handlers have no events to publish), which is correct behavior.

## Threat Flags

No new network endpoints or auth paths introduced. All handlers are internal tool functions called only via ToolDispatcher (authenticated path). No new trust boundary surface beyond what was already established by Wave 1.

## Self-Check: PASSED

- consultas.py exists: FOUND
- test_phase2_wave2.py exists: FOUND
- Commit 1b44864 exists: FOUND
- 9/9 tests GREEN: CONFIRMED
- 0 forbidden MongoDB writes: CONFIRMED
- GET /categories (not /accounts): CONFIRMED
