from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models.schemas import TradeSuggestionResponse
from services import claude_service
from services.context_loader import load_context

router = APIRouter(prefix="/ai", tags=["ai"])


class ChatRequest(BaseModel):
    message: str


class SuggestTradesRequest(BaseModel):
    message: str = "Suggest trades based on today's context."
    allow_loss: bool = False


@router.get("/briefing")
def get_briefing():
    try:
        ctx = load_context()
        briefing = claude_service.morning_briefing(ctx)
        return {
            "briefing": briefing,
            "date": ctx.date,
            "minutes_remaining": ctx.minutes_remaining,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Briefing failed: {e}")


@router.post("/chat")
def chat(request: ChatRequest):
    try:
        ctx = load_context()
        reply = claude_service.chat(ctx, request.message)
        return {"reply": reply, "date": ctx.date}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Chat failed: {e}")


@router.post("/suggest-trades", response_model=TradeSuggestionResponse)
def suggest_trades(request: SuggestTradesRequest):
    try:
        ctx = load_context()
        return claude_service.suggest_trades(ctx, request.message, request.allow_loss)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Trade suggestion failed: {e}")
