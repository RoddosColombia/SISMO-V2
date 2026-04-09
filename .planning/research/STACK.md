# Technology Stack: SISMO V2

**Project:** SISMO V2 — Sistema Inteligente de Soporte y Monitoreo Operativo
**Domain:** AI Agent Orchestrator for Accounting Automation (ERP Integration)
**Researched:** 2026-04-09
**Confidence:** HIGH (V1 production validation + current library versions)

---

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

---

## Installation

### Backend

```bash
# Create virtualenv
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Core dependencies
pip install fastapi==0.115.0 uvicorn==0.30.0 pydantic==2.7.1 python-dotenv==1.0.1

# Database
pip install motor==3.7.0 pymongo==4.9.2

# AI & HTTP
pip install anthropic==0.38.0 httpx==0.27.0

# Data processing
pip install pandas==2.2.2 openpyxl==3.1.5 python-dateutil==2.9.0

# Security & utilities
pip install cryptography==43.0.1 PyJWT==2.8.0 passlib==1.7.4 bcrypt==4.1.2

# Optional: batch processing
pip install APScheduler==3.10.4

# Dev dependencies
pip install pytest==7.4.3 pytest-asyncio==0.23.2 black==24.1.1 isort==5.13.2
```

### Frontend

```bash
# Using Node 18+ (LTS)
npm install
# or
yarn install

# Build
npm run build

# Development
npm start
```

---

## Architecture Patterns: What To Use, What To Avoid

### Pattern 1: Async/Await for All I/O

**What:** Every database query, HTTP request, and Alegra API call uses async/await.

**When:** Always. No synchronous I/O in request handlers.

**Example:**
```python
from motor.motor_asyncio import AsyncIOMotorDatabase
from httpx import AsyncClient

async def register_expense(db: AsyncIOMotorDatabase, amount: float):
    # Async MongoDB call
    result = await db.cartera_pagos.insert_one({"monto": amount})
    
    # Async HTTP call to Alegra
    async with AsyncClient() as client:
        response = await client.post(
            "https://api.alegra.com/api/v1/journals",
            json=payload,
            auth=("email", "token")
        )
    return response.json()
```

**Why:** Motor + httpx are non-blocking. Using synchronous calls (requests, sync MongoDB) blocks the entire event loop. Agent systems need to handle 20+ concurrent user requests; synchronous I/O causes request queuing and timeouts.

---

### Pattern 2: Tool Use (Anthropic SDK) Instead of ACTION_MAP

**What:** Replace string-based action parsing with native Anthropic Tool Use.

**When:** Phase 0 requirement. All agent requests that execute actions.

**Example:**
```python
from anthropic import Anthropic

tools = [
    {
        "name": "registrar_gasto",
        "description": "Registra un gasto en Alegra",
        "input_schema": {
            "type": "object",
            "properties": {
                "cuenta_id": {"type": "integer"},
                "monto": {"type": "number"},
                "descripcion": {"type": "string"},
                "retenciones": {"type": "number"}
            },
            "required": ["cuenta_id", "monto", "descripcion"]
        }
    }
]

# Claude calls tools directly
response = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1024,
    tools=tools,
    messages=[{"role": "user", "content": "registra un gasto de $100k"}]
)

# Handle tool calls
if response.stop_reason == "tool_use":
    for block in response.content:
        if block.type == "tool_use":
            tool_name = block.name
            tool_input = block.input
            # Execute with type safety
```

**Why:** Tool Use is typed, validated, and less error-prone than parsing text. The SDK handles tool invocation loops. Significantly reduces prompt engineering needed.

---

### Pattern 3: request_with_verify() for All Alegra Writes

**What:** Every write to Alegra must be verified: POST → HTTP 200 → GET to confirm → report success.

**When:** Every time. No exceptions. Phase 0 requirement C6.

**Example:**
```python
async def request_with_verify(
    client: AsyncClient,
    method: str,
    endpoint: str,
    payload: dict,
    lookup_field: str
) -> dict:
    """POST/PUT to Alegra, verify with GET. Return verified record or raise."""
    
    # Step 1: POST
    create_response = await client.post(
        f"https://api.alegra.com/api/v1/{endpoint}",
        json=payload,
        auth=("email", "token")
    )
    create_response.raise_for_status()
    created = create_response.json()
    alegra_id = created.get("id") or created.get("id_journal")
    
    # Step 2: GET verification
    verify_response = await client.get(
        f"https://api.alegra.com/api/v1/{endpoint}/{alegra_id}",
        auth=("email", "token")
    )
    verify_response.raise_for_status()
    verified = verify_response.json()
    
    # Step 3: Return verified record
    return verified
```

