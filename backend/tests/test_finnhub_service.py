"""
Unit tests for finnhub_service's quarterly earnings functions. Monkeypatches
_client() with a fake object so these run without a live Finnhub API key.
"""

from services import finnhub_service


class _FakeFinnhubClient:
    def __init__(self, by_ticker):
        self._by_ticker = by_ticker

    def company_earnings(self, ticker, limit=None):
        return self._by_ticker.get(ticker, [])


_AAPL_RAW = [
    {
        "symbol": "AAPL",
        "estimate": 1.9884,
        "actual": 2.01,
        "period": "2026-03-31",
        "surprise": 0.0216,
        "surprisePercent": 1.0863,
        "year": 2026,
        "quarter": 2,
    }
]


def test_get_quarterly_earnings_maps_fields(monkeypatch):
    monkeypatch.setattr(
        finnhub_service, "_client", lambda: _FakeFinnhubClient({"AAPL": _AAPL_RAW})
    )
    result = finnhub_service.get_quarterly_earnings("aapl", limit=4)
    assert result == [
        {
            "period": "2026-03-31",
            "quarter": 2,
            "year": 2026,
            "estimate": 1.9884,
            "actual": 2.01,
            "surprise": 0.0216,
            "surprise_percent": 1.0863,
        }
    ]


def test_get_quarterly_earnings_empty_for_unsupported_ticker(monkeypatch):
    """ETFs like TQQQ/SQQQ have no earnings history — Finnhub returns an empty
    list, which should pass through as [] rather than erroring."""
    monkeypatch.setattr(finnhub_service, "_client", lambda: _FakeFinnhubClient({}))
    assert finnhub_service.get_quarterly_earnings("TQQQ") == []


def test_get_quarterly_earnings_filters_out_stale_outlier_quarters(monkeypatch):
    """Regression (live case, ticker T): Finnhub's history for T is missing
    2025-09-30 entirely and fills the 4th slot with a Q3 2000 record instead of
    just returning 3 — the ancient outlier must be filtered out, not displayed."""
    raw = [
        {"symbol": "T", "estimate": 0.5996, "actual": 0.65, "period": "2026-06-30",
         "surprise": 0.0504, "surprisePercent": 8.4056, "year": 2026, "quarter": 2},
        {"symbol": "T", "estimate": 0.5609, "actual": 0.57, "period": "2026-03-31",
         "surprise": 0.0091, "surprisePercent": 1.6224, "year": 2026, "quarter": 1},
        {"symbol": "T", "estimate": 0.4719, "actual": 0.52, "period": "2025-12-31",
         "surprise": 0.0481, "surprisePercent": 10.1928, "year": 2025, "quarter": 4},
        {"symbol": "T", "estimate": 0.6069, "actual": 0.57, "period": "2000-09-30",
         "surprise": -0.0369, "surprisePercent": -6.0801, "year": 2000, "quarter": 3},
    ]
    monkeypatch.setattr(finnhub_service, "_client", lambda: _FakeFinnhubClient({"T": raw}))
    result = finnhub_service.get_quarterly_earnings("T", limit=4)
    periods = [q["period"] for q in result]
    assert "2000-09-30" not in periods
    assert periods == ["2026-06-30", "2026-03-31", "2025-12-31"]


def test_get_quarterly_earnings_sorts_descending_even_if_source_unsorted(monkeypatch):
    raw = [
        {"symbol": "X", "estimate": 1.0, "actual": 1.1, "period": "2025-06-30",
         "surprise": 0.1, "surprisePercent": 10.0, "year": 2025, "quarter": 2},
        {"symbol": "X", "estimate": 1.0, "actual": 1.2, "period": "2026-03-31",
         "surprise": 0.2, "surprisePercent": 20.0, "year": 2026, "quarter": 1},
    ]
    monkeypatch.setattr(finnhub_service, "_client", lambda: _FakeFinnhubClient({"X": raw}))
    result = finnhub_service.get_quarterly_earnings("X", limit=4)
    assert [q["period"] for q in result] == ["2026-03-31", "2025-06-30"]


def test_get_batch_quarterly_earnings_keys_by_ticker_and_survives_failure(monkeypatch):
    class _PartiallyFailingClient:
        def company_earnings(self, ticker, limit=None):
            if ticker == "AAPL":
                return _AAPL_RAW
            if ticker == "BROKEN":
                raise RuntimeError("finnhub down")
            return []

    monkeypatch.setattr(finnhub_service, "_client", lambda: _PartiallyFailingClient())
    result = finnhub_service.get_batch_quarterly_earnings(["AAPL", "TQQQ", "BROKEN"])
    assert result["AAPL"][0]["actual"] == 2.01
    assert result["TQQQ"] == []
    assert result["BROKEN"] == []
