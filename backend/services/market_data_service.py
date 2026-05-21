"""
Market data service — thin wrapper that delegates to schwab_service.
yfinance was used as a placeholder; Schwab provides real-time data now.
get_daily_bars is retained for paper trade validation and backtesting.
"""

from services import schwab_service


def get_previous_day_movers(tickers: list[str], limit: int = 20) -> list[dict]:
    return schwab_service.get_previous_day_movers(tickers, limit=limit)


def get_scanner_results(tickers: list[str], min_change_pct: float = 2.0) -> list[dict]:
    return schwab_service.get_scanner_results(tickers, min_change_pct=min_change_pct)


def get_daily_bars(ticker: str, from_date: str, to_date: str) -> list[dict]:
    return schwab_service.get_daily_bars(ticker, from_date, to_date)
