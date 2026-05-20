import json

import anthropic

from services.context_loader import DailyContext

_MODEL = "claude-sonnet-4-6"

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

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


def morning_briefing(ctx: DailyContext) -> str:
    """Call Claude with the full daily context and return a plain-text morning briefing."""
    system = _BRIEFING_SYSTEM.format(
        profit_mode=ctx.profit_mode,
        trade_scope=ctx.trade_scope,
        goal_dollars=int(ctx.daily_goal),
    )
    response = _get_client().messages.create(
        model=_MODEL,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": json.dumps(ctx.to_dict(), default=str)}],
    )
    return response.content[0].text
