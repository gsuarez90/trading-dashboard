import os
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

ET = ZoneInfo("America/New_York")
from pydantic import BaseModel

from models.schemas import DailyCashSummary, PaperTrade, TradeSetup
from services import dynamo_service, paper_trading_service, portfolio_factory

router = APIRouter(prefix="/paper-trades", tags=["paper-trades"])


class OpenTradeRequest(BaseModel):
    setup: TradeSetup
    allow_loss: bool = False


class CloseTradeRequest(BaseModel):
    exit_price: float
    close_reason: str = "manual"


@router.post("", response_model=PaperTrade)
def open_trade(request: OpenTradeRequest):
    try:
        cash = portfolio_factory.get_provider().get_cash()
        trading_mode = os.environ.get("TRADING_MODE", "paper")
        return paper_trading_service.open_trade(
            request.setup, cash, trading_mode, request.allow_loss
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Open trade failed: {e}")


@router.get("/pending")
def list_pending(date: str = Query(default=None)):
    try:
        today = date or datetime.now(tz=ET).strftime("%Y-%m-%d")
        return dynamo_service.get_pending_trades_for_date(today)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"List pending failed: {e}")


@router.get("/summary", response_model=DailyCashSummary)
def get_summary(date: str = Query(default=None)):
    try:
        today = date or datetime.now(tz=ET).strftime("%Y-%m-%d")
        trading_mode = os.environ.get("TRADING_MODE", "paper")
        return paper_trading_service.get_daily_summary(today, trading_mode)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Summary failed: {e}")


@router.get("")
def list_trades(date: str = Query(default=None)):
    try:
        today = date or datetime.now(tz=ET).strftime("%Y-%m-%d")
        return dynamo_service.get_trades_by_date(today)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"List trades failed: {e}")


@router.get("/{trade_id}")
def get_trade(trade_id: str):
    trade = dynamo_service.get_trade(trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
    return trade


@router.post("/{trade_id}/close")
def close_trade(trade_id: str, request: CloseTradeRequest):
    try:
        return paper_trading_service.close_trade(trade_id, request.exit_price, request.close_reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Close trade failed: {e}")
