import os
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from models.schemas import DailyCashSummary, PaperTrade, TradeSetup
from services import dynamo_service
from services.guardrail_service import GuardrailContext, check_all

ET = ZoneInfo("America/New_York")


def open_trade(
    setup: TradeSetup,
    cash: float,
    trading_mode: str,
    allow_loss: bool = False,
    now: datetime | None = None,
) -> PaperTrade:
    """Run guardrails, then persist a new trade record.

    now is injectable so tests can control market-hours checks without hitting
    real wall-clock time.
    """
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
        try:
            dynamo_service.log_guardrail_event(
                ticker=setup.ticker,
                rules_triggered=result.triggered,
                messages=result.messages,
                date=today,
                timestamp=now_et.isoformat(),
            )
        except Exception:
            pass
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
        mode=trading_mode,
    )
    dynamo_service.put_trade(trade)
    return trade


def close_trade(trade_id: str, exit_price: float, close_reason: str = "manual") -> dict:
    """Close an open trade and calculate realized P&L."""
    trade = dynamo_service.get_trade(trade_id)
    if trade is None:
        raise ValueError(f"Trade {trade_id} not found")
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


def get_daily_summary(today: str, trading_mode: str) -> DailyCashSummary:
    """Aggregate today's trade results into a DailyCashSummary."""
    trades = dynamo_service.get_trades_by_date(today)
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

    settlement_note = (
        "Intraday cash — settles T+1" if trading_mode == "paper" else "Live trades settle T+2"
    )

    return DailyCashSummary(
        date=today,
        goal=goal,
        realized_pnl=realized_pnl,
        open_positions=open_positions,
        goal_hit=goal_hit,
        goal_hit_time=goal_hit_time,
        settlement_note=settlement_note,
        trading_mode=trading_mode,
    )
