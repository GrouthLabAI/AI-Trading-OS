# AI Trading OS - Chat API
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.llm_adapter import get_llm

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []  # [{"role": "user"|"assistant", "content": "..."}]


class ChatResponse(BaseModel):
    reply: str


# ---------------------------------------------------------------------------
# Non-streaming chat endpoint (used by agents internally)
# ---------------------------------------------------------------------------

@router.post("/", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send a message and get a full AI response."""
    try:
        llm = get_llm()
        messages = req.history + [{"role": "user", "content": req.message}]
        reply = await llm.chat(messages)
        return ChatResponse(reply=reply)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM error: {str(e)}")


# ---------------------------------------------------------------------------
# Streaming chat endpoint (used by the frontend Chat UI)
# ---------------------------------------------------------------------------

@router.post("/stream")
async def chat_stream(req: ChatRequest):
    """Send a message and stream the AI response token-by-token via SSE."""
    try:
        llm = get_llm()
        messages = req.history + [{"role": "user", "content": req.message}]

        async def event_stream():
            try:
                async for token in llm.chat_stream(messages):
                    # JSON-encode each token to preserve \n, \r, etc.
                    yield f"data: {json.dumps(token)}\n\n"
                yield f"data: {json.dumps('[DONE]')}\n\n"
            except Exception as e:
                yield f"data: {json.dumps(f'[ERROR] {str(e)}')}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
