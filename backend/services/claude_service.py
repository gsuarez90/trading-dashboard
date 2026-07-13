import json
import logging
import os
import re

import anthropic

from models.schemas import TradeSuggestionResponse
from services import dynamo_service, finnhub_service, portfolio_factory, schwab_service
from services.context_loader import (
    DailyContext,
    _cached_scanner_results,
    _cached_sentiment,
    _enrich_positions,
    _get_watchlist,
)
from services.guardrail_service import GuardrailContext, check_all

_MODEL = "claude-sonnet-4-6"
logger = logging.getLogger(__name__)

_GUARDRAIL_NAMES = [
    "daily_loss_limit",
    "position_size_cap",
    "cost_basis_protection",
    "reward_risk_minimum",
    "daily_trade_limit",
    "market_hours_lock",
    "intraday_30min_cutoff",
    "buying_power_check",
    "option_liquidity_check",
    "expiration_proximity",
]

_BRIEFING_SYSTEM = """\
You are a personal trading analyst assistant for a retail day trader.
You will receive a JSON payload containing: scanner results, top intraday
movers, sentiment scores, portfolio holdings with cost basis and unrealized
P&L, available cash balance, logged trades today, realized P&L today,
guardrail status, and minutes remaining in the trading session.

Current settings:
- Profit mode: {profit_mode}
- Trade scope: {trade_scope}
- Daily goal: ${goal_dollars}

Produce a concise morning briefing:
1. Overall market conditions and intraday volatility today
2. Whether today supports the ${goal_dollars} goal safely
3. Top setups — constrained to trade_scope
4. Key risks
5. Holdings overlapping with today's setups
6. Honest assessment — if today looks poor for trading, say so

If profit_mode is cash_intraday, assess opening range setups via the 5-min technical_indicators:
note which tickers have bounce_setup=true (price above ORH + EMA(3) > EMA(6) + above VWAP) as
primary long candidates. Flag any ticker where price_below_orl=true as a structure to avoid.
Never suggest selling below cost basis unless allow_loss is true.
Plain text only, no markdown.\
"""

_CHAT_SYSTEM = """\
You are a personal trading analyst assistant. Full daily context is in
the payload including scanner results, intraday movers, sentiment,
portfolio with cost basis, cash balance, trade history, realized P&L,
guardrail status, guardrail_events (trades blocked today with ticker and rule), and minutes remaining in session.

Current settings:
- Profit mode: {profit_mode}
- Trade scope: {trade_scope}
- Daily goal: ${goal_dollars}

Answer the user's question concisely and accurately based on the daily context.
Never suggest selling below cost basis unless allow_loss is true.
Plain text only, no markdown.\
"""

# ── Options pivot (intraday-options-pivot-plan.md) — config-gated prompt sections ──
# INCLUDE_OPTIONS_SUGGESTIONS=true (default): options are the primary cash_intraday
# suggestion. Bullish structure (bounce_setup/pullback_setup) -> long call, falling
# back to the equity long if no viable contract exists. Bearish structure
# (breakdown_setup/pulldown_setup) -> long put, with no equity fallback (the equity
# system never shorts) — excluded entirely if no viable put exists. =false: an
# emergency kill switch back to the original equity-only, bullish-only behavior
# (bearish hard-excluded, no options tool at all) — same env-var pattern as
# PORTFOLIO_MODE/TRADING_MODE, not a staged rollout.

_BEARISH_HANDLING_EQUITY_ONLY = """\
- If price_below_orl is true, exclude that ticker entirely — bearish structure.
- Tickers where both bounce_setup and pullback_setup are false must be excluded from suggestions.\
"""

_BEARISH_HANDLING_WITH_OPTIONS = """\
- If price_below_orl is true, this is bearish structure — check breakdown_setup/pulldown_setup:
  if either is true, this ticker qualifies for a long PUT suggestion via the options-primary
  rule below (instrument_type="option") — never an equity suggestion, since the equity system
  never shorts.
- A ticker must show at least one true qualifier — bounce_setup, pullback_setup,
  breakdown_setup, or pulldown_setup — to appear in `suggestions` at all. Exclude it entirely
  if all four are false.\
"""

