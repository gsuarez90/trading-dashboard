"""
DynamoDB-backed cache layer + Lambda handler implementations.

Three scheduled jobs:
  run_daily_refresh()   — 7:00am ET: scanner + sentiment → DynamoDB
  run_price_monitor()   — every 5 min, market hours: auto-close paper trades at target/stop
  run_end_of_day()      — 3:45pm ET: close all open paper trades, flag live trades
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from services import claude_service, dynamo_service, finnhub_service, schwab_service
from services import paper_trading_service
from services.context_loader import _get_watchlist, load_context

ET = ZoneInfo("America/New_York")


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_is_fresh(cached_at: str | None) -> bool:
    """True if the cache was written today (ET)."""
    if not cached_at:
        return False
    try:
        ts = datetime.fromisoformat(cached_at).astimezone(ET)
        return ts.date() == datetime.now(tz=ET).date()
    except Exception:
        return False


def get_cached_scanner(tickers: list[str] | None = None, limit: int = 20) -> list[dict] | None:
    """Return cached scanner movers if fresh, else None."""
    data, cached_at = dynamo_service.get_cache("scanner")
    if data is not None and _cache_is_fresh(cached_at):
        movers = data if tickers is None else [m for m in data if m["ticker"] in set(tickers)]
        return movers[:limit]
    return None


def get_cached_sentiment() -> list[dict] | None:
    """Return cached sentiment scores if fresh, else None."""
    data, cached_at = dynamo_service.get_cache("sentiment")
    if data is not None and _cache_is_fresh(cached_at):
        return data
    return None


def get_cached_briefing() -> dict | None:
    """Return cached briefing payload {briefing, date} if fresh, else None."""
    data, cached_at = dynamo_service.get_cache("briefing")
    if data is not None and _cache_is_fresh(cached_at):
        return data
    return None


# ── Lambda handlers ───────────────────────────────────────────────────────────

def run_daily_refresh() -> dict:
    """7:00am ET — pre-compute scanner + sentiment and write to DynamoDB cache."""
    tickers = _get_watchlist()
    errors = []

    # Scanner / movers
    try:
        movers = schwab_service.get_previous_day_movers(tickers, limit=50)
        dynamo_service.put_cache("scanner", movers)
        scanner_count = len(movers)
    except Exception as e:
        errors.append(f"scanner: {e}")
        scanner_count = 0

    # Sentiment — score top movers only (API rate limit friendly)
    try:
        sentiment_tickers = [m["ticker"] for m in movers[:15]] if scanner_count else tickers[:15]
        sentiment = finnhub_service.score_batch_sentiment(sentiment_tickers)
        dynamo_service.put_cache("sentiment", sentiment)
        sentiment_count = len(sentiment)
    except Exception as e:
        errors.append(f"sentiment: {e}")
        sentiment_count = 0

    # Morning briefing — generated once, cached for the day
    try:
        ctx = load_context()
        briefing_text = claude_service.morning_briefing(ctx)
        dynamo_service.put_cache("briefing", {"briefing": briefing_text, "date": ctx.date})
        briefing_ok = True
    except Exception as e:
        errors.append(f"briefing: {e}")
        briefing_ok = False

    return {
        "refreshed_at": datetime.now(tz=ET).isoformat(),
        "scanner_count": scanner_count,
        "sentiment_count": sentiment_count,
        "briefing_cached": briefing_ok,
        "errors": errors,
    }


def run_price_monitor() -> dict:
    """Every 1 min during market hours — fill pending orders + check open trades.

    Pending paper orders: fill when market price meets the limit condition.
    Open paper trades: auto-close at target or stop.
    Live trades: flag for manual close (never auto-closed).
    """
    today = datetime.now(tz=ET).strftime("%Y-%m-%d")
    open_trades = dynamo_service.get_open_trades()
    pending_trades = dynamo_service.get_pending_trades_for_date(today)

    if not open_trades and not pending_trades:
        return {"checked": 0, "filled": 0, "closed": 0, "flagged": 0}

    # Single batch quote call covering all unique tickers
    all_tickers = list({t["ticker"] for t in open_trades + pending_trades if t.get("ticker")})
    try:
        quotes = {q["ticker"]: q["price"] for q in schwab_service.get_batch_quotes(all_tickers)}
    except Exception:
        quotes = {}

    now_iso = datetime.now(tz=ET).isoformat()
    filled = 0
    closed = 0
    flagged = 0

    # ── Fill pending orders ───────────────────────────────────────────────────
    for trade in pending_trades:
        ticker = trade.get("ticker")
        price = quotes.get(ticker)
        if price is None:
            continue

        limit = trade.get("limit_price") or trade.get("entry_price")
        direction = trade.get("direction", "long")

        fill_condition = (price <= limit) if direction == "long" else (price >= limit)
        if not fill_condition:
            continue

        try:
            paper_trading_service.fill_pending_order(trade["trade_id"], price)
            filled += 1
        except Exception:
            pass

    # ── Monitor open trades ───────────────────────────────────────────────────
    for trade in open_trades:
        ticker = trade.get("ticker")
        price = quotes.get(ticker)
        if price is None:
            continue

        target = trade.get("target_price")
        stop = trade.get("stop_loss")
        direction = trade.get("direction", "long")
        mode = trade.get("mode", "paper")

        hit_target = (price >= target) if direction == "long" else (price <= target)
        hit_stop   = (price <= stop)   if direction == "long" else (price >= stop)

        close_reason = None
        if hit_target:
            close_reason = "target_hit"
        elif hit_stop:
            close_reason = "stop_hit"

        if close_reason is None:
            continue

        if mode == "paper":
            try:
                paper_trading_service.close_trade(trade["trade_id"], price, close_reason)
                closed += 1
            except Exception:
                pass
        else:
            try:
                dynamo_service.update_trade(trade["trade_id"], {
                    "flagged_for_manual_close": True,
                    "flag_reason": close_reason,
                    "flag_price": price,
                    "flag_time": now_iso,
                })
                flagged += 1
            except Exception:
                pass

    return {
        "checked": len(open_trades) + len(pending_trades),
        "filled": filled,
        "closed": closed,
        "flagged": flagged,
    }


def run_end_of_day() -> dict:
    """3:45pm ET — expire pending orders, close open paper trades, flag live trades."""
    today = datetime.now(tz=ET).strftime("%Y-%m-%d")

    # Expire any orders that never filled today
    expired = paper_trading_service.expire_unfilled_orders(today)

    open_trades = dynamo_service.get_open_trades()
    if not open_trades:
        return {"paper_closed": 0, "live_flagged": 0, "expired": expired}

    tickers = list({t["ticker"] for t in open_trades if t.get("ticker")})
    try:
        quotes = {q["ticker"]: q["price"] for q in schwab_service.get_batch_quotes(tickers)}
    except Exception:
        quotes = {}

    now_iso = datetime.now(tz=ET).isoformat()
    paper_closed = 0
    live_flagged = 0

    for trade in open_trades:
        ticker = trade.get("ticker")
        price = quotes.get(ticker)
        mode = trade.get("mode", "paper")

        if mode == "paper":
            exit_price = price or trade.get("entry_price", 0)
            try:
                paper_trading_service.close_trade(trade["trade_id"], exit_price, "eod_close")
                paper_closed += 1
            except Exception:
                pass
        else:
            try:
                dynamo_service.update_trade(trade["trade_id"], {
                    "flagged_for_manual_close": True,
                    "flag_reason": "eod_close",
                    "flag_time": now_iso,
                })
                live_flagged += 1
            except Exception:
                pass

    return {"paper_closed": paper_closed, "live_flagged": live_flagged, "expired": expired}
