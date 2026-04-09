---
phase: 02-core-accounting-operations
plan: "01"
subsystem: dispatcher
tags: [dispatcher, chat, wave1, routing, tool-use]
dependency_graph:
  requires: [phase-01]
  provides: [ToolDispatcher, execute_approved_action, is_read_only_tool, is_conciliation_tool]
  affects: [backend/agents/chat.py, backend/agents/contador/handlers/]
tech_stack:
  added: []
  patterns: [lazy-import-try-except, async-generator-sse, stub-handler-registry]
key_files:
  created:
    - backend/agents/contador/handlers/__init__.py
    - backend/agents/contador/handlers/dispatcher.py
    - backend/tests/test_phase2_wave1.py
  modified:
    - backend/agents/chat.py
decisions:
  - "Wave 1 stubs: 28 stub handlers in dispatcher.py register all tool names at init time so Test 4 passes before Waves 2-6 add real implementations"
  - "Async iterator helper _make_stream_mock(): proper async __aiter__ / __anext__ required for Python 3.14 mock compatibility"
  - "Pre-existing test failure test_no_journal_entries_in_tool_definitions (test_infrastructure.py) predates this plan — tools.py is immutable per CLAUDE.md"
metrics:
  duration_minutes: 45
  completed_date: "2026-04-09"
  tasks_completed: 2
  tasks_total: 2
  files_created: 3
  files_modified: 1
---

# Phase 02 Plan 01: ToolDispatcher + chat.py Integration Summary

**One-liner:** ToolDispatcher routing layer with 28 stub handlers, lazy wave imports, and chat.py wired for immediate read-tool execution vs. ExecutionCard write-tool confirmation.

## What Was Built

### Task 1 — ToolDispatcher with full handler registry (commit `3c0a778`)

**`backend/agents/contador/handlers/dispatcher.py`:**
- `ToolDispatcher` class: receives `AlegraClient`, `db`, `EventPublisher` at init
- `_build_handlers()`: lazy imports Waves 2-6 handler modules via `try/except ImportError` — Wave 1 works without any wave modules present
- `_DEFAULT_HANDLERS`: 28 Wave 1 stubs covering all tool names required by the plan
- `READ_ONLY_TOOLS` frozenset (14 tools): classifies tools that execute without ExecutionCard
- `CONCILIATION_TOOLS` frozenset (5 tools): returns Phase 3 stub immediately
- `dispatch()`: routes tool_name → handler, catches `PermissionError` and generic `Exception` into structured error dicts

**`backend/agents/contador/handlers/__init__.py`:**
- Re-exports `ToolDispatcher`, `is_read_only_tool`, `is_conciliation_tool`

### Task 2 — chat.py wired to ToolDispatcher (commit `cf851f7`)

**`backend/agents/chat.py` modifications:**
- Import `ToolDispatcher`, `is_read_only_tool`, `is_conciliation_tool` from handlers
- `process_chat()` signature gains `dispatcher: ToolDispatcher | None = None` parameter
- Read-only tools: if `is_read_only_tool(block.name) and dispatcher`, call `dispatcher.dispatch()` immediately and yield `{"type": "tool_result", ...}` SSE — no MongoDB write, no confirmation
- Conciliation tools: yield Phase 3 stub SSE immediately
- Write tools: existing ExecutionCard flow unchanged (D-06 preserved)
- New `execute_approved_action(session_id, db, dispatcher)`: loads pending_action from MongoDB session, dispatches via `dispatcher.dispatch()`, clears pending_action, returns result

## Test Results

| Suite | Tests | Result |
|-------|-------|--------|
| test_phase2_wave1.py (Wave 1) | 10/10 | ALL PASS |
| Phase 1 suite (pre-existing) | 128/129 | 1 pre-existing failure |

**Pre-existing failure:** `test_infrastructure.py::TestToolUseNative::test_no_journal_entries_in_tool_definitions` — the test checks `'journal-entries' not in desc` but `crear_causacion` mentions it in a "NUNCA usar" warning. `tools.py` is immutable per CLAUDE.md. This failure predates this plan (confirmed by stash verification).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Python 3.14 async iterator mock compatibility**
- **Found during:** Task 2 (Tests 7, 8, 10 failing)
- **Issue:** `fake_stream.__aiter__ = MagicMock(return_value=iter([]))` returns a sync list_iterator. Python 3.14 `async for` requires `__anext__`, not just `__aiter__`.
- **Fix:** Added `_make_stream_mock()` helper using a proper `AsyncIterEmpty` class with `__aiter__` and `async def __anext__` that raises `StopAsyncIteration`. Used in all 3 affected tests.
- **Files modified:** `backend/tests/test_phase2_wave1.py`
- **Commit:** `cf851f7`

## Security Verification (CLAUDE.md)

| Check | Command | Result |
|-------|---------|--------|
| No app.alegra.com/api/r1 | grep -rn "app.alegra.com/api/r1" handlers/ | 0 results PASS |
| No /journal-entries in handlers | grep -rn "journal-entries" handlers/ | 0 results PASS |
| No ID 5495 | grep -rn "5495" handlers/ | 0 results PASS |
| MongoDB write violations | grep -rn insert_one\|update_one handlers/ | 0 results PASS |

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. `execute_approved_action` reads from `agent_sessions` (already existed in Phase 1). The handler registry is built from code imports — LLM cannot inject arbitrary handlers (T-02-W1-01 mitigated). Session lookup uses server-side `pending_action` storage (T-02-W1-02 mitigated).

## Known Stubs

The following stubs are intentional Wave 1 placeholders — each raises `NotImplementedError` with the wave that will implement them:

| Stub | File | Resolved By |
|------|------|-------------|
| 7 egresos handlers | handlers/dispatcher.py | Wave 3 (02-03-PLAN) |
| 4 ingresos/CXC handlers | handlers/dispatcher.py | Wave 4 (02-04-PLAN) |
| 4 facturacion handlers | handlers/dispatcher.py | Wave 5 (02-05-PLAN) |
| 8 consultas handlers | handlers/dispatcher.py | Wave 2 (02-02-PLAN) |
| 5 cartera/nomina/catalogo handlers | handlers/dispatcher.py | Wave 6 (02-06-PLAN) |

These stubs do not block Wave 1's goal: the ToolDispatcher routing layer is complete and functional. Stubs will be replaced atomically as each wave is implemented.

## Self-Check: PASSED

| Item | Status |
|------|--------|
| handlers/__init__.py exists | FOUND |
| handlers/dispatcher.py exists | FOUND |
| test_phase2_wave1.py exists | FOUND |
| chat.py exists | FOUND |
| commit 3c0a778 (Task 1) | FOUND |
| commit cf851f7 (Task 2) | FOUND |
| All 10 Wave 1 tests | PASS |
| Phase 1 regression (128/129) | PASS (1 pre-existing) |
