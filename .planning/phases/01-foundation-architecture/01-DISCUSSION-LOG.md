# Phase 1: Foundation & Architecture - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-09
**Phase:** 01-foundation-architecture
**Areas discussed:** Router strategy, Tool Use scope, Project structure, Test strategy

---

## Router Strategy

### Confidence Measurement

| Option | Description | Selected |
|--------|-------------|----------|
| LLM classifier | Claude clasifica intent con JSON estructurado (agent + confidence) | |
| Keyword + rules | Reglas deterministas primero, LLM solo como fallback para ambiguos | ✓ |
| You decide | Claude elige el approach optimo | |

**User's choice:** Keyword + rules
**Notes:** Deterministic rules for known patterns, LLM classifier only as fallback for truly ambiguous messages.

### Multi-Intent Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Primer intent wins | Router despacha al primer agente detectado | |
| Respuesta secuencial | Router detecta ambos, ejecuta en secuencia | |
| Pedir aclaracion | Router pide al usuario que enfoque en una cosa | ✓ |

**User's choice:** Pedir aclaracion
**Notes:** None

### Session Behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Sticky session | Conversacion sigue con agente hasta cambio explicito | |
| Re-clasificar siempre | Cada mensaje pasa por el router | |
| Sticky + override | Sticky por defecto, pregunta si detecta intent para otro agente | ✓ |

**User's choice:** Sticky + override
**Notes:** None

---

## Tool Use Scope

### Tool Count in Phase 0

| Option | Description | Selected |
|--------|-------------|----------|
| Todas las 9 tools | Registrar las 9 tools del spec | |
| Solo el framework | Framework + 1-2 tools de ejemplo | |
| (Other) | Cargar las 32 tools de V1's tool_executor.py | ✓ |

**User's choice:** Extract all 32 tool definitions from V1's tool_executor.py. Framework built from scratch but tool definitions reused.
**Notes:** User specified exact file path: C:\Users\AndresSanJuan\roddos-workspace\SISMO\backend\tool_executor.py

### Other Agents

| Option | Description | Selected |
|--------|-------------|----------|
| Solo Contador | CFO/RADAR/Loanbook solo system prompt + identidad | ✓ |
| Tools basicos todos | Cada agente recibe 1-2 tools de lectura | |

**User's choice:** Solo Contador
**Notes:** None

### Write Confirmation UX

| Option | Description | Selected |
|--------|-------------|----------|
| Preview + confirm | Agente propone asiento en texto, usuario dice si | |
| ExecutionCard UI | Componente React con vista previa + boton Confirmar | ✓ |

**User's choice:** ExecutionCard UI
**Notes:** None

---

## Project Structure

### Backend Layout

| Option | Description | Selected |
|--------|-------------|----------|
| Por feature/dominio | backend/agents/contador/, backend/services/alegra/, etc. | ✓ |
| Por capa | backend/routers/, backend/services/, backend/models/ | |
| Plano + prefijos | backend/ai_chat.py, backend/accounting_engine.py (como V1) | |

**User's choice:** Por feature/dominio
**Notes:** None

### Dependency Management

| Option | Description | Selected |
|--------|-------------|----------|
| Singleton global | database.py y alegra_client.py con instancias globales | |
| Dependency injection | FastAPI Depends() inyecta db y alegra_client | ✓ |
| You decide | Claude elige | |

**User's choice:** Dependency injection
**Notes:** None

### Repo Layout

| Option | Description | Selected |
|--------|-------------|----------|
| Monorepo | SISMO-V2/backend/ + SISMO-V2/frontend/ | ✓ |
| Solo backend | SISMO-V2 es solo backend | |

**User's choice:** Monorepo
**Notes:** None

---

## Test Strategy

### Alegra API Testing

| Option | Description | Selected |
|--------|-------------|----------|
| Mock HTTP responses | httpx mock para simular respuestas de Alegra | |
| Sandbox real | Cuenta de prueba en Alegra | |
| Ambos | Mocks para unit + sandbox para integration | ✓ |

**User's choice:** Ambos
**Notes:** None

### Framework

| Option | Description | Selected |
|--------|-------------|----------|
| pytest + httpx | pytest con AsyncClient de httpx | ✓ |
| pytest + TestClient | FastAPI TestClient (sync wrapper) | |
| You decide | Claude elige | |

**User's choice:** pytest + httpx
**Notes:** None

### Smoke Tests Automation

| Option | Description | Selected |
|--------|-------------|----------|
| Automatizados | Los 22 como pytest tests en CI | |
| Semi-auto | Infraestructura automatizada, flujo completo manual | ✓ |
| Checklist manual | Los 22 se verifican manualmente | |

**User's choice:** Semi-auto
**Notes:** None

---

## Claude's Discretion

- Exact directory hierarchy details within the domain-based backend pattern
- Error handling patterns and retry logic
- Event schema validation approach
- httpx mock patterns

## Deferred Ideas

None — discussion stayed within phase scope.
