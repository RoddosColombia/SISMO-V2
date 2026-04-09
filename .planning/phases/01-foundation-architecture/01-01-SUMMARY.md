---
phase: 01-foundation-architecture
plan: 01
subsystem: backend-foundation
tags: [fastapi, motor, permissions, router, event-bus, tdd]
dependency_graph:
  requires: []
  provides: [database-di, intent-router, write-permissions, event-publisher, agent-prompts]
  affects: [all subsequent plans in phase 01 and later phases]
tech_stack:
  added:
    - fastapi==0.115.0
    - uvicorn==0.30.0
    - pydantic==2.7.1
    - motor==3.7.0 (AsyncIOMotorClient)
    - anthropic>=0.38.0
    - httpx==0.27.0
    - python-dotenv==1.0.1
  patterns:
    - FastAPI lifespan context manager for DB connection lifecycle
    - AsyncIOMotorClient with get_db() Depends() for DI
    - Keyword scoring router with 0.70 confidence threshold
    - WRITE_PERMISSIONS allowlist enforced with PermissionError before writes
    - append-only roddos_events via insert_one (never update/delete)
    - TDD: RED (failing tests committed) -> GREEN (implementations committed)
key_files:
  created:
    - backend/pyproject.toml (pinned dependencies for entire backend)
    - backend/.env.example (11 env vars: MONGO_URL, DB_NAME, ALEGRA_EMAIL, ALEGRA_TOKEN, ANTHROPIC_API_KEY, TOOL_USE_ENABLED, JWT_SECRET, MERCATELY_API_KEY, DIAN_MODO, N8N_API_KEY, GLOBAL66_WEBHOOK_SECRET)
    - backend/main.py (FastAPI app with lifespan, CORS, /health endpoint)
    - backend/core/__init__.py
    - backend/core/database.py (AsyncIOMotorClient, get_db, init_db, close_db, lifespan)
    - backend/core/router.py (route_intent, route_with_sticky, IntentResult, CONFIDENCE_THRESHOLD=0.70, KEYWORDS)
    - backend/core/permissions.py (WRITE_PERMISSIONS dict, validate_write_permission)
    - backend/core/events.py (publish_event async function — append-only)
    - backend/agents/__init__.py
    - backend/agents/prompts.py (SYSTEM_PROMPTS dict with 4 verbatim agent prompts)
    - backend/agents/contador/__init__.py
    - backend/agents/cfo/__init__.py
    - backend/agents/radar/__init__.py
    - backend/agents/loanbook/__init__.py
    - backend/services/__init__.py
    - backend/services/alegra/__init__.py
    - backend/tests/__init__.py
    - backend/tests/conftest.py (pytest-asyncio AsyncClient fixture)
    - backend/tests/test_permissions.py (7 tests)
    - backend/tests/test_events.py (2 tests)
  modified: []
decisions:
  - "Keyword scoring confidence formula: top>=2 AND top>=2x second => 0.90; top>second => 0.50+delta; tied => 0.40 (per plan D-01)"
  - "Sticky session: route_with_sticky() boosts ambiguous messages to 0.75 when current_agent is set (per D-03)"
  - "TDD for permissions and events: RED committed separately from GREEN to preserve audit trail"
  - "pyproject.toml includes asyncio_mode=auto to simplify pytest-asyncio setup"
metrics:
  duration: ~25 minutes
  completed: 2026-04-09
  tasks_completed: 3
  files_created: 20
  tests_passing: 9
---

# Phase 1 Plan 01: Backend Foundation — Project Scaffold, Router, Permissions, EventBus Summary

**One-liner:** FastAPI backend scaffold with Motor async DI, keyword router (0.70 threshold), code-enforced WRITE_PERMISSIONS allowlist, and append-only roddos_events EventPublisher — 9/9 tests passing.

## What Was Built

### Task 1: Project scaffold, database DI, and domain structure (commit 5224e0c)

Created the monorepo backend structure with all domain directories:

- `backend/pyproject.toml` — pinned versions (fastapi==0.115.0, motor==3.7.0, anthropic>=0.38.0)
- `backend/.env.example` — all 11 env vars documented
- `backend/core/database.py` — `AsyncIOMotorClient` with lifespan context manager; `get_db()` raises RuntimeError if uninitialized (fail-fast pattern)
- `backend/main.py` — FastAPI app with CORS middleware and `/health` endpoint
- Domain packages: `agents/{contador,cfo,radar,loanbook}`, `services/alegra`, `core`, `tests`

### Task 2: Intent router and system prompts (commit a451784)

- `backend/core/router.py` — `CONFIDENCE_THRESHOLD = 0.70`; `route_intent()` scores keywords and returns `IntentResult(agent, confidence, clarification)`; `route_with_sticky()` implements D-03 sticky session
- `backend/agents/prompts.py` — `SYSTEM_PROMPTS` dict with verbatim texts for all 4 agents from `.planning/SISMO_V2_System_Prompts.md`

Router keyword coverage:
- contador: 20 keywords (gasto, factura, journal, asiento, arriendo, retención, iva, nómina, extracto, ...)
- cfo: 17 keywords (p&l, estado de resultados, semáforo, flujo de caja, utilidad, balance, ...)
- radar: 10 keywords (cobranza, mora, cuota vencida, deudor, pago pendiente, ...)
- loanbook: 10 keywords (loanbook, crédito, entrega de moto, cronograma, lb-, ...)

### Task 3: WRITE_PERMISSIONS enforcer and EventPublisher — TDD (commits 1a64332, 37c7a71)

**RED phase (1a64332):** 9 tests written and committed before implementation — confirmed they fail with ModuleNotFoundError.

**GREEN phase (37c7a71):**
- `backend/core/permissions.py` — `WRITE_PERMISSIONS` allowlist + `validate_write_permission()` that raises `PermissionError` for unknown agents (T-01-05) or unauthorized targets
- `backend/core/events.py` — `publish_event()` uses `insert_one()` exclusively; immutable append-only pattern (T-01-02)

## Test Results

```
9 passed in 0.05s
  test_permissions.py: 7 PASSED
  test_events.py: 2 PASSED
```

## Threat Mitigations Applied

| Threat | Mitigation |
|--------|-----------|
| T-01-01 Spoofing | agent_type derived from routing logic, never from raw user input |
| T-01-02 Tampering | events.py uses insert_one only — no update/replace/delete |
| T-01-04 Info Disclosure | .env.example has placeholder values only |
| T-01-05 Privilege Escalation | Unknown agent_type raises PermissionError — allowlist-only model |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all modules are functional implementations (no placeholder returns or hardcoded empty values).

## Threat Flags

None — no new network endpoints, auth paths, or file access patterns beyond the plan's threat model.

## Self-Check

### Files exist:
- backend/pyproject.toml: FOUND
- backend/core/database.py: FOUND
- backend/core/router.py: FOUND
- backend/core/permissions.py: FOUND
- backend/core/events.py: FOUND
- backend/agents/prompts.py: FOUND
- backend/main.py: FOUND
- backend/tests/test_permissions.py: FOUND
- backend/tests/test_events.py: FOUND

### Commits exist:
- 5224e0c: feat(01-01): project scaffold — FOUND
- a451784: feat(01-01): intent router — FOUND
- 1a64332: test(01-01): RED phase tests — FOUND
- 37c7a71: feat(01-01): GREEN phase implementation — FOUND

## Self-Check: PASSED
