import os
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from models.schemas import DailyCashSummary, PaperTrade, TradeSetup
from services import dynamo_service
from services.guardrail_service import GuardrailContext, check_all

ET = ZoneInfo("America/New_York")


def _live_trades_by_date(today: str) -> list[dict]:
    return [t for t in dynamo_service.get_trades_by_date(today) if t.get("mode") == "live"]


def log_trade(
    setup: TradeSetup,
    cash: float,
    allow_loss: bool = False,
    now: datetime | None = None,
) -> PaperTrade:
    """Log a live trade that was manually placed in Robinhood.

    Requires TRADING_MODE=live — raises if called in paper mode.
    Runs the full guardrail suite before persisting (same code path as paper).
    now is injectable for deterministic test control.
    """
    trading_mode = os.environ.get("TRADING_MODE", "paper")
    if trading_mode != "live":
        raise ValueError(
            "Live trade logging requires TRADING_MODE=live. "
            "Current mode is paper — use POST /paper-trades to log a paper trade."
        )

    now_et = (
        (now.replace(tzinfo=ET) if now.tzinfo is None else now.astimezone(ET))
        if now is not None
        else datetime.now(tz=ET)
    )
    today = now_et.strftime("%Y-%m-%d")

    realized_pnl_today = dynamo_service.get_realized_pnl_today(today)
    trade_count_today = dynamo_service.get_trade_count_today(today)

    ctx = GuardrailContext(
        cash=cash,
        realized_pnl_today=realized_pnl_today,
        trade_count_today=trade_count_today,
        trading_mode=trading_mode,
        allow_loss=allow_loss,
        now=now_et,
    )
    result = check_all(setup, ctx)
    if not result.allowed:
        raise ValueError(
            f"Trade blocked: {', '.join(result.triggered)}. {'; '.join(result.messages)}"
        )

    trade = PaperTrade(
        trade_id=str(uuid.uuid4()),
        date=today,
        ticker=setup.ticker,
        direction=setup.direction,
        trade_type=setup.trade_type,
        shares=setup.shares,
        entry_price=setup.entry_price,
        target_price=setup.target_price,
        stop_loss=setup.stop_loss,
        expected_gain=setup.expected_gain,
        max_loss=setup.max_loss,
        reward_risk_ratio=setup.reward_risk_ratio,
        confidence=setup.confidence,
        rationale=setup.rationale,
        setup_type=setup.setup_type,
        entry_time=now_et.isoformat(),
        status="open",
        mode="live",
    )
    dynamo_service.put_trade(trade)
    return trade


def log_exit(trade_id: str, exit_price: float, close_reason: str = "manual") -> dict:
    """Record that the user manually closed a live trade in Robinhood."""
    trade = dynamo_service.get_trade(trade_id)
    if trade is None:
        raise ValueError(f"Trade {trade_id} not found")
    if trade.get("mode") != "live":
        raise ValueError(
            f"Trade {trade_id} is a paper trade — use POST /paper-trades/{{id}}/close instead"
        )
    if trade.get("status") != "open":
        raise ValueError(f"Trade {trade_id} is already closed")

    shares = trade["shares"]
    entry_price = trade["entry_price"]
    direction = trade["direction"]

    if direction == "long":
        realized_pnl = round((exit_price - entry_price) * shares, 2)
    else:
        realized_pnl = round((entry_price - exit_price) * shares, 2)

    updates = {
        "status": "closed",
        "exit_price": exit_price,
        "exit_time": datetime.now(tz=ET).isoformat(),
        "realized_pnl": realized_pnl,
        "close_reason": close_reason,
    }
    dynamo_service.update_trade(trade_id, updates)
    return {**trade, **updates}


def get_live_summary(today: str) -> DailyCashSummary:
    """Aggregate today's live trade results. Excludes paper trades."""
    trades = _live_trades_by_date(today)
    open_positions = sum(1 for t in trades if t.get("status") == "open")
    closed = [t for t in trades if t.get("status") != "open"]
    realized_pnl = round(sum(t.get("realized_pnl", 0) or 0 for t in closed), 2)

    goal = float(os.environ.get("DAILY_GOAL", 100))
    goal_hit = realized_pnl >= goal

    goal_hit_time = None
    if goal_hit:
        running = 0.0
        for t in sorted(closed, key=lambda x: x.get("exit_time", "") or ""):
            running += t.get("realized_pnl", 0) or 0
            if running >= goal:
                goal_hit_time = t.get("exit_time")
                break

    return DailyCashSummary(
        date=today,
        goal=goal,
        realized_pnl=realized_pnl,
        open_positions=open_positions,
        goal_hit=goal_hit,
        goal_hit_time=goal_hit_time,
        settlement_note="Live trades settle T+2",
        trading_mode="live",
    )
