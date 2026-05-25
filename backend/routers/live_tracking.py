import os
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

ET = ZoneInfo("America/New_York")
from pydantic import BaseModel

from models.schemas import DailyCashSummary, PaperTrade, TradeSetup
from services import dynamo_service, live_tracking_service, portfolio_factory

router = APIRouter(prefix="/live-trades", tags=["live-trades"])


class LogTradeRequest(BaseModel):
    setup: TradeSetup
    allow_loss: bool = False


class LogExitRequest(BaseModel):
    exit_price: float
    close_reason: str = "manual"


@router.post("", response_model=PaperTrade)
def log_trade(request: LogTradeRequest):
    try:
        cash = portfolio_factory.get_provider().get_cash()
        return live_tracking_service.log_trade(request.setup, cash, request.allow_loss)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Log trade failed: {e}")


@router.get("/summary", response_model=DailyCashSummary)
def get_summary(date: str = Query(default=None)):
    try:
        today = date or datetime.now(tz=ET).strftime("%Y-%m-%d")
        return live_tracking_service.get_live_summary(today)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Summary failed: {e}")


@router.get("")
def list_trades(date: str = Query(default=None)):
    try:
        today = date or datetime.now(tz=ET).strftime("%Y-%m-%d")
        trades = dynamo_service.get_trades_by_date(today)
        return [t for t in trades if t.get("mode") == "live"]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"List trades failed: {e}")


@router.get("/{trade_id}")
def get_trade(trade_id: str):
    trade = dynamo_service.get_trade(trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
    return trade


@router.post("/{trade_id}/exit")
def log_exit(trade_id: str, request: LogExitRequest):
    try:
        return live_tracking_service.log_exit(trade_id, request.exit_price, request.close_reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Log exit failed: {e}")
