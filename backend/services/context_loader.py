import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from services import (
    dynamo_service,
    finnhub_service,
    market_data_service,
    portfolio_factory,
    schwab_service,
)
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
    "BTC/USD",
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


def _prev_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _cache_is_fresh(cached_at: str) -> bool:
    """True if cached_at is on or after the last expected 9:35am ET weekday refresh."""
    try:
        ts = datetime.fromisoformat(cached_at).astimezone(ET)
        now_et = datetime.now(tz=ET)
        d = now_et.date()
        wd = d.weekday()
        if wd < 5:
            h, m = now_et.hour, now_et.minute
            last_refresh = d if (h > 9 or (h == 9 and m >= 35)) else _prev_weekday(d)
        elif wd == 5:
            last_refresh = d - timedelta(days=1)
        else:
            last_refresh = d - timedelta(days=2)
        return ts.date() >= last_refresh
    except Exception:
        return False


def _cached_scanner_results(min_change_pct: float) -> list[dict] | None:
    """Return DynamoDB-cached scanner data if written on or after the last refresh date.

    Duplicates cache_service._last_refresh_date logic to avoid circular import
    (cache_service imports context_loader, so the reverse is not possible).
    """
    try:
        data, cached_at = dynamo_service.get_cache("scanner")
        if data is None or not cached_at or not _cache_is_fresh(cached_at):
            return None
        return [m for m in data if abs(m.get("change_pct", 0)) >= min_change_pct]
    except Exception:
        return None


def _cached_sentiment() -> list[dict] | None:
    """Return DynamoDB-cached sentiment scores if written on or after the last refresh date."""
    try:
        data, cached_at = dynamo_service.get_cache("sentiment")
        if data is None or not cached_at or not _cache_is_fresh(cached_at):
            return None
        return data
    except Exception:
        return None


def _get_watchlist() -> list[str]:
    raw = os.environ.get("WATCHLIST", "")
    if raw:
        return [t.strip().upper() for t in raw.split(",") if t.strip()]
    # Movers API only has meaningful data during market hours; outside hours it can
    # hang indefinitely (no timeout on the underlying HTTP client) causing Lambda 503s.
    if _minutes_remaining(datetime.now(tz=ET)) > 0:
        try:
            dynamic = schwab_service.get_dynamic_watchlist()
            if dynamic:
                return dynamic
        except Exception:
            pass
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

    # ── Round 1: all independent I/O in parallel ──────────────────────────────
    def _fetch_portfolio():
        try:
            return portfolio_factory.get_provider().get_portfolio()
        except Exception:
            return {"cash": 0.0, "equity": 0.0, "positions": []}

    def _fetch_scanner():
        try:
            cached = _cached_scanner_results(min_change_pct)
            if cached is not None:
                return cached
            return market_data_service.get_scanner_results(tickers, min_change_pct=min_change_pct)
        except Exception:
            return []

    def _fetch_movers():
        try:
            cached = _cached_scanner_results(min_change_pct=0)
            if cached is not None:
                return sorted(cached, key=lambda m: abs(m.get("change_pct", 0)), reverse=True)[:10]
            return market_data_service.get_previous_day_movers(tickers, limit=10)
        except Exception:
            return []

    def _fetch_trades():
        try:
            return dynamo_service.get_trades_by_date(today)
        except Exception:
            return []

    def _fetch_guardrail_events():
        try:
            return dynamo_service.get_guardrail_events_by_date(today)
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=5) as pool:
        f_portfolio = pool.submit(_fetch_portfolio)
        f_scanner = pool.submit(_fetch_scanner)
        f_movers = pool.submit(_fetch_movers)
        f_trades = pool.submit(_fetch_trades)
        f_guardrail_events = pool.submit(_fetch_guardrail_events)

    portfolio = f_portfolio.result()
    scanner_results = f_scanner.result()
    top_movers = f_movers.result()
    trades_today = f_trades.result()
    guardrail_events = f_guardrail_events.result()

    cash = float(portfolio.get("cash", 0.0))

    # ── Round 2: enrich positions + sentiment in parallel ─────────────────────
    sentiment_tickers = list(
        {m["ticker"] for m in top_movers} | {p["ticker"] for p in portfolio.get("positions", [])}
    )

    def _enrich():
        try:
            return _enrich_positions(portfolio.get("positions", []))
        except Exception:
            return portfolio.get("positions", [])

    def _fetch_sentiment():
        try:
            cached = _cached_sentiment()
            if cached is not None:
                return cached
            return finnhub_service.score_batch_sentiment(sentiment_tickers)
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_enriched = pool.submit(_enrich)
        f_sentiment = pool.submit(_fetch_sentiment)

    portfolio["positions"] = f_enriched.result()
    sentiment = f_sentiment.result()

    # ── Local computation (no I/O) ────────────────────────────────────────────
    realized_pnl_today = round(
        sum(t.get("realized_pnl", 0) or 0 for t in trades_today if t.get("status") == "closed"),
        2,
    )
    trade_count_today = sum(
        1 for t in trades_today if t.get("status") in {"open", "closed", "pending"}
    )

    # ── Guardrail status ──────────────────────────────────────────────────────
    ctx = GuardrailContext(
        cash=cash,
        realized_pnl_today=realized_pnl_today,
        trade_count_today=trade_count_today,
        trading_mode=trading_mode,
        now=now_et,
    )
    guardrail_status = get_status(ctx)

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