**Why:** V1 had 176 duplicate journals because of missed POST responses. This pattern is auditable and prevents ghosts.

---

### Pattern 4: Background Tasks for Batch Operations

**What:** Imports >10 rows, bank reconciliations, P&L aggregations run in background.

**When:** Whenever processing takes >1 second or affects >10 records.

**Example:**
```python
from fastapi import BackgroundTasks

@app.post("/importar-extracto")
async def import_bank_statement(file: UploadFile, background_tasks: BackgroundTasks):
    # Queue task, return immediately
    job_id = str(uuid.uuid4())
    background_tasks.add_task(
        process_statement_async,
        file_content=await file.read(),
        job_id=job_id,
        db=db
    )
    return {"job_id": job_id, "status": "procesando"}

# Check status with GET /jobs/{job_id}
async def process_statement_async(file_content: bytes, job_id: str, db):
    # Long-running: parse Excel, classify, create journals
    # Update progress in MongoDB
    await db.jobs.update_one(
        {"_id": job_id},
        {"$set": {"progress": 50, "status": "clasificando"}}
    )
```

**Why:** FastAPI's `BackgroundTasks` are simple and sufficient for <100 jobs/day. No Celery overhead for SISMO's current scale. SSE can push progress updates to frontend.

---

### Pattern 5: Server-Sent Events (SSE) for Real-Time Updates

**What:** Agent reasoning, processing steps stream to frontend in real-time.

**When:** Long-running operations, agent reasoning chain, progress updates.

**Example:**
```python
from fastapi.responses import StreamingResponse

async def event_generator(query: str):
    """Stream Claude reasoning steps."""
    async with AsyncAnthropic() as client:
        with client.messages.stream(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            messages=[{"role": "user", "content": query}]
        ) as stream:
            for text in stream.text_stream:
                yield f"data: {json.dumps({'text': text})}\n\n"

@app.get("/chat/{agent_id}/stream")
async def chat_stream(agent_id: str, query: str):
    return StreamingResponse(
        event_generator(query),
        media_type="text/event-stream"
    )
```

**Frontend (Axios):**
```javascript
const response = await axios.get(`/chat/${agentId}/stream`, {
    params: { query },
    responseType: 'stream'
});

const reader = response.data.getReader();
const decoder = new TextDecoder();

while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const chunk = decoder.decode(value);
    // Parse SSE format: "data: {...}\n\n"
}
```

**Why:** Provides real-time feedback for 10+ second operations. Users see agent reasoning, not blank spinners. Streaming reduces latency perception.

---

### Pattern 6: Dependency Injection for MongoDB Connection

**What:** FastAPI's `Depends()` provides `db` to all handlers. Single connection pool.

**When:** Every handler that touches MongoDB or Alegra.

**Example:**
```python
# database.py
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from fastapi import Depends

client: AsyncIOMotorClient | None = None
db: AsyncIOMotorDatabase | None = None

async def init_db():
    global client, db
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    yield db
    await client.close()

async def get_db() -> AsyncIOMotorDatabase:
    return db

# routes.py
@app.post("/registrar-gasto")
async def register_expense(
    payload: GastoSchema,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    # db is the Motor client, ready to use
    result = await db.cartera_pagos.insert_one(payload.dict())
```

**Why:** Single connection pool reused across all requests. Motor's AsyncIOMotorClient is thread-safe and connection-efficient. No per-request overhead.

---

### Anti-Pattern 1: Synchronous MongoDB Access

**Bad:**
```python
# NEVER do this in FastAPI
from pymongo import MongoClient

client = MongoClient(...)  # Blocks event loop
db = client.mydb
result = db.collection.find_one({"_id": 123})  # Blocking call
```

**Why:** Blocks the entire async event loop. One slow query stalls all users. FastAPI can't handle concurrent requests.

**Use instead:** Motor with async/await.

---

### Anti-Pattern 2: Synchronous HTTP to Alegra

**Bad:**
```python
# NEVER do this in FastAPI
import requests

response = requests.post(
    "https://api.alegra.com/api/v1/journals",
    json=payload
)  # Blocks event loop
```

**Why:** Same reason — blocks event loop.

**Use instead:** `httpx.AsyncClient()`.

---

### Anti-Pattern 3: ACTION_MAP String Parsing

