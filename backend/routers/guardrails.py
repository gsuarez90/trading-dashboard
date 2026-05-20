import os
from datetime import date

from fastapi import APIRouter, HTTPException

from services import dynamo_service, guardrail_service
from services.guardrail_service import GuardrailContext

router = APIRouter(prefix="/guardrails", tags=["guardrails"])


def _build_context(**overrides) -> GuardrailContext:
    today = date.today().isoformat()
    return GuardrailContext(
        cash=overrides.get("cash", 0.0),
        realized_pnl_today=dynamo_service.get_realized_pnl_today(today),
        trade_count_today=dynamo_service.get_trade_count_today(today),
        trading_mode=os.environ.get("TRADING_MODE", "paper"),
    )


@router.get("/status")
def get_status():
    try:
        ctx = _build_context()
        return guardrail_service.get_status(ctx)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Guardrail status failed: {e}")


@router.post("/kill-switch")
def kill_switch(confirmed: bool = False):
    try:
        trading_mode = os.environ.get("TRADING_MODE", "paper")
        return guardrail_service.trigger_kill_switch(confirmed=confirmed, trading_mode=trading_mode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kill switch failed: {e}")
