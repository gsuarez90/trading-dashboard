"""
DynamoDB-backed cache layer + Lambda handler implementations.

Three scheduled jobs:
  run_daily_refresh()   — 9:32am ET: scanner + sentiment + briefing → DynamoDB
  run_price_monitor()   — every 5 min, market hours: auto-close paper trades at target/stop
  run_end_of_day()      — 3:45pm ET: close all open paper trades, flag live trades
"""

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from services import claude_service, dynamo_service, finnhub_service, schwab_service
from services import paper_trading_service
from services.context_loader import _get_watchlist, load_context

ET = ZoneInfo("America/New_York")
logger = logging.getLogger()
logger.setLevel(logging.INFO)


# ── Cache helpers ─────────────────────────────────────────────────────────────


def _last_refresh_date() -> date:
    """Date of the most recent expected 9:32am ET weekday refresh.

    Used to determine whether cached data is still valid across weekends and
    Monday pre-market (before the 9:32am refresh fires).
    """
    now_et = datetime.now(tz=ET)
    d = now_et.date()
    wd = d.weekday()  # Mon=0 … Fri=4, Sat=5, Sun=6
    if wd < 5:  # Weekday
        h, m = now_et.hour, now_et.minute
        if h > 9 or (h == 9 and m >= 32):
            return d  # Today's 9:32am refresh has already run
        # Before 9:32am — last refresh was the previous weekday
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        return d
    elif wd == 5:  # Saturday
        return d - timedelta(days=1)  # Friday
    else:  # Sunday
        return d - timedelta(days=2)  # Friday


def _cache_is_fresh(cached_at: str | None) -> bool:
    """True if the cache was written on or after the last expected refresh date.

    Replaces the previous today-only check so Friday's cache remains valid
    through the weekend and Monday pre-market (before the 9:35am refresh fires).
    """
    if not cached_at:
        return False
    try:
        ts = datetime.fromisoformat(cached_at).astimezone(ET)
        return ts.date() >= _last_refresh_date()
    except Exception:
        return False


def get_cached_scanner(tickers: list[str] | None = None, limit: int = 20) -> list[dict] | None:
    """Return live-priced movers for the cached ticker watchlist if cache is fresh, else None.

    The cache stores only ticker symbols (selected at morning refresh). Prices, change %,
    and volume are always fetched live — get_previous_day_movers() calls the Schwab real-time
    quotes endpoint despite its name; "previous day" refers to the change % baseline only.
    """
    data, cached_at = dynamo_service.get_cache("scanner")
    if data is not None and _cache_is_fresh(cached_at):
        # data is a list of ticker strings, not full mover objects
        cached_tickers = data if tickers is None else [t for t in data if t in set(tickers)]
        try:
            return schwab_service.get_previous_day_movers(cached_tickers, limit=limit)
        except Exception:
            return None
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


def get_cached_live_briefing() -> dict | None:
    """Return cached live briefing payload {briefing, date} if fresh, else None."""
    data, cached_at = dynamo_service.get_cache("briefing_live")
    if data is not None and _cache_is_fresh(cached_at):
        return data
    return None


def store_live_briefing(briefing_text: str, date: str) -> None:
    """Write live briefing to DynamoDB cache."""
    dynamo_service.put_cache("briefing_live", {"briefing": briefing_text, "date": date})


# ── Lambda handlers ───────────────────────────────────────────────────────────


def run_live_briefing_refresh() -> dict:
    """9:35am ET weekdays — generate morning briefing with live Robinhood portfolio context."""
    logger.info("Live briefing refresh starting")
    try:
        ctx = load_context()
        briefing_text = claude_service.morning_briefing(ctx)
        store_live_briefing(briefing_text, ctx.date)
        logger.info("Live briefing refresh complete")
        return {"refreshed_at": datetime.now(tz=ET).isoformat(), "briefing_cached": True}
    except Exception as e:
        logger.error("Live briefing refresh failed: %s", e, exc_info=True)
        return {"refreshed_at": datetime.now(tz=ET).isoformat(), "briefing_cached": False, "error": str(e)}


