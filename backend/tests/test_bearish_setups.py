"""
Unit tests for the bearish-mirror fields added to
_compute_indicators_from_candles() for the options pivot
(intraday-options-pivot-plan.md §3.1): breakdown_setup/pulldown_setup and
their supporting fields (peak_rvol_down, rvol_pct_of_peak_down,
bounce_from_low_pct, closest_approach_to_orh_pct, bars_since_breakdown).

Each test here is the literal direction-mirror of the corresponding bullish
test in test_technical_indicators.py — same candle-count structure, values
flipped around the opening range so the ticker breaks down instead of out.
"""

from services.schwab_service import _compute_indicators_from_candles


def _bucket(n: int, high: float, low: float, close: float, volume: float) -> list[dict]:
    """n identical 1-min candles — enough to fill one 5-min bucket."""
    return [{"high": high, "low": low, "close": close, "volume": volume} for _ in range(n)]


def test_fresh_breakdown_qualifies_breakdown_setup_only():
    candles = _bucket(5, 100, 98, 99, 1000) + _bucket(5, 97.5, 95, 96, 1800)
    r = _compute_indicators_from_candles(candles)
    assert r["orh"] == 100.0
    assert r["orl"] == 98.0
    assert r["breakdown_setup"] is True
    assert r["pulldown_setup"] is False
    assert r["bars_since_breakdown"] == 0
    assert r["price_below_orl"] is True


def test_pulldown_after_breakdown_qualifies_pulldown_setup_only():
    """Broke the ORL on a volume spike, then bounced partway — still holding
    below EMA(6)/VWAP with negative momentum, but no longer below the ORL
    itself."""
    candles = (
        _bucket(5, 100, 98, 99, 1000)  # opening range -> orh=100, orl=98
        + _bucket(5, 97.5, 95, 96, 2500)  # breakdown spike, big volume (peak rvol)
        + _bucket(5, 98, 96.5, 97, 500)  # bounce, low volume, still below resistance
    )
    r = _compute_indicators_from_candles(candles)
    assert r["bars_since_breakdown"] == 1
    assert r["breakdown_setup"] is False
    assert r["pulldown_setup"] is True
    assert r["price_above_orh"] is False
    # rvol has decayed well off its peak, which is exactly the case pulldown_setup exists for
    assert r["peak_rvol_down"] > r["rvol"]
    assert r["rvol_pct_of_peak_down"] < 1.0


def test_never_broke_down_qualifies_neither_bearish_setup():
    candles = _bucket(5, 100, 98, 99, 1000) + _bucket(5, 100.5, 98.5, 100, 900)
    r = _compute_indicators_from_candles(candles)
    assert r["bars_since_breakdown"] is None
    assert r["breakdown_setup"] is False
    assert r["pulldown_setup"] is False


def test_reclaim_above_orh_qualifies_neither_bearish_setup():
    candles = _bucket(5, 100, 98, 99, 1000) + _bucket(5, 102, 100, 101.5, 1500)
    r = _compute_indicators_from_candles(candles)
    assert r["price_above_orh"] is True
    assert r["breakdown_setup"] is False
    assert r["pulldown_setup"] is False


def test_peak_rvol_down_tracks_the_days_highest_reading_not_just_current():
    """A ticker that spiked volume on the breakdown and has since cooled should
    report peak_rvol_down from the spike, not the current quieter reading."""
    candles = (
        _bucket(5, 100, 98, 99, 1000)
        + _bucket(5, 97.5, 95, 96, 2500)
        + _bucket(5, 98, 96.5, 97, 500)
    )
    r = _compute_indicators_from_candles(candles)
    assert r["peak_rvol_down"] == 2.5
    assert r["rvol"] < r["peak_rvol_down"]


def test_bounce_from_low_pct_reflects_distance_from_intraday_low():
    candles = _bucket(5, 100, 98, 99, 1000) + _bucket(5, 97, 95, 96, 1800)
    r = _compute_indicators_from_candles(candles)
    # intraday low is 95, current price is 96 -> bounced a bit off the low
    assert 0 < r["bounce_from_low_pct"] < 2


def test_closest_approach_to_orh_pct_catches_a_tested_high_even_after_recovery():
    """Sold off, spiked back up to nearly the ORH, then partially rolled back
    down — mirrors test_closest_approach_to_orl_pct_catches_a_tested_low
    on the bullish side."""
    candles = (
        _bucket(5, 100, 98, 99, 1000)  # opening range -> orh=100, orl=98
        + _bucket(5, 97.5, 92, 93, 2000)  # breakdown, sells off hard
        + _bucket(5, 99.8, 93.5, 94.5, 1500)  # spikes back up, nearly reclaims orh
        + _bucket(5, 96, 94, 95, 900)  # partial rollover back down
    )
    r = _compute_indicators_from_candles(candles)
    assert r["bounce_from_low_pct"] > 2  # looks like a real but unremarkable bounce
    assert 0 < r["closest_approach_to_orh_pct"] < 1  # but it nearly reclaimed the ORH


def test_closest_approach_to_orh_pct_none_without_a_breakdown():
    candles = _bucket(5, 100, 98, 99, 1000) + _bucket(5, 100.5, 98.5, 100, 900)
    r = _compute_indicators_from_candles(candles)
    assert r["closest_approach_to_orh_pct"] is None


def test_pulldown_setup_excludes_a_ticker_that_actually_reclaimed_the_orh():
    """Mirrors test_pullback_setup_excludes_a_ticker_that_actually_broke_the_orl:
    broke down, then spiked well above the ORH, then rolled back over enough
    that price_above_orh (current-only) no longer shows it. Without the
    closest_approach_to_orh_pct >= 0 guard this would wrongly qualify as
    pulldown_setup — a structural reclaim-and-rollover is not the same as
    "resistance held"."""
    candles = (
        _bucket(5, 100, 98, 99, 1000)  # opening range -> orh=100, orl=98
        + _bucket(5, 97.5, 92, 93, 2000)  # breakdown, sells off hard
        + _bucket(5, 104, 99.5, 103, 1500)  # spikes well above the orh (104 vs orh=100)
        + _bucket(5, 99, 96, 97, 900)  # rolls back over below the orh
    )
    r = _compute_indicators_from_candles(candles)
    assert r["price_above_orh"] is False  # current price no longer shows the reclaim
    assert r["closest_approach_to_orh_pct"] < 0  # but it happened
    assert r["pulldown_setup"] is False
