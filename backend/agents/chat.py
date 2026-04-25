"""
process_chat() — Core agent orchestration with Tool Use and SSE streaming.

Flow:
  1. route_with_sticky() -> agent_type
  2. Build Claude API call with system prompt + tools (if TOOL_USE_ENABLED)
  3. Stream text responses directly
  4. For tool_use blocks:
     - Read-only: execute immediately, second Claude call for natural language response
     - Write: validate_write_permission, yield ExecutionCard SSE event
  5. Write tools are NOT executed here — approval via POST /api/chat/approve-plan
  6. approve-plan executes the tool, then makes a second Claude call for confirmation text

ExecutionCard SSE event format:
  event: tool_proposal
  data: {
    "tool_name": "registrar_gasto",
    "tool_input": {...},
    "proposal": "DEBITO 5480 $3.614.953 / CREDITO ReteFuente $126.523 / CREDITO Banco",
    "session_id": "...",
    "requires_confirmation": true
  }
"""
import json
import os
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
import anthropic
from motor.motor_asyncio import AsyncIOMotorDatabase

from agents.prompts import SYSTEM_PROMPTS
from agents.contador.tools import get_tools_for_agent
from core.router import route_with_sticky, IntentResult
from core.permissions import validate_write_permission
from agents.contador.handlers import ToolDispatcher, is_read_only_tool, is_conciliation_tool

ANTHROPIC_MODEL = "claude-sonnet-4-5"

MAX_HISTORY_MESSAGES = 20  # Last N messages to include (user + assistant pairs)
SESSION_TTL_SECONDS = 72 * 3600  # 72 hours


async def _ensure_chat_sessions_index(db: AsyncIOMotorDatabase) -> None:
    """Create TTL index on chat_sessions.updated_at (idempotent)."""
    try:
        await db.chat_sessions.create_index(
            "updated_at",
            expireAfterSeconds=SESSION_TTL_SECONDS,
        )
    except Exception:
        pass  # Index already exists or MongoDB error — non-fatal


async def _load_history(db: AsyncIOMotorDatabase, session_id: str) -> list[dict]:
    """Load conversation history for a session, limited to last N messages."""
    doc = await db.chat_sessions.find_one(
        {"session_id": session_id},
        {"messages": 1},
    )
    if not doc or not doc.get("messages"):
        return []
    return doc["messages"][-MAX_HISTORY_MESSAGES:]


async def _save_messages(
    db: AsyncIOMotorDatabase,
    session_id: str,
    agent_type: str,
    user_message: str,
    assistant_message: str,
) -> None:
    """Append user + assistant message pair to the session."""
    now = datetime.now(timezone.utc)
    await db.chat_sessions.update_one(
        {"session_id": session_id},
        {
            "$push": {
                "messages": {
                    "$each": [
                        {"role": "user", "content": user_message},
                        {"role": "assistant", "content": assistant_message},
                    ],
                },
            },
            "$set": {
                "agent_type": agent_type,
                "updated_at": now,
            },
            "$setOnInsert": {
                "session_id": session_id,
            },
        },
        upsert=True,
    )


def _check_read_only_for_agent(tool_name: str, agent_type: str) -> bool:
    """Return True if tool_name is read-only for the given agent_type."""
    if agent_type == "loanbook":
        from agents.loanbook.handlers.dispatcher import is_read_only_tool as lb_iro
        return lb_iro(tool_name)
    return is_read_only_tool(tool_name)


def _make_dispatcher(agent_type: str, db: AsyncIOMotorDatabase):
    """Create the right dispatcher for the given agent_type."""
    if agent_type == "loanbook":
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        return LoanToolDispatcher(db=db)
    # Default: contador
    from services.alegra.client import AlegraClient
    alegra = AlegraClient(db=db)
    return ToolDispatcher(alegra=alegra, db=db, event_bus=None)


