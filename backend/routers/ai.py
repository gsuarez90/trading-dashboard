from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models.schemas import TradeSuggestionResponse
from services import cache_service, claude_service
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
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from services.context_loader import _minutes_remaining

        now_et = datetime.now(tz=ZoneInfo("America/New_York"))
        cached = cache_service.get_cached_briefing()
        if cached:
            return {
                "briefing": cached["briefing"],
                "date": cached["date"],
                "minutes_remaining": _minutes_remaining(now_et),
            }
        # No cache — return null rather than calling load_context() + Claude (timeout risk)
        return {
            "briefing": None,
            "date": now_et.strftime("%Y-%m-%d"),
            "minutes_remaining": _minutes_remaining(now_et),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Briefing failed: {e}")


@router.get("/sentiment")
def get_sentiment():
    try:
        cached = cache_service.get_cached_sentiment()
        return {"sentiment": cached or []}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Sentiment failed: {e}")


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
