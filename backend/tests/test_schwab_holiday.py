"""Unit tests for the pure holiday-gap date logic in schwab_service.

Unlike test_schwab_service.py, this doesn't touch the live Schwab API —
_has_holiday_gap is pure date arithmetic, so it's tested directly.
"""

from datetime import date

from services.schwab_service import _has_holiday_gap


def test_no_gap_ordinary_weekday():
    # Tuesday -> Wednesday, no holiday
    assert _has_holiday_gap(date(2026, 7, 7), date(2026, 7, 8)) is False


def test_no_gap_ordinary_friday_to_monday():
    # Friday -> Monday is the normal weekend gap, not a holiday
    assert _has_holiday_gap(date(2026, 7, 3), date(2026, 7, 6)) is False


def test_gap_friday_before_holiday_monday():
    # Friday -> Tuesday: Monday is a holiday, extending the weekend
    assert _has_holiday_gap(date(2026, 7, 3), date(2026, 7, 7)) is True


def test_gap_midweek_holiday():
    # Wednesday -> Friday: Thursday is a holiday (e.g. Thanksgiving)
    assert _has_holiday_gap(date(2026, 11, 25), date(2026, 11, 27)) is True


def test_no_gap_thursday_to_friday():
    assert _has_holiday_gap(date(2026, 11, 26), date(2026, 11, 27)) is False
