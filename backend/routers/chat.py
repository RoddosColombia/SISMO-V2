"""
Chat router -- POST /api/chat (SSE) + POST /api/chat/approve-plan (ExecutionCard).
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_db
from core.auth import get_current_user
from agents.chat import process_chat

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    agent_type: str | None = None
    session_id: str | None = None
    current_agent: str | None = None
    correlation_id: str | None = None


class ApproveRequest(BaseModel):
    session_id: str
    confirmed: bool


@router.post("")
async def chat_endpoint(
    request: ChatRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Stream agent response as Server-Sent Events."""
    return StreamingResponse(
        process_chat(
            message=request.message,
            db=db,
            agent_type=request.agent_type,
            session_id=request.session_id,
            current_agent=request.current_agent,
            correlation_id=request.correlation_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/approve-plan")
async def approve_plan(
    request: ApproveRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Execute or cancel a pending tool action from ExecutionCard.
    The actual tool execution logic is implemented in Phase 2+ per each tool.
    For Phase 1: validates the pending action exists and returns a stub response.

    Security (T-02-02): tool_input comes from agent_sessions (set by agent), not from
    request body -- user cannot inject arbitrary tool_input via this endpoint.
    """
    session = await db.agent_sessions.find_one({"session_id": request.session_id})
    if not session or not session.get("pending_action"):
        raise HTTPException(status_code=404, detail="No hay accion pendiente para esta sesion.")

    pending = session["pending_action"]

    if not request.confirmed:
        await db.agent_sessions.update_one(
            {"session_id": request.session_id},
            {"$unset": {"pending_action": ""}},
        )
        return {"status": "cancelado", "message": "Accion cancelada por el usuario."}

    # Phase 1: Return the pending action for confirmation (tool execution in Phase 2+)
    # The tool executor will be wired here in subsequent plans
    return {
        "status": "pendiente_ejecucion",
        "tool_name": pending["tool_name"],
        "tool_input": pending["tool_input"],
        "message": (
            f"Accion '{pending['tool_name']}' confirmada. "
            "La ejecucion se implementa en la siguiente fase."
        ),
    }
