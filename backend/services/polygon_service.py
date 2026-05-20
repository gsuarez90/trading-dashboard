"""
Market data service backed by yfinance (free, ~15-min delayed during market hours).
Replaces the Polygon.io dependency which was removed from requirements.txt.
"""

from datetime import date, timedelta

import yfinance as yf

_MIN_PRICE = 5.0
_MIN_VOLUME = 500_000


def _pct_change(prev: float, last: float) -> float:
    return round((last - prev) / prev * 100, 2)


def get_previous_day_movers(tickers: list[str], limit: int = 20) -> list[dict]:
    """Previous-day % movers for a given ticker list.

    Downloads 5 days of daily bars via yfinance and computes the most recent
    day-over-day change. Sorted by absolute % change, descending.
    """
    if not tickers:
        return []

    from_date = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")
    to_date = date.today().strftime("%Y-%m-%d")

    data = yf.download(
        tickers,
        start=from_date,
        end=to_date,
        interval="1d",
        progress=False,
        auto_adjust=True,
        group_by="ticker" if len(tickers) > 1 else "column",
    )

    if data.empty:
        return []

    results = []
    for ticker in tickers:
        try:
            if len(tickers) == 1:
                closes = data["Close"]
                opens = data["Open"]
                highs = data["High"]
                lows = data["Low"]
                volumes = data["Volume"]
            else:
                closes = data["Close"][ticker]
                opens = data["Open"][ticker]
                highs = data["High"][ticker]
                lows = data["Low"][ticker]
                volumes = data["Volume"][ticker]

            closes = closes.dropna()
            if len(closes) < 2:
                continue

            prev_close = float(closes.iloc[-2])
            last_close = float(closes.iloc[-1])
            volume = float(volumes.iloc[-1]) if not volumes.empty else 0

            if last_close < _MIN_PRICE or volume < _MIN_VOLUME:
                continue

            change_pct = _pct_change(prev_close, last_close)
            results.append(
                {
                    "ticker": ticker,
                    "direction": "up" if change_pct >= 0 else "down",
                    "price": round(last_close, 2),
                    "open": round(float(opens.iloc[-1]), 2) if not opens.empty else None,
                    "high": round(float(highs.iloc[-1]), 2) if not highs.empty else None,
                    "low": round(float(lows.iloc[-1]), 2) if not lows.empty else None,
                    "change_pct": change_pct,
                    "volume": int(volume),
                    "vwap": None,
                }
            )
        except Exception:
            continue

    results.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
    return results[:limit]


def get_scanner_results(tickers: list[str], min_change_pct: float = 2.0) -> list[dict]:
    """Daily scan for the morning briefing — movers above a % threshold."""
    movers = get_previous_day_movers(tickers, limit=len(tickers))
    return [m for m in movers if abs(m["change_pct"]) >= min_change_pct]


def get_daily_bars(ticker: str, from_date: str, to_date: str) -> list[dict]:
    """Daily OHLCV bars for a ticker. Dates as 'YYYY-MM-DD'.

    Used for paper trade validation and backtesting.
    """
    data = yf.download(
        ticker,
        start=from_date,
        end=to_date,
        interval="1d",
        progress=False,
        auto_adjust=True,
    )
    if data.empty:
        return []

    result = []
    for ts, row in data.iterrows():
        result.append(
            {
                "date": ts.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
                "vwap": None,
            }
        )
    return result