_OPTIONS_PRIMARY_SECTION = """
Options as the default cash_intraday expression (equity fallback for bullish only):
- Once you know which tickers qualify (bullish or bearish), call get_option_chain ONCE with
  every qualifying ticker in the same call (it accepts a list) — never call it once per ticker.
  Each call is a full round trip and the agentic loop has a limited number of turns; calling it
  per-ticker on a day with several qualifying setups can exhaust that budget before you ever
  reach submit_trade_suggestions.
- For a ticker that qualifies bullish (bounce_setup or pullback_setup), the default suggestion
  is a long CALL, not equity shares. Source real strikes, premiums, and Greeks from
  get_option_chain's response for that ticker — never invent option prices. Select the strike
  closest to a 0.40-0.60 delta (near-the-money), using the equity entry level described above
  as the reference underlying price.
- If no viable call exists for a bullish ticker — get_option_chain returned nothing usable for
  it, or every candidate would fail the liquidity/DTE guardrails (option_liquidity_check/
  expiration_proximity) — fall back to the equity long exactly as described above (shares, at
  the stated entry/stop levels, instrument_type="equity") instead of dropping the ticker. A
  good technical setup should never be thrown away just because the options side isn't
  tradeable that day.
- For a ticker that qualifies bearish (breakdown_setup or pulldown_setup), the suggestion is a
  long PUT, sourced the same way (0.40-0.60 delta near-the-money). There is no equity fallback
  for bearish — the equity system never shorts — so if no viable put exists, exclude the ticker
  entirely rather than suggesting anything.
- Only use expirations get_option_chain already returned — it only queries the 7-21 day
  window, so every contract you see already clears the floor/ceiling.
- Size contracts to a $1,000-$6,000 target capital band (scale toward $6k for high
  confidence, toward $1k for lower confidence): contracts = floor(target_dollars /
  (premium * 100)). This target band is what determines contract count — not the
  position size cap. The cap is a separate backstop that may allow a larger position;
  do not size up to it. If the cap is smaller than $1,000, size down to the cap instead.
- Stop loss at approximately -35% of entry premium; pick a target premium that keeps
  reward_risk_ratio >= 1.5 (same minimum as equity).
- multiplier is always 100 for options (1 for the equity fallback) — set instrument_type
  correctly ("option" vs "equity"), it determines how every downstream guardrail and P&L
  calculation scales.
- breakeven_price, expected_gain, max_loss, and reward_risk_ratio are recomputed server-side
  from your prices — report your best estimate, it will be corrected automatically.
- robinhood_instructions for an option must say "buy to open" at entry and "sell to close" at
  exit — never "exercise" — same 3:45pm alarm reminder pattern as equities.
- setup_type: "breakout" or "pullback_reclaim" for a bullish call (or the equity fallback),
  "breakdown" or "pulldown_reclaim" for a put.
"""

_OPTION_CHAIN_STEP = """\
5. get_option_chain — once you know every ticker that qualified via technical_indicators \
(bullish or bearish), call this ONCE with all of them together (it accepts a list of tickers) \
to price their call/put suggestions. Never call this per-ticker or to explore randomly — \
one batched call, not several.
"""

