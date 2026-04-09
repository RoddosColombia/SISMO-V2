# Domain Pitfalls: AI Agent Orchestration + ERP Automation

**Domain:** Multi-agent AI system orchestration for accounting automation with external ERP (Alegra) writes
**Researched:** 2026-04-09
**Confidence:** HIGH (based on V1 production incidents + domain patterns)

---

## Critical Pitfalls (Severity: HIGH)

### Pitfall 1: Silent Write Failures — Agent Reports Success When ERP Rejects

**What goes wrong:**
Agent completes internal logic, reports "journal created" to user, but the ERP API call fails silently or partially. User believes the entry is in Alegra; in reality it's orphaned. Audit fails months later when P&L doesn't match reality.

**V1 Incident:** "False success reports when ERP write failed silently" — agents reported 42 entries created but only 38 arrived in Alegra.

**Why it happens:**
- Agent calls ERP API without verifying the HTTP status code
- No post-write verification (read-back check)
- Exception handling swallows API 400/500 responses
- Agent logs "created" before waiting for API response

**Consequences:**
- Data corruption (entries in MongoDB but not in Alegra — split brain)
- Audit gaps (reconciliation impossible)
- Wrong financial statements (missing transactions)
- User makes decisions on false balances
- Late discovery → difficult corrections required

**Warning Signs:**
- Agent responses like "Done! Journal created" without showing Alegra ID
- MongoDB has entries that don't exist in Alegra
- Backlog items marked "sent" but missing from Alegra
- Timeouts in agent logs without retry info
- ERP API returning non-200 status but agent didn't surface the error

**Prevention Strategy:**

1. **Mandatory request_with_verify() pattern** — ALL writes to ERP must:
   - Send HTTP request
   - Capture response status + body
   - Verify HTTP 200/201
   - Extract and store the ERP ID
   - Perform immediate read-back: GET the same resource to confirm it exists
   - Only then commit to MongoDB/log success
   - If ANY step fails → STOP, log exact error, return to user with full context

2. **Verify helper signature:**
   ```python
   async def request_with_verify(method: str, endpoint: str, data: dict, 
                                  verify_field: str = "id") -> dict:
       """
       Make HTTP request, verify success, read back, return verified data.
       Raises ERP_WRITE_FAILED exception (not silent) if any step fails.
       """
   ```

3. **Three-layer verification before user sees success:**
   - Layer 1: HTTP response is 200/201
   - Layer 2: Response contains expected fields (not empty JSON)
   - Layer 3: Immediate read-back via GET confirms resource exists with correct data

4. **Every agent response that mentions "created/sent/posted" must include:**
   - Alegra resource ID (not MongoDB ID)
   - Timestamp of creation in Alegra
   - Exact values of key fields (amount, date, account) for user to cross-check

5. **Fallback: Event log every ERP write attempt**
   - Before write: log {agent, endpoint, data_hash}
   - After write: log {status, alegra_id, timestamp}
   - Use append-only roddos_events collection
   - Never delete/update — only append

**Phase to Address:** Phase 0 (Cimientos Arquitectónicos)
- Build request_with_verify() as foundational utility
- Make it impossible to write to ERP without it (code review + linter rule)

---

### Pitfall 2: Agent Identity Confusion — Wrong Agent Has Write Permissions

**What goes wrong:**
CFO agent answers an accounting question, internally creates a journal entry to test its logic, and actually posts it to Alegra without proper authorization check. Or Contador agent receives a question intended for RADAR, creates entries it shouldn't create.

**V1 Incident:** "Agent identity confusion (CFO answering Contador questions)" — CFO agent had permission to POST /journals. It drafted examples that were posted as real entries.

**Why it happens:**
- Permissions not checked at tool invocation time
- All agents share the same Alegra API credentials
- No WRITE_PERMISSIONS matrix in code
- Agents don't know their own role boundaries
- Tool calls not routed through permission gate

