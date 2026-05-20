from fastapi import APIRouter, HTTPException

from services import claude_service
from services.context_loader import load_context

router = APIRouter(prefix="/ai", tags=["ai"])


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
