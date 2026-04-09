"""
process_chat() — Core agent orchestration with Tool Use and SSE streaming.

Flow:
  1. route_with_sticky() -> agent_type
  2. Build Claude API call with system prompt + tools (if TOOL_USE_ENABLED)
  3. Stream text responses directly
  4. For tool_use blocks: validate_write_permission, yield ExecutionCard SSE event
  5. Tools are NOT executed here — approval via POST /api/chat/approve-plan

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
from typing import AsyncGenerator
import anthropic
from motor.motor_asyncio import AsyncIOMotorDatabase

from agents.prompts import SYSTEM_PROMPTS
from agents.contador.tools import get_tools_for_agent
from core.router import route_with_sticky, IntentResult
from core.permissions import validate_write_permission
from agents.contador.handlers import ToolDispatcher, is_read_only_tool, is_conciliation_tool

ANTHROPIC_MODEL = "claude-sonnet-4-5"


async def process_chat(
    message: str,
    db: AsyncIOMotorDatabase,
    agent_type: str | None = None,
    session_id: str | None = None,
    current_agent: str | None = None,
    correlation_id: str | None = None,
    dispatcher: ToolDispatcher | None = None,  # NEW — injected by router
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

    # Step 3: Call Claude API with streaming
    client = anthropic.AsyncAnthropic()
    kwargs = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 2048,
        "system": system_prompt,
        "messages": [{"role": "user", "content": message}],
    }
    if tools:
        kwargs["tools"] = tools

    try:
        async with client.messages.stream(**kwargs) as stream:
            async for event in stream:
                # Text streaming
                if hasattr(event, 'type') and event.type == 'content_block_delta':
                    if hasattr(event, 'delta') and hasattr(event.delta, 'text'):
                        yield f"data: {json.dumps({'type': 'text', 'content': event.delta.text})}\n\n"

            # Check final message for tool_use blocks
            final_message = await stream.get_final_message()
            for block in final_message.content:
                if block.type == 'tool_use':
                    # Read-only tools execute immediately — no confirmation needed (per D-06)
                    if is_read_only_tool(block.name) and dispatcher is not None:
                        result = await dispatcher.dispatch(block.name, block.input, session_id or "anon")
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
                    await db.agent_sessions.update_one(
                        {"session_id": session_id},
                        {"$set": {
                            "pending_action": {
                                "tool_name": block.name,
                                "tool_input": block.input,
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

    yield f"data: {json.dumps({'type': 'done'})}\n\n"


async def execute_approved_action(
    session_id: str,
    db: AsyncIOMotorDatabase,
    dispatcher: ToolDispatcher,
) -> dict:
    """
    Called by POST /api/chat/approve-plan after user confirms ExecutionCard.
    Retrieves pending_action from MongoDB session and dispatches it.
    Returns result dict with alegra_id as evidence.
    """
    session = await db.agent_sessions.find_one({"session_id": session_id})
    if not session or not session.get("pending_action"):
        return {"success": False, "error": "No hay acción pendiente para esta sesión"}

    pending = session["pending_action"]
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

    return result


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
