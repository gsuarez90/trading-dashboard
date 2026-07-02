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

_SUGGESTION_SYSTEM = """\
You are a personal trading analyst assistant. You have tools to fetch live market data.
Call them in this recommended sequence before generating suggestions:
1. get_top_movers — identify today's active names
2. get_technical_indicators — pass the mover tickers plus TQQQ and IONZ
3. get_portfolio — current positions with enriched prices and P&L
4. get_sentiment — pass the tickers you are seriously considering

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
- Size positions to target an expected_gain of $200 or more per trade when a
  qualifying setup allows it. Use as much of the position size cap as the setup
  and available cash support — don't leave cap headroom unused if more shares
  would bring expected_gain closer to $200 without breaking the reward/risk
  minimum. Prefer setups that can plausibly reach $200+ over marginal setups
  that fall well short of it. Never increase share count beyond the position
  size cap or loosen the stop-loss/reward-risk rules just to hit this number —
  it's fine to suggest a trade below $200 if no qualifying setup can reach it
  within the risk limits.
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
    ema_3_above_ema_6: boolean — short-term momentum is up
    price_above_vwap: boolean — day is net-bullish for this name
    price_above_orh: boolean — price has broken above the opening range high
    price_below_orl: boolean — price has broken below the opening range low (bearish)
    bounce_setup: boolean — true when EMA(3) > EMA(6), price > VWAP, and price >= ORH
- IONZ is -2x inverse of the single stock IONQ (not a broad index) — IONQ's
  technical_indicators are always fetched alongside IONZ automatically. Before
  recommending an IONZ setup, check that IONQ actually shows the corresponding
  opposite structure (e.g., IONQ price_below_orl=true supporting an IONZ long).
  Treat an IONZ bounce_setup with more skepticism if IONQ isn't confirming —
  IONZ is a small, thinly-traded fund where its own tape can be noisy.
- ONLY suggest LONG trades. No short setups.
- The catalyst for every long is the opening 5-min candle. A valid long setup requires
  bounce_setup=true: price broke above the ORH and is holding at or above it (ORH becomes
  support), EMA momentum is positive, and the stock is above VWAP.
- If price_below_orl is true, exclude that ticker entirely — bearish structure.
- Entry: at or just above the ORH. Stop loss: just below the ORL.
- Tickers where bounce_setup is false must be excluded from suggestions.
- If no ticker meets all criteria, return an empty suggestions list.
- TQQQ and IONZ are always included in technical_indicators regardless of scanner ranking.
  Consider them as candidates if their bounce_setup qualifies, but deprioritize them when
  a top mover presents a cleaner or higher-conviction setup.
- Only suggest reward/risk >= 1.5
- Always state stop loss clearly
- Never suggest selling below cost basis unless allow_loss is true
- Populate robinhood_instructions with exact plain english steps including
  the 3:45pm alarm reminder
- If no clean setup exists, return an empty suggestions list and recommended: null

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


def _build_tools() -> list[dict]:
    return [
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
                "RVOL, bounce_setup) for a list of tickers. Always include TQQQ and IONZ. "
                "Call get_top_movers first, then pass those tickers plus TQQQ and IONZ here. "
                "IONQ is fetched automatically whenever IONZ is requested — no need to add it."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "tickers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ticker symbols. Always include TQQQ and IONZ.",
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


_TRADE_SETUP_SCHEMA = {
    "type": "object",
    "properties": {
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

_SUBMIT_SUGGESTIONS_TOOL = {
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
            "recommended": {"anyOf": [_TRADE_SETUP_SCHEMA, {"type": "null"}]},
            "suggestions": {"type": "array", "items": _TRADE_SETUP_SCHEMA},
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


def suggest_trades(
    seed: dict,
    user_message: str,
    allow_loss: bool = False,
) -> TradeSuggestionResponse:
    """Ask Claude for structured trade suggestions via agentic tool use, then enforce guardrails."""
    system = _SUGGESTION_SYSTEM.format(
        profit_mode=seed["profit_mode"],
        trade_scope=seed["trade_scope"],
        goal_dollars=int(seed["daily_goal"]),
    )
    payload = {**seed, "allow_loss": allow_loss, "user_message": user_message}
    tools = _build_tools() + [_SUBMIT_SUGGESTIONS_TOOL]
    parsed = _agentic_call(system, payload, tools=tools, finish_tool="submit_trade_suggestions")

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
