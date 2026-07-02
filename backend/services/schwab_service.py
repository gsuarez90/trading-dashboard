"""
Schwab market data service — real-time quotes and price history.
Replaces yfinance (market_data_service.py) and Finnhub quote calls.

Local dev:  reads token from schwab_token.json (written by scripts/schwab_auth.py)
Lambda:     reads/writes token via Secrets Manager (wired up at Step 21)
"""

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import boto3
import schwab

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

_MIN_PRICE = 5.0
_MIN_VOLUME = 500_000

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client

    api_key = os.environ.get("SCHWAB_CLIENT_ID")
    app_secret = os.environ.get("SCHWAB_CLIENT_SECRET")
    if not api_key or not app_secret:
        from services.ssm_service import get_secret

        api_key = api_key or get_secret("/trading-app/schwab-client-id")
        app_secret = app_secret or get_secret("/trading-app/schwab-client-secret")

    # Lambda: token stored in Secrets Manager
    secret_arn = os.environ.get("SCHWAB_TOKEN_SECRET_ARN")
    if secret_arn:
        sm = boto3.client("secretsmanager")

        def _read():
            return json.loads(sm.get_secret_value(SecretId=secret_arn)["SecretString"])

        def _write(token, **kwargs):
            sm.put_secret_value(SecretId=secret_arn, SecretString=json.dumps(token))

        _client = schwab.auth.client_from_access_functions(
            api_key=api_key,
            app_secret=app_secret,
            token_read_func=_read,
            token_write_func=_write,
        )
        return _client

    # Local dev: token file written by scripts/schwab_auth.py
    token_path = os.environ.get("SCHWAB_TOKEN_PATH", "schwab_token.json")
    resolved = Path(token_path)
    if not resolved.is_absolute():
        resolved = Path(__file__).resolve().parent.parent / token_path

    if not resolved.exists():
        raise RuntimeError(
            f"Schwab token not found at {resolved}. " "Run scripts/schwab_auth.py to authenticate."
        )

    _client = schwab.auth.client_from_token_file(
        token_path=str(resolved),
        api_key=api_key,
        app_secret=app_secret,
    )
    return _client


# ── Quotes (replaces finnhub_service.get_batch_quotes) ───────────────────────


def get_batch_quotes(tickers: list[str]) -> list[dict]:
    """Real-time quotes for a list of tickers.

    Returns same shape as finnhub_service.get_batch_quotes() so portfolio.py
    needs no changes.
    """
    if not tickers:
        return []

    resp = _get_client().get_quotes(tickers)
    resp.raise_for_status()
    data = resp.json()

    results = []
    for ticker in tickers:
        entry = data.get(ticker, {})
        quote = entry.get("quote", {})
        price = quote.get("lastPrice") or quote.get("mark")
        if price is None:
            continue
        results.append({"ticker": ticker, "price": round(float(price), 2)})
    return results


# ── Dynamic watchlist via Schwab movers ──────────────────────────────────────

_WATCHLIST_INDEXES = [
    schwab.client.Client.Movers.Index.SPX,
    schwab.client.Client.Movers.Index.COMPX,
    schwab.client.Client.Movers.Index.DJI,
]


def get_dynamic_watchlist(min_price: float = _MIN_PRICE) -> list[str]:
    """Return a deduplicated list of top movers across SPX, Nasdaq, and Dow.

    Replaces the static _DEFAULT_TICKERS in context_loader. Falls back to an
    empty list if the API call fails — callers should handle the fallback.
    """
    client = _get_client()
    seen: set[str] = set()
    tickers: list[str] = []

    for index in _WATCHLIST_INDEXES:
        try:
            resp = client.get_movers(
                index,
                sort_order=schwab.client.Client.Movers.SortOrder.PERCENT_CHANGE_UP,
            )
            resp.raise_for_status()
            data = resp.json()
            # Response is a list of mover objects
            screeners = data.get("screeners", data) if isinstance(data, dict) else data
            for item in screeners:
                symbol = item.get("symbol") or item.get("ticker")
                last = item.get("lastPrice") or item.get("price") or 0
                if symbol and symbol not in seen and float(last) >= min_price:
                    seen.add(symbol)
                    tickers.append(symbol)
        except Exception:
            logger.exception("schwab get_movers failed for index %s", index)
            continue

    return tickers


# ── Scanner / movers (replaces market_data_service) ──────────────────────────


