from __future__ import annotations

from pydantic import BaseModel, model_validator

# ── Claude trade suggestion models ───────────────────────────────────────────


class TradeSetup(BaseModel):
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


class TradeSuggestionResponse(BaseModel):
    goal: float
    profit_mode: str
    trade_scope: str
    suggestions: list[TradeSetup]
    risk_note: str
    market_conditions: str
    intraday_viability: str | None
    recommended: TradeSetup | None
    guardrails_checked: list[str]
    any_guardrail_triggered: bool


# ── DynamoDB trade record ─────────────────────────────────────────────────────


class PaperTrade(BaseModel):
    trade_id: str  # UUID, DynamoDB partition key
    date: str  # YYYY-MM-DD, GSI key
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
    setup_type: str
    status: str  # "pending" | "open" | "closed" | "expired"
    mode: str  # "paper" | "live"
    limit_price: float | None = None  # Claude's suggested entry; set at placement
    pending_since: str | None = None  # ISO timestamp when order was queued
    entry_time: str | None = None  # ISO timestamp when order filled
    entry_slippage: float | None = None  # entry_price - limit_price at fill
    exit_price: float | None = None
    exit_time: str | None = None
    realized_pnl: float | None = None
    close_reason: str | None = (
        None  # "target_hit" | "stop_hit" | "manual" | "eod_close" | "kill_switch"
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