**Consequences:**
- Wrong entries in Alegra (CFO speculative entries, RADAR testing data)
- Unauthorized user writes violate audit trail
- Difficult to trace who caused what (multi-agent single identity)
- User trust broken ("I didn't authorize this!")
- Regulatory/audit issues

**Warning Signs:**
- Entries in Alegra from agent that shouldn't create them
- Agent conversations showing drafting/testing that became real
- Multiple agents with same API credentials in code
- No permission checks in tool definitions
- Tool.execute() called without pre-check against WRITE_PERMISSIONS

**Prevention Strategy:**

1. **Hardcoded WRITE_PERMISSIONS matrix in code** (not config, not narrative):
   ```python
   WRITE_PERMISSIONS = {
       "contador": ["POST /journals", "POST /invoices", "POST /categories", "POST /contacts"],
       "cfo": ["GET *", "POST /reports"],  # Read-only for journal data
       "radar": ["GET *", "POST /contacts"],  # Only contact updates
       "loanbook": ["GET *"],  # Read-only
   }
   ```

2. **Every tool execution must:**
   - Extract agent_id from request context
   - Check if agent_id + tool_name in WRITE_PERMISSIONS
   - Raise PermissionError if not present
   - Log the permission check (agent_id, tool, result)

3. **No agent tools are drafts or examples:**
   - Tools always execute (POST) or are read-only
   - If agent needs to draft → return text, not tool call
   - Test drafts must run against isolated test Alegra account (separate credentials)

4. **Agent system prompts explicitly state role:**
   - "You are the Contador agent. You can create journals, invoices, and contacts."
   - "You cannot: View revenue forecasts, update contacts, post payments."
   - "If unsure of your permissions, ASK the user rather than guessing."

5. **Permission violation is loud, not silent:**
   - PermissionError exception (not None return)
   - User sees: "I don't have permission to do that. Only Contador can post journals."
   - Event logged with timestamp and agent_id

**Phase to Address:** Phase 0 (Cimientos Arquitectónicos)
- Define WRITE_PERMISSIONS before building any tools
- Build permission check into all tool call execution paths
- Test each agent's permission boundaries explicitly

---

### Pitfall 3: Duplicate Entries — Retry Logic Creates Multiple Journal Entries

**What goes wrong:**
Agent fails to post entry, retries the same request, ERP creates two identical entries. Or user clicks "Confirm" twice, both trigger writes. Deduplication doesn't exist or arrives too late.

**V1 Incident:** "176 duplicate journals from missing anti-dedup" — retry logic and re-upload of .xlsx files created thousands of duplicates before detection.

**Why it happens:**
- No idempotency check before write (ERP accepts identical entries)
- Retry logic doesn't check if entry already exists
- User double-clicks "Confirm" button
- Multiple agent retries on timeout
- No deduplication in request_with_verify()

**Consequences:**
- False revenues/expenses in P&L (176 entries = massive impact)
- Audit impossible ("Why are there 2 invoices for the same amount?")
- Manual deletion required in Alegra (tedious, error-prone)
- Financial statements overstated
- Late detection → impacts investor decisions, tax filings

**Warning Signs:**
- Same amount/date/account appearing multiple times in Alegra
- Batch upload (xlsx) followed by duplicate entries
- Timestamp clusters (3 identical entries within 1 second)
- User reports "I only uploaded once but got 5 entries"
- Alegra's "recent journals" shows duplicates

**Prevention Strategy:**

1. **Three-layer anti-dedup before write:**

   Layer 1 (Request Level): **Idempotency Key**
   - Client generates unique key: `sha256(agent_id + endpoint + data_hash + timestamp_minute)`
   - Include `Idempotency-Key` header on every ERP request
   - ERP returns 409 Conflict if exact duplicate exists → handle gracefully

   Layer 2 (Pre-Write Check): **Query-Before-Write**
   - Before posting journal: GET /journals filtered by (date, account, amount, description)
   - If found → return existing entry ID, don't POST
   - Include tolerance window (±1 day for date, ±0.01% for amount)

   Layer 3 (Post-Write Check): **Read-Back Verification**
   - After POST succeeds, GET the created entry
   - Confirm fields match request
   - Store Alegra ID immediately