def get_previous_day_movers(tickers: list[str], limit: int = 20) -> list[dict]:
    """Real-time % movers using Schwab quote data (netPercentChange from prev close)."""
    if not tickers:
        return []

    resp = _get_client().get_quotes(tickers)
    resp.raise_for_status()
    data = resp.json()

    results = []
    for ticker in tickers:
        entry = data.get(ticker, {})
        quote = entry.get("quote", {})

        last = quote.get("lastPrice") or quote.get("mark")
        volume = quote.get("totalVolume")
        change_pct = quote.get("netPercentChange")
        open_price = quote.get("openPrice")
        high = quote.get("highPrice")
        low = quote.get("lowPrice")
        prev_close = quote.get("closePrice")

        if last is None or volume is None or change_pct is None:
            continue
        if float(last) < _MIN_PRICE or float(volume) < _MIN_VOLUME:
            continue

        results.append(
            {
                "ticker": ticker,
                "direction": "up" if float(change_pct) >= 0 else "down",
                "price": round(float(last), 2),
                "open": round(float(open_price), 2) if open_price is not None else None,
                "high": round(float(high), 2) if high is not None else None,
                "low": round(float(low), 2) if low is not None else None,
                "prev_close": round(float(prev_close), 2) if prev_close is not None else None,
                "change_pct": round(float(change_pct), 2),
                "volume": int(volume),
                "vwap": None,
            }
        )

    results.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
    return results[:limit]


def get_scanner_results(tickers: list[str], min_change_pct: float = 2.0) -> list[dict]:
    """Movers above a % threshold — used by the morning briefing context."""
    movers = get_previous_day_movers(tickers, limit=len(tickers))
    return [m for m in movers if abs(m["change_pct"]) >= min_change_pct]


# ── Price history ─────────────────────────────────────────────────────────────


def _fetch_today_status() -> dict:
    """Single Schwab call for today's market open/closed status.

    Used by get_market_status() and context_loader._minutes_remaining().
    Kept separate so callers that only need is_open don't pay for the
    forward query that computes next_open_date.
    """
    resp = _get_client().get_market_hours([schwab.client.Client.MarketHours.Market.EQUITY])
    resp.raise_for_status()
    equity = next(iter(resp.json().get("equity", {}).values()), {})
    return {
        "is_open": equity.get("isOpen", False),
        "date": equity.get("date"),
    }


def get_market_status() -> dict:
    """Returns current equity market status plus next trading day.

    Queries today's status, then walks forward day-by-day until Schwab
    confirms a trading day — typically 1 extra call (tomorrow), up to 4
    over a long weekend. Accounts for all NYSE holidays automatically.
    """
    client = _get_client()
    today = _fetch_today_status()
    now_et = datetime.now(tz=ET)

    # Schwab's isOpen means "is today a trading day", not "is the market open right now".
    # Cross-check with current ET time so after-hours returns is_open=False.
    within_hours = (
        now_et.weekday() < 5
        and (now_et.hour > 9 or (now_et.hour == 9 and now_et.minute >= 30))
        and now_et.hour < 16
    )
    # Pre-market on a trading day: the next open is today — skip the forward walk.
    pre_market = now_et.weekday() < 5 and (
        now_et.hour < 9 or (now_et.hour == 9 and now_et.minute < 30)
    )
    if today["is_open"] and pre_market:
        next_open = now_et.date().strftime("%Y-%m-%d")
    else:
        check = now_et.date()
        next_open = None
        for _ in range(10):
            check += timedelta(days=1)
            r = client.get_market_hours(
                [schwab.client.Client.MarketHours.Market.EQUITY], date=check
            )
            r.raise_for_status()
            eq = next(iter(r.json().get("equity", {}).values()), {})
            if eq.get("isOpen", False):
                next_open = check.strftime("%Y-%m-%d")
                break

    return {
        "is_open": today["is_open"] and within_hours,
        "date": today["date"],
        "next_open_date": next_open,
    }


def get_daily_bars(ticker: str, from_date: str, to_date: str) -> list[dict]:
    """Daily OHLCV bars for a ticker. Dates as 'YYYY-MM-DD'.

    Used for paper trade validation and backtesting.
    """
    start = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=ET)
    end = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=ET)

    resp = _get_client().get_price_history_every_day(
        ticker,
        start_datetime=start,
        end_datetime=end,
        need_previous_close=False,
    )
    resp.raise_for_status()
    data = resp.json()

    result = []
    for candle in data.get("candles", []):
        ts = datetime.fromtimestamp(candle["datetime"] / 1000, tz=ET)
        result.append(
            {
                "date": ts.strftime("%Y-%m-%d"),
                "open": round(float(candle["open"]), 2),
                "high": round(float(candle["high"]), 2),
                "low": round(float(candle["low"]), 2),
                "close": round(float(candle["close"]), 2),
                "volume": int(candle["volume"]),
                "vwap": None,
            }
        )
    return result


