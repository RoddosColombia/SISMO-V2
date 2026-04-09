# SISMO V2 — Sistema Inteligente de Soporte y Monitoreo Operativo

## What This Is

Orquestador de agentes IA que automatiza la operación contable y financiera de RODDOS S.A.S., concesionario de motos TVS con financiación propia en Bogotá. El Agente Contador causa asientos, facturas y pagos en Alegra (ERP contable); los demás agentes (CFO, RADAR, Loanbook) consumen esa información para análisis, cobranza y gestión de créditos. Reimplementación limpia del backend con fork del frontend existente.

## Core Value

Cada peso que entra o sale de RODDOS queda como un registro verificado en Alegra — el P&L refleja la realidad del negocio sin intervención manual.

## Requirements

### Validated

(None yet — ship to validate)

### Active

**Fase 0 — Cimientos Arquitectónicos:**
- [ ] Router con threshold de confianza 0.70 para despacho correcto de agentes
- [ ] System prompts diferenciados por agente (Contador, CFO, RADAR, Loanbook)
- [ ] WRITE_PERMISSIONS en código — PermissionError si agente escribe donde no debe
- [ ] Tool Use nativo (Anthropic API) con feature flag para rollback a ACTION_MAP
- [ ] Bus de eventos funcional (roddos_events append-only) con publicación obligatoria
- [ ] request_with_verify() como patrón único para toda escritura en Alegra

**Fase 1 — Agente Contador Completo:**
- [ ] Egresos por chat (clasificación automática + retenciones + confirmación)
- [ ] Conciliación bancaria masiva (.xlsx) + movimientos individuales por chat
- [ ] Nómina mensual discriminada por empleado con anti-duplicados
- [ ] CXC socios (Andrés/Iván) — nunca como gasto operativo
- [ ] Facturación directa en Alegra (POST /invoices) con VIN obligatorio
- [ ] Ingresos por cuotas de cartera (doble operación: payment + journal)
- [ ] Ingresos no operacionales (motos recuperadas, intereses bancarios)
- [ ] Módulo Backlog operativo (red de seguridad para movimientos no causados)
- [ ] P&L automático construido por CFO desde Alegra (resultado de todo lo anterior)

### Out of Scope

- Agentes nuevos más allá de los 4 existentes (Contador, CFO, RADAR, Loanbook) — primero consolidar los actuales
- App móvil nativa — web-first, mobile responsive después
- Integración con otros ERPs — Alegra es el ERP canónico, sin alternativas
- Multi-tenancy — SISMO es exclusivo para RODDOS S.A.S.
- Parser de Global66 y Banco de Bogotá — sin formato documentado aún
- Migración de datos históricos de V1 — arranque limpio

## Context

**Empresa:** RODDOS S.A.S., concesionario TVS en Bogotá. Financiación propia (planes P39S, P52S, P78S semanales). ~3 personas clave: Andrés (CEO/dev), Iván (CGO), Liz (operaciones/backlog).

**SISMO V1:** Llegó a Fase 8-A (10/10 tests) con 34 colecciones MongoDB, 67 tests, 64 índices. Agente Contador en ~4.8/10 — el objetivo de V2 es llevarlo a 9.0/10.

**Problema raíz:** El dinero no fluía correctamente. Sin egresos causados no hay gastos en el P&L. Sin facturación no hay ingresos. Sin pagos de cuotas el recaudo no aparece. El CFO quedaba ciego ante cualquier omisión.

**ROG-4 — Regla fundamental:** Alegra es la fuente canónica de toda información contable. MongoDB es almacenamiento operativo temporal (sesiones, cache, estado de jobs, loanbooks, inventario). NUNCA es fuente de verdad contable.

**Backend:** Reimplementación limpia — sin herencia de deuda técnica de V1. Solo las specs como guía.

**Frontend:** Fork del frontend actual (sismo-bice.vercel.app) con refactor incremental.

**Estado del Backlog:** 298 movimientos pendientes (BBVA 33, Bancolombia 188, Nequi 76) que Liz concilia manualmente.

**Retenciones Colombia 2026:** Arrendamiento 3.5%, Servicios 4%, Honorarios PN 10%, PJ 11%, Compras 2.5% (base >$1.344.573), ReteICA Bogotá 0.414%. Auteco (NIT 860024781) = autoretenedor, NUNCA ReteFuente. IVA cuatrimestral.

## Constraints

- **Stack:** FastAPI Python 3.11 + React 19 + MongoDB Atlas (async Motor) + Claude Sonnet via Anthropic SDK + Alegra API + Mercately WhatsApp
- **Deploy:** Render (backend) + Vercel (frontend) + MongoDB Atlas M0
- **Alegra API:** Base URL `https://api.alegra.com/api/v1/`, Basic auth, NUNCA `/journal-entries` ni `/accounts` (403), fechas `yyyy-MM-dd` estricto
- **Contable:** IVA cuatrimestral, retenciones calculadas automáticamente, Fallback cuenta ID 5493 (NUNCA 5495)
- **Seguridad:** WRITE_PERMISSIONS en código (no en narrativa), request_with_verify() obligatorio, anti-duplicados 3 capas
- **Criterio de éxito:** 22 smoke tests pasando

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Reimplementar backend limpio (no migrar V1) | Evitar herencia de deuda técnica acumulada en 8 fases | -- Pending |
| Fork frontend de V1 con refactor | UI funcional que solo necesita extensiones (Backlog page) | -- Pending |
| Alegra como fuente canónica (ROG-4) | MongoDB causó inconsistencias contables en V1 cuando se usó como fuente | -- Pending |
| Tool Use nativo con feature flag | Migrar de ACTION_MAP frágil a herramientas tipadas, con rollback seguro | -- Pending |
| Fase 0 completa ANTES de Fase 1 | Los cimientos previenen los loops de identidad/permisos/verificación de V1 | -- Pending |
| 4 agentes con bus de eventos | Comunicación desacoplada via roddos_events — ningún agente llama a otro directamente | -- Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? -> Move to Out of Scope with reason
2. Requirements validated? -> Move to Validated with phase reference
3. New requirements emerged? -> Add to Active
4. Decisions to log? -> Add to Key Decisions
5. "What This Is" still accurate? -> Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check -- still the right priority?
3. Audit Out of Scope -- reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-09 after initialization*