async def process_chat(
    message: str,
    db: AsyncIOMotorDatabase,
    agent_type: str | None = None,
    session_id: str | None = None,
    current_agent: str | None = None,
    correlation_id: str | None = None,
    dispatcher=None,  # Kept for backward compat — ignored, dispatcher built internally
    imagen: str | None = None,  # base64 data URI (data:image/jpeg;base64,...)
) -> AsyncGenerator[str, None]:
    """
    Async generator that yields SSE-formatted strings.

    SSE formats:
      data: {"type": "text", "content": "..."}          -- streaming text
      data: {"type": "tool_proposal", ...}               -- ExecutionCard
      data: {"type": "clarification", "question": "..."}  -- router ambiguous
      data: {"type": "error", "message": "..."}          -- handled error
      data: {"type": "done"}                              -- stream complete
    """
    if not session_id:
        session_id = str(uuid.uuid4())
    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    # Step 1: Route intent
    if agent_type is None:
        intent = route_with_sticky(message, current_agent)
        if intent.confidence < 0.70:
            yield f"data: {json.dumps({'type': 'clarification', 'question': intent.clarification})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return
        agent_type = intent.agent

    system_prompt = SYSTEM_PROMPTS.get(agent_type, SYSTEM_PROMPTS['contador'])

    # Step 2: Build tools list (feature flag gated per D-04/FOUND-04)
    tool_use_enabled = os.environ.get("TOOL_USE_ENABLED", "true").lower() == "true"
    tools = get_tools_for_agent(agent_type) if tool_use_enabled else []

    # Build agent-appropriate dispatcher and read-only checker.
    # Use injected dispatcher when provided (backward compat for router + tests).
    # Always derive check_read_only from agent_type so loanbook tools are classified correctly.
    if tool_use_enabled:
        active_dispatcher = dispatcher if dispatcher is not None else _make_dispatcher(agent_type, db)
        check_read_only = lambda name: _check_read_only_for_agent(name, agent_type)
    else:
        active_dispatcher = None
        check_read_only = lambda _: False

    # Step 2b: Load conversation history and build messages array
    await _ensure_chat_sessions_index(db)
    history = await _load_history(db, session_id)

    # Build current message — multimodal if image attached
    if imagen:
        # Extract base64 data and media type from data URI
        # Format: "data:image/jpeg;base64,/9j/4AAQ..."
        if imagen.startswith("data:"):
            parts = imagen.split(",", 1)
            media_type = parts[0].split(":")[1].split(";")[0]  # "image/jpeg"
            image_data = parts[1]
        else:
            media_type = "image/jpeg"
            image_data = imagen

        user_content = [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
            {"type": "text", "text": message or "Procesa este comprobante y propone el asiento contable."},
        ]
    else:
        user_content = message

    messages = history + [{"role": "user", "content": user_content}]

    # Step 3: Call Claude API with streaming
    client = anthropic.AsyncAnthropic()
    kwargs = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 2048,
        "system": system_prompt,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools

    assistant_text_parts: list[str] = []  # accumulate streamed text for history

    try:
        async with client.messages.stream(**kwargs) as stream:
            async for event in stream:
                # Text streaming
                if hasattr(event, 'type') and event.type == 'content_block_delta':
                    if hasattr(event, 'delta') and hasattr(event.delta, 'text'):
                        assistant_text_parts.append(event.delta.text)
                        yield f"data: {json.dumps({'type': 'text', 'content': event.delta.text})}\n\n"

            # Check final message for tool_use blocks
            final_message = await stream.get_final_message()
            for block in final_message.content:
                if block.type == 'tool_use':
                    # Read-only tools: execute immediately, then second Claude call for natural language
                    if check_read_only(block.name) and active_dispatcher is not None:
                        result = await active_dispatcher.dispatch(block.name, block.input, session_id or "anon")

                        # Second Claude call — feed tool_result back for a natural language response
                        second_messages = messages + [
                            {
                                "role": "assistant",
                                "content": [{"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}],
                            },
                            {
                                "role": "user",
                                "content": [{"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result, ensure_ascii=False)}],
                            },
                        ]
                        try:
                            async with client.messages.stream(
                                model=ANTHROPIC_MODEL,
                                max_tokens=1024,
                                system=system_prompt,
                                messages=second_messages,
                            ) as second_stream:
                                async for evt in second_stream:
                                    if hasattr(evt, 'type') and evt.type == 'content_block_delta':
                                        if hasattr(evt, 'delta') and hasattr(evt.delta, 'text'):
                                            assistant_text_parts.append(evt.delta.text)
                                            yield f"data: {json.dumps({'type': 'text', 'content': evt.delta.text})}\n\n"
                        except Exception:
                            # Fallback: show raw result if second call fails
                            raw = result.get("message") or json.dumps(result, ensure_ascii=False)
                            yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': block.name, 'result': result})}\n\n"
                        continue

                    # Conciliation tools return Phase 3 stub immediately (per D-07)
                    if is_conciliation_tool(block.name):
                        yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': block.name, 'result': {'success': True, 'message': 'Conciliación bancaria disponible en Phase 3'}})}\n\n"
                        continue

                    # Write tools: validate permissions, show ExecutionCard (existing behavior preserved, per D-06)
                    try:
                        validate_write_permission(agent_type, f"POST /{block.name}", 'alegra')
                    except PermissionError:
                        pass  # Non-Alegra tools don't need permission check

                    # Serialize ExecutionCard (D-06)
                    proposal = _format_tool_proposal(block.name, block.input)
                    card = {
                        "type": "tool_proposal",
                        "tool_name": block.name,
                        "tool_input": block.input,
                        "proposal": proposal,
                        "session_id": session_id,
                        "correlation_id": correlation_id,
                        "requires_confirmation": True,
                    }
                    # Persist pending action to MongoDB for ExecutionCard approval (T-02-02)
                    # Store tool_use_id and user_message so execute_approved_action
                    # can build the correct tool_result message for Claude.
                    await db.agent_sessions.update_one(
                        {"session_id": session_id},
                        {"$set": {
                            "pending_action": {
                                "tool_name": block.name,
                                "tool_input": block.input,
                                "tool_use_id": block.id,    # needed for second Claude call
                                "user_message": message,    # needed to reconstruct context
                                "correlation_id": correlation_id,
                            },
                            "agent_type": agent_type,
                        }},
                        upsert=True,
                    )
                    yield f"data: {json.dumps(card)}\n\n"

    except anthropic.APIError as e:
        yield f"data: {json.dumps({'type': 'error', 'message': f'Error con la API de Claude: {str(e)}'})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': f'Error inesperado: {str(e)}'})}\n\n"

    # Save conversation history (user message + assistant response)
    # Don't save base64 image data in history — save text description only
    save_message = message or "Procesa este comprobante"
    if imagen:
        save_message = f"[imagen adjunta] {save_message}"
    assistant_text = "".join(assistant_text_parts)
    if assistant_text:
        try:
            await _save_messages(db, session_id, agent_type, save_message, assistant_text)
        except Exception:
            pass  # Non-fatal — don't break the stream for a history save failure

    yield f"data: {json.dumps({'type': 'done'})}\n\n"


async def execute_approved_action(
    session_id: str,
    db: AsyncIOMotorDatabase,
    dispatcher,  # ToolDispatcher or LoanToolDispatcher — passed from router
) -> dict:
    """
    Called by POST /api/chat/approve-plan after user confirms ExecutionCard.
    Retrieves pending_action from MongoDB session, dispatches it, then makes
    a second Claude call to produce a natural language confirmation for the UI.
    Returns {"status": "ejecutado", "final_response": "...", "tool_result": {...}}.
    """
    session = await db.agent_sessions.find_one({"session_id": session_id})
    if not session or not session.get("pending_action"):
        return {"success": False, "error": "No hay acción pendiente para esta sesión"}

    pending = session["pending_action"]
    agent_type = session.get("agent_type", "contador")

    result = await dispatcher.dispatch(
        tool_name=pending["tool_name"],
        tool_input=pending["tool_input"],
        user_id=session_id,
    )

    # Clear pending action after execution
    await db.agent_sessions.update_one(
        {"session_id": session_id},
        {"$unset": {"pending_action": ""}}
    )

    # Second Claude call — use tool_use_id + tool_result to get natural language response
    tool_use_id = pending.get("tool_use_id", str(uuid.uuid4()))
    user_message = pending.get("user_message", "Ejecuta la acción contable solicitada")
    system_prompt = SYSTEM_PROMPTS.get(agent_type, SYSTEM_PROMPTS['contador'])

    summary_messages = [
        {"role": "user", "content": user_message},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": tool_use_id, "name": pending["tool_name"], "input": pending["tool_input"]}],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": json.dumps(result, ensure_ascii=False)}],
        },
    ]

    client = anthropic.AsyncAnthropic()
    try:
        final_msg = await client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=512,
            system=system_prompt,
            messages=summary_messages,
        )
        final_text = "".join(b.text for b in final_msg.content if hasattr(b, 'text'))
        if not final_text:
            raise ValueError("empty response")
    except Exception:
        if result.get("success"):
            final_text = f"Acción ejecutada: {pending['tool_name']}."
        else:
            final_text = f"Error: {result.get('error', 'Error desconocido')}"

    return {
        "status": "ejecutado",
        "final_response": final_text,
        "tool_result": result,
    }