# ── Technical indicators ──────────────────────────────────────────────────────


def get_technical_indicators(tickers: list[str]) -> dict[str, dict]:
    """5-min intraday indicators using the opening range candle as the catalyst.

    Fetches today's 1-min bars for each ticker via Schwab price history, then
    aggregates them into 5-min buckets for ORH/ORL/EMA(3)/EMA(6) — this keeps
    those indicators' original 15-min/30-min lookback character (low noise)
    while still giving RVOL access to finer-grained volume data than a single
    5-min fetch would provide.

    bucket[0] (the first 5 one-min candles, 9:30-9:35am) is the opening range —
    its high/low are the Opening Range High (ORH) and Opening Range Low (ORL).

    RVOL compares the latest 1-min candle's volume to the average volume of
    every 1-min candle since the opening range (excluding the opening range
    itself, which is structurally always the day's highest-volume period and
    would otherwise skew a same-day baseline — especially early in the
    session when few candles exist to average against).

    Runs all tickers in parallel. Skips tickers with fewer than 6 five-min
    buckets (not enough history for EMA(6) to be meaningful).

    Returns dict keyed by ticker:
    {
        orh, orl,                        # opening range high/low (9:30-9:35am)
        ema_3, ema_6, vwap, rvol,
        ema_3_above_ema_6, price_above_vwap,
        price_above_orh, price_below_orl,
        current_price, bounce_setup
    }
    """
    if not tickers:
        return {}

    today_et = datetime.now(tz=ET)
    start = today_et.replace(hour=9, minute=30, second=0, microsecond=0)
    end = today_et

    def _compute(ticker: str) -> tuple[str, dict | None]:
        try:
            resp = _get_client().get_price_history_every_minute(
                ticker,
                start_datetime=start,
                end_datetime=end,
                need_previous_close=False,
            )
            resp.raise_for_status()
            candles = resp.json().get("candles", [])

            # 5-min buckets from 1-min candles — preserves ORH/ORL/EMA's original
            # lookback window. Last bucket may be partial (still-forming 5-min bar).
            buckets = [candles[i : i + 5] for i in range(0, len(candles), 5)]
            if len(buckets) < 6:
                return ticker, None

            bucket_highs = [max(float(c["high"]) for c in b) for b in buckets]
            bucket_lows = [min(float(c["low"]) for c in b) for b in buckets]
            bucket_closes = [float(b[-1]["close"]) for b in buckets]

            orh = round(bucket_highs[0], 2)
            orl = round(bucket_lows[0], 2)

            # EMA — seed with SMA of first `period` buckets, then smooth forward
            def _ema(period: int) -> float:
                sma = sum(bucket_closes[:period]) / period
                k = 2 / (period + 1)
                val = sma
                for price in bucket_closes[period:]:
                    val = price * k + val * (1 - k)
                return round(val, 4)

            ema3 = _ema(3)
            ema6 = _ema(6)

            # VWAP and current price — computed on the raw 1-min series for precision
            closes = [float(c["close"]) for c in candles]
            highs = [float(c["high"]) for c in candles]
            lows = [float(c["low"]) for c in candles]
            vols = [float(c["volume"]) for c in candles]

            total_vol = sum(vols)
            vwap = (
                round(
                    sum((highs[i] + lows[i] + closes[i]) / 3 * vols[i] for i in range(len(candles)))
                    / total_vol,
                    4,
                )
                if total_vol > 0
                else None
            )

            current = closes[-1]

            # RVOL — current 1-min candle vs the average of 1-min candles since
            # the opening range (excludes the opening range itself and the
            # current candle from its own baseline).
            post_opening_vols = vols[5:-1]
            if post_opening_vols:
                baseline = sum(post_opening_vols) / len(post_opening_vols)
                rvol = round(vols[-1] / baseline, 2) if baseline > 0 else None
            else:
                rvol = None

            return ticker, {
                "orh": orh,
                "orl": orl,
                "ema_3": ema3,
                "ema_6": ema6,
                "vwap": vwap,
                "rvol": rvol,
                "current_price": round(current, 2),
                "ema_3_above_ema_6": ema3 > ema6,
                "price_above_vwap": vwap is not None and current > vwap,
                "price_above_orh": current > orh,
                "price_below_orl": current < orl,
                "bounce_setup": (
                    ema3 > ema6 and vwap is not None and current > vwap and current >= orh
                ),
            }
        except Exception:
            logger.exception("schwab get_technical_indicators failed for ticker %s", ticker)
            return ticker, None

    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        for ticker, data in pool.map(_compute, tickers):
            if data is not None:
                results[ticker] = data
    return results
