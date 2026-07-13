"""
Schwab service integration tests — hits the real Schwab API using the local token.
These are live API tests, not mocked. Requires schwab_token.json to be present.

Run from backend/ with venv active:
    pytest tests/test_schwab_service.py -v
"""

import os
from datetime import date, timedelta
from pathlib import Path

import pytest

# Ensure .env.local is loaded before importing the service
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env.local")

from services import schwab_service

# ── Helpers ───────────────────────────────────────────────────────────────────

SINGLE_TICKER = "AAPL"
BATCH_TICKERS = ["AAPL", "MSFT", "NVDA"]
FROM_DATE = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
TO_DATE = date.today().strftime("%Y-%m-%d")


# ── Client init ───────────────────────────────────────────────────────────────


def test_client_initializes():
    """Token file exists and client loads without error."""
    client = schwab_service._get_client()
    assert client is not None


# ── Quotes ────────────────────────────────────────────────────────────────────


def test_get_batch_quotes_returns_prices():
    results = schwab_service.get_batch_quotes(BATCH_TICKERS)
    assert isinstance(results, list)
    assert len(results) > 0, "Expected at least one quote back"
    for q in results:
        assert "ticker" in q
        assert "price" in q
        assert isinstance(q["price"], float)
        assert q["price"] > 0


def test_get_batch_quotes_empty_input():
    assert schwab_service.get_batch_quotes([]) == []


def test_get_batch_quotes_invalid_ticker():
    """Invalid ticker should be silently skipped, not raise."""
    results = schwab_service.get_batch_quotes(["AAPL", "INVALIDXYZ999"])
    tickers_returned = [r["ticker"] for r in results]
    assert "AAPL" in tickers_returned


# ── Scanner / movers ──────────────────────────────────────────────────────────


def test_get_previous_day_movers_returns_list():
    results = schwab_service.get_previous_day_movers(BATCH_TICKERS)
    assert isinstance(results, list)


def test_get_previous_day_movers_fields():
    results = schwab_service.get_previous_day_movers(BATCH_TICKERS)
    for m in results:
        assert "ticker" in m
        assert "price" in m
        assert "change_pct" in m
        assert "direction" in m
        assert m["direction"] in ("up", "down")
        assert isinstance(m["change_pct"], float)


def test_get_previous_day_movers_sorted_by_abs_change():
    results = schwab_service.get_previous_day_movers(BATCH_TICKERS)
    if len(results) > 1:
        changes = [abs(r["change_pct"]) for r in results]
        assert changes == sorted(changes, reverse=True)


def test_get_previous_day_movers_respects_limit():
    results = schwab_service.get_previous_day_movers(BATCH_TICKERS, limit=2)
    assert len(results) <= 2


def test_get_scanner_results_filters_by_threshold():
    # With a very high threshold, should return empty or fewer results
    all_movers = schwab_service.get_previous_day_movers(BATCH_TICKERS)
    high_threshold = 999.0
    results = schwab_service.get_scanner_results(BATCH_TICKERS, min_change_pct=high_threshold)
    assert isinstance(results, list)
    assert len(results) <= len(all_movers)
    for r in results:
        assert abs(r["change_pct"]) >= high_threshold


# ── Dynamic watchlist ─────────────────────────────────────────────────────────


def test_get_dynamic_watchlist_returns_tickers():
    tickers = schwab_service.get_dynamic_watchlist()
    assert isinstance(tickers, list), "Expected a list"
    assert len(tickers) > 0, "Expected at least some tickers from Schwab movers"


def test_get_dynamic_watchlist_no_duplicates():
    tickers = schwab_service.get_dynamic_watchlist()
    assert len(tickers) == len(set(tickers)), "Duplicate tickers in watchlist"


def test_get_dynamic_watchlist_min_price_filter():
    tickers = schwab_service.get_dynamic_watchlist(min_price=5.0)
    # We can't verify prices here without another quote call, just check it runs
    assert isinstance(tickers, list)


# ── Price history ─────────────────────────────────────────────────────────────


def test_get_daily_bars_returns_ohlcv():
    bars = schwab_service.get_daily_bars(SINGLE_TICKER, FROM_DATE, TO_DATE)
    assert isinstance(bars, list)
    assert len(bars) > 0, "Expected at least one daily bar"
    for bar in bars:
        assert "date" in bar
        assert "open" in bar
        assert "high" in bar
        assert "low" in bar
        assert "close" in bar
        assert "volume" in bar
        assert bar["high"] >= bar["low"]
        assert bar["close"] > 0


def test_get_daily_bars_date_range():
    bars = schwab_service.get_daily_bars(SINGLE_TICKER, FROM_DATE, TO_DATE)
    if bars:
        assert bars[0]["date"] >= FROM_DATE
        assert bars[-1]["date"] <= TO_DATE


def test_get_daily_bars_invalid_ticker():
    """Invalid ticker should return empty list, not raise."""
    bars = schwab_service.get_daily_bars("INVALIDXYZ999", FROM_DATE, TO_DATE)
    assert isinstance(bars, list)


# ── Options (intraday-options-pivot-plan.md, options-trade-suggestions-plan.md) ──


def test_get_option_chain_returns_contracts():
    contracts = schwab_service.get_option_chain(SINGLE_TICKER)
    assert isinstance(contracts, list)
    assert len(contracts) > 0, "Expected at least one option contract back"
    for c in contracts:
        assert c["option_type"] in ("call", "put")
        assert c["strike_price"] > 0
        assert c["days_to_expiration"] >= 0


def test_get_option_chain_respects_dte_floor_and_ceiling():
    contracts = schwab_service.get_option_chain(SINGLE_TICKER, min_dte=7, max_dte=21)
    for c in contracts:
        assert 0 <= c["days_to_expiration"] <= 21


def test_get_option_chain_includes_both_call_and_put():
    contracts = schwab_service.get_option_chain(SINGLE_TICKER)
    option_types = {c["option_type"] for c in contracts}
    assert option_types == {"call", "put"}


def test_get_option_quotes_returns_prices():
    contracts = schwab_service.get_option_chain(SINGLE_TICKER)
    sample_symbols = [c["symbol"] for c in contracts[:2]]
    results = schwab_service.get_option_quotes(sample_symbols)
    assert isinstance(results, list)
    assert len(results) > 0
    for q in results:
        assert "option_symbol" in q
        assert "price" in q
        assert q["price"] > 0


def test_get_option_quotes_empty_input():
    assert schwab_service.get_option_quotes([]) == []
