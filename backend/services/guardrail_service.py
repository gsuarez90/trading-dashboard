import os
from dataclasses import dataclass, field
from datetime import datetime, time
from zoneinfo import ZoneInfo

from models.schemas import TradeSetupAny
from services import dynamo_service

ET = ZoneInfo("America/New_York")
_MARKET_OPEN = time(9, 30)
_MARKET_CLOSE = time(16, 0)
_INTRADAY_CUTOFF = time(15, 30)  # intraday trades need >= 30 min remaining


# ── Context + Result types ────────────────────────────────────────────────────


@dataclass
class GuardrailContext:
    cash: float
    realized_pnl_today: float
    trade_count_today: int
    trading_mode: str  # "paper" | "live"
    allow_loss: bool = False
    now: datetime | None = None  # injectable for tests — naive or tz-aware

    def current_et(self) -> datetime:
        if self.now is not None:
            if self.now.tzinfo is None:
                return self.now.replace(tzinfo=ET)
            return self.now.astimezone(ET)
        return datetime.now(tz=ET)


@dataclass
class GuardrailResult:
    allowed: bool
    triggered: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


# ── Individual guardrail checks ───────────────────────────────────────────────


def _check_daily_loss_limit(trade, ctx: GuardrailContext) -> tuple[bool, str]:
    # $1,500 default (up from equity-only $200) — sized for $1k-$6k option
    # positions under the options pivot (intraday-options-pivot-plan.md §1).
    # Shared counter across equity and option trades, not per-instrument.
    limit = float(os.environ.get("DAILY_LOSS_LIMIT", 1500))
    if ctx.realized_pnl_today <= -limit:
        return True, (
            f"Daily loss limit reached "
            f"(${abs(ctx.realized_pnl_today):.2f} lost of ${limit:.2f} limit)"
        )
    return False, ""


def _check_position_size(trade, ctx: GuardrailContext) -> tuple[bool, str]:
    max_pct = float(os.environ.get("MAX_POSITION_SIZE_PCT", 20)) / 100
    max_allowed = ctx.cash * max_pct
    position_value = trade.entry_price * trade.shares * trade.multiplier
    if position_value > max_allowed:
        return True, (
            f"Position ${position_value:.2f} exceeds "
            f"{max_pct * 100:.0f}% of cash (${max_allowed:.2f})"
        )
    return False, ""


def _check_cost_basis(trade: TradeSetupAny, ctx: GuardrailContext) -> tuple[bool, str]:
    if not trade.uses_existing_holding:
        return False, ""
    if ctx.allow_loss:
        return False, ""
    if trade.cost_basis is None:
        return False, ""
    if trade.entry_price < trade.cost_basis:
        return True, (
            f"Entry ${trade.entry_price:.2f} below cost basis "
            f"${trade.cost_basis:.2f} — pass allow_loss=true to override"
        )
    return False, ""


def _check_reward_risk(trade: TradeSetupAny, ctx: GuardrailContext) -> tuple[bool, str]:
    if trade.reward_risk_ratio < 1.5:
        return True, (f"Reward/risk {trade.reward_risk_ratio:.2f} is below minimum 1.5")
    return False, ""


def _check_daily_trade_limit(trade, ctx: GuardrailContext) -> tuple[bool, str]:
    # PDT rule does not apply when account equity exceeds $25k — set PDT_EXEMPT=true in SSM
    if os.environ.get("PDT_EXEMPT", "false").lower() == "true":
        return False, ""
    # 2 default (down from 3) — options pivot decision (§1, §8 Q7). One
    # shared counter across equity and option trades, not per-instrument —
    # at the top of the $1k-$6k option sizing band, a single full-sized loss
    # can still consume most of the daily_loss_limit budget, so "2" functions
    # as a ceiling more than a guarantee of two independent full-sized
    # attempts for larger trades (smaller ones have much more headroom).
    limit = int(os.environ.get("DAILY_TRADE_LIMIT", 2))
    if ctx.trade_count_today >= limit:
        return True, f"Daily trade limit reached ({ctx.trade_count_today}/{limit})"
    return False, ""


def _check_market_hours(trade, ctx: GuardrailContext) -> tuple[bool, str]:
    now_et = ctx.current_et()
    if now_et.weekday() >= 5:
        return True, "Market is closed (weekend)"
    t = now_et.time()
    if t < _MARKET_OPEN or t >= _MARKET_CLOSE:
        return True, (
            f"Outside market hours — 9:30am–4:00pm ET only "
            f"(current: {t.strftime('%I:%M %p')} ET)"
        )
    return False, ""


def _check_intraday_cutoff(trade: TradeSetupAny, ctx: GuardrailContext) -> tuple[bool, str]:
    if trade.trade_type != "intraday_cash":
        return False, ""
    now_et = ctx.current_et()
    if now_et.time() >= _INTRADAY_CUTOFF:
        return True, "Less than 30 minutes left in session — intraday trade blocked"
    return False, ""


def _check_buying_power(trade, ctx: GuardrailContext) -> tuple[bool, str]:
    position_value = trade.entry_price * trade.shares * trade.multiplier
    if position_value > ctx.cash:
        return True, (
            f"Insufficient cash — need ${position_value:.2f}, " f"available ${ctx.cash:.2f}"
        )
    return False, ""


