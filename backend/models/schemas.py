from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

# ── Claude trade suggestion models ───────────────────────────────────────────


class TradeSetup(BaseModel):
    instrument_type: Literal["equity"] = "equity"
    multiplier: int = 1
    ticker: str
    direction: str  # "long" | "short"
    trade_type: str  # "intraday_cash" | "swing" | "partial_trim"
    profit_mode: str
    entry_price: float
    target_price: float
    stop_loss: float
    shares: int
    expected_gain: float
    max_loss: float
    reward_risk_ratio: float  # minimum 1.5
    confidence: str  # "high" | "medium" | "low"
    rationale: str
    setup_type: str
    uses_existing_holding: bool
    cost_basis: float | None
    current_unrealized_pnl: float | None
    avg_daily_range_pct: float | None
    robinhood_instructions: str  # plain english steps for manual placement
    ml_probability: float | None  # Phase 2
    ml_calibration_note: str | None  # Phase 2

    @model_validator(mode="after")
    def _recompute_gain_risk(self) -> "TradeSetup":
        """Claude self-reports expected_gain/max_loss/reward_risk_ratio and its
        arithmetic is not reliable — recompute from entry/target/stop/shares so
        the numbers are always internally consistent with the rest of the setup.
        """
        if self.direction == "short":
            gain_per_share = self.entry_price - self.target_price
            loss_per_share = self.stop_loss - self.entry_price
        else:
            gain_per_share = self.target_price - self.entry_price
            loss_per_share = self.entry_price - self.stop_loss

        self.expected_gain = round(gain_per_share * self.shares, 2)
        self.max_loss = round(loss_per_share * self.shares, 2)
        if self.max_loss > 0:
            self.reward_risk_ratio = round(self.expected_gain / self.max_loss, 2)
        return self


class OptionTradeSetup(BaseModel):
    """Long call/put suggestion — intraday-options-pivot-plan.md /
    options-trade-suggestions-plan.md. Always a long position (buy to open,
    sell to close): option_type carries the directional view on the
    underlying, direction stays "long" for both calls and puts so the
    existing long-side fill/close comparison in run_price_monitor() applies
    unmodified (pivot plan §3.3). Reuses entry_price/target_price/stop_loss
    to mean premium-per-share and shares to mean contracts, matching
    TradeSetup's field semantics rather than inventing a parallel vocabulary
    — only multiplier (100 vs. 1) and the option-specific fields below are
    new (additive plan §3.2).

    Also carries the same "generic" fields the 8 existing guardrail checks
    and paper-trade lifecycle read off any trade (trade_type, profit_mode,
    uses_existing_holding, cost_basis, etc.) with option-appropriate
    defaults, so those checks run against an option trade unmodified — no
    "existing holding to average into" concept exists for a same-day long
    option, so uses_existing_holding/cost_basis default to
    False/None and cost_basis_protection is expected to no-op.
    """

    instrument_type: Literal["option"] = "option"
    ticker: str  # underlying symbol
    option_symbol: str  # OCC-format contract symbol (for quote lookups)
    option_type: str  # "call" | "put"
    direction: Literal["long"] = "long"
    trade_type: str  # "intraday_cash" | "swing" | "partial_trim"
    profit_mode: str
    strike_price: float
    expiration_date: str  # ISO date
    days_to_expiration: int
    entry_price: float  # premium per share at entry
    target_price: float  # premium per share, take-profit
    stop_loss: float  # premium per share, stop
    shares: int  # contracts
    multiplier: int = 100
    breakeven_price: float
    delta_at_entry: float | None
    implied_volatility_at_entry: float | None
    bid_ask_spread_pct: float | None
    open_interest: int | None
    volume: int | None
    underlying_price_at_entry: float
    expected_gain: float
    max_loss: float
    reward_risk_ratio: float  # minimum 1.5
    confidence: str  # "high" | "medium" | "low"
    rationale: str
    setup_type: str  # "breakout" | "pullback_reclaim" | "breakdown" | "pulldown_reclaim"
    uses_existing_holding: bool = False
    cost_basis: float | None = None
    current_unrealized_pnl: float | None = None
    avg_daily_range_pct: float | None = None
    robinhood_instructions: str
    ml_probability: float | None = None
    ml_calibration_note: str | None = None

    @model_validator(mode="after")
    def _recompute_gain_risk(self) -> "OptionTradeSetup":
        """Same recompute-from-prices discipline as TradeSetup — never trust
        Claude's own math — scaled by multiplier (contract = 100 shares).
        Also derives breakeven_price rather than trusting Claude's report:
        strike + premium for a call, strike - premium for a put.
        """
        gain_per_contract = self.target_price - self.entry_price
        loss_per_contract = self.entry_price - self.stop_loss

        self.expected_gain = round(gain_per_contract * self.shares * self.multiplier, 2)
        self.max_loss = round(loss_per_contract * self.shares * self.multiplier, 2)
        if self.max_loss > 0:
            self.reward_risk_ratio = round(self.expected_gain / self.max_loss, 2)

        self.breakeven_price = round(
            (
                self.strike_price + self.entry_price
                if self.option_type == "call"
                else self.strike_price - self.entry_price
            ),
            2,
        )
        return self


