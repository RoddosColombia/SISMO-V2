<!-- GSD:project-start source:PROJECT.md -->
## Project

**SISMO V2 — Sistema Inteligente de Soporte y Monitoreo Operativo**

Orquestador de agentes IA que automatiza la operación contable y financiera de RODDOS S.A.S., concesionario de motos TVS con financiación propia en Bogotá. El Agente Contador causa asientos, facturas y pagos en Alegra (ERP contable); los demás agentes (CFO, RADAR, Loanbook) consumen esa información para análisis, cobranza y gestión de créditos. Reimplementación limpia del backend con fork del frontend existente.

**Core Value:** Cada peso que entra o sale de RODDOS queda como un registro verificado en Alegra — el P&L refleja la realidad del negocio sin intervención manual.

### Constraints

- **Stack:** FastAPI Python 3.11 + React 19 + MongoDB Atlas (async Motor) + Claude Sonnet via Anthropic SDK + Alegra API + Mercately WhatsApp
- **Deploy:** Render (backend) + Vercel (frontend) + MongoDB Atlas M0
- **Alegra API:** Base URL `https://api.alegra.com/api/v1/`, Basic auth, NUNCA `/journal-entries` ni `/accounts` (403), fechas `yyyy-MM-dd` estricto
- **Contable:** IVA cuatrimestral, retenciones calculadas automáticamente, Fallback cuenta ID 5493 (NUNCA 5495)
- **Seguridad:** WRITE_PERMISSIONS en código (no en narrativa), request_with_verify() obligatorio, anti-duplicados 3 capas
- **Criterio de éxito:** 22 smoke tests pasando
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Recommended Stack
### Core Framework
| Technology | Version | Purpose | Why |
|-----------|---------|---------|-----|
| **FastAPI** | 0.115+ | HTTP server, dependency injection, async request handling | Lightweight async-first framework optimized for Python 3.11+ type hints. Industry standard for AI agent APIs. V1 used 0.110.1; upgrade to current 0.115+ for performance and security patches. Built-in support for streaming responses (SSE) and background tasks. |
| **Python** | 3.11 | Language runtime | LTS release (support until 2027). Stable asyncio, better typing, excellent with Pydantic v2. Required by Anthropic SDK and Motor for full async support. |
| **Uvicorn** | 0.30+ | ASGI server | Drop-in FastAPI server. V1 used 0.25.0; upgrade to 0.30+ for H11 improvements and production stability. |
| **Pydantic** | 2.7+ | Request/response validation, config | Type-safe validation with zero runtime overhead. V2 is mandatory for FastAPI modern patterns. |
### Database Access
| Technology | Version | Purpose | Why |
|-----------|---------|---------|-----|
| **Motor** | 3.7+ | Async MongoDB driver | **Critical for agent systems.** Motor provides non-blocking MongoDB access required for concurrent agent requests without thread pools. V1 used 3.7.0 — maintain or upgrade to 3.8+. All Alegra querying happens in parallel; synchronous MongoDB locks the event loop. |
| **PyMongo** | 4.9+ | MongoDB client library (Motor dependency) | Motor is a wrapper around PyMongo; versions must stay synchronized. |
| **MongoDB Atlas** | M0 tier | Managed MongoDB (deployment target) | 512MB free tier sufficient for development. Production: upgrade to M2+ with connection pooling (10+ concurrent connections for agent concurrency). |
### AI Agent Framework
| Technology | Version | Purpose | Why |
|-----------|---------|---------|-----|
| **Anthropic SDK** | 0.38+ | Claude API client, Tool Use | V1 used 0.34.0 — **upgrade to 0.38+ for native Tool Use support.** Essential for Phase 0 requirement: "Tool Use nativo (Anthropic API)". Tool Use provides type-safe agent tool invocation instead of ACTION_MAP string parsing. SDK is async-first; pairs perfectly with FastAPI. |
| **anthropic.AsyncAnthropic()** | Built-in | Async client wrapper | Use instead of sync client. Prevents event loop blocking. Critical for streaming responses and parallel agent requests. |
### Data Processing & ERP Integration
| Technology | Version | Purpose | Why |
|-----------|---------|---------|-----|
| **httpx** | 0.27+ | Async HTTP client | Alegra API calls must be non-blocking. httpx is async-native (unlike requests). V1 used 0.27.0 — current standard. Use `httpx.AsyncClient()` in context managers for connection pooling. |
| **openpyxl** | 3.1+ | Excel file parsing | Bank statement imports (.xlsx format). Non-async but isolated in background tasks. V1 used 3.1.5. |
| **pandas** | 2.2+ | Tabular data operations | Bank reconciliation workflows. V1 used 2.2.2. Use `pd.read_excel()` in `BackgroundTasks` only. |
| **python-dateutil** | 2.9+ | Date parsing and manipulation | Flexible date parsing for Colombian accounting (multiple date formats in legacy data). V1 used 2.9.0. |
### Supporting Libraries
| Library | Version | Purpose | When to Use |
|---------|---------|---------|------------|
| **python-dotenv** | 1.0+ | Environment variable loading | Loading `.env` files in development. Production: Render provides secrets via environment directly. |
| **requests** | 2.32+ | Synchronous HTTP client | Fallback only. Prefer httpx. Used in some legacy compatibility modules. V1 used 2.32.3. |
| **aiohttp** | 3.9+ | Async HTTP client (alternative to httpx) | Not recommended for new code. Stick with httpx for consistency. |
| **APScheduler** | 3.10+ | Background task scheduler | Job scheduling for batch operations (nightly reconciliation, P&L aggregation). Use with caution — prefer Celery if >100 jobs/day. |
| **cryptography** | 43.0+ | Encryption, JWT signing | Password hashing, token generation. V1 used 43.0.1. Keep up-to-date for security patches. |
| **pdfplumber** | 0.11+ | PDF extraction | Bank statements in PDF format (fallback). V1 used 0.11.0. Not in critical path. |
### Frontend Stack
| Technology | Version | Purpose | Why |
|-----------|---------|---------|-----|
| **React** | 19.0+ | UI framework | V1 used 19.0.0. Concurrent rendering, better performance. Stable with Vite/modern tooling. |
| **React Router** | 7.5+ | Client-side routing | V1 used 7.5.1. Tree-shaking friendly for production builds. |
| **TailwindCSS** | 3.4+ | Utility-first CSS | V1 used 3.4.17. JIT compilation, excellent for rapid iteration. |
| **Radix UI** | ^1.1+ | Headless component library | V1 has 13+ Radix components (dialog, select, tabs, etc.). Accessibility-first. Continue this pattern. |
| **React Hook Form** | 7.56+ | Form state management | V1 used 7.56.2. Minimal re-renders, integrates with Zod validation. |
| **Zod** | 3.24+ | TypeScript schema validation | V1 used 3.24.4. Validates form inputs before sending to backend. |
| **Axios** | 1.8+ | HTTP client for frontend | V1 used 1.8.4. Server-Sent Events (SSE) compatible. Pair with `axios.get(..., { responseType: 'stream' })` for streaming. |
| **recharts** | 3.6+ | React charting library | V1 used 3.6.0. P&L dashboards, financial charts. Responsive and animation-friendly. |
| **xlsx** | 0.18+ | Excel file handling (frontend) | V1 used 0.18.5. For downloading P&L, balance sheet as Excel. |
| **sonner** | 2.0+ | Toast notifications | V1 used 2.0.3. Better UX than native alerts. |
| **date-fns** | 4.1+ | Date formatting (frontend) | V1 used 4.1.0. Colombian date format: `dd/MM/yyyy`. |
## Installation
### Backend
# Create virtualenv
# Core dependencies
# Database
# AI & HTTP
# Data processing
# Security & utilities
# Optional: batch processing
# Dev dependencies
### Frontend
# Using Node 18+ (LTS)
# or
# Build
# Development
## Architecture Patterns: What To Use, What To Avoid
### Pattern 1: Async/Await for All I/O
### Pattern 2: Tool Use (Anthropic SDK) Instead of ACTION_MAP
# Claude calls tools directly
# Handle tool calls
### Pattern 3: request_with_verify() for All Alegra Writes
### Pattern 4: Background Tasks for Batch Operations
# Check status with GET /jobs/{job_id}
### Pattern 5: Server-Sent Events (SSE) for Real-Time Updates
### Pattern 6: Dependency Injection for MongoDB Connection
# database.py
# routes.py
### Anti-Pattern 1: Synchronous MongoDB Access
# NEVER do this in FastAPI
### Anti-Pattern 2: Synchronous HTTP to Alegra
# NEVER do this in FastAPI
### Anti-Pattern 3: ACTION_MAP String Parsing
# Old pattern — fragile
# Parse text for action: "registra_gasto:5480:500000:..."
### Anti-Pattern 4: Hardcoding Database Names or Connection Strings
# NEVER hardcode
### Anti-Pattern 5: Alegra Writes Without Verification
# NEVER skip verification
# Return success immediately
### Anti-Pattern 6: Mixing MongoDB and Alegra as Truth Sources
# NEVER read from MongoDB for accounting data
# Use this to construct P&L
# Read P&L data from Alegra, use MongoDB only for caching
## Scalability Considerations
| Concern | At 100 users (dev) | At 1K users (MVP) | At 10K users (mature) |
|---------|------------|------------|-------------|
| **Database** | MongoDB M0, single connection | M2, 10 connections, indexes on `timestamp`, `agent_id` | M5+, sharded on `agent_id`, read replicas |
| **API Server** | FastAPI single instance, Render free tier | 2 Render instances, load balancer | 3+ instances, auto-scaling based on latency |
| **Alegra API** | Sync calls within request (~500ms latency) | Batch endpoint calls, implement caching (Redis) | Dedicate thread pool for Alegra queries, implement circuit breaker |
| **Streaming (SSE)** | Single `/chat/{id}/stream` endpoint per user | Keep-alive timeout 60s, reconnect logic on frontend | Rate limiting: max 10 concurrent streams per user |
| **Background Tasks** | Single Render instance, APScheduler in-process | Separated job queue (APScheduler + MongoDB queue) | Celery + Redis for distributed jobs |
## Alternatives Considered
| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| **Async HTTP** | httpx | aiohttp | aiohttp is heavier, httpx is simpler and matches FastAPI ecosystem. |
| **Async HTTP** | httpx | requests (sync) | requests blocks event loop. Never use in FastAPI. |
| **MongoDB Driver** | Motor | pymongo (sync) | pymongo blocks event loop. Motor is the only option. |
| **Agent Framework** | Anthropic SDK Tool Use | LangChain | LangChain adds abstraction overhead; Anthropic SDK is simpler and more direct for Claude. |
| **Agent Framework** | Anthropic SDK Tool Use | ACTION_MAP (custom parsing) | ACTION_MAP is fragile; Tool Use is typed and validated. |
| **Background Tasks** | APScheduler (in-process) | Celery + Redis | Celery is overkill for <100 jobs/day. Add only if job volume exceeds 1000/day. |
| **Background Tasks** | APScheduler (in-process) | AWS Lambda | Adds AWS vendor lock-in and latency. Render + APScheduler is simpler for <500 jobs/day. |
| **Streaming** | Server-Sent Events (SSE) | WebSockets | SSE is sufficient for one-way streaming (agent reasoning). WebSockets add complexity for full-duplex. |
| **Streaming** | Server-Sent Events (SSE) | Polling | Polling burns API quota and adds latency. SSE is better. |
| **Frontend Framework** | React 19 | Vue 3 | Both are viable; V1 chose React, stick for consistency. |
| **CSS Framework** | TailwindCSS | Bootstrap | Tailwind is lighter, better for rapid iteration. V1 chose it. |
| **Form Validation** | Zod + React Hook Form | Formik | Formik is heavier; Hook Form + Zod is more modern and minimal. |
## What NOT to Use and Why
| Technology | Why Avoid |
|-----------|-----------|
| **Django** | Too heavy for a microservice-oriented agent system. FastAPI is 10x faster for API endpoints. |
| **Flask** | Synchronous by default. Requires significant async refactoring. FastAPI is built for async. |
| **SQLAlchemy** | Relational model doesn't fit MongoDB + Alegra API architecture. ORM overhead not needed. |
| **requests (sync)** | Blocks event loop in FastAPI. httpx is the async replacement. |
| **pymongo (sync)** | Blocks event loop. Motor is required for async MongoDB. |
| **Celery (for <1K jobs/day)** | Over-engineered. APScheduler in-process is sufficient until 1000+ jobs/day. |
| **Redis (unless caching data)** | Adds infrastructure complexity. Use only if implementing distributed cache for Alegra results. Start with MongoDB caching. |
| **GraphQL** | REST is simpler for agent-driven APIs. GraphQL adds schema complexity. Stick with REST + Tool Use. |
| **Next.js** | V1 uses Vercel for frontend hosting, but CRA + manual routing is sufficient. Next.js is heavier for a simple SPA. |
| **Socket.io** | WebSockets add bidirectional complexity. SSE is sufficient for agent reasoning streaming. |
| **Pydantic V1** | Pydantic V2 is faster, better with FastAPI. V1 is deprecated (support ends 2025). |
## Version Pinning Strategy
### Critical (Pin Exactly)
- `anthropic==0.38.0+` — API changes in tool definitions
- `motor==3.7.0+` — Async driver, patch version matters
- `fastapi==0.115.0+` — Core framework, breaking changes across minor versions
- `pydantic==2.7+` — Validation engine, used everywhere
### Compatible (Pin Minor, Allow Patch)
- `uvicorn>=0.30.0,<1.0` — ASGI server, patch upgrades are safe
- `httpx>=0.27.0,<1.0` — HTTP client, backward compatible
- `pandas>=2.2.0,<3.0` — Data processing, minor version safe
- `openpyxl>=3.1.0,<4.0` — Excel parsing, stable
### Flexible (Latest Safe)
- `python-dotenv` — Simple utility, latest is safe
- `python-dateutil` — Stable library
- `cryptography` — Keep patched for security
### Frontend (Pin Minor)
- `react>=19.0.0,<20.0`
- `react-router>=7.5.0,<8.0`
- `tailwindcss>=3.4.0,<4.0`
## Sources
- **SISMO V1 Production Codebase:** `/roddos-workspace/SISMO/` — 67 tests, 8 phases, validated async patterns
- **Anthropic SDK Documentation (2026):** Official SDK changelog; Tool Use stable since v0.35
- **FastAPI Official Docs:** `fastapi.tiangolo.com` — async/await patterns, SSE examples
- **Motor Documentation:** `motor.readthedocs.io` — async MongoDB best practices
- **Python 3.11 Typing:** `docs.python.org/3.11` — type hints stability, async/await performance
- **SISMO V2 Requirements:** `.planning/SISMO_V2_Fase0_Fase1.md` — Phase 0 Tool Use, request_with_verify(), bus de eventos
## Installation Checklist for Phase 0
- [ ] `motor>=3.7.0` installed (not pymongo alone)
- [ ] `anthropic>=0.38.0` with Tool Use support
- [ ] `httpx>=0.27.0` (async HTTP client)
- [ ] `FastAPI>=0.115.0` with SSE support
- [ ] `.env` file with `MONGO_URL` and `DB_NAME` (no hardcoding)
- [ ] `AsyncIOMotorClient` in `database.py` (not sync MongoClient)
- [ ] Tool definitions for 32 Contador tools (Phase 0 C4 requirement)
- [ ] `request_with_verify()` function implemented (Phase 0 C6)
- [ ] Event schema in MongoDB `roddos_events` collection (Phase 0 C5)
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, or `.github/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