_SUGGESTION_SYSTEM = """\
You are a personal trading analyst assistant. You have tools to fetch live market data.
Call them in this recommended sequence before generating suggestions:
1. get_top_movers — identify today's active names
2. get_technical_indicators — pass the mover tickers plus TQQQ, SQQQ, IONZ, IONQ, NVDA, and SPCX
3. get_portfolio — current positions with enriched prices and P&L
4. get_sentiment — pass the tickers you are seriously considering
{option_chain_step}
Only call get_quotes or get_scanner_results if you need additional data.

Current settings:
- Profit mode: {profit_mode}
- Trade scope: {trade_scope}
- Daily goal: ${goal_dollars}

When generating trade suggestions:
- Respect trade_scope strictly
- Respect profit_mode:
  * cash_intraday: entry AND exit must happen today. Only suggest stocks
    with sufficient avg_daily_range_pct. Do not suggest with < 30 min left.
  * swing: overnight holds acceptable
  * holdings: partial trims and rebuys only
- Calculate position sizes from available cash and shares owned
- EQUITY sizing (applies only to an equity suggestion — either the equity
  fallback described in the options rules below, or every suggestion when
  INCLUDE_OPTIONS_SUGGESTIONS is off): target an expected_gain of $200 or more
  per trade when a qualifying setup allows it. Use as much of the position
  size cap as the setup and available cash support — don't leave cap headroom
  unused if more shares would bring expected_gain closer to $200 without
  breaking the reward/risk minimum. Prefer setups that can plausibly reach
  $200+ over marginal setups that fall well short of it. Never increase share
  count beyond the position size cap or loosen the stop-loss/reward-risk rules
  just to hit this number — it's fine to suggest a trade below $200 if no
  qualifying setup can reach it within the risk limits.
- OPTION sizing is completely different and does NOT follow the $200/
  max-the-cap rule above — an option suggestion targets the $1,000-$6,000
  capital band described in the options rules below, regardless of how much
  cap headroom is available. Do not size an option position to use up the
  position size cap; the cap is only a backstop, never the target.
- Use technical_indicators (5-min intraday) for setup qualification. Each ticker entry contains:
    orh: Opening Range High — high of the 9:30-9:35am opening candle (key support level)
    orl: Opening Range Low  — low of the 9:30-9:35am opening candle (breakdown level)
    ema_3, ema_6: exponential moving averages across all 5-min closes today
    vwap: cumulative volume-weighted average price since open
    rvol: current 1-min candle's volume vs the average volume per 1-min candle
      since the opening range. rvol above ~1 means volume is keeping pace with
      or exceeding the recent baseline; below ~1 means it's fading. This is
      informational only — weigh it in your rationale and confidence, but do
      not treat any specific rvol value as a hard requirement to qualify or
      reject a setup.
    peak_rvol: the highest rvol reading for this ticker so far today.
    rvol_pct_of_peak: current rvol as a fraction of peak_rvol (e.g. 0.75 means
      volume has cooled to 75% of today's peak). Use this to separate "never
      had real volume" (rvol and peak_rvol both low) from "spiked hard and is
      cooling off but still active" (current rvol looks unremarkable, but
      peak_rvol was high) — the latter can still support a trade even though
      the current rvol reading alone looks weak.
    pullback_from_high_pct: how far (in %) price has pulled back from its
      intraday high so far. A small pullback on an otherwise-bullish tape is
      normal consolidation; a large one is a genuine warning sign. This is a
      snapshot of where price is right now — it can look calm even after a
      violent round trip, so always read it together with
      closest_approach_to_orl_pct below.
    closest_approach_to_orl_pct: how close (in %) price got to the ORL at its
      worst point since the breakout, regardless of where it has since
      recovered to (near 0 or negative means the level was genuinely tested
      or briefly broken intraminute even if the current snapshot looks calm).
      A ticker that dipped to within 1% of its ORL and bounced is a much
      weaker "held support" story than one that never came close — even if
      both show the same pullback_from_high_pct right now.
    bars_since_breakout: number of completed 5-min bars since price first
      closed above the ORH today (null if it hasn't broken out yet). A higher
      number with price still holding well above VWAP/EMA(6) suggests a
      mature, still-valid trend rather than a stale or failed breakout.
    ema_3_above_ema_6: boolean — short-term momentum is up
    price_above_vwap: boolean — day is net-bullish for this name
    price_above_orh: boolean — price has broken above the opening range high
    price_below_orl: boolean — price has broken below the opening range low (bearish)
    bounce_setup: boolean — true when EMA(3) > EMA(6), price > VWAP, and price >= ORH.
      This is the fresh-breakout pattern: price is at or above the ORH right now.
    pullback_setup: boolean — true when the ticker broke the ORH earlier today
      (bars_since_breakout is not null) but has since pulled back below it, while
      still holding above EMA(6) or VWAP with EMA(3) > EMA(6), and without breaking
      down through the ORL. This is the "already ran, cooled off, but still
      structurally bullish" pattern — use it for tickers whose original breakout
      numbers (rvol, range) have decayed by the time you're evaluating them, but
      the day's trend is still intact.
    breakdown_setup: boolean — the bearish mirror of bounce_setup: true when
      EMA(3) < EMA(6), price < VWAP, and price <= ORL. This is the fresh-breakdown
      pattern: price is at or below the ORL right now (ORL becomes resistance on a
      failed retest, mirroring "ORH becomes support" for bounce_setup).
    pulldown_setup: boolean — the bearish mirror of pullback_setup: true when the
      ticker broke down through the ORL earlier today (bars_since_breakdown is not
      null) but has since bounced partway back up, while still holding below EMA(6)
      or VWAP with EMA(3) < EMA(6), and without reclaiming back above the ORH. This
      is the "already broke down, bounced, but still structurally bearish" pattern.
    bars_since_breakdown, peak_rvol_down, rvol_pct_of_peak_down, bounce_from_low_pct,
      closest_approach_to_orh_pct: literal bearish mirrors of bars_since_breakout,
      peak_rvol, rvol_pct_of_peak, pullback_from_high_pct, and
      closest_approach_to_orl_pct respectively — same interpretation, opposite
      direction. ORH plays the role ORL plays on the bullish side: the level that
      must NOT be reclaimed for the breakdown to still be considered valid.
- IONZ is -2x inverse of the single stock IONQ (not a broad index) — IONQ's
  technical_indicators are always fetched alongside IONZ automatically. Before
  recommending an IONZ setup, check that IONQ actually shows the corresponding
  opposite structure (e.g., IONQ price_below_orl=true supporting an IONZ long).
  Treat an IONZ bounce_setup with more skepticism if IONQ isn't confirming —
  IONZ is a small, thinly-traded fund where its own tape can be noisy.
- IONZ macro-day priority: check SPY and QQQ's own technical_indicators. If SPY or
  QQQ show price_above_vwap=false or ema_3_above_ema_6=false (a "down" day), or
  price is trading in a tight range close to today's open (a "sideways" day), and
  IONZ independently qualifies via its own bounce_setup or breakdown_setup (never
  relaxed — IONZ must still clear its own technical gate like every other ticker),
  boost IONZ's rank/confidence above other competing qualifying setups for the
  day. This never substitutes for IONZ's own technical trigger — it only breaks
  ties/ranks higher when multiple setups qualify and the day's trade limit can't
  take them all.
- ONLY suggest LONG trades in `suggestions`. No short setups.
- The catalyst for every long is the opening 5-min candle. A valid long setup requires
  bounce_setup=true OR pullback_setup=true:
    * bounce_setup=true (fresh breakout): price broke above the ORH and is holding at or
      above it (ORH becomes support), EMA momentum is positive, and the stock is above VWAP.
      Entry: at or just above the ORH. Stop loss: just below the ORL. setup_type: "breakout".
    * pullback_setup=true (pullback/reclaim): the ticker already broke out earlier today and
      has since cooled off, but is still holding above EMA(6)/VWAP with positive EMA momentum,
      and the ORL genuinely held (closest_approach_to_orl_pct >= 0) rather than being broken
      and recovered. Entry: at or just above the current price (the EMA(6)/VWAP reclaim level,
      not the original ORH). Stop loss: just below EMA(6) or the lowest price since the
      breakout, whichever is tighter, while still keeping reward/risk >= 1.5. setup_type:
      "pullback_reclaim". Weigh rvol_pct_of_peak, pullback_from_high_pct, and
      closest_approach_to_orl_pct in your confidence — a deep pullback with rvol far
      below its peak is weaker than a shallow one with rvol still elevated, and a
      ticker that came within a percent or two of its ORL before recovering (even if
      it currently looks like only a mild pullback) is a weaker "held support" story
      than one that never came close.
{bearish_handling}
- If no ticker meets all criteria, return an empty suggestions list.
- TQQQ, SQQQ, IONZ, IONQ, NVDA, and SPCX are always included in technical_indicators regardless
  of scanner ranking. Consider them as candidates if their bounce_setup qualifies, but deprioritize
  them when a top mover presents a cleaner or higher-conviction setup.
- SQQQ is the -3x leveraged inverse of the Nasdaq-100, the mirror image of TQQQ's +3x exposure —
  a bearish view on the Nasdaq is expressed as a long SQQQ trade, not a short. Evaluate TQQQ and
  SQQQ independently against bounce_setup; do not suggest both at once since they are opposing
  bets on the same underlying index.
- Only suggest reward/risk >= 1.5
- Always state stop loss clearly
- Never suggest selling below cost basis unless allow_loss is true
- Populate robinhood_instructions with exact plain english steps including
  the 3:45pm alarm reminder
- If no clean setup exists, return an empty suggestions list and recommended: null
- If the payload's before_10am_et is true, the opening range is still fresh (before 10:00am ET) and
  breakouts are more prone to reversing before they're confirmed. Mention this briefly as a caution
  in risk_note, but still evaluate bounce_setup/pullback_setup normally and generate suggestions as usual — this is
  a warning, not a reason to withhold suggestions or return an empty list.
- If the payload's holiday_adjacent is true, today is the last session before an extended
  (holiday) break — volume can look strong while remaining structurally thin, producing
  breakouts that qualify on paper but fail to hold. Mention this briefly as a caution in
  risk_note, but still evaluate bounce_setup/pullback_setup normally and generate suggestions as usual — this
  is a warning, not a reason to withhold suggestions or return an empty list.
{options_primary_section}
Never force a trade to hit the goal by taking disproportionate risk.

When your analysis is complete, call the submit_trade_suggestions tool exactly once
with your full answer. That tool call is the ONLY way to deliver your answer — never
respond with plain text or markdown instead of calling it.\
"""

