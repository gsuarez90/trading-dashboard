from datetime import datetime
from zoneinfo import ZoneInfo

from services.context_loader import _PINNED_TICKERS, _is_before_10am_et

ET = ZoneInfo("America/New_York")


def _et(y, m, d, h, minute):
    return datetime(y, m, d, h, minute, tzinfo=ET)


def test_before_10am_true_at_open():
    assert _is_before_10am_et(_et(2026, 7, 6, 9, 30)) is True


def test_before_10am_true_at_959():
    assert _is_before_10am_et(_et(2026, 7, 6, 9, 59)) is True


def test_before_10am_false_at_1000():
    assert _is_before_10am_et(_et(2026, 7, 6, 10, 0)) is False


def test_before_10am_false_before_open():
    assert _is_before_10am_et(_et(2026, 7, 6, 9, 0)) is False


def test_before_10am_false_on_weekend():
    # 2026-07-04 is a Saturday
    assert _is_before_10am_et(_et(2026, 7, 4, 9, 45)) is False


def test_before_10am_false_midday():
    assert _is_before_10am_et(_et(2026, 7, 6, 13, 0)) is False


def test_pinned_tickers_include_tqqq_sqqq_ionz_ionq_nvda_and_spcx():
    assert set(_PINNED_TICKERS) == {"TQQQ", "SQQQ", "IONZ", "IONQ", "NVDA", "SPCX", "SPY"}
