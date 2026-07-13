"""
Tests for the options pivot's schema additions (schemas.py Build Order step
4): OptionTradeSetup's recompute-from-prices validator, TradeSetup's
backward-compatible instrument_type/multiplier defaults, and the
TradeSetupAny discriminated union.
"""

from models.schemas import OptionTradeSetup, TradeSetup, TradeSuggestionResponse


def _make_option_trade(**overrides) -> OptionTradeSetup:
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
        target_price=13.0,
        stop_loss=5.6,
        shares=6,
        breakeven_price=0.0,  # recomputed by the validator regardless of input
        delta_at_entry=0.75,
        implied_volatility_at_entry=23.84,
        bid_ask_spread_pct=7.73,
        open_interest=174,
        volume=62,
        underlying_price_at_entry=316.98,
        expected_gain=0.0,  # recomputed by the validator regardless of input
        max_loss=0.0,
        reward_risk_ratio=0.0,
        confidence="high",
        rationale="Clean breakout, healthy liquidity",
        setup_type="breakout",
        robinhood_instructions="Buy to open 6 AAPL 07/20/2026 310 Call",
    )
    defaults.update(overrides)
    return OptionTradeSetup(**defaults)


def test_option_trade_defaults_instrument_type_and_multiplier():
    trade = _make_option_trade()
    assert trade.instrument_type == "option"
    assert trade.multiplier == 100
    assert trade.direction == "long"


def test_option_trade_recomputes_gain_risk_scaled_by_multiplier():
    # (13.0 - 8.68) * 6 contracts * 100 multiplier
    trade = _make_option_trade()
    assert trade.expected_gain == round((13.0 - 8.68) * 6 * 100, 2)
    assert trade.max_loss == round((8.68 - 5.6) * 6 * 100, 2)
    assert trade.reward_risk_ratio == round(trade.expected_gain / trade.max_loss, 2)


def test_option_trade_discards_claudes_self_reported_math():
    """Same discipline as TradeSetup._recompute_gain_risk (commit 9d048a4) —
    whatever Claude reports for expected_gain/max_loss/reward_risk_ratio is
    discarded and recomputed from entry/target/stop/shares/multiplier."""
    trade = _make_option_trade(expected_gain=999999.0, max_loss=1.0, reward_risk_ratio=999.0)
    assert trade.expected_gain == round((13.0 - 8.68) * 6 * 100, 2)
    assert trade.max_loss == round((8.68 - 5.6) * 6 * 100, 2)


def test_option_trade_breakeven_call_is_strike_plus_premium():
    trade = _make_option_trade(option_type="call", strike_price=310.0, entry_price=8.68)
    assert trade.breakeven_price == round(310.0 + 8.68, 2)


def test_option_trade_breakeven_put_is_strike_minus_premium():
    trade = _make_option_trade(
        option_type="put",
        strike_price=100.0,
        entry_price=3.5,
        target_price=6.0,
        stop_loss=2.0,
    )
    assert trade.breakeven_price == round(100.0 - 3.5, 2)


def test_option_trade_generic_fields_default_for_no_existing_holding():
    """No 'existing holding to average into' concept for a same-day long
    option — uses_existing_holding/cost_basis default so
    cost_basis_protection can run unmodified against an option trade and
    simply no-op (intraday-options-pivot-plan.md §6)."""
    trade = _make_option_trade()
    assert trade.uses_existing_holding is False
    assert trade.cost_basis is None


def test_equity_trade_defaults_instrument_type_and_multiplier():
    """Backward compatibility — existing TradeSetup construction sites don't
    pass instrument_type/multiplier and must keep working unmodified."""
    trade = TradeSetup(
        ticker="AAPL",
        direction="long",
        trade_type="intraday_cash",
        profit_mode="cash_intraday",
        entry_price=100.0,
        target_price=104.0,
        stop_loss=98.0,
        shares=10,
        expected_gain=0.0,
        max_loss=0.0,
        reward_risk_ratio=0.0,
        confidence="high",
        rationale="Strong momentum",
        setup_type="breakout",
        uses_existing_holding=False,
        cost_basis=None,
        current_unrealized_pnl=None,
        avg_daily_range_pct=2.0,
        robinhood_instructions="Buy 10 AAPL at market",
        ml_probability=None,
        ml_calibration_note=None,
    )
    assert trade.instrument_type == "equity"
    assert trade.multiplier == 1


def test_trade_suggestion_response_discriminates_equity_and_option_from_dicts():
    """The forced-tool-call path hands back plain dicts (Claude's tool_use
    input) — confirms TradeSetupAny correctly discriminates on
    instrument_type when parsing raw dict input, not just constructed
    Python objects."""
    equity_dict = dict(
        instrument_type="equity",
        ticker="NVDA",
        direction="long",
        trade_type="intraday_cash",
        profit_mode="cash_intraday",
        entry_price=100.0,
        target_price=104.0,
        stop_loss=98.0,
        shares=10,
        expected_gain=0.0,
        max_loss=0.0,
        reward_risk_ratio=0.0,
        confidence="high",
        rationale="Strong momentum",
        setup_type="breakout",
        uses_existing_holding=False,
        cost_basis=None,
        current_unrealized_pnl=None,
        avg_daily_range_pct=2.0,
        robinhood_instructions="Buy 10 NVDA at market",
        ml_probability=None,
        ml_calibration_note=None,
    )
    option_dict = dict(
        instrument_type="option",
        ticker="TSLA",
        option_symbol="TSLA  260801P00250000",
        option_type="put",
        strike_price=250.0,
        expiration_date="2026-08-01",
        days_to_expiration=14,
        trade_type="intraday_cash",
        profit_mode="cash_intraday",
        entry_price=5.0,
        target_price=9.0,
        stop_loss=3.0,
        shares=5,
        breakeven_price=0.0,
        delta_at_entry=-0.45,
        implied_volatility_at_entry=55.0,
        bid_ask_spread_pct=4.0,
        open_interest=500,
        volume=120,
        underlying_price_at_entry=245.0,
        expected_gain=0.0,
        max_loss=0.0,
        reward_risk_ratio=0.0,
        confidence="medium",
        rationale="Clean breakdown",
        setup_type="breakdown",
        robinhood_instructions="Buy to open 5 TSLA 08/01/2026 250 Put",
    )

    response = TradeSuggestionResponse(
        goal=100.0,
        profit_mode="cash_intraday",
        trade_scope="holdings_only",
        suggestions=[equity_dict, option_dict],
        risk_note="",
        market_conditions="",
        intraday_viability=None,
        recommended=equity_dict,
        guardrails_checked=[],
        any_guardrail_triggered=False,
    )

    assert isinstance(response.suggestions[0], TradeSetup)
    assert isinstance(response.suggestions[1], OptionTradeSetup)
    assert response.suggestions[1].option_type == "put"
    assert isinstance(response.recommended, TradeSetup)
