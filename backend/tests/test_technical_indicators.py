"""
Unit tests for _compute_indicators_from_candles() — the pure candle math behind
get_technical_indicators(). Uses synthetic candles so these run without live
market hours or a Schwab token, unlike the rest of test_schwab_service.py.
"""

from services.schwab_service import _compute_indicators_from_candles


def _bucket(n: int, high: float, low: float, close: float, volume: float) -> list[dict]:
    """n identical 1-min candles — enough to fill one 5-min bucket."""
    return [{"high": high, "low": low, "close": close, "volume": volume} for _ in range(n)]


def test_insufficient_candles_returns_none():
    assert _compute_indicators_from_candles(_bucket(4, 100, 99, 99.5, 1000)) is None


def test_fresh_breakout_qualifies_bounce_setup_only():
    candles = _bucket(5, 100, 98, 99, 1000) + _bucket(5, 103, 100.5, 102, 1800)  # noqa: E501
    r = _compute_indicators_from_candles(candles)
    assert r["orh"] == 100.0
    assert r["orl"] == 98.0
    assert r["bounce_setup"] is True
    assert r["pullback_setup"] is False
    assert r["bars_since_breakout"] == 0
    assert r["price_above_orh"] is True


def test_pullback_after_breakout_qualifies_pullback_setup_only():
    """Broke the ORH on a volume spike, then cooled off — still holding above
    EMA(6)/VWAP with positive momentum, but no longer above the ORH itself."""
    candles = (
        _bucket(5, 100, 98, 99, 1000)  # opening range -> orh=100, orl=98
        + _bucket(5, 102, 100.5, 101, 2500)  # breakout spike, big volume (peak rvol)
        + _bucket(5, 101, 99.5, 99.8, 500)  # pullback, low volume, still above support
    )
    r = _compute_indicators_from_candles(candles)
    assert r["bars_since_breakout"] == 1
    assert r["bounce_setup"] is False
    assert r["pullback_setup"] is True
    assert r["price_above_orh"] is False
    assert r["price_below_orl"] is False
    # rvol has decayed well off its peak, which is exactly the case pullback_setup exists for
    assert r["peak_rvol"] > r["rvol"]
    assert r["rvol_pct_of_peak"] < 1.0


def test_never_broke_out_qualifies_neither_setup():
    candles = _bucket(5, 100, 98, 99, 1000) + _bucket(5, 99.5, 97.5, 98, 900)
    r = _compute_indicators_from_candles(candles)
    assert r["bars_since_breakout"] is None
    assert r["bounce_setup"] is False
    assert r["pullback_setup"] is False


def test_breakdown_through_orl_qualifies_neither_setup():
    candles = _bucket(5, 100, 98, 99, 1000) + _bucket(5, 98, 96, 96.5, 1500)
    r = _compute_indicators_from_candles(candles)
    assert r["price_below_orl"] is True
    assert r["bounce_setup"] is False
    assert r["pullback_setup"] is False


def test_peak_rvol_tracks_the_days_highest_reading_not_just_current():
    """A ticker that spiked volume earlier and has since cooled should report
    peak_rvol from the spike, not the current quieter reading — this is the
    whole point of the field (rvol alone can't distinguish the two cases)."""
    candles = (
        _bucket(5, 100, 98, 99, 1000)
        + _bucket(5, 102, 100.5, 101, 2500)
        + _bucket(5, 101, 99.5, 99.8, 500)
    )
    r = _compute_indicators_from_candles(candles)
    assert r["peak_rvol"] == 2.5
    assert r["rvol"] < r["peak_rvol"]


def test_pullback_from_high_pct_reflects_distance_from_intraday_high():
    candles = _bucket(5, 100, 98, 99, 1000) + _bucket(5, 103, 100.5, 102, 1800)
    r = _compute_indicators_from_candles(candles)
    # intraday high is 103, current price is 102 -> pulled back a bit under 1%
    assert 0 < r["pullback_from_high_pct"] < 2


def test_closest_approach_to_orl_pct_catches_a_tested_low_even_after_recovery():
    """Rallied, crashed to nearly the ORL, then partially recovered — mirrors a
    real live case (IONQ, 2026-07-06) where the current pullback looked mild
    (~5%) but price had actually come within a fraction of a percent of the
    ORL an hour earlier. pullback_from_high_pct alone can't see that; this
    field is exactly for catching it."""
    candles = (
        _bucket(5, 100, 98, 99, 1000)  # opening range -> orh=100, orl=98
        + _bucket(5, 106, 100.5, 105, 2000)  # breakout, rallies
        + _bucket(5, 105, 98.2, 98.5, 1500)  # crashes back down, nearly touches orl
        + _bucket(5, 101, 99, 100.5, 900)  # partial recovery
    )
    r = _compute_indicators_from_candles(candles)
    assert r["pullback_from_high_pct"] > 4  # looks like a real but unremarkable pullback
    assert 0 < r["closest_approach_to_orl_pct"] < 1  # but it nearly tested the ORL


def test_closest_approach_to_orl_pct_none_without_a_breakout():
    candles = _bucket(5, 100, 98, 99, 1000) + _bucket(5, 99.5, 97.5, 98, 900)
    r = _compute_indicators_from_candles(candles)
    assert r["closest_approach_to_orl_pct"] is None


def test_pullback_setup_excludes_a_ticker_that_actually_broke_the_orl():
    """Mirrors a real live case (LHSW, 2026-07-06): broke out, then crashed well
    below the ORL, then recovered enough that price_below_orl (current-only)
    no longer shows it. Without the closest_approach_to_orl_pct >= 0 guard this
    would wrongly qualify as pullback_setup — a structural breakdown-and-bounce
    is not the same as "support held"."""
    candles = (
        _bucket(5, 100, 98, 99, 1000)  # opening range -> orh=100, orl=98
        + _bucket(5, 106, 100.5, 105, 2000)  # breakout, rallies
        + _bucket(5, 105, 87, 96, 1500)  # crashes well below the orl (87 vs orl=98)
        + _bucket(5, 100, 95, 99, 900)  # recovers back above the orl
    )
    r = _compute_indicators_from_candles(candles)
    assert r["price_below_orl"] is False  # current price no longer shows the breakdown
    assert r["closest_approach_to_orl_pct"] < 0  # but it happened
    assert r["pullback_setup"] is False
