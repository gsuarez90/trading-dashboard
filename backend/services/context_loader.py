import os
from dataclasses import asdict, dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from services import dynamo_service, finnhub_service, market_data_service, portfolio_factory, schwab_service
from services.guardrail_service import GuardrailContext, get_status

ET = ZoneInfo("America/New_York")
_MARKET_OPEN = time(9, 30)
_MARKET_CLOSE = time(16, 0)

# Default watchlist — overridden by WATCHLIST env var (comma-separated tickers)
_DEFAULT_TICKERS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
    "SPY",
    "QQQ",
    "AMD",
    "NFLX",
    "ORCL",
    "CRM",
    "PLTR",
]


@dataclass
class DailyContext:
    date: str
    cash: float
    portfolio: dict
    scanner_results: list
    top_movers: list
    sentiment: list
    trades_today: list
    realized_pnl_today: float
    trade_count_today: int
    guardrail_status: dict
    guardrail_events: list
    minutes_remaining: int
    trading_mode: str
    profit_mode: str
    trade_scope: str
    daily_goal: float

    def to_dict(self) -> dict:
        return asdict(self)


def _minutes_remaining(now_et: datetime) -> int:
    if now_et.weekday() >= 5:
        return 0
    t = now_et.time()
    if t < _MARKET_OPEN or t >= _MARKET_CLOSE:
        return 0
    close_dt = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return max(0, int((close_dt - now_et).total_seconds() / 60))


def _enrich_positions(positions: list[dict]) -> list[dict]:
    """Add current_price, unrealized_pnl, unrealized_pnl_pct to each position."""
    if not positions:
        return positions
    tickers = [p["ticker"] for p in positions if p.get("ticker")]
    try:
        quotes = {q["ticker"]: q for q in schwab_service.get_batch_quotes(tickers)}
    except Exception:
        quotes = {}

    enriched = []
    for pos in positions:
        ticker = pos.get("ticker")
        quote = quotes.get(ticker, {})
        current_price = quote.get("price") or pos.get("current_price")
        avg_cost = pos.get("avg_cost") or 0
        shares = pos.get("shares") or 0

        unrealized_pnl = None
        unrealized_pnl_pct = None
        if current_price and avg_cost and shares:
            unrealized_pnl = round((current_price - avg_cost) * shares, 2)
            unrealized_pnl_pct = round((current_price - avg_cost) / avg_cost * 100, 2)

        enriched.append(
            {
                **pos,
                "current_price": current_price,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pnl_pct": unrealized_pnl_pct,
            }
        )
    return enriched


def _get_watchlist() -> list[str]:
    # Explicit override via env var always wins
    raw = os.environ.get("WATCHLIST", "")
    if raw:
        return [t.strip().upper() for t in raw.split(",") if t.strip()]
    # Dynamic: top movers across SPX, Nasdaq, Dow via Schwab
    try:
        dynamic = schwab_service.get_dynamic_watchlist()
        if dynamic:
            return dynamic
    except Exception:
        pass
    # Static fallback if Schwab is unavailable
    return _DEFAULT_TICKERS


def load_context(
    tickers: list[str] | None = None,
    min_change_pct: float = 2.0,
    now: datetime | None = None,
) -> DailyContext:
    """Assemble the full daily context payload for Claude.

    Fetches scanner results, sentiment, enriched portfolio, trade history, and
    guardrail status. Each external call is guarded so a partial failure still
    returns a usable context with reduced data.
    """
    if tickers is None:
        tickers = _get_watchlist()

    now_et = (
        (now.replace(tzinfo=ET) if now.tzinfo is None else now.astimezone(ET))
        if now is not None
        else datetime.now(tz=ET)
    )
    today = now_et.strftime("%Y-%m-%d")

    trading_mode = os.environ.get("TRADING_MODE", "paper")
    profit_mode = os.environ.get("PROFIT_MODE", "cash_intraday")
    trade_scope = os.environ.get("TRADE_SCOPE", "open")
    daily_goal = float(os.environ.get("DAILY_GOAL", 100))

    # ── Portfolio ─────────────────────────────────────────────────────────────
    try:
        portfolio = portfolio_factory.get_provider().get_portfolio()
        portfolio["positions"] = _enrich_positions(portfolio.get("positions", []))
    except Exception:
        portfolio = {"cash": 0.0, "equity": 0.0, "positions": []}
    cash = float(portfolio.get("cash", 0.0))

    # ── Scanner + movers ──────────────────────────────────────────────────────
    try:
        scanner_results = market_data_service.get_scanner_results(
            tickers, min_change_pct=min_change_pct
        )
        top_movers = market_data_service.get_previous_day_movers(tickers, limit=10)
    except Exception:
        scanner_results = []
        top_movers = []

    # ── Sentiment — scored for movers + holdings ──────────────────────────────
    sentiment_tickers = list(
        {m["ticker"] for m in top_movers} | {p["ticker"] for p in portfolio.get("positions", [])}
    )
    try:
        sentiment = finnhub_service.score_batch_sentiment(sentiment_tickers)
    except Exception:
        sentiment = []

    # ── Trade history ─────────────────────────────────────────────────────────
    try:
        trades_today = dynamo_service.get_trades_by_date(today)
    except Exception:
        trades_today = []

    realized_pnl_today = round(
        sum(t.get("realized_pnl", 0) or 0 for t in trades_today if t.get("status") != "open"),
        2,
    )
    trade_count_today = len(trades_today)

    # ── Guardrail status ──────────────────────────────────────────────────────
    ctx = GuardrailContext(
        cash=cash,
        realized_pnl_today=realized_pnl_today,
        trade_count_today=trade_count_today,
        trading_mode=trading_mode,
        now=now_et,
    )
    guardrail_status = get_status(ctx)

    try:
        guardrail_events = dynamo_service.get_guardrail_events_by_date(today)
    except Exception:
        guardrail_events = []

    return DailyContext(
        date=today,
        cash=cash,
        portfolio=portfolio,
        scanner_results=scanner_results,
        top_movers=top_movers,
        sentiment=sentiment,
        trades_today=trades_today,
        realized_pnl_today=realized_pnl_today,
        trade_count_today=trade_count_today,
        guardrail_status=guardrail_status,
        guardrail_events=guardrail_events,
        minutes_remaining=_minutes_remaining(now_et),
        trading_mode=trading_mode,
        profit_mode=profit_mode,
        trade_scope=trade_scope,
        daily_goal=daily_goal,
    )