TradeSetupAny = Annotated[TradeSetup | OptionTradeSetup, Field(discriminator="instrument_type")]


class TradeSuggestionResponse(BaseModel):
    goal: float
    profit_mode: str
    trade_scope: str
    suggestions: list[TradeSetupAny]
    risk_note: str
    market_conditions: str
    intraday_viability: str | None
    recommended: TradeSetupAny | None
    guardrails_checked: list[str]
    any_guardrail_triggered: bool
    # Phase 0 shadow mode (intraday-options-pivot-plan.md §7) — the option-equivalent
    # of each qualifying setup (bullish or bearish), for calibration only. Never
    # surfaced as a recommendation; suggestions/recommended stay equity-only and
    # unchanged while this is populated.
    shadow_option_suggestions: list[OptionTradeSetup] = []


# ── DynamoDB trade record ─────────────────────────────────────────────────────


class PaperTrade(BaseModel):
    trade_id: str  # UUID, DynamoDB partition key
    date: str  # YYYY-MM-DD, GSI key
    instrument_type: str = "equity"  # "equity" | "option"
    multiplier: int = 1  # 1 for equity, 100 for options — see close_trade()
    ticker: str
    direction: str  # "long" | "short"
    trade_type: str  # "intraday_cash" | "swing"
    shares: int
    entry_price: float  # actual fill price; equals limit_price until filled
    target_price: float
    stop_loss: float
    expected_gain: float
    max_loss: float
    reward_risk_ratio: float
    confidence: str
    rationale: str
    # Option-only fields — None for equity trades
    option_symbol: str | None = None  # OCC-format contract symbol
    option_type: str | None = None  # "call" | "put"
    strike_price: float | None = None
    expiration_date: str | None = None  # ISO date
    days_to_expiration: int | None = None
    breakeven_price: float | None = None
    delta_at_entry: float | None = None
    implied_volatility_at_entry: float | None = None
    bid_ask_spread_pct: float | None = None
    open_interest: int | None = None
    volume: int | None = None
    underlying_price_at_entry: float | None = None
    setup_type: str
    # "shadow_open"/"shadow_closed" (mode="shadow") are Phase 0 calibration-only
    # records (intraday-options-pivot-plan.md §7) — a distinct status namespace
    # so they are never picked up by get_open_trades()/get_trades_by_date(),
    # which drive real guardrails, P&L, and the dashboard. See
    # dynamo_service.get_shadow_open_trades() / paper_trading_service.log_shadow_trade().
    status: str  # "pending" | "open" | "closed" | "expired" | "shadow_open" | "shadow_closed"
    mode: str  # "paper" | "live" | "shadow"
    limit_price: float | None = None  # Claude's suggested entry; set at placement
    pending_since: str | None = None  # ISO timestamp when order was queued
    entry_time: str | None = None  # ISO timestamp when order filled
    entry_slippage: float | None = None  # entry_price - limit_price at fill
    exit_price: float | None = None
    exit_time: str | None = None
    realized_pnl: float | None = None
    close_reason: str | None = (
        None  # "target_hit" | "stop_hit" | "manual" | "eod_close" | "kill_switch" | "expired"
    )


# ── Daily summary ─────────────────────────────────────────────────────────────


class DailyCashSummary(BaseModel):
    date: str
    goal: float
    realized_pnl: float
    cumulative_pnl: float = 0.0
    open_positions: int
    goal_hit: bool
    goal_hit_time: str | None
    settlement_note: str
    trading_mode: str


# ── Phase 2 (defined now so imports don't break later) ───────────────────────


class ValidationResult(BaseModel):
    date: str
    paper_pnl: float
    spy_pnl: float | None = None
    random_pnl: float | None = None
    beat_spy: bool | None = None
    beat_random: bool | None = None
    slippage_adjusted_pnl: float | None = None