_anthropic_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            from services.ssm_service import get_secret

            api_key = get_secret("/trading-app/anthropic-key")
        _anthropic_client = anthropic.Anthropic(api_key=api_key)
    return _anthropic_client


def _extract_json(text: str) -> str:
    """Strip markdown code fences from Claude's response if present.

    Handles truncated responses where the closing fence was cut off by max_tokens.
    """
    text = text.strip()
    # Complete code fence — prefer this
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        return match.group(1).strip()
    # Opening fence only (truncated response) — strip the fence and return remainder
    match = re.search(r"```(?:json)?\s*([\s\S]+)", text)
    if match:
        return match.group(1).strip()
    return text


def _build_tools(include_options: bool = False) -> list[dict]:
    tools = [
        {
            "name": "get_portfolio",
            "description": (
                "Fetch the current portfolio: cash balance, equity, and positions "
                "with current prices and unrealized P&L."
            ),
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "get_top_movers",
            "description": (
                "Fetch today's top intraday movers (up to 10) with price, change %, and volume. "
                "Call this first — use the returned tickers as input to get_technical_indicators."
            ),
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "get_scanner_results",
            "description": "Fetch movers filtered to a minimum absolute change % threshold.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "min_change_pct": {
                        "type": "number",
                        "description": "Minimum absolute % change to include. Default 2.0.",
                    }
                },
                "required": [],
            },
        },
        {
            "name": "get_sentiment",
            "description": "Fetch Finnhub news sentiment scores for a list of tickers.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "tickers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ticker symbols to score.",
                    }
                },
                "required": ["tickers"],
            },
        },
        {
            "name": "get_technical_indicators",
            "description": (
                "Fetch 5-min opening range indicators (ORH, ORL, EMA(3), EMA(6), VWAP, "
                "RVOL, bounce_setup) for a list of tickers. Always include TQQQ, SQQQ, IONZ, "
                "IONQ, NVDA, and SPCX. Call get_top_movers first, then pass those tickers plus "
                "TQQQ, SQQQ, IONZ, IONQ, NVDA, and SPCX here. IONQ is also fetched automatically "
                "whenever IONZ is requested, as a safety net."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "tickers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ticker symbols. Always include TQQQ, SQQQ, IONZ, IONQ, NVDA, and SPCX.",
                    }
                },
                "required": ["tickers"],
            },
        },
        {
            "name": "get_quotes",
            "description": "Fetch real-time last prices for specific tickers.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "tickers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ticker symbols.",
                    }
                },
                "required": ["tickers"],
            },
        },
    ]
    if include_options:
        tools.append(
            {
                "name": "get_option_chain",
                "description": (
                    "Fetch real option-chain contracts (calls and puts, 7-21 days to "
                    "expiration, near-the-money) for one or more underlying tickers in a "
                    "single call — strikes, bid/ask, mark, Greeks, open interest, volume. "
                    "Pass every ticker you're seriously considering at once rather than "
                    "calling this once per ticker — each call is a full round trip, and the "
                    "agentic loop has a limited number of turns. Use this to source real "
                    "prices for a call/put suggestion; never invent option prices."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "tickers": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Underlying ticker symbols to price at once.",
                        }
                    },
                    "required": ["tickers"],
                },
            }
        )
    return tools