def run_daily_refresh() -> dict:
    """7:00am ET — pre-compute scanner + sentiment and write to DynamoDB cache."""
    logger.info("Daily refresh starting")
    tickers = _get_watchlist()
    logger.info("Watchlist: %d tickers", len(tickers))
    errors = []

    # Scanner / movers
    try:
        movers = schwab_service.get_previous_day_movers(tickers, limit=50)
        dynamo_service.put_cache("scanner", [m["ticker"] for m in movers])
        scanner_count = len(movers)
        logger.info("Scanner cached %d tickers", scanner_count)
    except Exception as e:
        logger.error("Scanner failed: %s", e, exc_info=True)
        errors.append(f"scanner: {e}")
        scanner_count = 0

    # Sentiment — score top movers only (API rate limit friendly)
    try:
        sentiment_tickers = [m["ticker"] for m in movers[:15]] if scanner_count else tickers[:15]
        sentiment = finnhub_service.score_batch_sentiment(sentiment_tickers)
        dynamo_service.put_cache("sentiment", sentiment)
        sentiment_count = len(sentiment)
        logger.info("Sentiment scored %d tickers", sentiment_count)
    except Exception as e:
        logger.error("Sentiment failed: %s", e, exc_info=True)
        errors.append(f"sentiment: {e}")
        sentiment_count = 0

    # Morning briefing — generated once, cached for the day
    try:
        ctx = load_context()
        briefing_text = claude_service.morning_briefing(ctx)
        dynamo_service.put_cache("briefing", {"briefing": briefing_text, "date": ctx.date})
        briefing_ok = True
        logger.info("Briefing cached")
    except Exception as e:
        logger.error("Briefing failed: %s", e, exc_info=True)
        errors.append(f"briefing: {e}")
        briefing_ok = False

    if errors:
        logger.warning("Daily refresh completed with errors: %s", errors)
    else:
        logger.info("Daily refresh complete — scanner=%d sentiment=%d briefing=%s",
                    scanner_count, sentiment_count, briefing_ok)

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
        logger.info("Price monitor: no open or pending trades")
        return {"checked": 0, "filled": 0, "closed": 0, "flagged": 0}

    logger.info("Price monitor: %d open, %d pending", len(open_trades), len(pending_trades))

    # Single batch quote call covering all unique tickers
    all_tickers = list({t["ticker"] for t in open_trades + pending_trades if t.get("ticker")})
    try:
        quotes = {q["ticker"]: q["price"] for q in schwab_service.get_batch_quotes(all_tickers)}
        logger.info("Price monitor: quotes fetched for %d tickers", len(quotes))
    except Exception as e:
        logger.error("Price monitor: Schwab quotes failed — trades will not be evaluated: %s", e, exc_info=True)
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
            logger.info("Filled pending order %s %s @ %.2f", ticker, trade["trade_id"], price)
        except Exception as e:
            logger.error("Failed to fill pending order %s: %s", trade["trade_id"], e)

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
        hit_stop = (price <= stop) if direction == "long" else (price >= stop)

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
                logger.info("Closed paper trade %s %s @ %.2f (%s)", ticker, trade["trade_id"], price, close_reason)
            except Exception as e:
                logger.error("Failed to close paper trade %s: %s", trade["trade_id"], e)
        else:
            try:
                dynamo_service.update_trade(
                    trade["trade_id"],
                    {
                        "flagged_for_manual_close": True,
                        "flag_reason": close_reason,
                        "flag_price": price,
                        "flag_time": now_iso,
                    },
                )
                flagged += 1
                logger.info("Flagged live trade %s %s for manual close (%s)", ticker, trade["trade_id"], close_reason)
            except Exception as e:
                logger.error("Failed to flag live trade %s: %s", trade["trade_id"], e)

    logger.info("Price monitor complete — filled=%d closed=%d flagged=%d", filled, closed, flagged)
    return {
        "checked": len(open_trades) + len(pending_trades),
        "filled": filled,
        "closed": closed,
        "flagged": flagged,
    }


def run_end_of_day() -> dict:
    """3:45pm ET — expire pending orders, close open paper trades, flag live trades."""
    logger.info("EOD handler starting")
    today = datetime.now(tz=ET).strftime("%Y-%m-%d")

    # Expire any orders that never filled today
    expired = paper_trading_service.expire_unfilled_orders(today)
    if expired:
        logger.info("EOD: expired %d unfilled orders", expired)

    open_trades = dynamo_service.get_open_trades()
    if not open_trades:
        logger.info("EOD: no open trades")
        return {"paper_closed": 0, "live_flagged": 0, "expired": expired}

    logger.info("EOD: processing %d open trades", len(open_trades))
    tickers = list({t["ticker"] for t in open_trades if t.get("ticker")})
    try:
        quotes = {q["ticker"]: q["price"] for q in schwab_service.get_batch_quotes(tickers)}
        logger.info("EOD: quotes fetched for %d tickers", len(quotes))
    except Exception as e:
        logger.error("EOD: Schwab quotes failed — using entry prices as fallback: %s", e, exc_info=True)
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
                logger.info("EOD: closed paper trade %s %s @ %.2f", ticker, trade["trade_id"], exit_price)
            except Exception as e:
                logger.error("EOD: failed to close paper trade %s: %s", trade["trade_id"], e)
        else:
            try:
                dynamo_service.update_trade(
                    trade["trade_id"],
                    {
                        "flagged_for_manual_close": True,
                        "flag_reason": "eod_close",
                        "flag_time": now_iso,
                    },
                )
                live_flagged += 1
                logger.info("EOD: flagged live trade %s %s for manual close", ticker, trade["trade_id"])
            except Exception as e:
                logger.error("EOD: failed to flag live trade %s: %s", trade["trade_id"], e)

    logger.info("EOD complete — paper_closed=%d live_flagged=%d expired=%d", paper_closed, live_flagged, expired)
    return {"paper_closed": paper_closed, "live_flagged": live_flagged, "expired": expired}
