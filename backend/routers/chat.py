"""
Chat router -- POST /api/chat (SSE) + POST /api/chat/approve-plan (ExecutionCard).
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_db
from core.auth import get_current_user
from agents.chat import process_chat, execute_approved_action

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    agent_type: str | None = None
    session_id: str | None = None
    current_agent: str | None = None
    correlation_id: str | None = None
    imagen: str | None = None       # base64 data URI (data:image/jpeg;base64,...)
    pdf_base64: str | None = None   # base64-encoded PDF (sin prefijo data URI)


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
            imagen=request.imagen,
            pdf_base64=request.pdf_base64,
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

    Security (T-02-02): tool_input comes from agent_sessions (set by agent), not from
    request body -- user cannot inject arbitrary tool_input via this endpoint.
    """
    session = await db.agent_sessions.find_one({"session_id": request.session_id})
    if not session or not session.get("pending_action"):
        raise HTTPException(status_code=404, detail="No hay accion pendiente para esta sesion.")

    if not request.confirmed:
        await db.agent_sessions.update_one(
            {"session_id": request.session_id},
            {"$unset": {"pending_action": ""}},
        )
        return {"status": "cancelado", "message": "Accion cancelada por el usuario."}

    # Create agent-appropriate dispatcher based on the session's agent_type
    agent_type = session.get("agent_type", "contador")
    if agent_type == "loanbook":
        from agents.loanbook.handlers.dispatcher import LoanToolDispatcher
        dispatcher = LoanToolDispatcher(db=db)
    else:
        from services.alegra.client import AlegraClient
        from agents.contador.handlers import ToolDispatcher
        alegra = AlegraClient(db=db)
        dispatcher = ToolDispatcher(alegra=alegra, db=db, event_bus=None)

    result = await execute_approved_action(request.session_id, db, dispatcher)
    return result
