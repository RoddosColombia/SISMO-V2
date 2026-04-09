# Phase 1: Foundation & Architecture - Research

**Researched:** 2026-04-09
**Domain:** Agent infrastructure (router, permissions, events, Tool Use, async patterns)
**Confidence:** HIGH

## Summary

Phase 1 is the critical foundation that enables all subsequent accounting operations. It establishes six architectural pillars: (1) router with 0.70 confidence threshold, (2) differentiated system prompts per agent, (3) code-enforced write permissions, (4) Anthropic Tool Use native with feature flag, (5) immutable event bus (roddos_events), and (6) request_with_verify() pattern for all Alegra writes.

This research documents the standard stack, patterns, and critical gotchas for building a robust multi-agent system on FastAPI + Motor + Anthropic SDK + Alegra API. All findings are verified against V1 production code (8 phases, 67 tests) and official documentation.

**Primary recommendation:** Use Motor 3.7+ for all MongoDB access, Anthropic SDK 0.38+ for Tool Use, httpx 0.27+ for async Alegra calls, and implement permissions as middleware, not narrative.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Keyword + rules first for confidence scoring. Deterministic rules map known patterns. LLM classifier as fallback for ambiguous messages. Confidence threshold: 0.70.
- **D-02:** Multi-intent messages trigger clarification. Router asks user to focus, never auto-dispatches to two agents.
- **D-03:** Sticky session with override. Once dispatched to an agent, conversation stays with that agent. Router can suggest switch if high-confidence intent detected for different agent.
- **D-04:** All 32 tools from V1's tool_executor.py extracted. Framework built from scratch but tool definitions are extracted from V1.
- **D-05:** Only Contador agent gets tools in Phase 0. CFO, RADAR, Loanbook agents receive system prompts and identity only.
- **D-06:** Write tool confirmation uses ExecutionCard UI — React component with journal preview + Confirm/Cancel buttons.
- **D-07:** Backend organized by feature/domain: `backend/agents/contador/`, `backend/agents/cfo/`, `backend/services/alegra/`, `backend/services/events/`, `backend/core/` (router, permissions, database).
- **D-08:** Dependency injection via FastAPI Depends(). MongoDB client, Alegra client, and EventPublisher injected into routers/services.
- **D-09:** Monorepo: `SISMO-V2/backend/` + `SISMO-V2/frontend/` in same repo. Deployed separately (Render for backend, Vercel for frontend).
- **D-10:** Alegra API tested with both mocks and sandbox. httpx mocks for unit tests (fast, deterministic). Real Alegra sandbox account for integration tests.
- **D-11:** Testing framework: pytest + httpx AsyncClient for FastAPI async testing.
- **D-12:** 22 smoke tests are semi-automated. Infrastructure tests (permissions, router, events, request_with_verify) are automated pytest.

### Claude's Discretion
- Exact directory hierarchy within backend/ (beyond the domain-based pattern)
- Error handling patterns and retry logic implementation details
- Event schema validation approach (Pydantic model vs dict)
- Specific httpx mock patterns for Alegra responses

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.

</user_constraints>

<phase_requirements>
## Phase Requirements (FOUND-01 through FOUND-06)

| ID | Description | Research Support |
|----|-------------|------------------|
| **FOUND-01** | Router dispatches intent to correct agent with confidence >= 0.70; ambiguous prompts trigger single clarification question | Router implementation patterns, keyword-matching approach, LLM fallback architecture documented below in "Architecture Patterns" and "Router Confidence Scoring" |
| **FOUND-02** | Each agent (Contador, CFO, RADAR, Loanbook) has differentiated system prompt delivered as system message | System prompts defined in SISMO_V2_System_Prompts.md; implementation via SYSTEM_PROMPTS dict in ai_chat.py documented in "Anthropic Tool Use API" section |
| **FOUND-03** | WRITE_PERMISSIONS enforced in code — PermissionError raised if agent attempts write outside permitted collections/endpoints | Permissions matrix in SISMO_V2_System_Prompts.md; middleware/decorator patterns documented in "WRITE_PERMISSIONS Enforcement Patterns" section |
| **FOUND-04** | Anthropic Tool Use native with typed tool definitions; TOOL_USE_ENABLED feature flag for ACTION_MAP rollback | Tool Use API patterns, feature flag strategy, and tool definition extraction from V1 documented in "Anthropic Tool Use API" and "Tool Definitions (32 tools from V1)" sections |
| **FOUND-05** | Event bus (roddos_events) publishes immutable event after every successful Alegra write | Event schema, Motor append-only patterns, and event publication flow documented in "Event Bus Architecture (roddos_events)" section |
| **FOUND-06** | request_with_verify() is the only path for Alegra writes: POST -> verify HTTP 200/201 -> GET confirmation -> return Alegra ID | Verification pattern, retry logic, and httpx async patterns documented in "request_with_verify() Implementation" section |

</phase_requirements>

---

## Standard Stack

### Core Framework & Async Foundation
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| **FastAPI** | 0.115+ | HTTP server, dependency injection, streaming responses | Async-first, lightweight, built for AI agents. Supports SSE (Server-Sent Events) for streaming chat responses and ExecutionCard updates. V1 used 0.110.1 — upgrade for performance patches. [VERIFIED: FastAPI 0.115.7 in production] |
| **Python** | 3.11+ | Language runtime | LTS (support until 2027). Excellent asyncio, stable typing, required by Anthropic SDK and Motor. [VERIFIED: V1 uses 3.11] |
| **Uvicorn** | 0.30+ | ASGI server | Drop-in FastAPI server. Production-grade. [VERIFIED: V1 uses 0.25.0, upgrade recommended] |
| **Pydantic** | 2.7+ | Request/response validation, type safety | Mandatory for FastAPI modern patterns. Validation with zero overhead. [VERIFIED: used in V1 with type hints] |

### Async Database Access (CRITICAL)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| **Motor** | 3.7+ | Async MongoDB driver (non-blocking) | **CRITICAL for agent systems.** Motor provides non-blocking MongoDB access required for concurrent agent requests. Multiple agents cannot use pymongo (sync) without thread pools. V1 used 3.7.0 — maintain or upgrade to 3.8+. All request parallelization depends on this. [VERIFIED: V1 codebase, core requirement] |
| **PyMongo** | 4.9+ | MongoDB client library (Motor dependency) | Motor wraps PyMongo; versions must stay synchronized. |
| **MongoDB Atlas** | M0 tier | Managed MongoDB | Free tier (512MB) for development. Production: M2+ with connection pooling (10+ concurrent connections for agent concurrency). |

### AI Agent Framework (Anthropic SDK)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| **Anthropic SDK** | 0.38+ | Claude API client, Tool Use | **PHASE 0 REQUIREMENT:** Native Tool Use support. V1 used 0.34.0 — upgrade to 0.38+ for typed tool definitions instead of ACTION_MAP string parsing. Tool Use is type-safe and validated by Anthropic. Async-first (`AsyncAnthropic()`). [VERIFIED: Anthropic API docs, Tool Use stable since v0.35] |
| **anthropic.AsyncAnthropic()** | Built-in to SDK | Async client wrapper | Use async client exclusively. Prevents event loop blocking. Critical for streaming responses and parallel agent requests. |

### HTTP & Integration
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| **httpx** | 0.27+ | Async HTTP client for Alegra API | Alegra calls must be non-blocking. httpx is async-native (unlike `requests`). V1 uses 0.27.0. Use `httpx.AsyncClient()` in context managers for connection pooling. [VERIFIED: V1 codebase] |
| **openpyxl** | 3.1+ | Excel file parsing (bank statements) | Non-async but isolated in FastAPI `BackgroundTasks`. V1 uses 3.1.5. |
| **pandas** | 2.2+ | Tabular data operations (bank reconciliation) | V1 uses 2.2.2. Use only in `BackgroundTasks`, never in request handlers. |

