# Phase 3: Conciliación Bancaria - Context

**Gathered:** 2026-04-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Bank reconciliation: 4 bank parsers (Bancolombia/BBVA/Davivienda .xlsx + Nequi PDF), motor de clasificación con confianza 0-1, anti-duplicados 3 capas, BackgroundTasks para lotes, y módulo Backlog completo (backend + UI básica) para movimientos no clasificados.

**Note:** Phase 3 was originally "Revenue & Invoicing" in the roadmap but that scope was absorbed into Phase 2. This phase is now Conciliación Bancaria — the component with the most edge cases that merited its own cycle.

**Requirements covered:** CONC-01, CONC-02, CONC-03, BACK-01, BACK-02, BACK-03

</domain>

<decisions>
## Implementation Decisions

### Parser Strategy
- **D-01:** Auto-detect banco by extension + headers. PDF = Nequi always. .xlsx = detect by header row position (row 14 = BBVA, row 15 + sheet "Extracto" = Bancolombia, skiprows 4 = Davivienda).
- **D-02:** Nequi parser uses pdfplumber (not tabula-py). No JRE dependency.
- **D-03:** Nequi format: columns `Fecha del movimiento` / `Descripcion` / `Valor` / `Saldo`. Date DD/MM/YYYY. Negative = cargo, Positive = abono. No separate "Naturaleza" column.
- **D-04:** openpyxl for .xlsx parsing (Bancolombia, BBVA, Davivienda).
- **D-05:** Global66 and Banco de Bogota parsers deferred — format not documented.

### Nequi Specifics (from real extracto April 2026)
- **D-06:** PDF extracto, account 3102511280, titular Andres San Juan.
- **D-07:** Description patterns: "GRAVAMEN AL MOVIMIENTO" (4x1000 tax), "ENVIO CON BRE-B A: [NAME]" (outgoing), "De [NAME]" (incoming), "Recarga desde Bancolombia" (cross-bank).
- **D-08:** Valor format: $-2,919.54 (negative=egreso) / $250,000.00 (positive=ingreso). Comma=thousands, dot=decimal.

### Classification Engine
- **D-09:** Reuse and extend _classify_gasto pattern from egresos.py. Keyword matching + retenciones service for gasto classification.
- **D-10:** Confidence threshold 0.70 — above = auto-cause, below = Backlog.
- **D-11:** Nequi "GRAVAMEN AL MOVIMIENTO" = auto-classify as impuesto 4x1000 (confianza 1.0).
- **D-12:** "ENVIO CON BRE-B A: ANDRES" or "80075452" = CXC socio (confianza 1.0, never gasto operativo).

### Anti-Duplicados 3 Capas
- **D-13:** Capa 1: hash MD5 del archivo completo → colección conciliacion_extractos_procesados.
- **D-14:** Capa 2: hash MD5 por movimiento (fecha+descripcion+monto) → colección conciliacion_movimientos_procesados.
- **D-15:** Capa 3: GET Alegra post-POST para confirmar el journal fue creado.

### Backlog Flow
- **D-16:** Movimientos < 0.70 confianza van directo al Backlog (sin WhatsApp por ahora).
- **D-17:** WhatsApp notifications deferred to Phase 4+.
- **D-18:** Backlog incluye backend completo + UI básica en Phase 3:
  - Colección: backlog_movimientos en MongoDB (dato operativo, permitido)
  - Endpoints: GET /api/backlog, GET /api/backlog/count, POST /api/backlog/{id}/causar
  - Frontend: BacklogPage.tsx con tabla, filtros (banco/fecha/razón), badge en sidebar, botón "Causar" con modal

### Background Tasks
- **D-19:** BackgroundTasks + job_id para lotes > 10 movimientos.
- **D-20:** Estado del job en colección conciliacion_jobs (MongoDB operativo, permitido).
- **D-21:** Endpoint GET /api/conciliacion/estado/{job_id} para polling de progreso.

### Files That MUST NOT Be Modified
- **D-22:** backend/agents/contador/tools.py — already has conciliacion tools defined
- **D-23:** backend/core/permissions.py, events.py, database.py, client.py — Phase 1 infrastructure

### Claude's Discretion
- Exact classification rules beyond the documented patterns
- BackgroundTask retry/exponential backoff details
- Backlog UI styling and layout specifics
- Error message wording

</decisions>

<canonical_refs>
## Canonical References

### SISMO V2 Specifications
- `.planning/SISMO_V2_Fase0_Fase1.md` — Capacidad 2: Conciliación bancaria spec with formats
- `.planning/SISMO_V2_Plan_Ejecucion.md` — F1-C2 execution tasks
- `.planning/SISMO_V2_Registro_Canonico.md` — Extracto formats by bank, conciliacion collections
- `.planning/SISMO_V2_CLAUDE.md` — Bank formats (Bancolombia row 15, BBVA row 14, Davivienda skiprows=4)

### Phase 2 Code (read for handler patterns)
- `backend/agents/contador/handlers/egresos.py` — _classify_gasto pattern to extend
- `backend/agents/contador/handlers/dispatcher.py` — CONCILIATION_TOOLS to replace with real handlers
- `backend/services/retenciones.py` — retenciones calculation for classified gastos

### Nequi Format (from real extracto)
- Memory: project_nequi_format.md — PDF format, columns, patterns, values

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_classify_gasto()` in egresos.py — keyword-based classification, extendable
- `calcular_retenciones()` in retenciones.py — for classified expenses
- `request_with_verify()` in client.py — for all Alegra writes
- `publish_event()` in events.py — for post-write events
- `CONCILIATION_TOOLS` frozenset in dispatcher.py — stub handlers to replace
- `ToolDispatcher._build_handlers()` — lazy import pattern for new handlers

### Established Patterns
- Handler signature: `async def handle_X(tool_input, alegra, db, event_bus, user_id) -> dict`
- Anti-MongoDB verification grep after every wave
- Tests use AsyncMock for AlegraClient, MagicMock for db

### Integration Points
- dispatcher.py — replace conciliation stubs with real handlers
- POST /api/conciliacion/cargar-extracto — new router
- BacklogPage.tsx — new frontend page
- Sidebar badge — count from GET /api/backlog/count

</code_context>

<specifics>
## Specific Ideas

- Nequi GRAVAMEN AL MOVIMIENTO = 4x1000 impuesto, cuenta Impuestos (5505), confianza 1.0
- Nequi "ENVIO CON BRE-B A: ANDRES" = detect socio Andres, route to CXC
- Bancolombia: sheet "Extracto", headers row 15, cols FECHA (d/m) / DESCRIPCION / VALOR
- BBVA: headers row 14, cols "FECHA DE OPERACION" (DD-MM-YYYY) / "CONCEPTO" / "IMPORTE (COP)"
- Davivienda: skiprows=4, cols Fecha / Descripcion / Valor / Naturaleza (C=ingreso, D=egreso)
- Anti-dup hash: MD5(f"{fecha}|{descripcion}|{monto}") per movement

</specifics>

<deferred>
## Deferred Ideas

- WhatsApp notifications for low-confidence movements — Phase 4+
- Global66 parser — format not documented
- Banco de Bogota parser — format not documented
- Advanced classification ML model — too early, need clean data first

</deferred>

---

*Phase: 03-conciliacion-bancaria*
*Context gathered: 2026-04-09*