def _check_option_liquidity(trade, ctx: GuardrailContext) -> tuple[bool, str]:
    """No-ops for equity trades. Wide spreads/thin open interest produce
    unrealistic paper-trade fills and are unrealistic to execute live —
    options-trade-suggestions-plan.md §3.7."""
    if trade.instrument_type != "option":
        return False, ""
    max_spread_pct = float(os.environ.get("OPTION_MAX_SPREAD_PCT", 15))
    min_open_interest = int(os.environ.get("OPTION_MIN_OPEN_INTEREST", 50))
    if trade.bid_ask_spread_pct is not None and trade.bid_ask_spread_pct > max_spread_pct:
        return True, (
            f"Bid-ask spread {trade.bid_ask_spread_pct:.1f}% exceeds " f"{max_spread_pct:.0f}% max"
        )
    if trade.open_interest is not None and trade.open_interest < min_open_interest:
        return True, f"Open interest {trade.open_interest} below minimum {min_open_interest}"
    return False, ""


def _check_expiration_proximity(trade, ctx: GuardrailContext) -> tuple[bool, str]:
    """No-ops for equity trades. Enforces both the options pivot's 7-day
    min-DTE floor (gentle enough theta/gamma for a setup that takes 20-40
    minutes to confirm, even though the position exits same-day regardless)
    and its ~3-week max-DTE ceiling (keeps cash_intraday distinct from a
    future swing-mode option) — intraday-options-pivot-plan.md §1, §6."""
    if trade.instrument_type != "option":
        return False, ""
    min_dte = int(os.environ.get("OPTION_MIN_DTE", 7))
    max_dte = int(os.environ.get("OPTION_MAX_DTE", 21))
    if trade.days_to_expiration < min_dte:
        return True, (
            f"{trade.days_to_expiration} days to expiration is below the " f"{min_dte}-day minimum"
        )
    if trade.days_to_expiration > max_dte:
        return True, (
            f"{trade.days_to_expiration} days to expiration exceeds the " f"{max_dte}-day maximum"
        )
    return False, ""


# ── Public API ────────────────────────────────────────────────────────────────

_CHECKS = [
    ("daily_loss_limit", _check_daily_loss_limit),
    ("position_size_cap", _check_position_size),
    ("cost_basis_protection", _check_cost_basis),
    ("reward_risk_minimum", _check_reward_risk),
    ("daily_trade_limit", _check_daily_trade_limit),
    ("market_hours_lock", _check_market_hours),
    ("intraday_30min_cutoff", _check_intraday_cutoff),
    ("buying_power_check", _check_buying_power),
    ("option_liquidity_check", _check_option_liquidity),
    ("expiration_proximity", _check_expiration_proximity),
]


def check_all(trade: TradeSetupAny, ctx: GuardrailContext) -> GuardrailResult:
    """Run all 10 guardrails. Same code path for paper and live trading."""
    triggered = []
    messages = []
    for name, fn in _CHECKS:
        fired, msg = fn(trade, ctx)
        if fired:
            triggered.append(name)
            messages.append(msg)
    return GuardrailResult(allowed=not triggered, triggered=triggered, messages=messages)


def get_status(ctx: GuardrailContext) -> dict:
    """Returns current guardrail status without a specific trade — used by the dashboard."""
    limit = float(os.environ.get("DAILY_LOSS_LIMIT", 1500))
    trade_limit = int(os.environ.get("DAILY_TRADE_LIMIT", 2))
    pdt_exempt = os.environ.get("PDT_EXEMPT", "false").lower() == "true"
    now_et = ctx.current_et()
    t = now_et.time()
    in_market_hours = now_et.weekday() < 5 and _MARKET_OPEN <= t < _MARKET_CLOSE
    intraday_ok = t < _INTRADAY_CUTOFF if in_market_hours else False

    return {
        "daily_loss_limit": {
            "limit": limit,
            "realized_pnl_today": ctx.realized_pnl_today,
            "triggered": ctx.realized_pnl_today <= -limit,
        },
        "daily_trade_limit": {
            "limit": None if pdt_exempt else trade_limit,
            "trades_today": ctx.trade_count_today,
            "triggered": False if pdt_exempt else ctx.trade_count_today >= trade_limit,
            "pdt_exempt": pdt_exempt,
        },
        "market_hours": {
            "in_session": in_market_hours,
            "intraday_window_open": intraday_ok,
            "current_et": now_et.strftime("%I:%M %p ET"),
        },
        "trading_mode": ctx.trading_mode,
    }


def trigger_kill_switch(confirmed: bool, trading_mode: str) -> dict:
    """Closes all open paper trades and flags all open live trades for manual close.

    Requires confirmed=True — callers must pass explicit user confirmation.
    Same code path for paper and live.
    """
    if not confirmed:
        raise ValueError("Kill switch requires explicit confirmation (confirmed=True)")

    open_trades = dynamo_service.get_open_trades()
    now_iso = datetime.now(tz=ET).isoformat()
    paper_closed = 0
    live_flagged = 0

    for trade in open_trades:
        if trade.get("mode") == "paper":
            dynamo_service.update_trade(
                trade["trade_id"],
                {
                    "status": "closed",
                    "close_reason": "kill_switch",
                    "exit_time": now_iso,
                },
            )
            paper_closed += 1
        else:
            dynamo_service.update_trade(
                trade["trade_id"],
                {
                    "flagged_for_manual_close": True,
                    "kill_switch_time": now_iso,
                },
            )
            live_flagged += 1

    return {
        "paper_trades_closed": paper_closed,
        "live_trades_flagged": live_flagged,
        "timestamp": now_iso,
    }
