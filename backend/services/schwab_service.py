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


def _has_holiday_gap(today: date, next_trading_day: date) -> bool:
    """True when next_trading_day is further out than the ordinary next weekday.

    A gap here means a market holiday sits between today and the next session —
    covers July 4th, Thanksgiving, Labor Day, etc. without a hardcoded holiday list.
    """
    expected = today + timedelta(days=1)
    while expected.weekday() >= 5:
        expected += timedelta(days=1)
    return next_trading_day > expected


def is_holiday_adjacent_session() -> bool:
    """True when today is the last trading session before a holiday-extended break.

    Reuses get_market_status()'s live Schwab forward-walk (which already resolves
    all NYSE holidays) to find the next real trading day, then checks whether a
    holiday — not just the weekend — sits between today and that day. Informational
    only: thin, holiday-adjacent volume tends to produce more false breakouts.
    """
    status = get_market_status()
    if not status.get("next_open_date"):
        return False
    today = datetime.now(tz=ET).date()
    next_open = datetime.strptime(status["next_open_date"], "%Y-%m-%d").date()
    return _has_holiday_gap(today, next_open)


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


def _compute_indicators_from_candles(candles: list[dict]) -> dict | None:
    """Pure candle math extracted from get_technical_indicators() so it can be
    unit tested with synthetic candles instead of requiring live market hours.

    bucket[0] (the first 5 one-min candles, 9:30-9:35am) is the opening range —
    its high/low are the Opening Range High (ORH) and Opening Range Low (ORL).

    RVOL compares a candle's volume to a weighted average of every prior 1-min
    candle today. Only the very first candle (the 9:30-9:31am opening auction
    print, structurally the day's biggest single-minute volume event) is
    down-weighted by half rather than excluded — candles 2-5 of the opening
    range already trade like normal continuous flow and are kept at full
    weight, giving a much fuller baseline early in the session than excluding
    the whole opening range would. peak_rvol/rvol_pct_of_peak recompute this
    same formula at every candle since the ticker's own ORH breakout (not the
    whole session) so the current reading can be read as "decayed from this
    breakout's own volume" vs. "never had volume behind it" — the two look
    identical from a single current rvol value alone. Scoping to since-breakout
    (rather than a whole-day max) avoids an unrelated midday print elsewhere in
    the session — a block trade, a halt reopen — swamping the signal.

    EMA(3) and EMA(6) seed with the first bucket's close (not an N-period SMA),
    matching how most charting platforms render EMA lines from the first bar
    rather than waiting for N complete periods — the same convention Robinhood's
    own charts use. Early readings are naturally less "settled" (closer to the
    seed value) until enough bars have accumulated, which is expected EMA
    behavior, not a defect.

    bars_since_breakout/pullback_setup identify a second, later entry pattern:
    a ticker that already broke the ORH earlier today, has since pulled back,
    but is still holding above EMA(6)/VWAP with positive EMA momentum — as
    distinct from bounce_setup, which only qualifies a ticker still at/above
    the ORH right now. pullback_setup additionally requires
    closest_approach_to_orl_pct >= 0 — the ORL must have actually held at its
    worst point, not just been approached. price_below_orl alone isn't enough
    to catch this: it only checks the *current* price, so a ticker that broke
    below the ORL intraminute and has since recovered would otherwise still
    qualify as if support had cleanly held.

    breakdown_setup/pulldown_setup are the bearish mirror of the above,
    added for the options pivot (intraday-options-pivot-plan.md §3.1) — same
    math, opposite direction. ORL plays the role ORH plays on the bullish
    side (the level that was broken through), and ORH plays the role ORL
    plays (the level that must NOT be reclaimed for the setup to still be
    valid — reclaiming it means the breakdown failed). bars_since_breakdown/
    peak_rvol_down/rvol_pct_of_peak_down/bounce_from_low_pct/
    closest_approach_to_orh_pct are the literal mirrors of
    bars_since_breakout/peak_rvol/rvol_pct_of_peak/pullback_from_high_pct/
    closest_approach_to_orl_pct, anchored to the breakdown bucket instead of
    the breakout bucket.

    Returns None if there aren't at least 5 candles yet (opening range not
    complete). Otherwise returns:
    {
        orh, orl,                        # opening range high/low (9:30-9:35am)
        ema_3, ema_6, vwap, rvol, peak_rvol, rvol_pct_of_peak,
        pullback_from_high_pct, closest_approach_to_orl_pct, bars_since_breakout,
        peak_rvol_down, rvol_pct_of_peak_down, bounce_from_low_pct,
        closest_approach_to_orh_pct, bars_since_breakdown,
        ema_3_above_ema_6, ema_3_below_ema_6, price_above_vwap, price_below_vwap,
        price_above_orh, price_below_orl,
        current_price, bounce_setup, pullback_setup,
        breakdown_setup, pulldown_setup
    }
    """
    if len(candles) < 5:
        return None

    # 5-min buckets from 1-min candles — preserves ORH/ORL/EMA's original
    # lookback window. Last bucket may be partial (still-forming 5-min bar).
    buckets = [candles[i : i + 5] for i in range(0, len(candles), 5)]

    bucket_highs = [max(float(c["high"]) for c in b) for b in buckets]
    bucket_lows = [min(float(c["low"]) for c in b) for b in buckets]
    bucket_closes = [float(b[-1]["close"]) for b in buckets]

    orh = round(bucket_highs[0], 2)
    orl = round(min(float(c["low"]) for c in buckets[0]), 2)

    # EMA — seed with the first bucket's close (not an N-period SMA), then
    # smooth forward. Always computable, even with just one bucket — early
    # readings sit closer to the seed value until more bars accumulate,
    # same convention most charting platforms (including Robinhood) use.
    def _ema(period: int) -> float:
        k = 2 / (period + 1)
        val = bucket_closes[0]
        for price in bucket_closes[1:]:
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

    def _rvol_at(i: int) -> float | None:
        """RVOL as of candle i — candle i's volume vs a weighted baseline of
        every candle before it. Same formula as the original single-point rvol,
        applied at every index so a peak can be tracked across the day."""
        baseline_vols = vols[:i]
        if not baseline_vols:
            return None
        weights = [0.5 if j == 0 else 1.0 for j in range(len(baseline_vols))]
        baseline = sum(v * w for v, w in zip(baseline_vols, weights)) / sum(weights)
        return round(vols[i] / baseline, 2) if baseline > 0 else None

    rvol = _rvol_at(len(vols) - 1)

    # First 5-min bucket after the opening range itself whose high broke the
    # ORH. bucket[0] defines orh so it's excluded from this search.
    breakout_bucket_idx = next((i for i in range(1, len(buckets)) if bucket_highs[i] > orh), None)
    bars_since_breakout = (
        (len(buckets) - 1) - breakout_bucket_idx if breakout_bucket_idx is not None else None
    )

    # peak_rvol is scoped to a fixed window right after this ticker's own
    # breakout — the volume conviction of the breakout itself — rather than
    # "anytime since." Most breakouts happen within the first bucket or two,
    # so an open-ended since-breakout search still spans nearly the whole
    # session and gets swamped by an unrelated print hours later (a block
    # trade, a halt reopen) that has nothing to do with this setup. 15
    # candles (~3 buckets / 15 minutes) bounds the search to the breakout's
    # immediate volume thrust.
    _PEAK_WINDOW_CANDLES = 15
    peak_search_start = max(breakout_bucket_idx * 5, 1) if breakout_bucket_idx is not None else 1
    peak_search_end = min(peak_search_start + _PEAK_WINDOW_CANDLES, len(vols))
    rvol_series = [
        r for i in range(peak_search_start, peak_search_end) if (r := _rvol_at(i)) is not None
    ]
    peak_rvol = max(rvol_series) if rvol_series else rvol
    rvol_pct_of_peak = round(rvol / peak_rvol, 2) if rvol is not None and peak_rvol else None

    high_since_open = max(highs)
    pullback_from_high_pct = (
        round((high_since_open - current) / high_since_open * 100, 2)
        if high_since_open > 0
        else None
    )

    # pullback_from_high_pct only reflects where price is *right now* vs. the
    # day's high — it can't tell "drifted down smoothly" apart from "spiked,
    # crashed to the edge of support, and clawed back to the same % off the
    # high." closest_approach_to_orl_pct fills that gap: how close price got
    # to the ORL at its worst point since the breakout, regardless of where
    # it has since recovered to. A small or negative value means the level
    # was genuinely tested (or briefly broken) even if the current snapshot
    # looks calm.
    closest_approach_to_orl_pct = (
        round((min(lows[breakout_bucket_idx * 5 :]) - orl) / orl * 100, 2)
        if breakout_bucket_idx is not None and orl > 0
        else None
    )

    # First 5-min bucket after the opening range itself whose low broke the
    # ORL — the literal mirror of breakout_bucket_idx.
    breakdown_bucket_idx = next((i for i in range(1, len(buckets)) if bucket_lows[i] < orl), None)
    bars_since_breakdown = (
        (len(buckets) - 1) - breakdown_bucket_idx if breakdown_bucket_idx is not None else None
    )

    # peak_rvol_down mirrors peak_rvol exactly, just anchored to the
    # breakdown bucket instead of the breakout bucket — the volume
    # conviction of the breakdown itself.
    peak_search_start_down = (
        max(breakdown_bucket_idx * 5, 1) if breakdown_bucket_idx is not None else 1
    )
    peak_search_end_down = min(peak_search_start_down + _PEAK_WINDOW_CANDLES, len(vols))
    rvol_series_down = [
        r
        for i in range(peak_search_start_down, peak_search_end_down)
        if (r := _rvol_at(i)) is not None
    ]
    peak_rvol_down = max(rvol_series_down) if rvol_series_down else rvol
    rvol_pct_of_peak_down = (
        round(rvol / peak_rvol_down, 2) if rvol is not None and peak_rvol_down else None
    )

    low_since_open = min(lows)
    bounce_from_low_pct = (
        round((current - low_since_open) / low_since_open * 100, 2) if low_since_open > 0 else None
    )

    # Mirrors closest_approach_to_orl_pct's role: ORH is the level that must
    # NOT be reclaimed for a breakdown to still be considered valid (the
    # inverse of ORL needing to hold for a bullish pullback). Positive means
    # ORH stayed clear (never approached); negative means price reclaimed
    # above it at some point, invalidating the breakdown thesis even if the
    # current snapshot has since rolled back over.
    closest_approach_to_orh_pct = (
        round((orh - max(highs[breakdown_bucket_idx * 5 :])) / orh * 100, 2)
        if breakdown_bucket_idx is not None and orh > 0
        else None
    )

    price_above_orh = current > orh
    price_below_orl = current < orl
    ema_3_above_ema_6 = ema3 > ema6
    ema_3_below_ema_6 = ema3 < ema6
    price_above_vwap = vwap is not None and current > vwap
    price_below_vwap = vwap is not None and current < vwap
    bounce_setup = ema_3_above_ema_6 and vwap is not None and current > vwap and current >= orh
    breakdown_setup = ema_3_below_ema_6 and price_below_vwap and current <= orl

    pullback_setup = (
        bars_since_breakout is not None
        and not bounce_setup
        and not price_below_orl
        and ema_3_above_ema_6
        and (current >= ema6 or price_above_vwap)
        # the ORL must have actually held, not just been approached — a ticker
        # that broke below it intraminute and recovered is a structural
        # breakdown-and-bounce, not a "support held" continuation, even
        # though price_below_orl (current only) no longer shows it
        and closest_approach_to_orl_pct is not None
        and closest_approach_to_orl_pct >= 0
    )

    pulldown_setup = (
        bars_since_breakdown is not None
        and not breakdown_setup
        and not price_above_orh
        and ema_3_below_ema_6
        and (current <= ema6 or price_below_vwap)
        # mirrors pullback_setup's ORL guard: the ORH must have actually
        # held (never reclaimed), not just been approached
        and closest_approach_to_orh_pct is not None
        and closest_approach_to_orh_pct >= 0
    )

    return {
        "orh": orh,
        "orl": orl,
        "ema_3": ema3,
        "ema_6": ema6,
        "vwap": vwap,
        "rvol": rvol,
        "peak_rvol": peak_rvol,
        "rvol_pct_of_peak": rvol_pct_of_peak,
        "pullback_from_high_pct": pullback_from_high_pct,
        "closest_approach_to_orl_pct": closest_approach_to_orl_pct,
        "bars_since_breakout": bars_since_breakout,
        "peak_rvol_down": peak_rvol_down,
        "rvol_pct_of_peak_down": rvol_pct_of_peak_down,
        "bounce_from_low_pct": bounce_from_low_pct,
        "closest_approach_to_orh_pct": closest_approach_to_orh_pct,
        "bars_since_breakdown": bars_since_breakdown,
        "current_price": round(current, 2),
        "ema_3_above_ema_6": ema_3_above_ema_6,
        "ema_3_below_ema_6": ema_3_below_ema_6,
        "price_above_vwap": price_above_vwap,
        "price_below_vwap": price_below_vwap,
        "price_above_orh": price_above_orh,
        "price_below_orl": price_below_orl,
        "bounce_setup": bounce_setup,
        "pullback_setup": pullback_setup,
        "breakdown_setup": breakdown_setup,
        "pulldown_setup": pulldown_setup,
    }