_TRADE_SETUP_SCHEMA = {
    "type": "object",
    "properties": {
        "instrument_type": {"type": "string", "enum": ["equity"]},
        "ticker": {"type": "string"},
        "direction": {"type": "string", "enum": ["long", "short"]},
        "trade_type": {"type": "string", "enum": ["intraday_cash", "swing", "partial_trim"]},
        "profit_mode": {"type": "string"},
        "entry_price": {"type": "number"},
        "target_price": {"type": "number"},
        "stop_loss": {"type": "number"},
        "shares": {"type": "integer"},
        "expected_gain": {"type": "number"},
        "max_loss": {"type": "number"},
        "reward_risk_ratio": {"type": "number"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "rationale": {"type": "string"},
        "setup_type": {"type": "string"},
        "uses_existing_holding": {"type": "boolean"},
        "cost_basis": {"type": ["number", "null"]},
        "current_unrealized_pnl": {"type": ["number", "null"]},
        "avg_daily_range_pct": {"type": ["number", "null"]},
        "robinhood_instructions": {"type": "string"},
        "ml_probability": {"type": ["number", "null"]},
        "ml_calibration_note": {"type": ["string", "null"]},
    },
    "required": [
        "instrument_type",
        "ticker",
        "direction",
        "trade_type",
        "profit_mode",
        "entry_price",
        "target_price",
        "stop_loss",
        "shares",
        "expected_gain",
        "max_loss",
        "reward_risk_ratio",
        "confidence",
        "rationale",
        "setup_type",
        "uses_existing_holding",
        "cost_basis",
        "current_unrealized_pnl",
        "avg_daily_range_pct",
        "robinhood_instructions",
        "ml_probability",
        "ml_calibration_note",
    ],
}

_OPTION_TRADE_SETUP_SCHEMA = {
    "type": "object",
    "properties": {
        "instrument_type": {"type": "string", "enum": ["option"]},
        "ticker": {"type": "string"},
        "option_symbol": {"type": "string"},
        "option_type": {"type": "string", "enum": ["call", "put"]},
        "strike_price": {"type": "number"},
        "expiration_date": {"type": "string"},
        "days_to_expiration": {"type": "integer"},
        "trade_type": {"type": "string", "enum": ["intraday_cash", "swing", "partial_trim"]},
        "profit_mode": {"type": "string"},
        "entry_price": {"type": "number"},
        "target_price": {"type": "number"},
        "stop_loss": {"type": "number"},
        "shares": {"type": "integer"},
        "breakeven_price": {"type": "number"},
        "delta_at_entry": {"type": ["number", "null"]},
        "implied_volatility_at_entry": {"type": ["number", "null"]},
        "bid_ask_spread_pct": {"type": ["number", "null"]},
        "open_interest": {"type": ["integer", "null"]},
        "volume": {"type": ["integer", "null"]},
        "underlying_price_at_entry": {"type": "number"},
        "expected_gain": {"type": "number"},
        "max_loss": {"type": "number"},
        "reward_risk_ratio": {"type": "number"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "rationale": {"type": "string"},
        "setup_type": {"type": "string"},
        "robinhood_instructions": {"type": "string"},
    },
    "required": [
        "instrument_type",
        "ticker",
        "option_symbol",
        "option_type",
        "strike_price",
        "expiration_date",
        "days_to_expiration",
        "trade_type",
        "profit_mode",
        "entry_price",
        "target_price",
        "stop_loss",
        "shares",
        "breakeven_price",
        "delta_at_entry",
        "implied_volatility_at_entry",
        "bid_ask_spread_pct",
        "open_interest",
        "volume",
        "underlying_price_at_entry",
        "expected_gain",
        "max_loss",
        "reward_risk_ratio",
        "confidence",
        "rationale",
        "setup_type",
        "robinhood_instructions",
    ],
}


def _build_submit_suggestions_tool(include_options: bool) -> dict:
    """suggestions/recommended accept either shape via a oneOf/anyOf discriminated
    on instrument_type when options are enabled — confirmed reliable against
    claude-sonnet-4-6 via scripts/test_option_schema_union_live.py. Kill-switch
    off reverts to the original equity-only schema exactly.
    """
    suggestion_item_schema = (
        {"oneOf": [_TRADE_SETUP_SCHEMA, _OPTION_TRADE_SETUP_SCHEMA]}
        if include_options
        else _TRADE_SETUP_SCHEMA
    )
    recommended_schema = (
        {"anyOf": [_TRADE_SETUP_SCHEMA, _OPTION_TRADE_SETUP_SCHEMA, {"type": "null"}]}
        if include_options
        else {"anyOf": [_TRADE_SETUP_SCHEMA, {"type": "null"}]}
    )
    return {
        "name": "submit_trade_suggestions",
        "description": (
            "Deliver your final trade suggestions. Call this exactly once, after you are "
            "done gathering data — this is the only way to answer, do not respond in plain text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "goal": {"type": "number"},
                "profit_mode": {"type": "string"},
                "trade_scope": {"type": "string"},
                "risk_note": {"type": "string"},
                "market_conditions": {"type": "string"},
                "intraday_viability": {"type": ["string", "null"]},
                "guardrails_checked": {"type": "array", "items": {"type": "string"}},
                "any_guardrail_triggered": {"type": "boolean"},
                "recommended": recommended_schema,
                "suggestions": {"type": "array", "items": suggestion_item_schema},
            },
            "required": [
                "goal",
                "profit_mode",
                "trade_scope",
                "risk_note",
                "market_conditions",
                "intraday_viability",
                "guardrails_checked",
                "any_guardrail_triggered",
                "recommended",
                "suggestions",
            ],
        },
    }


def _execute_tool(name: str, tool_input: dict) -> dict | list:
    logger.info("Tool call: %s inputs=%s", name, tool_input)
    if name == "get_portfolio":
        portfolio = portfolio_factory.get_provider().get_portfolio()
        portfolio["positions"] = _enrich_positions(portfolio.get("positions", []))
        return portfolio
    if name == "get_top_movers":
        cached = _cached_scanner_results(min_change_pct=0)
        if cached is not None:
            return sorted(cached, key=lambda m: abs(m.get("change_pct", 0)), reverse=True)[:10]
        return schwab_service.get_previous_day_movers(_get_watchlist(), limit=10)
    if name == "get_scanner_results":
        min_pct = float(tool_input.get("min_change_pct", 2.0))
        cached = _cached_scanner_results(min_pct)
        if cached is not None:
            return cached
        return schwab_service.get_scanner_results(_get_watchlist(), min_change_pct=min_pct)
    if name == "get_sentiment":
        tickers = tool_input.get("tickers", [])
        cached = _cached_sentiment()
        if cached is not None:
            return [s for s in cached if s.get("ticker") in set(tickers)] if tickers else cached
        return finnhub_service.score_batch_sentiment(tickers)
    if name == "get_technical_indicators":
        tickers = tool_input.get("tickers", [])
        # IONZ is -2x inverse of the single stock IONQ (not a broad index) — always
        # fetch IONQ alongside it so its structure can confirm or contradict the move.
        if "IONZ" in tickers and "IONQ" not in tickers:
            tickers = [*tickers, "IONQ"]
        return schwab_service.get_technical_indicators(tickers)
    if name == "get_quotes":
        return schwab_service.get_batch_quotes(tool_input.get("tickers", []))
    if name == "get_option_chain":
        return schwab_service.get_option_chains(tool_input.get("tickers", []))
    raise ValueError(f"Unknown tool: {name}")


def _agentic_call(
    system: str,
    payload: dict,
    tools: list[dict],
    finish_tool: str | None = None,
    max_iterations: int = 6,
) -> str | dict:
    """Run the Anthropic tool-use agentic loop.

    Claude receives the seed payload and may emit tool_use blocks. If finish_tool is
    set, Claude must deliver its final answer by calling that tool — its input is
    returned directly as a dict, guaranteeing schema-valid output instead of relying
    on Claude to format a plain-text response correctly. tool_choice is forced to
    "any" in this case so Claude cannot spend a turn writing plain text instead of
    calling a tool — that costs a full extra round trip we can't afford under the
    Lambda timeout. The end_turn nudge below is a defensive fallback in case Claude
    still stops without calling anything. Without finish_tool, the final end_turn
    text is returned normally.
    """
    messages = [{"role": "user", "content": json.dumps(payload, default=str)}]
    extra_kwargs = {"tool_choice": {"type": "any"}} if finish_tool else {}
    for _ in range(max_iterations):
        response = _get_client().messages.create(
            model=_MODEL,
            max_tokens=4096,
            system=system,
            tools=tools,
            messages=messages,
            **extra_kwargs,
        )
        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            results = []
            finish_input = None
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if finish_tool and block.name == finish_tool:
                    finish_input = block.input
                    results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": "Received."}
                    )
                    continue
                try:
                    result = _execute_tool(block.name, block.input)
                except Exception as exc:
                    logger.exception("Tool %s failed", block.name)
                    result = {"error": str(exc)}
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    }
                )
            if finish_input is not None:
                return finish_input
            messages.append({"role": "user", "content": results})
            continue
        if response.stop_reason == "end_turn":
            if finish_tool:
                messages.append({"role": "assistant", "content": response.content})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"You must call the {finish_tool} tool to submit your answer. "
                            "Do not respond in plain text."
                        ),
                    }
                )
                continue
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
            return ""
    raise ValueError(f"Agentic loop exceeded {max_iterations} iterations without a final answer")