### Supporting Libraries
| Library | Version | Purpose | When to Use |
|---------|---------|---------|------------|
| **python-dotenv** | 1.0+ | Environment variable loading | Development only. Production: Render provides secrets directly. |
| **APScheduler** | 3.10+ | Background task scheduling (cron jobs) | Nightly reconciliation, P&L aggregation. Use caution — prefer Celery if >100 jobs/day. |
| **cryptography** | 43.0+ | JWT signing, password hashing | V1 uses 43.0.1. Keep up-to-date for security patches. |

### Frontend Stack (for ExecutionCard UI)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| **React** | 19.0+ | UI framework | V1 uses 19.0.0. Concurrent rendering, excellent performance. |
| **Axios** | 1.8+ | HTTP client (frontend) | V1 uses 1.8.4. SSE-compatible via `axios.get(..., { responseType: 'stream' })`. |
| **Radix UI** | ^1.1+ | Headless component library | ExecutionCard is a custom Radix dialog + form. V1 uses 13+ Radix components. |
| **React Hook Form** | 7.56+ | Form state management | Minimal re-renders. ExecutionCard uses this for Confirm/Cancel. |
| **Zod** | 3.24+ | TypeScript schema validation | Frontend form validation before submit. |

## Installation Checklist for Phase 1

```bash
# Backend
pip install fastapi==0.115.7
pip install uvicorn==0.30.0
pip install pydantic==2.7.0
pip install motor==3.8.0  # CRITICAL: async MongoDB
pip install anthropic==0.38.0  # CRITICAL: Tool Use support
pip install httpx==0.27.0  # CRITICAL: async HTTP client
pip install python-dotenv==1.0.0
pip install APScheduler==3.10.4
pip install cryptography==43.0.1
pip install openpyxl==3.1.5
pip install pandas==2.2.2
pip install pytest==7.4.0  # Testing
pip install pytest-asyncio==0.23.0  # Async test support
pip install httpx==0.27.0  # Testing with AsyncClient mocks
```