**Bad:**
```python
# Old pattern — fragile
response = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    messages=[...],
    # No tools defined
)

# Parse text for action: "registra_gasto:5480:500000:..."
action_line = [line for line in response.content[0].text.split('\n') 
               if line.startswith('registra_')]
```

**Why:** Ambiguous, error-prone, requires complex parsing logic.

**Use instead:** Tool Use with structured tool definitions.

---

### Anti-Pattern 4: Hardcoding Database Names or Connection Strings

**Bad:**
```python
# NEVER hardcode
db = client['sismo']  # Hardcoded
```

**Why:** Breaks multi-environment deployments. V1 had this bug.

**Use instead:**
```python
db_name = os.environ['DB_NAME']
db = client[db_name]  # Respects dev/prod environments
```

---

### Anti-Pattern 5: Alegra Writes Without Verification

**Bad:**
```python
# NEVER skip verification
response = await client.post(
    "https://api.alegra.com/api/v1/journals",
    json=payload
)
# Return success immediately
return {"status": "creado"}  # Might be false!
```

**Why:** V1 had 176 duplicate journals from this.

**Use instead:** `request_with_verify()` pattern (Pattern 3).

---

### Anti-Pattern 6: Mixing MongoDB and Alegra as Truth Sources

**Bad:**
```python
# NEVER read from MongoDB for accounting data
latest_journal = db.roddos_events.find_one(sort=[("timestamp", -1)])
# Use this to construct P&L
```

**Why:** V1 failed here. MongoDB is unreliable for accounting. Alegra is the source of truth (ROG-4).

**Use instead:**
```python
# Read P&L data from Alegra, use MongoDB only for caching
async with AsyncClient() as client:
    journals = await client.get(
        "https://api.alegra.com/api/v1/journals",
        auth=("email", "token")
    )
```

---

## Scalability Considerations

| Concern | At 100 users (dev) | At 1K users (MVP) | At 10K users (mature) |
|---------|------------|------------|-------------|
| **Database** | MongoDB M0, single connection | M2, 10 connections, indexes on `timestamp`, `agent_id` | M5+, sharded on `agent_id`, read replicas |
| **API Server** | FastAPI single instance, Render free tier | 2 Render instances, load balancer | 3+ instances, auto-scaling based on latency |
| **Alegra API** | Sync calls within request (~500ms latency) | Batch endpoint calls, implement caching (Redis) | Dedicate thread pool for Alegra queries, implement circuit breaker |
| **Streaming (SSE)** | Single `/chat/{id}/stream` endpoint per user | Keep-alive timeout 60s, reconnect logic on frontend | Rate limiting: max 10 concurrent streams per user |
| **Background Tasks** | Single Render instance, APScheduler in-process | Separated job queue (APScheduler + MongoDB queue) | Celery + Redis for distributed jobs |

---

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

---

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

---

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

---

## Sources

- **SISMO V1 Production Codebase:** `/roddos-workspace/SISMO/` — 67 tests, 8 phases, validated async patterns
- **Anthropic SDK Documentation (2026):** Official SDK changelog; Tool Use stable since v0.35
- **FastAPI Official Docs:** `fastapi.tiangolo.com` — async/await patterns, SSE examples
- **Motor Documentation:** `motor.readthedocs.io` — async MongoDB best practices
- **Python 3.11 Typing:** `docs.python.org/3.11` — type hints stability, async/await performance
- **SISMO V2 Requirements:** `.planning/SISMO_V2_Fase0_Fase1.md` — Phase 0 Tool Use, request_with_verify(), bus de eventos

---

## Installation Checklist for Phase 0

Before building Phase 0, verify:

- [ ] `motor>=3.7.0` installed (not pymongo alone)
- [ ] `anthropic>=0.38.0` with Tool Use support
- [ ] `httpx>=0.27.0` (async HTTP client)
- [ ] `FastAPI>=0.115.0` with SSE support
- [ ] `.env` file with `MONGO_URL` and `DB_NAME` (no hardcoding)
- [ ] `AsyncIOMotorClient` in `database.py` (not sync MongoClient)
- [ ] Tool definitions for 32 Contador tools (Phase 0 C4 requirement)
- [ ] `request_with_verify()` function implemented (Phase 0 C6)
- [ ] Event schema in MongoDB `roddos_events` collection (Phase 0 C5)

---

**Next Step:** Use this stack to build Phase 0 cimientos. If you hit a version conflict or need to add a library, check this document first — avoid adding tech debt.