def morning_briefing(ctx: DailyContext) -> str:
    """Return a plain-text morning briefing from Claude given the full daily context."""
    system = _BRIEFING_SYSTEM.format(
        profit_mode=ctx.profit_mode,
        trade_scope=ctx.trade_scope,
        goal_dollars=int(ctx.daily_goal),
    )
    response = _get_client().messages.create(
        model=_MODEL,
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": json.dumps(ctx.to_dict(), default=str)}],
    )
    return response.content[0].text


def chat(ctx: DailyContext, user_message: str) -> str:
    """Free-form chat with Claude using the full daily context as background."""
    system = _CHAT_SYSTEM.format(
        profit_mode=ctx.profit_mode,
        trade_scope=ctx.trade_scope,
        goal_dollars=int(ctx.daily_goal),
    )
    response = _get_client().messages.create(
        model=_MODEL,
        max_tokens=1024,
        system=system,
        messages=[
            {"role": "user", "content": json.dumps(ctx.to_dict(), default=str)},
            {
                "role": "assistant",
                "content": "I have reviewed today's market data and your portfolio. What would you like to know?",
            },
            {"role": "user", "content": user_message},
        ],
    )
    return response.content[0].text


def _include_options_suggestions() -> bool:
    """INCLUDE_OPTIONS_SUGGESTIONS — SSM plain param in Lambda, .env.local locally.
    Default true: options are the primary cash_intraday expression
    (intraday-options-pivot-plan.md). Set to false as an emergency kill switch to
    revert instantly to the original equity-only, bullish-only behavior without a
    redeploy — same config-gated pattern as PORTFOLIO_MODE/TRADING_MODE.
    """
    return os.environ.get("INCLUDE_OPTIONS_SUGGESTIONS", "true").lower() == "true"


