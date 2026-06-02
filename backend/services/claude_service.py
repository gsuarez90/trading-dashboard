import json
import os
import re

import anthropic

from models.schemas import TradeSuggestionResponse
from services import dynamo_service
from services.context_loader import DailyContext
from services.guardrail_service import GuardrailContext, check_all

_MODEL = "claude-sonnet-4-6"

_GUARDRAIL_NAMES = [
    "daily_loss_limit",
    "position_size_cap",
    "cost_basis_protection",
    "reward_risk_minimum",
    "daily_trade_limit",
    "market_hours_lock",
    "intraday_60min_cutoff",
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

If profit_mode is cash_intraday, assess average daily range viability.
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
You are a personal trading analyst assistant. Full daily context is in
the payload including scanner results, intraday movers, sentiment,
portfolio with cost basis, cash balance, trade history, realized P&L,
guardrail status, and minutes remaining in session.

Current settings:
- Profit mode: {profit_mode}
- Trade scope: {trade_scope}
- Daily goal: ${goal_dollars}

When generating trade suggestions:
- Respect trade_scope strictly
- Respect profit_mode:
  * cash_intraday: entry AND exit must happen today. Only suggest stocks
    with sufficient avg_daily_range_pct. Do not suggest with < 60 min left.
  * swing: overnight holds acceptable
  * holdings: partial trims and rebuys only
- Calculate position sizes from available cash and shares owned
- Use technical_indicators (20-day SMA) to assess trend direction for each ticker: above_sma = bullish bias, below_sma = bearish bias; price_vs_sma_pct shows how extended the move is
- Only suggest reward/risk >= 1.5
- Always state stop loss clearly
- Never suggest selling below cost basis unless allow_loss is true
- Populate robinhood_instructions with exact plain english steps including
  the 3:45pm alarm reminder
- If no clean setup exists, return an empty suggestions list and recommended: null

Never force a trade to hit the goal by taking disproportionate risk.

Return ONLY a single valid JSON object with this exact structure (no markdown, no explanation).
Every TradeSetup must include ALL fields below with EXACT field names:

{{
  "goal": <float>,
  "profit_mode": <string>,
  "trade_scope": <string>,
  "risk_note": <string>,
  "market_conditions": <string>,
  "intraday_viability": <string or null>,
  "guardrails_checked": [],
  "any_guardrail_triggered": false,
  "recommended": <TradeSetup or null>,
  "suggestions": [
    {{
      "ticker": <string>,
      "direction": <"long" or "short">,
      "trade_type": <"intraday_cash" or "swing" or "partial_trim">,
      "profit_mode": <string>,
      "entry_price": <float>,
      "target_price": <float>,
      "stop_loss": <float>,
      "shares": <int>,
      "expected_gain": <float>,
      "max_loss": <float>,
      "reward_risk_ratio": <float>,
      "confidence": <"high" or "medium" or "low">,
      "rationale": <string>,
      "setup_type": <string>,
      "uses_existing_holding": <bool>,
      "cost_basis": <float or null>,
      "current_unrealized_pnl": <float or null>,
      "avg_daily_range_pct": <float or null>,
      "robinhood_instructions": <string — exact plain english steps including 3:45pm alarm>,
      "ml_probability": null,
      "ml_calibration_note": null
    }}
  ]
}}\
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
    ctx: DailyContext,
    user_message: str,
    allow_loss: bool = False,
) -> TradeSuggestionResponse:
    """Ask Claude for structured trade suggestions, then enforce guardrails server-side."""
    system = _SUGGESTION_SYSTEM.format(
        profit_mode=ctx.profit_mode,
        trade_scope=ctx.trade_scope,
        goal_dollars=int(ctx.daily_goal),
    )
    payload = {**ctx.to_dict(), "allow_loss": allow_loss, "user_message": user_message}
    response = _get_client().messages.create(
        model=_MODEL,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": json.dumps(payload, default=str)}],
    )
    raw = _extract_json(response.content[0].text)
    if not raw:
        raise ValueError(
            f"Claude returned empty response. "
            f"Stop reason: {response.stop_reason}. Usage: {response.usage}"
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude returned invalid JSON: {e}\nRaw: {raw[:500]}")

    # Inject envelope fields in case Claude omitted them
    parsed.setdefault("goal", ctx.daily_goal)
    parsed.setdefault("profit_mode", ctx.profit_mode)
    parsed.setdefault("trade_scope", ctx.trade_scope)
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
        cash=ctx.cash,
        realized_pnl_today=ctx.realized_pnl_today,
        trade_count_today=ctx.trade_count_today,
        trading_mode=ctx.trading_mode,
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