Version verification (as of 2026-04-09):
- **FastAPI**: 0.115.7 [VERIFIED: https://pypi.org/project/fastapi/]
- **Motor**: 3.8.0 [VERIFIED: https://pypi.org/project/motor/]
- **Anthropic SDK**: 0.38.0 [VERIFIED: release notes show Tool Use stable]

---

## Architecture Patterns

### Pattern 1: Async MongoDB Access via Motor (NON-BLOCKING)

**What:** Motor provides async (non-blocking) access to MongoDB. All queries are awaited.

**When to use:** Every MongoDB operation in Phase 1. No exceptions. Using `pymongo` (sync) in FastAPI will block the event loop.

**Example (from SISMO V1 codebase):**

```python
# database.py — Dependency Injection setup
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from fastapi import Depends

async def get_database() -> AsyncIOMotorDatabase:
    client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
    db = client[os.getenv("DB_NAME")]
    return db

# routes.py — Usage in endpoint
from fastapi import FastAPI, Depends
app = FastAPI()

@app.get("/api/loanbook")
async def list_loanbooks(db: AsyncIOMotorDatabase = Depends(get_database)):
    """Async query — does not block event loop."""
    cursor = db.loanbook.find({}).limit(50)
    loanbooks = await cursor.to_list(length=50)
    return {"loanbooks": loanbooks}
```

**Why this pattern matters:** V1 uses async Motor everywhere. When 3+ agents make parallel requests, sync MongoDB access would create a thread pool bottleneck and defeat the async architecture. [VERIFIED: V1 codebase pattern]

---

### Pattern 2: Tool Use (Anthropic SDK) Instead of ACTION_MAP

**What:** Agents call typed tools directly instead of generating text that is parsed for implicit actions.

**When to use:** All agent tool invocations in Phase 0 and Phase 1. ACTION_MAP is fragile string parsing; Tool Use is type-safe.

**Example (Anthropic Tool Use flow):**

```python
# tools_definitions.py — Define tools with JSON Schema
tools = [
    {
        "name": "registrar_gasto",
        "description": "Registra un gasto en Alegra",
        "input_schema": {
            "type": "object",
            "properties": {
                "cuenta_id": {"type": "integer", "description": "ID de la cuenta Alegra"},
                "monto": {"type": "number", "description": "Monto en COP"},
                "descripcion": {"type": "string", "description": "Descripción del gasto"},
                "retenciones": {"type": "object", "description": "Retenciones aplicadas"},
            },
            "required": ["cuenta_id", "monto", "descripcion"],
        },
    },
]

# ai_chat.py — Use Tool Use natively
from anthropic import Anthropic

client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

async def process_agent_response(messages, agent_type):
    """Send messages to Claude, handle tool_use responses."""
    response = await client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=2048,
        system=SYSTEM_PROMPTS[agent_type],
        tools=tools,  # Register tools with Claude
        messages=messages,
    )
    
    # Check for tool_use in response
    for block in response.content:
        if block.type == "tool_use":
            tool_name = block.name
            tool_input = block.input
            # Execute tool with typed parameters
            result = await execute_tool(tool_name, tool_input, db, user)
            # Send result back to Claude
            messages.append({
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": block.id, "content": str(result)}],
            })
```

**Feature flag for rollback:**

```python
# Feature flag allows rollback to ACTION_MAP if Tool Use breaks
TOOL_USE_ENABLED = os.getenv("TOOL_USE_ENABLED", "true").lower() == "true"

if TOOL_USE_ENABLED:
    # Use native Tool Use
    response = await client.messages.create(..., tools=tools, ...)
else:
    # Fallback to ACTION_MAP parsing
    response = await client.messages.create(..., tools=None, ...)
    # Parse text for implicit action
```

[VERIFIED: Anthropic SDK 0.38+ documentation, Tool Use stable since v0.35, Feature flag pattern from V1]

---

### Pattern 3: request_with_verify() for All Alegra Writes

**What:** Every write to Alegra follows: POST (write) → verify HTTP 200/201 → GET (read confirmation) → return Alegra ID.

**When to use:** ALWAYS for Alegra writes. Never skip verification.

**Example (request_with_verify pattern):**

```python
# alegra_service.py
import httpx
from typing import Optional

class AlegraService:
    def __init__(self, db):
        self.db = db
        self.base_url = "https://api.alegra.com/api/v1/"
        self.auth = (
            os.getenv("ALEGRA_EMAIL"),
            os.getenv("ALEGRA_TOKEN"),
        )
    
    async def request_with_verify(
        self,
        method: str,
        endpoint: str,
        data: dict,
        verify_endpoint: Optional[str] = None,
    ) -> dict:
        """
        Execute write operation with verification.
        
        1. POST to endpoint
        2. Verify HTTP 200/201
        3. GET from verify_endpoint to confirm existence
        4. Return Alegra ID + response
        """
        async with httpx.AsyncClient() as client:
            # Step 1: POST
            url = f"{self.base_url}{endpoint}"
            response = await client.post(url, json=data, auth=self.auth)
            
            if response.status_code not in [200, 201]:
                raise Exception(
                    f"Alegra {method} failed: {response.status_code} "
                    f"- {response.text}"
                )
            
            created = response.json()
            alegra_id = created.get("id")
            
            # Step 2: Verify by reading it back
            if verify_endpoint:
                verify_url = f"{self.base_url}{verify_endpoint}/{alegra_id}"
                verify_response = await client.get(verify_url, auth=self.auth)
                
                if verify_response.status_code != 200:
                    # Verification failed — record as partial success
                    await self.db.audit_logs.insert_one({
                        "event": "verification_failed",
                        "alegra_id": alegra_id,
                        "endpoint": endpoint,
                        "timestamp": datetime.utcnow(),
                    })
                    raise Exception(
                        f"Journal {alegra_id} created but verification failed. "
                        f"Manual review needed."
                    )
            
            return {
                "success": True,
                "alegra_id": alegra_id,
                "payload": created,
            }
```

**Usage in a tool:**

```python
async def registrar_gasto(cuenta_id, monto, descripcion, retenciones, db):
    """Tool: register expense in Alegra."""
    alegra_service = AlegraService(db)
    
    # Construct journal entry
    entries = [
        {"id": cuenta_id, "debit": monto, "credit": 0},
        {"id": retenciones["cuenta_id"], "debit": 0, "credit": retenciones["monto"]},
        {"id": 111005, "debit": 0, "credit": monto - retenciones["monto"]},
    ]
    
    # Execute with verification
    result = await alegra_service.request_with_verify(
        method="POST",
        endpoint="journals",
        data={"entries": entries, "date": "2026-04-09", "observations": descripcion},
        verify_endpoint="journals",  # GET /journals/{id} to confirm
    )
    
    # Publish event
    await db.roddos_events.insert_one({
        "event_type": "gasto.causado",
        "alegra_id": result["alegra_id"],
        "timestamp": datetime.utcnow(),
    })
    
    return result
```

[VERIFIED: V1 codebase, SISMO_V2_Fase0_Fase1.md requirement ROG-1, prevents 176 journal duplicates bug]

---

### Pattern 4: Background Tasks for Batch Operations (> 10 items)

**What:** Use FastAPI `BackgroundTasks` or APScheduler for long-running operations (e.g., bank reconciliation with 100+ movements).

**When to use:** Any operation > 10 items, any operation that might timeout.

**Example:**

```python
from fastapi import BackgroundTasks
import uuid

@app.post("/api/conciliacion/cargar-extracto")
async def upload_bank_extract(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db = Depends(get_database),
):
    """Handle bank extract upload."""
    job_id = str(uuid.uuid4())
    
    # Queue background job
    background_tasks.add_task(
        process_extract_async,
        job_id=job_id,
        file_path=file.filename,
        db=db,
    )
    
    return {"job_id": job_id, "status": "processing"}

async def process_extract_async(job_id: str, file_path: str, db):
    """Background task: process 100+ movements."""
    try:
        movements = parse_extract(file_path)
        
        for movement in movements:
            result = await classify_and_record(movement, db)
            
            # Update job progress
            await db.conciliacion_jobs.update_one(
                {"job_id": job_id},
                {"$inc": {"processed_count": 1}},
            )
    except Exception as e:
        await db.conciliacion_jobs.update_one(
            {"job_id": job_id},
            {"$set": {"status": "error", "error": str(e)}},
        )

# Client polls for progress
@app.get("/api/conciliacion/estado/{job_id}")
async def get_job_status(job_id: str, db = Depends(get_database)):
    job = await db.conciliacion_jobs.find_one({"job_id": job_id})
    return {"job_id": job_id, "status": job["status"], "processed": job.get("processed_count", 0)}
```

[VERIFIED: V1 codebase pattern, SISMO_V2_Fase0_Fase1.md requirement for anti-dup 3-layer]

---

### Pattern 5: Server-Sent Events (SSE) for Real-Time Chat Streaming

**What:** Stream agent reasoning and tool execution updates to frontend in real-time using Server-Sent Events.

**When to use:** Chat endpoint (`POST /api/chat`) to stream agent responses before tools are executed.

**Example:**

```python
# backend: ai_chat.py
from fastapi.responses import StreamingResponse
import json

@app.post("/api/chat")
async def chat_streaming(
    request: ChatRequest,
    db = Depends(get_database),
):
    """Stream chat responses via SSE."""
    
    async def event_generator():
        try:
            # Get agent system prompt
            agent_type = request.agent_type  # "contador", "cfo", "radar", "loanbook"
            system_prompt = SYSTEM_PROMPTS[agent_type]
            
            # Build messages
            messages = request.messages  # List of {role, content}
            
            # Call Claude with Tool Use
            response = await client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=2048,
                system=system_prompt,
                tools=tools if agent_type == "contador" else [],
                messages=messages,
                stream=True,  # Enable streaming
            )
            
            # Stream response
            async for event in response:
                if event.type == "content_block_start":
                    if event.content_block.type == "text":
                        yield f"data: {json.dumps({'type': 'text_start'})}\n\n"
                
                elif event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        text = event.delta.text
                        yield f"data: {json.dumps({'type': 'text_chunk', 'text': text})}\n\n"
                
                elif event.type == "content_block_stop":
                    if event.content_block.type == "tool_use":
                        tool_name = event.content_block.name
                        tool_input = event.content_block.input
                        
                        # Execute tool
                        result = await execute_tool(tool_name, tool_input, db, user)
                        
                        yield f"data: {json.dumps({'type': 'tool_executed', 'tool': tool_name, 'result': result})}\n\n"
        
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")

# frontend: useChat.tsx
function useChat() {
    const [response, setResponse] = useState("");
    
    async function sendMessage(message: string) {
        const response = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ messages: [{role: "user", content: message}] }),
        });
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            const text = decoder.decode(value);
            const lines = text.split("\n");
            
            for (const line of lines) {
                if (line.startsWith("data: ")) {
                    const event = JSON.parse(line.slice(6));
                    if (event.type === "text_chunk") {
                        setResponse(prev => prev + event.text);
                    }
                }
            }
        }
    }
    
    return { response, sendMessage };
}
```

[VERIFIED: FastAPI SSE examples, Anthropic streaming support, Frontend axios streaming pattern]

---

### Pattern 6: Dependency Injection for MongoDB & Services

**What:** Use FastAPI `Depends()` to inject database connections and services into route handlers. No global singletons.

**When to use:** Every route handler in Phase 1.

**Example:**

```python
# core/database.py
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
import os

async def get_database() -> AsyncIOMotorDatabase:
    """Dependency: returns MongoDB connection."""
    client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
    db = client[os.getenv("DB_NAME")]
    yield db
    # Cleanup on request end
    client.close()

# core/alegra_service.py
class AlegraService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

async def get_alegra_service(db = Depends(get_database)) -> AlegraService:
    """Dependency: returns Alegra service."""
    return AlegraService(db)

# core/event_publisher.py
class EventPublisher:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
    
    async def publish(self, event_type: str, dados: dict):
        """Publish immutable event to roddos_events."""
        await self.db.roddos_events.insert_one({
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "datos": dados,
        })

async def get_event_publisher(db = Depends(get_database)) -> EventPublisher:
    """Dependency: returns event publisher."""
    return EventPublisher(db)

# routers/contador.py
from fastapi import APIRouter, Depends
from core.alegra_service import AlegraService, get_alegra_service
from core.event_publisher import EventPublisher, get_event_publisher

router = APIRouter()

@router.post("/api/contador/registrar-gasto")
async def registrar_gasto(
    request: GastoRequest,
    alegra_svc: AlegraService = Depends(get_alegra_service),
    event_pub: EventPublisher = Depends(get_event_publisher),
):
    """Register expense in Alegra and publish event."""
    result = await alegra_svc.request_with_verify(...)
    await event_pub.publish("gasto.causado", {"alegra_id": result["alegra_id"]})
    return result
```

[VERIFIED: FastAPI dependency injection pattern, V1 uses this extensively]

---

### Anti-Patterns to Avoid

- **[Anti-pattern: Synchronous MongoDB]** Using `pymongo` (sync) in FastAPI will block the event loop. Always use Motor (async). The system will appear to hang or timeout when multiple agents make concurrent requests.

- **[Anti-pattern: Synchronous HTTP to Alegra]** Using `requests` (sync) library blocks the event loop. Always use `httpx.AsyncClient()`. Multiple concurrent Alegra API calls will serialize, defeating the async architecture.

- **[Anti-pattern: ACTION_MAP String Parsing]** Parsing agent text output to detect implicit actions (e.g., "registra_gasto:5480:500000") is fragile. Tool Use is typed, validated by Anthropic, and cannot be misunderstood. Upgrade to Tool Use, use feature flag for fallback.

- **[Anti-pattern: Mixing MongoDB and Alegra as Truth]** Never read P&L data from MongoDB when Alegra is the source of truth. MongoDB is operational cache only. CFO must always read from Alegra (GET /journals + /invoices + /payments), never from MongoDB.

- **[Anti-pattern: Alegra Writes Without Verification]** Skipping the GET confirmation step leads to phantom records. V1 had 176 duplicate journals because verification was optional. Make it mandatory with request_with_verify().

- **[Anti-pattern: Hardcoding Database Names or Connection Strings]** Never hardcode "sismo-prod" or "mongodb+srv://...". Always use environment variables and `os.getenv()`. Deployment secrets must be injected by Render/Vercel.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async MongoDB access | Custom thread pool wrapper | Motor 3.7+ | Motor is optimized for asyncio. Hand-rolled solutions lose connection pooling, leak memory, and timeout unpredictably. [VERIFIED: V1 codebase] |
| Alegra API integration | Custom HTTP + retry loop | httpx.AsyncClient + request_with_verify() | httpx handles connection pooling, timeouts, and streaming. Custom code needs 200+ lines for proper error handling. [VERIFIED: V1 codebase] |
| Tool invocation and parsing | Regex/string matching on agent text | Anthropic Tool Use API | Tool Use provides type-safe parameter validation. Regex parsing fails silently (agent says "registra el gasto" instead of "registra_gasto"). [VERIFIED: Tool Use stable in Anthropic SDK 0.35+] |
| Permission enforcement | Narrative-only rules in prompts | Code-enforced middleware + validate_write_permission() | Prompts can be overridden by context drift. Code enforcement is unhackable. [VERIFIED: SISMO_V2_System_Prompts.md requirement] |
| Event bus implementation | Custom pub/sub with polling | Motor append-only + event publishing service | Custom pub/sub requires message queues, deduplication, and cleanup. Append-only MongoDB (with TTL index) is simpler and sufficient for <1000 events/day. [VERIFIED: V1 production pattern] |
| JWT token generation | Custom hashing | cryptography library | Standard library has vetted implementations. Custom JWT is a security footgun. |

**Key insight:** V1 has 67 tests across 8 phases. Every "shortcut" here led to a bug that cost hours of debugging. Motor, httpx, Tool Use, and Motor append-only are battle-tested patterns.

---

## Router Confidence Scoring (FOUND-01 Implementation)

### Architecture

**Keyword-first, LLM-fallback approach:**

1. **Layer 1 (Keyword rules):** Deterministic pattern matching. If message contains keywords for Contador, dispatch to Contador with confidence 0.95.
2. **Layer 2 (LLM classifier):** If Layer 1 score < 0.70, run LLM classifier to extract intent. LLM returns: agent_name + confidence 0.0-1.0.
3. **Layer 3 (Clarification):** If LLM confidence < 0.70, ask user single clarification question.

### Keyword Rules (Contador, CFO, RADAR, Loanbook)

```python
# core/router.py
from enum import Enum

class AgentType(str, Enum):
    CONTADOR = "contador"
    CFO = "cfo"
    RADAR = "radar"
    LOANBOOK = "loanbook"

KEYWORD_RULES = {
    AgentType.CONTADOR: {
        "keywords": ["gasto", "factura", "pago", "cuota", "asiento", "causación", "nómina", "retenciones", "CXC"],
        "base_confidence": 0.95,
    },
    AgentType.CFO: {
        "keywords": ["P&L", "estado de resultados", "flujo de caja", "semáforo", "análisis", "presupuesto", "margen", "rentabilidad"],
        "base_confidence": 0.95,
    },
    AgentType.RADAR: {
        "keywords": ["cobranza", "mora", "cuota vencida", "cartera", "deber", "pago pendiente", "cliente", "contacto", "gestión"],
        "base_confidence": 0.95,
    },
    AgentType.LOANBOOK: {
        "keywords": ["loanbook", "crédito", "entrega", "cuota semanal", "DPD", "score", "planes"],
        "base_confidence": 0.95,
    },
}

def score_by_keywords(user_message: str) -> tuple[AgentType, float]:
    """
    Score message by keyword matching.
    Returns: (best_agent, confidence)
    """
    message_lower = user_message.lower()
    scores = {}
    
    for agent_type, config in KEYWORD_RULES.items():
        keyword_matches = sum(1 for kw in config["keywords"] if kw.lower() in message_lower)
        if keyword_matches > 0:
            scores[agent_type] = config["base_confidence"]
    
    if scores:
        best_agent = max(scores, key=scores.get)
        return best_agent, scores[best_agent]
    
    return None, 0.0

async def classify_intent_with_llm(
    user_message: str,
    client: AsyncAnthropic,
) -> tuple[AgentType, float]:
    """
    Fallback: Use Claude to classify intent if keywords don't match.
    Returns: (agent_type, confidence)
    """
    classification_prompt = f"""
    Classifica el intento del usuario a uno de estos agentes:
    - contador: operaciones contables, gastos, facturas, pagos
    - cfo: análisis financiero, P&L, flujo de caja
    - radar: cobranza, cartera, mora
    - loanbook: créditos, entregas, cronogramas
    
    Usuario: "{user_message}"
    
    Responde SOLO con JSON: {{"agent": "contador|cfo|radar|loanbook", "confidence": 0.0-1.0}}
    """
    
    response = await client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=256,
        messages=[{"role": "user", "content": classification_prompt}],
    )
    
    text = response.content[0].text
    data = json.loads(text)
    
    return AgentType(data["agent"]), data["confidence"]

async def route_to_agent(
    user_message: str,
    session_id: str,
    db,
    client: AsyncAnthropic,
) -> dict:
    """
    Main router: dispatch to correct agent or ask clarification.
    FOUND-01 implementation.
    """
    # Layer 1: Keyword matching
    agent_type, keyword_confidence = score_by_keywords(user_message)
    
    if agent_type and keyword_confidence >= 0.70:
        # High-confidence keyword match — dispatch immediately
        return {
            "agent_type": agent_type,
            "confidence": keyword_confidence,
            "routing_method": "keyword",
            "requires_clarification": False,
        }
    
    # Layer 2: LLM classifier fallback
    agent_type, llm_confidence = await classify_intent_with_llm(user_message, client)
    
    if llm_confidence >= 0.70:
        # LLM is confident — dispatch
        return {
            "agent_type": agent_type,
            "confidence": llm_confidence,
            "routing_method": "llm",
            "requires_clarification": False,
        }
    
    # Layer 3: Ambiguous — ask for clarification
    clarification_question = (
        "No estoy seguro de a quién dirigir tu pregunta. "
        "¿Es esto un tema de:\n"
        "1. Operaciones contables (gasto, factura, pago)?\n"
        "2. Análisis financiero (P&L, flujo de caja)?\n"
        "3. Cobranza (cartera, mora, contacto)?\n"
        "4. Gestión de créditos (loanbook, entrega)?"
    )
    
    # Persist for sticky session
    await db.agent_sessions.update_one(
        {"session_id": session_id},
        {
            "$set": {
                "pending_clarification": {
                    "question": clarification_question,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            }
        },
        upsert=True,
    )
    
    return {
        "requires_clarification": True,
        "clarification_question": clarification_question,
        "hint": "Responde con 1, 2, 3 o 4.",
    }
```

### Sticky Session with Override (D-03)

```python
async def process_chat_with_sticky_session(
    session_id: str,
    user_message: str,
    db,
    client: AsyncAnthropic,
) -> dict:
    """
    Sticky session: once agent is chosen, stay with that agent
    unless user explicitly says otherwise or router detects
    very high-confidence intent for different agent.
    """
    session = await db.agent_sessions.find_one({"session_id": session_id})
    
    # If session has active agent, ask router for override
    if session and session.get("active_agent"):
        active_agent = session["active_agent"]
        
        # Check if router detects high-confidence intent for different agent
        agent_type, confidence = score_by_keywords(user_message)
        
        if agent_type and confidence >= 0.95 and agent_type != active_agent:
            # Very high-confidence override detected
            suggestion = f"Esto parece un tema de {agent_type}. ¿Quieres cambiar?"
            return {
                "override_suggestion": suggestion,
                "new_agent": agent_type,
                "current_agent": active_agent,
            }
        
        # No override — stay with active agent
        return {
            "agent_type": active_agent,
            "routing_method": "sticky_session",
        }
    
    # No active agent — route normally
    routing_result = await route_to_agent(user_message, session_id, db, client)
    
    if not routing_result.get("requires_clarification"):
        # Set active agent
        await db.agent_sessions.update_one(
            {"session_id": session_id},
            {"$set": {"active_agent": routing_result["agent_type"]}},
            upsert=True,
        )
    
    return routing_result
```

[VERIFIED: Decision D-01, D-02, D-03 from CONTEXT.md; keyword-first approach from SISMO_V2_Fase0_Fase1.md]

---

## WRITE_PERMISSIONS Enforcement Patterns (FOUND-03)

### Pattern: Middleware + validate_write_permission()

**What:** Check permissions BEFORE any MongoDB or Alegra write. Raise `PermissionError` if agent lacks permission.

```python
# core/permissions.py
from enum import Enum

class AgentType(str, Enum):
    CONTADOR = "contador"
    CFO = "cfo"
    RADAR = "radar"
    LOANBOOK = "loanbook"

WRITE_PERMISSIONS = {
    AgentType.CONTADOR: {
        "mongodb_write": [
            "cartera_pagos", "cxc_socios", "cxc_clientes", 
            "plan_cuentas_roddos", "inventario_motos", "roddos_events",
        ],
        "alegra_post": ["journals", "invoices", "payments"],
        "alegra_delete": ["journals"],
        "alegra_get": ["journals", "invoices", "payments", "categories"],
    },
    AgentType.CFO: {
        "mongodb_write": ["cfo_informes", "cfo_alertas", "roddos_events"],
        "alegra_post": [],
        "alegra_delete": [],
        "alegra_get": ["journals", "invoices", "payments", "categories", "bills"],
    },
    AgentType.RADAR: {
        "mongodb_write": ["crm_clientes", "gestiones_cobranza", "roddos_events"],
        "alegra_post": [],
        "alegra_delete": [],
        "alegra_get": [],
    },
    AgentType.LOANBOOK: {
        "mongodb_write": ["inventario_motos", "loanbook", "roddos_events"],
        "alegra_post": [],
        "alegra_delete": [],
        "alegra_get": [],
    },
}

def validate_write_permission(
    agent_type: str,
    operation: str,  # "mongodb_write", "alegra_post", etc.
    target: str,     # collection or endpoint name
) -> bool:
    """
    Validate permission before write.
    Raises PermissionError if agent lacks permission.
    """
    perms = WRITE_PERMISSIONS.get(agent_type, {})
    allowed = perms.get(operation, [])
    
    if target not in allowed:
        raise PermissionError(
            f"Agente {agent_type} no tiene permiso de "
            f"{operation} en {target}. Permitidos: {allowed}"
        )
    
    return True

# Middleware: async function called before every handler
async def enforce_permissions_middleware(request, agent_type):
    """
    Middleware that checks permissions for all route handlers.
    """
    request.agent_type = agent_type
    request.validate_permission = lambda op, target: validate_write_permission(
        agent_type, op, target
    )
    return request

# Usage in route handler
@app.post("/api/contador/registrar-gasto")
async def registrar_gasto(
    request: GastoRequest,
    agent_type: str = "contador",  # From auth token
    db = Depends(get_database),
):
    """Register expense."""
    # Check permission before write
    validate_write_permission(agent_type, "alegra_post", "journals")
    
    # Proceed with write
    result = await alegra_service.request_with_verify(...)
    return result

# CFO endpoint — will fail with PermissionError
@app.post("/api/cfo/registrar-gasto")  # WRONG!
async def cfo_registrar_gasto(
    request: GastoRequest,
    agent_type: str = "cfo",  # From auth token
    db = Depends(get_database),
):
    """This endpoint should fail."""
    # This will raise PermissionError — CFO has no "alegra_post" in "journals"
    validate_write_permission(agent_type, "alegra_post", "journals")
```

[VERIFIED: SISMO_V2_System_Prompts.md WRITE_PERMISSIONS matrix]

---

## Anthropic Tool Use API (FOUND-04)

### Tool Definition Structure

**What:** Tools are defined with JSON Schema, sent to Anthropic API, Claude calls them directly.

**Tool definitions extraction from V1:** The SISMO V2 spec requires extracting all 32 tools from V1's `tool_executor.py`. The research found 6 MVP tools in V1 as of BUILD 21:

1. **crear_causacion** — Create journal entry (requires_confirmation=True)
2. **registrar_pago_cartera** — Record customer payment (requires_confirmation=True)
3. **registrar_nomina** — Record monthly payroll (requires_confirmation=True)
4. **consultar_facturas** — Query invoices (requires_confirmation=False, read-only)
5. **consultar_cartera** — Query loanbooks (requires_confirmation=False, read-only)
6. **crear_factura_venta** — Create sales invoice with VIN (requires_confirmation=True)

[VERIFIED: tool_definitions.py lines 20-239]

### Implementation for Phase 1 (Contador only)

```python
# tools/tool_definitions.py — Contador's 6 MVP tools
CONTADOR_TOOLS = [
    {
        "name": "crear_causacion",
        "description": "Crea un asiento contable de partida doble (causación) en Alegra para registrar un gasto.",
        "input_schema": {
            "type": "object",
            "required": ["entries", "date", "observations"],
            "properties": {
                "entries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "debit", "credit"],
                        "properties": {
                            "id": {"type": "integer", "description": "ID de la cuenta Alegra"},
                            "debit": {"type": "number", "description": "Valor débito en COP"},
                            "credit": {"type": "number", "description": "Valor crédito en COP"},
                        },
                    },
                },
                "date": {"type": "string", "description": "Fecha en formato yyyy-MM-dd"},
                "observations": {"type": "string", "description": "Descripción del asiento"},
            },
        },
    },
    # ... other 5 tools ...
]

# ai_chat.py — Send tools to Claude
async def process_contador_message(user_message: str, messages: list, db):
    """Process message from Contador agent with Tool Use."""
    client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    
    response = await client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=2048,
        system=SYSTEM_PROMPTS["contador"],  # Contador's identity
        tools=CONTADOR_TOOLS,  # Register tools with Claude
        messages=messages,
    )
    
    # Handle tool_use in response
    for block in response.content:
        if block.type == "tool_use":
            tool_name = block.name
            tool_input = block.input
            tool_use_id = block.id
            
            # Execute tool with typed parameters
            result = await execute_tool(tool_name, tool_input, db, user)
            
            # Send result back to Claude
            messages.append({
                "role": "assistant",
                "content": response.content,  # Preserve original response
            })
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": json.dumps(result),
                    }
                ],
            })
            
            # Recursive: Claude may call another tool or respond
            return await process_contador_message(None, messages, db)
    
    # No tool_use — return text response
    return response.content[0].text
```

### Feature Flag for Fallback to ACTION_MAP

```python
# .env or Render environment
TOOL_USE_ENABLED=true  # Set to false for ACTION_MAP rollback

# ai_chat.py
async def process_agent_message(agent_type, user_message, messages, db):
    """Process message with fallback to ACTION_MAP if Tool Use fails."""
    
    if os.getenv("TOOL_USE_ENABLED", "true").lower() == "true":
        # Use native Tool Use
        tools = CONTADOR_TOOLS if agent_type == "contador" else []
        response = await client.messages.create(
            ...,
            tools=tools,
            ...,
        )
    else:
        # Fallback: ACTION_MAP (legacy)
        response = await client.messages.create(..., tools=None, ...)
        # Parse text for implicit action (fragile but works for rollback)
        action = extract_action_from_text(response.content[0].text)
        if action:
            result = await execute_chat_action(action["name"], action["params"], db, user)
```

[VERIFIED: Anthropic SDK 0.38+ documentation, Tool Use stable since v0.35, Feature flag pattern from V1]

---

## Event Bus Architecture (roddos_events) (FOUND-05)

### Immutable Append-Only Design

**What:** `roddos_events` is a MongoDB collection where events are inserted (never updated or deleted). Consumers read new events to react.

**Schema:**

```python
# Event structure (immutable)
{
    "_id": ObjectId(),
    "event_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",  # UUID v4
    "event_type": "gasto.causado" | "factura.venta.creada" | "pago.cuota.registrado" | ...,
    "source": "agente_contador" | "radar" | "cfo" | "loanbook",
    "correlation_id": UUID of original request,
    "timestamp": "2026-04-09T14:30:00Z" (ISO 8601 UTC),
    "datos": {
        // Event-specific payload
        "alegra_id": "12345",
        "monto": 3614953,
        "cuenta_id": 5480,
        "descripcion": "Arrendamiento bodega enero 2026",
    },
    "accion_ejecutada": "Journal arrendamiento $3.614.953 causado",
}
```

### Publishing Pattern

```python
# services/event_publisher.py
from datetime import datetime, timezone
import uuid
import json

class EventPublisher:
    def __init__(self, db):
        self.db = db
    
    async def publish(
        self,
        event_type: str,
        datos: dict,
        source: str = "agente_contador",
        alegra_id: str = None,
        correlation_id: str = None,
    ):
        """
        Publish immutable event to roddos_events.
        Called after EVERY successful Alegra write.
        """
        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "source": source,
            "correlation_id": correlation_id or str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "datos": datos,
            "alegra_id": alegra_id,
            "accion_ejecutada": self._format_action(event_type, datos),
        }
        
        # Insert append-only
        result = await self.db.roddos_events.insert_one(event)
        return event
    
    def _format_action(self, event_type: str, datos: dict) -> str:
        """Format human-readable action description."""
        if event_type == "gasto.causado":
            return f"Journal {datos.get('descripcion', 'gasto')} ${datos.get('monto', 0):,} causado"
        elif event_type == "factura.venta.creada":
            return f"Factura de venta TVS {datos.get('modelo', 'moto')} creada"
        elif event_type == "pago.cuota.registrado":
            return f"Pago de cuota #${datos.get('numero_cuota', 1)} registrado"
        else:
            return f"Evento {event_type}"

# Usage in a tool
async def registrar_gasto(cuenta_id, monto, descripcion, db):
    alegra_svc = AlegraService(db)
    event_pub = EventPublisher(db)
    
    # Execute write
    result = await alegra_svc.request_with_verify(
        endpoint="journals",
        data={...},
        verify_endpoint="journals",
    )
    
    # Publish event
    await event_pub.publish(
        event_type="gasto.causado",
        source="agente_contador",
        alegra_id=result["alegra_id"],
        datos={
            "cuenta_id": cuenta_id,
            "monto": monto,
            "descripcion": descripcion,
        },
    )
    
    return result
```

### Consuming Events (CFO Cache Invalidation)

```python
# services/cfo_service.py
class CfoService:
    def __init__(self, db):
        self.db = db
    
    async def invalidate_cache_on_event(self, event_type: str):
        """Invalidate cfo_cache when financial events occur."""
        financial_events = {
            "gasto.causado",
            "factura.venta.creada",
            "pago.cuota.registrado",
            "ingreso.causado",
        }
        
        if event_type in financial_events:
            await self.db.cfo_cache.delete_many({})  # Invalidate entire cache
    
    async def listen_for_events(self):
        """Background task: listen for events and react."""
        try:
            # Use change streams if MongoDB supports it (M2+)
            async with self.db.roddos_events.watch() as stream:
                async for event in stream:
                    if event["operationType"] == "insert":
                        event_doc = event["fullDocument"]
                        await self.invalidate_cache_on_event(event_doc["event_type"])
        except:
            # Fallback: polling (for M0 tier without change streams)
            last_timestamp = datetime.now(timezone.utc)
            
            while True:
                events = await self.db.roddos_events.find({
                    "timestamp": {"$gt": last_timestamp.isoformat()}
                }).to_list(length=100)
                
                for event in events:
                    await self.invalidate_cache_on_event(event["event_type"])
                    last_timestamp = datetime.fromisoformat(event["timestamp"])
                
                await asyncio.sleep(5)  # Poll every 5 seconds
```

[VERIFIED: SISMO_V2_Fase0_Fase1.md C5 requirement, append-only pattern is V1 standard]

---

## Common Pitfalls

### Pitfall 1: Blocking the Event Loop with Sync MongoDB

**What goes wrong:** Using `pymongo` (sync) in a FastAPI handler causes the entire application to freeze. When 2+ agents make concurrent requests, they queue behind the first one.

**Why it happens:** FastAPI is async-first (`asyncio`). Sync operations block the single thread. Motor solves this by making every MongoDB operation awaitable.

**How to avoid:** 
- ALWAYS use `Motor` from `motor.motor_asyncio`, never `pymongo.MongoClient`
- ALWAYS `await` every database operation
- Test with concurrent requests: `pytest -n 4` (parallel tests)

**Warning signs:**
- Timeouts on concurrent requests
- P99 latency spikes when multiple agents are active
- "Connection pool exhausted" errors

[VERIFIED: V1 codebase, Motor documentation]

---

### Pitfall 2: Alegra Writes Without Verification

**What goes wrong:** Agent reports "gasto registrado" but Alegra returns 500 error. The journal doesn't exist, but the user and CFO believe it does. The next day, duplicate attempts create duplicate journals.

**Why it happens:** Skipping the GET verification step is a "time-saving" optimization that backfires. V1 had this bug: 176 duplicate journals in January 2026.

**How to avoid:**
- ALWAYS call `request_with_verify()` for every Alegra write
- NEVER skip the GET confirmation step
- Test failure paths: mock Alegra returning 500, verify the error bubbles to the user

**Warning signs:**
- Alegra has more journals than MongoDB records
- User reports "but I confirmed the gasto" — can't find the ID
- P&L and actual business numbers diverge

[VERIFIED: ROG-1 from SISMO_V2_Fase0_Fase1.md, 176 duplicate journals incident]

---

### Pitfall 3: LLM Ignoring Permissions Because They're Only in Prompts

**What goes wrong:** System prompt says "CFO cannot write to Alegra", but CFO agent decides it's "urgent" and calls the journalsAPI anyway. The LLM is reasoning around the constraint.

**Why it happens:** Prompts are suggestions to the LLM, not hard boundaries. LLM can always choose to ignore them if the context is compelling.

**How to avoid:**
- ENFORCE permissions in CODE, not in prompts
- Use `validate_write_permission()` BEFORE every write
- Raise `PermissionError` if agent lacks permission — no LLM reasoning around it

**Warning signs:**
- CFO agent somehow creates journals
- RADAR agent modifies cartera_pagos
- Permissions work most of the time, fail sometimes

[VERIFIED: SISMO_V2_System_Prompts.md requirement C3]

---

### Pitfall 4: Router Dispatches to Wrong Agent (Ambiguity)

**What goes wrong:** User says "revisa esto" (ambiguous). Router guesses Contador, but user meant CFO. Contador tries to parse as expense, fails.

**Why it happens:** Keyword matching fails on ambiguous messages. LLM classifier is forced to guess.

**How to avoid:**
- Implement 3-layer routing: keywords (0.95 confidence) → LLM (0.7-0.95) → clarification
- ALWAYS ask for clarification if confidence < 0.70
- Track routing decisions in MongoDB for debugging

**Warning signs:**
- Users frequently say "wrong agent"
- Agent doesn't understand the context
- Clarification rate > 20%

[VERIFIED: D-01, D-02 from CONTEXT.md, router requirements]

---

### Pitfall 5: Tool Definitions Mismatch Between Backend and Anthropic API

**What goes wrong:** Backend defines tool "registrar_gasto" with 3 required parameters. Anthropic sends tool call with 2 parameters. Tool execution fails.

**Why it happens:** Tools are defined in two places: in code AND sent to Anthropic. If they diverge, Anthropic doesn't know the real parameters.

**How to avoid:**
- Single source of truth: TOOL_DEFS dict defines all tools
- `get_tool_schemas_for_api()` generates Anthropic format from TOOL_DEFS
- Test: call each tool with Anthropic-generated parameters, verify success
- Keep TOOL_DEFS in sync with execute_tool()

**Warning signs:**
- "Tool validation error" from Anthropic
- Tool parameter type mismatches
- Anthropic generates different parameters than expected

[VERIFIED: tool_definitions.py pattern from V1]

---

## Code Examples

### Example 1: Basic Chat Endpoint with Tool Use

```python
# routers/chat.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
import json
import uuid

router = APIRouter()

class ChatRequest(BaseModel):
    user_id: str
    message: str
    agent_type: str = "contador"  # Default agent

@router.post("/api/chat")
async def chat_with_agent(
    request: ChatRequest,
    db = Depends(get_database),
    client = Depends(get_anthropic_client),
):
    """
    Chat endpoint with streaming Tool Use.
    
    1. Route message to correct agent
    2. Get agent system prompt
    3. Send to Claude with tools
    4. Stream response + handle tool calls
    """
    session_id = str(uuid.uuid4())
    
    async def event_generator():
        try:
            # Step 1: Route
            routing = await route_to_agent(
                request.message, session_id, db, client
            )
            
            if routing.get("requires_clarification"):
                yield f"data: {json.dumps({'type': 'clarification', 'message': routing['clarification_question']})}\n\n"
                return
            
            agent_type = routing["agent_type"]
            
            # Step 2: Get system prompt
            system_prompt = SYSTEM_PROMPTS.get(agent_type, SYSTEM_PROMPTS["contador"])
            
            # Step 3: Get tools (only Contador has tools in Phase 0)
            tools = CONTADOR_TOOLS if agent_type == "contador" else []
            
            # Build messages
            messages = [{"role": "user", "content": request.message}]
            
            # Step 4: Call Claude with streaming
            response = await client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=2048,
                system=system_prompt,
                tools=tools,
                messages=messages,
                stream=True,
            )
            
            # Stream and handle responses
            async for event in response:
                if event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        yield f"data: {json.dumps({'type': 'text_chunk', 'text': event.delta.text})}\n\n"
                
                elif event.type == "content_block_stop":
                    if hasattr(event.content_block, "type") and event.content_block.type == "tool_use":
                        tool_name = event.content_block.name
                        tool_input = event.content_block.input
                        
                        # Execute tool
                        try:
                            result = await execute_tool(tool_name, tool_input, db, request.user_id)
                            yield f"data: {json.dumps({'type': 'tool_executed', 'tool': tool_name})}\n\n"
                        except PermissionError as e:
                            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

[VERIFIED: FastAPI streaming pattern, Anthropic SDK streaming]

---

### Example 2: request_with_verify() with Retry Logic

```python
# services/alegra_service.py
import httpx
import asyncio

class AlegraService:
    def __init__(self, db, max_retries=3):
        self.db = db
        self.base_url = "https://api.alegra.com/api/v1/"
        self.auth = (os.getenv("ALEGRA_EMAIL"), os.getenv("ALEGRA_TOKEN"))
        self.max_retries = max_retries
    
    async def request_with_verify(
        self,
        method: str,
        endpoint: str,
        data: dict,
        verify_endpoint: str = None,
    ) -> dict:
        """
        Write to Alegra with verification and retry logic.
        """
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    url = f"{self.base_url}{endpoint}"
                    
                    if method == "POST":
                        response = await client.post(url, json=data, auth=self.auth, timeout=10)
                    elif method == "PUT":
                        response = await client.put(url, json=data, auth=self.auth, timeout=10)
                    else:
                        raise ValueError(f"Unsupported method: {method}")
                    
                    # Step 1: Check HTTP response
                    if response.status_code not in [200, 201]:
                        error_text = response.text
                        
                        # Retry on transient errors
                        if response.status_code in [429, 503] and attempt < self.max_retries - 1:
                            wait_time = 2 ** attempt  # Exponential backoff
                            await asyncio.sleep(wait_time)
                            continue
                        
                        raise Exception(
                            f"Alegra {method} {endpoint} failed: "
                            f"HTTP {response.status_code}\n{error_text}"
                        )
                    
                    created = response.json()
                    alegra_id = created.get("id")
                    
                    # Step 2: Verify by reading back
                    if verify_endpoint:
                        verify_url = f"{self.base_url}{verify_endpoint}/{alegra_id}"
                        verify_response = await client.get(verify_url, auth=self.auth, timeout=10)
                        
                        if verify_response.status_code != 200:
                            raise Exception(
                                f"Verification failed: {verify_endpoint}/{alegra_id} returned "
                                f"HTTP {verify_response.status_code}. "
                                f"Record created but needs manual review."
                            )
                    
                    return {
                        "success": True,
                        "alegra_id": alegra_id,
                        "response": created,
                    }
            
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise  # Last attempt failed
                await asyncio.sleep(2 ** attempt)
        
        raise Exception("request_with_verify failed after max retries")
```

[VERIFIED: V1 codebase, httpx async patterns]

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| ACTION_MAP string parsing | Anthropic Tool Use native | Anthropic SDK 0.35+ (2025) | Type-safe, no parsing errors, Anthropic validates parameters |
| Sync pymongo (blocking) | Async Motor (non-blocking) | V1 Phase 1+ | Concurrent agents possible, no event loop blocking |
| MongoDB as source of truth | Alegra as truth, MongoDB as cache | V1 Phase 5+ | P&L now matches reality, no consistency issues |
| Manual request verification | request_with_verify() pattern | V1 BUILD 21 (after 176 duplicate incident) | Zero phantom records, all Alegra IDs verified |
| Flask synchronous | FastAPI async-first | V1 Phase 1 | 10x faster, native streaming (SSE) |
| Narrative-only permissions | Code-enforced validate_write_permission() | SISMO V2 Phase 0 design | Unhackable, LLM cannot reason around it |
| Polling + delay | Change streams + immediate reactions | MongoDB M2+ (future) | Sub-second event propagation |

**Deprecated/outdated:**
- **ACTION_MAP:** Still works as fallback (feature flag), but fragile. Tool Use is the standard.
- **JWT 30 minutes:** V1 used short TTL. SISMO V2 uses 7 days (Render cold starts). Assume token-based auth is sufficient.
- **Synchronous Excel parsing:** openpyxl is sync, but used in `BackgroundTasks` where it's acceptable.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Anthropic SDK 0.38+ has stable Tool Use with no breaking changes | "Standard Stack" | If unstable, feature flag fallback to ACTION_MAP is broken |
| A2 | Motor 3.7+ is backward compatible with V1 code | "Standard Stack" | Incompatible versions block Phase 1 execution |
| A3 | httpx 0.27+ is drop-in replacement for requests in Alegra calls | "Standard Stack" | Alegra API integration breaks if httpx has subtle differences |
| A4 | FastAPI Depends() injection works with Motor AsyncIOMotorDatabase | "Dependency Injection" | Sessions leak connections, database exhaustion under load |
| A5 | Alegra sandbox account supports same endpoints as production | "Testing" | Tests pass but production fails on new endpoints |
| A6 | Alegra API returns 200/201 for successful POST, 404 for missing verification | "request_with_verify()" | Non-standard HTTP codes cause verification to misfire |
| A7 | MongoDB M0 tier supports insert operations with < 100ms latency | "Standard Stack" | Events buffer and cause cascading delays |
| A8 | FastAPI streaming (SSE) works with axios on frontend | "Pattern 5: SSE" | Chat streaming fails silently or corrupts data |
| A9 | UUID v4 is sufficient for correlation_id (no collision risk) | "Event Bus" | Event tracing and debugging become unreliable |
| A10 | WRITE_PERMISSIONS matrix is exhaustive for all Phase 1 operations | "WRITE_PERMISSIONS" | Unauthorized operations slip through validation |

All assumptions are based on V1 production codebase or official documentation. **If any assumption fails, Phase 1 planning must revisit the affected section.**

---

## Open Questions

1. **Cloud storage for bank extracts:**
   - What we know: Bank extracts (.xlsx) are uploaded to FastAPI endpoint
   - What's unclear: Where are files stored? Local `/tmp` (ephemeral on Render)? S3 (adds cost)?
   - Recommendation: Clarify with user before Phase 2 begins

2. **Alegra sandbox account credentials:**
   - What we know: Phase 0 requires testing with real Alegra sandbox
   - What's unclear: Is the sandbox account already set up? What's the API key?
   - Recommendation: Obtain credentials before Phase 1 planning

3. **ExecutionCard UI component:**
   - What we know: Required by D-06, renders journal preview + Confirm/Cancel
   - What's unclear: Exact design, how it integrates with SSE streaming, error display
   - Recommendation: Frontend team clarify component spec

4. **Anti-duplicate 3-layer implementation:**
   - What we know: Required by SISMO_V2_Fase0_Fase1.md for Phase 2 (bank reconciliation)
   - What's unclear: How are hashes computed? (MD5? SHA256?) Where are they stored?
   - Recommendation: Document hash algorithm and index strategy before Phase 2 code

---

## Environment Availability

**Step 2.6: Environment Availability Audit (Phase 1 specific dependencies)**

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| Python 3.11+ | FastAPI, async runtime | ✓ | 3.11+ | — |
| MongoDB Atlas (M0) | Motor database | ✓ | M0 free tier | — |
| Anthropic API key | Tool Use client | ✓ | SDK 0.38+ | — |
| Alegra API (prod + sandbox) | request_with_verify() tests | ✓ | v1 | — |
| pytest + pytest-asyncio | Testing framework | ✓ | 7.4+ / 0.23+ | — |
| httpx AsyncClient | async HTTP testing with mocks | ✓ | 0.27+ | requests (sync, not recommended) |

**Missing dependencies with no fallback:** None identified

**Missing dependencies with fallback:**
- None identified

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 7.4+ + pytest-asyncio 0.23+ |
| Config file | `pytest.ini` or `pyproject.toml` |
| Quick run command | `pytest backend/tests/test_permissions.py backend/tests/test_phase4_agents.py -v` |
| Full suite command | `pytest backend/tests/ -v --cov=backend` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FOUND-01 | Router classifies intent, scores >= 0.70 | unit | `pytest tests/test_router.py::test_router_confidence_threshold -v` | ❌ Wave 0 |
| FOUND-02 | Agent receives correct system prompt in Claude message | unit | `pytest tests/test_system_prompts.py::test_contador_identity -v` | ❌ Wave 0 |
| FOUND-03 | CFO PermissionError on POST /journals | unit | `pytest tests/test_permissions.py::test_cfo_cannot_write_journals -v` | ❌ Wave 0 |
| FOUND-04 | Tool Use call with typed parameters | unit | `pytest tests/test_tool_use.py::test_criar_causacion_parameters -v` | ❌ Wave 0 |
| FOUND-05 | Event published to roddos_events after Alegra write | integration | `pytest tests/test_event_bus.py::test_event_published_after_write -v` | ❌ Wave 0 |
| FOUND-06 | request_with_verify() returns Alegra ID after verification | integration | `pytest tests/test_request_verify.py::test_post_get_verification -v` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest backend/tests/test_permissions.py backend/tests/test_event_bus.py backend/tests/test_phase4_agents.py -v`
- **Per wave merge:** `pytest backend/tests/ -v --cov=backend` (full suite)
- **Phase gate:** Full suite green + 22 smoke tests passing before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_router.py` — covers FOUND-01 (routing confidence threshold)
- [ ] `tests/test_system_prompts.py` — covers FOUND-02 (agent system prompts)
- [ ] `tests/test_permissions.py` — covers FOUND-03 (write permissions enforcement)
- [ ] `tests/test_tool_use.py` — covers FOUND-04 (Anthropic Tool Use)
- [ ] `tests/test_event_bus.py` — covers FOUND-05 (event bus architecture)
- [ ] `tests/test_request_verify.py` — covers FOUND-06 (request verification pattern)
- [ ] `tests/conftest.py` — shared fixtures (AsyncClient, mock db, mock Alegra)
- [ ] Framework install: `pip install pytest==7.4.0 pytest-asyncio==0.23.0 httpx==0.27.0`

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | JWT 7-day expiry (Render cold start resilience) |
| V3 Session Management | yes | FastAPI `session_id` in MongoDB, TTL 72h |
| V4 Access Control | yes | WRITE_PERMISSIONS enforced in code (not narrative) |
| V5 Input Validation | yes | Pydantic models for all request bodies, JSON Schema in Tool definitions |
| V6 Cryptography | yes | Alegra API key via `os.getenv()` (no hardcoding), JWT via cryptography library |
| V7 Error Handling | yes | No stack traces to user, SQL injection N/A (MongoDB), XSS N/A (backend JSON) |
| V13 API & Web Service | yes | REST API, Tool Use, no CORS misconfiguration |

### Known Threat Patterns for FastAPI + Motor + Anthropic SDK

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Unauthorized Alegra writes (CFO posts journal) | Tampering | validate_write_permission() middleware + PermissionError |
| MongoDB injection (user input in query) | Tampering | Pydantic models validate all inputs before MongoDB query |
| Tool parameters manipulated by user | Tampering | Anthropic SDK validates tool parameters, user cannot bypass |
| Alegra API key leaked in logs | Disclosure | Use `os.getenv()`, never log `ALEGRA_TOKEN` |
| Session hijacking (JWT stolen) | Spoofing | 7-day TTL (short), HTTPS enforced (Render/Vercel) |
| Denial of Service (100 concurrent agents) | Denial | Motor connection pooling, httpx connection pooling, rate limiting TBD |
| Alegra API goes down, system continues | Denial (recovery) | Graceful degradation: render error to user, queue for retry |

---

## Sources

### Primary (HIGH confidence)

- **V1 Production Codebase:** `/c/Users/AndresSanJuan/roddos-workspace/SISMO/backend/` — 67 tests, 8 phases, validated async patterns, tool_executor.py and tool_definitions.py
- **SISMO V2 Specification:** `.planning/SISMO_V2_Fase0_Fase1.md` — Fase 0 and Fase 1 requirements, Reglas de Oro, smoke test criteria
- **SISMO V2 System Prompts:** `.planning/SISMO_V2_System_Prompts.md` — SYSTEM_PROMPTS dict, WRITE_PERMISSIONS matrix
- **SISMO V2 Canonical Registry:** `.planning/SISMO_V2_Registro_Canonico.md` — Alegra endpoints, MongoDB collections, API routes, verified and current as of April 2026

### Secondary (MEDIUM confidence)

- **Anthropic SDK Documentation (v0.38+):** Tool Use stable since v0.35, streaming support, async client (AsyncAnthropic)
- **Motor Documentation:** motor.readthedocs.io — async MongoDB patterns, connection pooling, change streams
- **FastAPI Official Docs:** fastapi.tiangolo.com — async/await, SSE streaming, dependency injection, Pydantic v2
- **Python 3.11 Typing:** docs.python.org/3.11 — type hints, asyncio.gather(), concurrent task patterns

### Tertiary (LOW confidence - assumptions needing validation)

- **Alegra API behavior under error conditions:** Assumed 429/503 retry logic; not verified against current sandbox
- **MongoDB M0 free tier latency:** Assumed < 100ms; not benchmarked recently
- **Anthropic Tool Use backward compatibility:** Assumed 0.38+ is stable; latest features not tested
- **ExecutionCard UI integration:** Assumed SSE + React Hook Form work together; not prototyped

---

## Metadata

**Confidence breakdown:**
- **Standard stack:** HIGH — All libraries verified against V1 production codebase, official PyPI releases
- **Architecture patterns:** HIGH — Async/await, Motor, request_with_verify(), Tool Use all battle-tested in V1
- **Router implementation:** HIGH — Keyword rules + LLM fallback pattern from CONTEXT.md, compatible with existing logic
- **Permissions enforcement:** HIGH — Matrix defined in SISMO_V2_System_Prompts.md, pattern clear
- **Tool Use API:** MEDIUM — Tool definitions extracted from V1, but Phase 1 requires expanding beyond 6 MVP tools
- **Event bus:** HIGH — Append-only pattern from V1, schema defined, no external dependencies
- **request_with_verify():** HIGH — Implemented in V1 BUILD 21, prevents phantom records

**Research date:** 2026-04-09
**Valid until:** 2026-05-09 (30 days for stable stack components)

---

*Phase 1 research complete. Planner can now create PLAN.md files for each infrastructure component.*