def _build_suggestion_system(
    profit_mode: str,
    trade_scope: str,
    goal_dollars: int,
    include_options: bool | None = None,
) -> str:
    if include_options is None:
        include_options = _include_options_suggestions()
    return _SUGGESTION_SYSTEM.format(
        profit_mode=profit_mode,
        trade_scope=trade_scope,
        goal_dollars=goal_dollars,
        option_chain_step=(_OPTION_CHAIN_STEP if include_options else ""),
        bearish_handling=(
            _BEARISH_HANDLING_WITH_OPTIONS if include_options else _BEARISH_HANDLING_EQUITY_ONLY
        ),
        options_primary_section=(_OPTIONS_PRIMARY_SECTION if include_options else ""),
    )


def suggest_trades(
    seed: dict,
    user_message: str,
    allow_loss: bool = False,
) -> TradeSuggestionResponse:
    """Ask Claude for structured trade suggestions via agentic tool use, then enforce guardrails."""
    include_options = _include_options_suggestions()
    system = _build_suggestion_system(
        profit_mode=seed["profit_mode"],
        trade_scope=seed["trade_scope"],
        goal_dollars=int(seed["daily_goal"]),
        include_options=include_options,
    )
    payload = {**seed, "allow_loss": allow_loss, "user_message": user_message}
    tools = _build_tools(include_options=include_options) + [
        _build_submit_suggestions_tool(include_options)
    ]
    # max_iterations bumped from the default 6 — the options-primary flow adds a
    # get_option_chain round trip (batched across every qualifying ticker, but
    # still a real turn) on top of the original movers/technical_indicators/
    # portfolio/sentiment sequence, and Claude sometimes retries a tool call.
    parsed = _agentic_call(
        system,
        payload,
        tools=tools,
        finish_tool="submit_trade_suggestions",
        max_iterations=10,
    )

    # Inject envelope fields in case Claude omitted them
    parsed.setdefault("goal", seed["daily_goal"])
    parsed.setdefault("profit_mode", seed["profit_mode"])
    parsed.setdefault("trade_scope", seed["trade_scope"])
    parsed.setdefault("suggestions", [])
    parsed.setdefault("risk_note", "")
    parsed.setdefault("market_conditions", "")
    parsed.setdefault("intraday_viability", None)
    parsed.setdefault("recommended", None)
    parsed.setdefault("guardrails_checked", [])
    parsed.setdefault("any_guardrail_triggered", False)

    suggestion = TradeSuggestionResponse.model_validate(parsed)

    # Server-side guardrail check — same code path paper and live
    guardrail_ctx = GuardrailContext(
        cash=seed["cash"],
        realized_pnl_today=seed["realized_pnl_today"],
        trade_count_today=seed["trade_count_today"],
        trading_mode=seed["trading_mode"],
        allow_loss=allow_loss,
    )
    any_triggered = False
    for trade in suggestion.suggestions:
        if check_all(trade, guardrail_ctx).triggered:
            any_triggered = True

    # If the recommended trade itself fails guardrails, block it and log the event
    if suggestion.recommended is not None:
        rec_result = check_all(suggestion.recommended, guardrail_ctx)
        if not rec_result.allowed:
            try:
                dynamo_service.log_guardrail_event(
                    ticker=suggestion.recommended.ticker,
                    rules_triggered=rec_result.triggered,
                    messages=rec_result.messages,
                )
            except Exception:
                pass
            blocked_msgs = "; ".join(rec_result.messages)
            suggestion.recommended = None
            suggestion.risk_note = (
                f"Recommended trade blocked by guardrails: {blocked_msgs}. {suggestion.risk_note}"
            )
            any_triggered = True

    suggestion.guardrails_checked = _GUARDRAIL_NAMES
    suggestion.any_guardrail_triggered = any_triggered

    return suggestion
