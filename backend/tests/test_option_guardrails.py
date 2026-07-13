"""
Tests for the options pivot's guardrail additions (Build Order step 5):
option_liquidity_check, expiration_proximity, and the multiplier-scaled
position_size_cap/buying_power_check math for OptionTradeSetup trades.
"""

import pytest

from models.schemas import OptionTradeSetup
from services.guardrail_service import GuardrailContext, check_all


@pytest.fixture(autouse=True)
def guardrail_env(monkeypatch):
    monkeypatch.setenv("DAILY_LOSS_LIMIT", "1500")
    monkeypatch.setenv("MAX_POSITION_SIZE_PCT", "20")
    monkeypatch.setenv("DAILY_TRADE_LIMIT", "2")
    monkeypatch.setenv("OPTION_MAX_SPREAD_PCT", "15")
    monkeypatch.setenv("OPTION_MIN_OPEN_INTEREST", "50")
    monkeypatch.setenv("OPTION_MIN_DTE", "7")
    monkeypatch.setenv("OPTION_MAX_DTE", "21")


def _make_ctx(**overrides) -> GuardrailContext:
    defaults = dict(
        cash=50_000.0,
        realized_pnl_today=0.0,
        trade_count_today=0,
        trading_mode="paper",
        allow_loss=False,
    )
    defaults.update(overrides)
    return GuardrailContext(**defaults)


def _make_valid_option_trade(**overrides) -> OptionTradeSetup:
    """A trade that passes every guardrail under the default context above —
    $5,208 position (6 contracts * $8.68 premium * 100), well under 20% of
    $50k cash, R/R 2.0, 7 DTE (at the floor, inclusive), healthy liquidity."""
    defaults = dict(
        ticker="AAPL",
        option_symbol="AAPL  260720C00310000",
        option_type="call",
        strike_price=310.0,
        expiration_date="2026-07-20",
        days_to_expiration=7,
        trade_type="intraday_cash",
        profit_mode="cash_intraday",
        entry_price=8.68,
        target_price=13.02,
        stop_loss=6.51,
        shares=6,
        breakeven_price=0.0,
        delta_at_entry=0.75,
        implied_volatility_at_entry=23.84,
        bid_ask_spread_pct=7.73,
        open_interest=174,
        volume=62,
        underlying_price_at_entry=316.98,
        expected_gain=0.0,
        max_loss=0.0,
        reward_risk_ratio=0.0,
        confidence="high",
        rationale="Clean breakout, healthy liquidity",
        setup_type="breakout",
        robinhood_instructions="Buy to open 6 AAPL 07/20/2026 310 Call",
    )
    defaults.update(overrides)
    return OptionTradeSetup(**defaults)


# ── option_liquidity_check ────────────────────────────────────────────────────


def test_option_liquidity_check_blocks_wide_spread():
    trade = _make_valid_option_trade(bid_ask_spread_pct=20.0)
    result = check_all(trade, _make_ctx())
    assert not result.allowed
    assert "option_liquidity_check" in result.triggered


def test_option_liquidity_check_blocks_thin_open_interest():
    trade = _make_valid_option_trade(open_interest=10)
    result = check_all(trade, _make_ctx())
    assert not result.allowed
    assert "option_liquidity_check" in result.triggered


def test_option_liquidity_check_allows_healthy_liquidity():
    trade = _make_valid_option_trade(bid_ask_spread_pct=5.0, open_interest=200)
    result = check_all(trade, _make_ctx())
    assert "option_liquidity_check" not in result.triggered


# ── expiration_proximity ──────────────────────────────────────────────────────


def test_expiration_proximity_blocks_below_min_dte_floor():
    trade = _make_valid_option_trade(days_to_expiration=3)
    result = check_all(trade, _make_ctx())
    assert not result.allowed
    assert "expiration_proximity" in result.triggered


def test_expiration_proximity_blocks_above_max_dte_ceiling():
    trade = _make_valid_option_trade(days_to_expiration=30)
    result = check_all(trade, _make_ctx())
    assert not result.allowed
    assert "expiration_proximity" in result.triggered


def test_expiration_proximity_allows_within_floor_and_ceiling():
    trade = _make_valid_option_trade(days_to_expiration=14)
    result = check_all(trade, _make_ctx())
    assert "expiration_proximity" not in result.triggered


# ── Multiplier-scaled position sizing ─────────────────────────────────────────


def test_position_size_cap_scales_by_option_multiplier():
    # entry=$10, 10 contracts, multiplier=100 -> $10,000 position.
    # 20% of $10k cash = $2,000 max allowed -> exceeds it.
    trade = _make_valid_option_trade(entry_price=10.0, target_price=15.0, stop_loss=8.0, shares=10)
    result = check_all(trade, _make_ctx(cash=10_000.0))
    assert not result.allowed
    assert "position_size_cap" in result.triggered


def test_buying_power_check_scales_by_option_multiplier():
    # entry=$10, 5 contracts, multiplier=100 -> $5,000 position, exceeds $1,000 cash
    trade = _make_valid_option_trade(entry_price=10.0, target_price=15.0, stop_loss=8.0, shares=5)
    result = check_all(trade, _make_ctx(cash=1_000.0))
    assert not result.allowed
    assert "buying_power_check" in result.triggered


def test_option_trade_passes_all_guardrails_under_default_context():
    trade = _make_valid_option_trade()
    result = check_all(trade, _make_ctx())
    assert result.allowed
    assert result.triggered == []