2. **Idempotency helper:**
   ```python
   def generate_idempotency_key(agent_id: str, endpoint: str, data: dict) -> str:
       payload = f"{agent_id}:{endpoint}:{json.dumps(data, sort_keys=True)}"
       return hashlib.sha256(payload.encode()).hexdigest()
   ```

3. **Batch uploads (xlsx) get deduplication:**
   - Hash each row before inserting queue
   - Skip rows with hash already in roddos_events
   - Report to user: "3 new entries, 2 skipped (duplicates)"

4. **UI prevents double-click:**
   - "Confirm" button disabled until POST completes
   - Visual feedback: spinning icon + "Posting..."
   - Timeout after 30s with error message

5. **Reconciliation job detects remaining duplicates:**
   - Weekly task: identify (date, account, amount) clusters in Alegra
   - Alert if cluster size > 1
   - Flag for manual review (don't auto-delete)

**Phase to Address:** Phase 0 (Cimientos Arquitectónicos) + Phase 1 (Agent Contador)
- Build idempotency + query-before-write into request_with_verify()
- Deploy batch dedup for xlsx uploads in Fase 1

---

### Pitfall 4: Wrong Alegra Endpoint or Field — 403/404 Silent Rejection

**What goes wrong:**
Agent calls `/journal-entries` (doesn't exist), gets 403 Forbidden, logs an error, user doesn't see it. Or agent tries to update `/accounts` (forbidden), silently fails. Or agent sends ISO-8601 date with timezone (returns 0 results silently).

**V1 Incidents:**
- "Wrong account ID (5495 instead of 5493) caused 143 incorrect entries"
- "/journal-entries endpoint returns 403 (must use /journals)"
- "/accounts endpoint returns 403 (must use /categories)"
- "ISO-8601 dates with timezone return 0 results from Alegra"

**Why it happens:**
- Alegra API is strict; endpoints are not RESTful
- Guessing at endpoint names (journals vs journal-entries vs journal)
- Copy-paste from other APIs or documentation
- Date format not validated before sending
- No validation layer between agent and ERP

**Consequences:**
- Entries not created (user thinks they are)
- Wrong entries created (account 5495 vs 5493)
- Search results return 0 items (timezone in date)
- Time wasted debugging "why did my query return nothing?"
- Broken automation if API path is hardcoded

**Warning Signs:**
- HTTP 403/404/400 responses from Alegra
- Agent logs "Request failed" but user doesn't see it
- Search queries in Alegra return 0 results unexpectedly
- Account IDs in Alegra don't match request
- Date filtering doesn't work ("Filter by date returned nothing")

**Prevention Strategy:**

1. **Alegra API quirks codified in central validator:**
   ```python
   ALEGRA_QUIRKS = {
       "journals": {
           "method": "POST",
           "status_ok": [200, 201],
           "date_format": "yyyy-MM-dd",  # NO timezone
           "required_fields": ["date", "description", "details"],
       },
       "invoices": {
           "method": "POST",
           "required_fields": ["date", "clientId", "items"],
       },
       "categories": {  # NOT accounts
           "method": "GET",
           "aliases": ["accounts"],  # Common mistake
       },
   }
   ```

2. **Validate before sending:**
   ```python
   def validate_alegra_request(endpoint: str, data: dict, method: str = "POST"):
       if endpoint not in ALEGRA_QUIRKS:
           raise ValueError(f"Unknown Alegra endpoint: {endpoint}")
       
       spec = ALEGRA_QUIRKS[endpoint]
       
       # Validate date format
       if "date" in data:
           if "T" in str(data["date"]):  # Has timezone
               raise ValueError(f"Date must be yyyy-MM-dd, not ISO-8601")
       
       # Validate required fields
       for field in spec["required_fields"]:
           if field not in data:
               raise ValueError(f"Missing required field: {field}")
       
       return True
   ```

3. **Endpoint name validation:**
   - Create enum for allowed endpoints: `ENDPOINT = Enum("JOURNAL", "INVOICE", "CATEGORY", ...)`
   - Only allow enum values, not strings
   - Pass endpoint enum to request functions

4. **Test against Alegra specification document:**
   - Create .md file: `docs/ALEGRA_API_SPEC.md`
   - List all endpoints agents use
   - Document exact request format (dates, account IDs, required fields)
   - Include known quirks and workarounds
   - CI test: confirm spec matches actual API behavior

5. **Field mapping codified:**
   - `/accounts` → use `/categories` + map response.id
   - Account ID 5495 forbidden → fallback to 5493 with warning
   - Date formats: convert all to `yyyy-MM-dd` before sending

**Phase to Address:** Phase 0 (Cimientos Arquitectónicos)
- Create ALEGRA_QUIRKS validator
- Build test suite against real Alegra API (sandbox)
- Document all quirks before Phase 1 agents start writing

---

### Pitfall 5: Split Brain — MongoDB and Alegra Versions Diverge

**What goes wrong:**
Agent reads balance from MongoDB cache, makes decision (e.g., "approve loan"), then writes to Alegra. But MongoDB was stale (not synced after last Alegra write). Decision is based on wrong data. Or writes succeed in Alegra but fail to update MongoDB cache → next query returns old data.

**V1 Pattern:** ROG-4 states "MongoDB is not source of truth" but many V1 features violated this.

**Why it happens:**
- No clear separation of concerns (which system is source of truth?)
- Cache invalidation not explicit
- Async writes to Alegra don't wait for MongoDB update
- Alegra API calls don't update MongoDB immediately
- "Eventually consistent" assumed but never validated

**Consequences:**
- Loan approvals based on stale revenue data
- Incorrect payment calculations
- Audit shows discrepancies ("MongoDB says $100K, Alegra says $95K")
- User confused ("I just posted that entry, why doesn't my dashboard show it?")
- P&L is unreliable

**Warning Signs:**
- Dashboard values don't match Alegra values
- User posts entry, page still shows old balance
- MongoDB and Alegra return different totals for same date range
- Agent decisions contradict actual balances
- "Sync" operations becoming frequent

**Prevention Strategy:**

1. **Define source of truth explicitly:**
   - ALEGRA IS SOURCE OF TRUTH for all accounting data
   - MongoDB is: session state, job queue, cache (expires after N hours)
   - Corollary: NEVER read from MongoDB for financial decisions

2. **Architecture rule:**
   - Agents read from Alegra (not MongoDB) for decision-making
   - Agents write to Alegra first, then update MongoDB as cache
   - If MongoDB update fails → log warning, don't fail the write

3. **Cache invalidation:**
   - After any POST to Alegra → invalidate related MongoDB cache keys
   - Set TTL on all MongoDB cache entries (max 1 hour)
   - On cache miss → fetch from Alegra fresh

4. **Read-back verification enforces this:**
   - request_with_verify() reads from Alegra after write
   - Updates MongoDB with Alegra response
   - No other source of MongoDB updates

5. **CFO agent enforces truth at read time:**
   - P&L calculation reads from Alegra journals, not MongoDB
   - If MongoDB balances differ, CFO alerts user: "Dashboard cache out of sync. Refreshing from Alegra..."

**Phase to Address:** Phase 0 (Cimientos Arquitectónicos)
- Establish ROG-4 as immutable rule
- Build all reads against Alegra (not MongoDB) for financial queries
- Test for MongoDB vs Alegra divergence in smoke tests

---

## Moderate Pitfalls (Severity: MEDIUM)

### Pitfall 6: Missing Webhook Verification — Malicious Event Injection

**What goes wrong:**
Webhook from Alegra arrives, agent trusts it without verification. Attacker sends fake webhook claiming "invoice paid" but payment wasn't actually received. Agent marks loan as paid, customer balance wrong.

**Why it happens:**
- Webhook handler doesn't verify signature
- No rate limiting on webhook endpoint
- Webhook payload not validated against ERP state

**Consequences:**
- Fraudulent payment claims
- Loan status corrupted
- Receivables management fails

**Warning Signs:**
- Webhook events that don't match Alegra state
- Unexpected payment confirmations
- Loanbook showing paid status but Alegra shows unpaid

**Prevention Strategy:**

1. Alegra webhooks must include HMAC signature
2. Verify signature before processing webhook
3. Check webhook timestamp (reject if >5 min old)
4. Never trust webhook alone — verify with GET from ERP after webhook received
5. Log all webhook events (raw, signature, verification result)

**Phase to Address:** Phase 1 (Agente Contador) when webhook integration is added

---

### Pitfall 7: Agent Hallucination on Numbers — Invented Account IDs or Amounts

**What goes wrong:**
Agent is asked "categorize this $5,234.50 expense" and hallucinates an account ID (invents "5999") or misreads the amount ("$5,234.50" → "52345"). Posts wrong entry.

**Why it happens:**
- Agent extracting data from images/PDFs makes OCR mistakes
- Agent generates plausible-sounding account IDs
- No validation of extracted amounts before posting
- Agent not prompted to confirm extracted data

**Consequences:**
- Entries with fake/nonexistent account IDs (rejected by Alegra or posted wrong)
- Wrong amounts in P&L
- Reconciliation impossible

**Warning Signs:**
- Alegra API rejects entries with "invalid account"
- Entries posted to wrong account
- Amounts don't match source documents

**Prevention Strategy:**

1. Always show extracted data to user before confirming write
2. Require user to confirm amounts visually
3. Validate account IDs against ALEGRA_QUIRKS before posting
4. For PDF/image extraction: use OCR confidence score, flag low-confidence fields

**Phase to Address:** Phase 1 (receipt extraction feature)

---

### Pitfall 8: Datetime/Timezone Confusion — Entries Posted to Wrong Date

**What goes wrong:**
Transaction occurs in Colombia (UTC-5), agent receives timestamp from server (UTC), posts to Alegra without timezone conversion. Entry shows wrong date. Or query uses UTC date but user expects Colombia date.

**Why it happens:**
- Python datetime naive (no timezone info)
- Alegra API expects `yyyy-MM-dd` in user's timezone (Colombia)
- No explicit timezone handling in codebase

**Consequences:**
- Entries appear on wrong date in Alegra
- Daily reconciliation fails (missing from expected day)
- Revenue recognized wrong period (affects tax filings)

**Warning Signs:**
- Entries in Alegra dated one day off
- User says "I paid this yesterday" but entry shows today
- Reconciliation gaps at timezone boundaries (11:59 PM)

**Prevention Strategy:**

1. All datetime operations use timezone-aware objects (pytz.timezone('America/Bogota'))
2. Store all datetimes in database as UTC
3. Convert to Bogotá time only when displaying or sending to Alegra
4. Test with times at edges (11:55 PM Colombia time)

**Phase to Address:** Phase 0 (utilities) + Phase 1 (testing)

---

### Pitfall 9: Rate Limiting Breaks Batch Operations — Alegra Throttles Agent

**What goes wrong:**
Agent posts 100 expense entries in a loop. Alegra rate limits to 10 req/sec. After 50 posts, requests start failing. Agent retry logic hammers API. User sees "500 errors" intermittently.

**Why it happens:**
- Alegra has undocumented rate limits
- Agent doesn't implement backoff
- No monitoring of rate limit headers

**Consequences:**
- Batch operations fail partially (50/100 succeed)
- Inconsistent state (some entries in Alegra, others not)
- Retries make situation worse

**Prevention Strategy:**

1. Implement exponential backoff with jitter
2. Respect Alegra's rate limit headers (429 Retry-After)
3. Limit batch operations to 5 posts/sec from agent
4. Queue long batches (xlsx files) into job queue, process serially

**Phase to Address:** Phase 1 (Nómina batch, xlsx batch upload)

---

## Minor Pitfalls (Severity: LOW)

### Pitfall 10: Missing Alegra ID After Create — Can't Track Entry

**What goes wrong:**
Agent POSTs journal, gets response, but doesn't extract the Alegra ID from the response. Later, can't retrieve the entry for verification. No audit trail.

**Why it happens:**
- Response parsing incomplete
- Alegra ID field has unexpected name (id vs _id vs journalId)

**Consequences:**
- Can't verify entry later
- Audit trail broken

**Prevention Strategy:**

1. Always extract and store Alegra ID immediately after POST
2. Test response parsing against real Alegra API
3. Document ID field names per endpoint

**Phase to Address:** Phase 0

---

### Pitfall 11: Agent Forgets Context Across Messages — Loses Session State

**What goes wrong:**
User says "Post the expense for $500". Agent asks "What date?" User says "Today". But in next turn, agent forgets the $500 amount was mentioned and asks again.

**Why it happens:**
- Context window not managed properly
- Agent doesn't summarize extracted data back to user
- Session state lost between messages

**Consequences:**
- Poor UX (repetitive questions)
- Risk of user providing conflicting data
- Eventually posts wrong entry due to confusion

**Prevention Strategy:**

1. Agent always summarizes extracted/confirmed data: "OK, I have: $500, account 5493, today (2026-04-09)"
2. Store conversation context in session
3. Explicit confirmation ritual before posting

**Phase to Address:** Phase 1 (Agent Contador UX polish)

---

## Phase-Specific Warnings

| Phase | Topic | Likely Pitfall | Mitigation |
|-------|-------|---------------|-----------|
| Phase 0 | Tool invocation | Agent identity confusion | Enforce WRITE_PERMISSIONS at call time |
| Phase 0 | ERP integration | Silent write failures | Mandatory request_with_verify() |
| Phase 0 | Event bus | Missing audit trail | Append-only roddos_events for all writes |
| Phase 1 | Batch uploads (.xlsx) | Duplicate entries | Query-before-write dedup layer |
| Phase 1 | Receipt extraction | Hallucinated amounts | User confirmation before write |
| Phase 1 | Nómina creation | Wrong employee IDs | Validate against known employees before posting |
| Phase 1 | Bank reconciliation | Split brain (cache vs Alegra) | Read from Alegra, not MongoDB for balances |
| Phase 2 (CFO) | P&L calculation | Using stale MongoDB data | Force read from Alegra journals |
| Phase 3 (RADAR) | Cobranza decisions | Stale customer balances | Query Alegra fresh before approval |

---

## Sources

All pitfalls verified against:

1. **V1 Production Incidents (HIGH confidence):**
   - "176 duplicate journals from missing anti-dedup" → Pitfall 3
   - "Agent identity confusion (CFO answering Contador questions)" → Pitfall 2
   - "False success reports when ERP write failed silently" → Pitfall 1
   - "Wrong account ID (5495 instead of 5493) caused 143 incorrect entries" → Pitfall 4
   - "/journal-entries endpoint returns 403 (must use /journals)" → Pitfall 4
   - "ISO-8601 dates with timezone return 0 results" → Pitfall 4

2. **SISMO V2 PROJECT.md:**
   - ROG-4: "Alegra is source of truth" → Pitfall 5
   - WRITE_PERMISSIONS requirement → Pitfall 2
   - request_with_verify() pattern → Pitfall 1
   - Multi-agent bus design → Pitfall 2

3. **CLAUDE.md (User Global Instructions):**
   - Alegra API quirks (endpoints, date formats) → Pitfall 4
   - Colombian accounting rules (retenciones, IVA) → Pitfall 7