async def process_system_event(
    message: str,
    db: AsyncIOMotorDatabase,
    agent_type: str,
    auto_approve: bool = True,
    correlation_id: str | None = None,
) -> dict:
    """
    Llama al agente Claude con un mensaje construido por el sistema (no por el humano).
    Si auto_approve=True, los write tools se ejecutan sin ExecutionCard.
    Retorna dict con resultado de la ejecución.
    Usado por: alegra_sync, dpd_scheduler, cualquier trigger automático.
    """
    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    system_prompt = SYSTEM_PROMPTS.get(agent_type, SYSTEM_PROMPTS['contador'])
    tools = get_tools_for_agent(agent_type)

    client = anthropic.AsyncAnthropic()
    response = await client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": message}],
        tools=tools,
    )

    results = []
    for block in response.content:
        if block.type == 'tool_use':
            if auto_approve:
                # Seleccionar dispatcher correcto según agent_type (CORRECCIÓN: bug original
                # usaba siempre ToolDispatcher del Contador, enviando asientos a Alegra
                # incluso para tools del agente Loanbook).
                if agent_type == "loanbook":
                    from agents.loanbook.handlers import LoanToolDispatcher
                    sys_dispatcher = LoanToolDispatcher(db)
                else:
                    sys_dispatcher = ToolDispatcher(db)
                result = await sys_dispatcher.dispatch(block.name, block.input, correlation_id)
                results.append({"tool": block.name, "result": result})
            else:
                results.append({"tool": block.name, "pending": True, "input": block.input})
        elif block.type == 'text':
            results.append({"text": block.text})

    return {"correlation_id": correlation_id, "results": results}


def _format_tool_proposal(tool_name: str, tool_input: dict) -> str:
    """Format a human-readable proposal string for ExecutionCard display."""
    if tool_name == 'crear_causacion' and 'entries' in tool_input:
        lines = []
        for entry in tool_input['entries']:
            if entry.get('debit', 0) > 0:
                lines.append(f"DEBITO cta {entry['id']}: ${entry['debit']:,.0f}")
            if entry.get('credit', 0) > 0:
                lines.append(f"CREDITO cta {entry['id']}: ${entry['credit']:,.0f}")
        return " | ".join(lines)
    if tool_name == 'registrar_gasto':
        monto = tool_input.get('monto', 0)
        desc = tool_input.get('descripcion', '')
        return f"Registrar gasto: {desc} -- ${monto:,.0f}"
    return f"Ejecutar {tool_name} con parametros: {json.dumps(tool_input, ensure_ascii=False)}"