def get_technical_indicators(tickers: list[str]) -> dict[str, dict]:
    """5-min intraday indicators using the opening range candle as the catalyst.

    Fetches today's 1-min bars for each ticker via Schwab price history, then
    hands them to _compute_indicators_from_candles() for the actual math. Runs
    all tickers in parallel. Skips tickers until the opening range itself is
    complete (5 one-min candles, 9:30-9:35am) — ORH/ORL need that full 5-minute
    window to be a fixed, meaningful reference level.

    need_extended_hours_data=False is required here — without it Schwab
    silently includes pre-market candles ahead of the requested start_datetime
    (observed starting as early as 7:00am ET), which shifts bucket[0] off the
    real 9:30-9:35am opening range and corrupts every field derived from
    orh/orl (bounce_setup, pullback_setup, price_above_orh, etc.).

    See _compute_indicators_from_candles() for the full field list.
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
                need_extended_hours_data=False,
            )
            resp.raise_for_status()
            candles = resp.json().get("candles", [])
            return ticker, _compute_indicators_from_candles(candles)
        except Exception:
            logger.exception("schwab get_technical_indicators failed for ticker %s", ticker)
            return ticker, None

    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        for ticker, data in pool.map(_compute, tickers):
            if data is not None:
                results[ticker] = data
    return results


# ── Options (intraday-options-pivot-plan.md, options-trade-suggestions-plan.md) ──

_OPTION_STRIKES_AROUND_ATM = 6


def _normalize_option_contract(contract: dict, option_type: str) -> dict:
    """Flattens one raw Schwab option-chain contract into the field set
    OptionTradeSetup needs. Field names below (bid/ask/mark/totalVolume/
    volatility/openInterest/strikePrice/expirationDate/daysToExpiration/
    breakEven/inTheMoney) are confirmed against a real response —
    scripts/test_option_chain_live.py, run 2026-07-13.
    """
    bid = contract.get("bid")
    ask = contract.get("ask")
    bid_ask_spread_pct = None
    if bid is not None and ask is not None:
        mid = (bid + ask) / 2
        if mid > 0:
            bid_ask_spread_pct = round((ask - bid) / mid * 100, 2)

    expiration_date = contract.get("expirationDate")
    if expiration_date:
        expiration_date = expiration_date.split("T")[0]

    return {
        "symbol": contract.get("symbol"),
        "option_type": option_type,
        "strike_price": float(contract["strikePrice"]),
        "expiration_date": expiration_date,
        "days_to_expiration": int(contract.get("daysToExpiration", 0)),
        "bid": bid,
        "ask": ask,
        "last": contract.get("last"),
        "mark": contract.get("mark"),
        "volume": contract.get("totalVolume"),
        "open_interest": contract.get("openInterest"),
        "delta": contract.get("delta"),
        "gamma": contract.get("gamma"),
        "theta": contract.get("theta"),
        "vega": contract.get("vega"),
        "implied_volatility": contract.get("volatility"),
        "breakeven_price": contract.get("breakEven"),
        "in_the_money": contract.get("inTheMoney"),
        "bid_ask_spread_pct": bid_ask_spread_pct,
    }


def get_option_chain(
    ticker: str,
    min_dte: int | None = None,
    max_dte: int | None = None,
    strikes_around_atm: int = _OPTION_STRIKES_AROUND_ATM,
) -> list[dict]:
    """Real Schwab option-chain contracts (calls and puts) for a ticker,
    normalized to a flat list of dicts — one per contract.

    Schwab's raw response nests contracts by expiration then strike
    (callExpDateMap/putExpDateMap); this flattens that into what
    OptionTradeSetup needs, via _normalize_option_contract().

    min_dte/max_dte default to the OPTION_MIN_DTE/OPTION_MAX_DTE env vars
    (SSM plain params in Lambda, .env.local locally — same pattern as
    DAILY_LOSS_LIMIT/MAX_POSITION_SIZE_PCT), read fresh at call time rather
    than cached at import, so the same config the guardrail_service.py
    expiration_proximity check enforces also governs what gets fetched
    here — one source of truth instead of two hardcoded numbers that could
    drift apart. Falls back to 7/21 — the options pivot's decided
    expiration floor/ceiling (intraday-options-pivot-plan.md §1, §6).
    """
    if min_dte is None:
        min_dte = int(os.environ.get("OPTION_MIN_DTE", 7))
    if max_dte is None:
        max_dte = int(os.environ.get("OPTION_MAX_DTE", 21))

    today = datetime.now(tz=ET)
    from_date = today + timedelta(days=min_dte)
    to_date = today + timedelta(days=max_dte)

    resp = _get_client().get_option_chain(
        ticker,
        contract_type=schwab.client.Client.Options.ContractType.ALL,
        strike_count=strikes_around_atm,
        strike_range=schwab.client.Client.Options.StrikeRange.NEAR_THE_MONEY,
        from_date=from_date,
        to_date=to_date,
    )
    resp.raise_for_status()
    data = resp.json()

    contracts = []
    for exp_date_map_key, option_type in (("callExpDateMap", "call"), ("putExpDateMap", "put")):
        for strikes in data.get(exp_date_map_key, {}).values():
            for entries in strikes.values():
                for contract in entries:
                    contracts.append(_normalize_option_contract(contract, option_type))
    return contracts


def get_option_quotes(option_symbols: list[str]) -> list[dict]:
    """Real-time premium quotes for OCC-format option symbols — used by the
    price monitor to check a held option's target/stop against its live
    premium.

    Confirmed via scripts/test_option_chain_live.py (2026-07-13) that
    client.get_quotes() accepts option OCC symbols directly, with the same
    quote field names (lastPrice/mark) as equities — same call shape as
    get_batch_quotes(), just keyed by option symbol instead of ticker.
    """
    if not option_symbols:
        return []

    resp = _get_client().get_quotes(option_symbols)
    resp.raise_for_status()
    data = resp.json()

    results = []
    for symbol in option_symbols:
        entry = data.get(symbol, {})
        quote = entry.get("quote", {})
        price = quote.get("mark") or quote.get("lastPrice")
        if price is None:
            continue
        results.append({"option_symbol": symbol, "price": round(float(price), 2)})
    return results


def closest_listed_strike(target_price: float, available_strikes: list[float]) -> float:
    """Nearest strike Schwab actually lists, given a computed target price.

    Strike increments vary by underlying price (e.g. $0.50 near $50, $5 near
    $500) — rather than hardcode an increment table, pick from the real
    strikes a get_option_chain() call already returned.
    """
    return min(available_strikes, key=lambda strike: abs(strike - target_price))
