import os
from datetime import datetime

from polygon import RESTClient

_MIN_PRICE = 5.0
_MIN_VOLUME = 500_000


def _client() -> RESTClient:
    return RESTClient(api_key=os.environ["POLYGON_API_KEY"])


def get_intraday_movers(limit: int = 20) -> list[dict]:
    """Top gainers and losers. Filters penny stocks (<$5) and thin volume (<500k)."""
    client = _client()
    raw_gainers = client.get_snapshot_direction("stocks", "gainers", include_otc=False) or []
    raw_losers = client.get_snapshot_direction("stocks", "losers", include_otc=False) or []

    def _shape(snap, direction: str) -> dict | None:
        price = (
            getattr(snap.min, "c", None)
            or getattr(snap.day, "c", None)
            or getattr(snap.prev_day, "c", None)
        )
        volume = getattr(snap.day, "v", 0) or 0
        if not price or price < _MIN_PRICE or volume < _MIN_VOLUME:
            return None
        return {
            "ticker": snap.ticker,
            "direction": direction,
            "price": price,
            "change_pct": round(snap.todays_change_perc or 0, 2),
            "change_dollar": round(snap.todays_change or 0, 2),
            "volume": int(volume),
            "vwap": getattr(snap.day, "vw", None),
        }

    half = limit // 2
    gainers = [r for s in raw_gainers[: half * 2] if (r := _shape(s, "up"))][:half]
    losers = [r for s in raw_losers[: half * 2] if (r := _shape(s, "down"))][:half]
    return gainers + losers


def get_stock_price(ticker: str) -> float | None:
    """Most recent price for a ticker. Returns None if unavailable."""
    client = _client()
    snap = client.get_snapshot_ticker("stocks", ticker)
    if not snap:
        return None
    return (
        getattr(snap.min, "c", None)
        or getattr(snap.day, "c", None)
        or getattr(snap.prev_day, "c", None)
    )


def get_scanner_results(min_change_pct: float = 2.0) -> list[dict]:
    """Daily scan — movers filtered to a minimum % change threshold."""
    movers = get_intraday_movers(limit=40)
    return [m for m in movers if abs(m["change_pct"]) >= min_change_pct]


def get_daily_bars(ticker: str, from_date: str, to_date: str) -> list[dict]:
    """Daily OHLCV bars for a ticker. Dates as 'YYYY-MM-DD'."""
    client = _client()
    bars = client.get_aggs(ticker, 1, "day", from_date, to_date, adjusted=True) or []
    result = []
    for b in bars:
        ts = getattr(b, "timestamp", None)
        result.append(
            {
                "date": datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d") if ts else None,
                "open": getattr(b, "open", None),
                "high": getattr(b, "high", None),
                "low": getattr(b, "low", None),
                "close": getattr(b, "close", None),
                "volume": getattr(b, "volume", None),
                "vwap": getattr(b, "vwap", None),
            }
        )
    return result
