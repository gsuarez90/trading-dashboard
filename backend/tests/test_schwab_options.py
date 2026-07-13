"""
Unit tests for the pure-function pieces of the options pivot's
schwab_service.py additions: _normalize_option_contract() and
closest_listed_strike(). Uses synthetic contract dicts shaped like a real
Schwab option-chain response (fields confirmed live via
scripts/test_option_chain_live.py, 2026-07-13) so these run without a
Schwab token or live market hours.

get_option_chain()/get_option_quotes() themselves are live-only (real API
calls, no local mocking) — covered in test_schwab_service.py, matching that
file's existing live-integration convention.
"""

from services import schwab_service
from services.schwab_service import _normalize_option_contract, closest_listed_strike


def _raw_contract(**overrides) -> dict:
    """A realistic raw Schwab contract dict, with sane defaults overridable
    per test. Field names/shapes match the live spike response exactly."""
    base = {
        "symbol": "AAPL  260720C00310000",
        "bid": 8.35,
        "ask": 9.0,
        "last": 8.55,
        "mark": 8.68,
        "totalVolume": 62,
        "volatility": 23.835,
        "delta": 0.75,
        "gamma": 0.03,
        "theta": -0.237,
        "vega": 0.141,
        "openInterest": 174,
        "strikePrice": 310.0,
        "expirationDate": "2026-07-20T20:00:00.000+00:00",
        "daysToExpiration": 7,
        "breakEven": 318.68,
        "inTheMoney": True,
    }
    base.update(overrides)
    return base


def test_normalize_option_contract_maps_all_fields():
    r = _normalize_option_contract(_raw_contract(), "call")
    assert r["symbol"] == "AAPL  260720C00310000"
    assert r["option_type"] == "call"
    assert r["strike_price"] == 310.0
    assert r["expiration_date"] == "2026-07-20"
    assert r["days_to_expiration"] == 7
    assert r["bid"] == 8.35
    assert r["ask"] == 9.0
    assert r["last"] == 8.55
    assert r["mark"] == 8.68
    assert r["volume"] == 62
    assert r["open_interest"] == 174
    assert r["delta"] == 0.75
    assert r["gamma"] == 0.03
    assert r["theta"] == -0.237
    assert r["vega"] == 0.141
    assert r["implied_volatility"] == 23.835
    assert r["breakeven_price"] == 318.68
    assert r["in_the_money"] is True


def test_normalize_option_contract_strips_time_from_expiration_date():
    r = _normalize_option_contract(
        _raw_contract(expirationDate="2026-08-01T20:00:00.000+00:00"), "put"
    )
    assert r["expiration_date"] == "2026-08-01"


def test_normalize_option_contract_computes_bid_ask_spread_pct():
    # bid=8.35, ask=9.0 -> mid=8.675, spread=(9.0-8.35)/8.675*100
    r = _normalize_option_contract(_raw_contract(), "call")
    expected = round((9.0 - 8.35) / 8.675 * 100, 2)
    assert r["bid_ask_spread_pct"] == expected


def test_normalize_option_contract_handles_missing_bid_ask():
    r = _normalize_option_contract(_raw_contract(bid=None, ask=None), "call")
    assert r["bid_ask_spread_pct"] is None


def test_normalize_option_contract_option_type_reflects_argument_not_data():
    """option_type comes from which exp-date map the caller pulled the
    contract from (callExpDateMap vs putExpDateMap) — get_option_chain()
    passes it in explicitly rather than reading it back out of the raw
    contract dict."""
    r = _normalize_option_contract(_raw_contract(), "put")
    assert r["option_type"] == "put"


def test_closest_listed_strike_picks_nearest():
    strikes = [300.0, 305.0, 310.0, 315.0, 320.0]
    assert closest_listed_strike(307.0, strikes) == 305.0
    assert closest_listed_strike(308.0, strikes) == 310.0


def test_closest_listed_strike_exact_match():
    strikes = [300.0, 305.0, 310.0]
    assert closest_listed_strike(305.0, strikes) == 305.0


def test_closest_listed_strike_handles_uneven_increments():
    """Strike increments vary by underlying price — this must work whether
    the gaps are $0.50, $2.50, or $5 apart, not just a fixed increment."""
    strikes = [50.0, 50.5, 51.0, 305.0, 310.0, 500.0, 505.0]
    assert closest_listed_strike(50.3, strikes) == 50.5
    assert closest_listed_strike(502.0, strikes) == 500.0


# ── get_option_chains (batched) ────────────────────────────────────────────
# Added after a live production bug: calling get_option_chain once per
# qualifying ticker exhausted the agentic loop's iteration budget on days
# with several qualifying setups. get_option_chains lets the Claude tool
# fetch every ticker's chain in one round trip instead of one per ticker.
# get_option_chain() itself is live-only (see module docstring) — these
# tests mock it to isolate get_option_chains()'s batching/error-handling.


def test_get_option_chains_returns_dict_keyed_by_ticker(monkeypatch):
    monkeypatch.setattr(
        schwab_service,
        "get_option_chain",
        lambda ticker, **kwargs: [{"symbol": f"{ticker}_CONTRACT"}],
    )
    result = schwab_service.get_option_chains(["AAPL", "NVDA"])
    assert set(result.keys()) == {"AAPL", "NVDA"}
    assert result["AAPL"] == [{"symbol": "AAPL_CONTRACT"}]
    assert result["NVDA"] == [{"symbol": "NVDA_CONTRACT"}]


def test_get_option_chains_empty_input():
    assert schwab_service.get_option_chains([]) == {}


def test_get_option_chains_one_ticker_failure_does_not_block_others(monkeypatch):
    def flaky(ticker, **kwargs):
        if ticker == "BADTICKER":
            raise RuntimeError("Schwab error")
        return [{"symbol": f"{ticker}_CONTRACT"}]

    monkeypatch.setattr(schwab_service, "get_option_chain", flaky)
    result = schwab_service.get_option_chains(["AAPL", "BADTICKER"])
    assert result["AAPL"] == [{"symbol": "AAPL_CONTRACT"}]
    assert result["BADTICKER"] == []
