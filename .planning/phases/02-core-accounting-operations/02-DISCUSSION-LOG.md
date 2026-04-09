# Phase 2: Core Accounting Operations - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-09
**Phase:** 02-core-accounting-operations
**Areas discussed:** Scope alignment, Retenciones engine

---

## Scope Alignment

| Option | Description | Selected |
|--------|-------------|----------|
| CONTEXT.md manda | Absorber 29 handlers en Phase 2, mover FACT/INGR/PL | ✓ |
| Roadmap manda | Phase 2 solo EGRE+CONC+NOMI+CXC (11 reqs original) | |
| Hibrido | Phase 2 = handlers operativos, Phase 3 = conciliacion, Phase 4 = backlog + P&L | |

**User's choice:** CONTEXT.md manda
**Notes:** SISMO_V2_Phase2_CONTEXT.md is the authoritative spec. 29 handlers absorbed into Phase 2. Conciliacion = Phase 3.

---

## Retenciones Engine

### Location

| Option | Description | Selected |
|--------|-------------|----------|
| Servicio compartido | backend/services/retenciones.py separado | ✓ |
| Dentro del handler | Cada handler calcula inline | |
| Motor matricial | Engine con reglas declarativas | |

**User's choice:** Servicio compartido (user specified exact signature and behavior)
**Notes:** User provided detailed spec: calcular_retenciones(tipo, monto, nit) -> {retefuente_tasa, retefuente_monto, reteica_tasa, reteica_monto, neto_a_pagar}

### Autoretenedores

| Option | Description | Selected |
|--------|-------------|----------|
| Lista hardcodeada | Solo Auteco NIT 860024781 por ahora | ✓ |
| Config en MongoDB | Coleccion proveedores_config | |
| You decide | Claude elige | |

**User's choice:** Lista hardcodeada
**Notes:** None

---

## Claude's Discretion

- Error message formatting details
- Background task implementation for masiva handlers
- Anti-duplicate hash algorithm
- Event payload structure

## Deferred Ideas

- Conciliacion bancaria parsers — Phase 3
- Backlog UI — later phase
