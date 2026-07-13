"""
Tests for cache_service.py's instrument-type branching in the real price
monitor and EOD handler — a mixed batch of open equity and option trades
must each get priced from the right quote source (ticker quotes for
equity, option-symbol premium quotes for options) and closed correctly.
"""

from datetime import datetime

import boto3
import pytest
from moto import mock_aws

from models.schemas import OptionTradeSetup, TradeSetup
from services import cache_service, dynamo_service, paper_trading_service, schwab_service

TABLE_NAME = "trading-dashboard-test"
MARKET_OPEN_TIME = datetime(2026, 7, 13, 10, 0, 0)


def _make_equity_setup(**overrides) -> TradeSetup:
    defaults = dict(
        ticker="NVDA",
        direction="long",
        trade_type="intraday_cash",
        profit_mode="cash_intraday",
        entry_price=100.0,
        target_price=104.0,
        stop_loss=98.0,
        shares=10,
        expected_gain=40.0,
        max_loss=20.0,
        reward_risk_ratio=2.0,
        confidence="high",
        rationale="test",
        setup_type="breakout",
        uses_existing_holding=False,
        cost_basis=None,
        current_unrealized_pnl=None,
        avg_daily_range_pct=2.0,
        robinhood_instructions="Buy 10 NVDA at market",
        ml_probability=None,
        ml_calibration_note=None,
    )
    defaults.update(overrides)
    return TradeSetup(**defaults)


def _make_option_setup(**overrides) -> OptionTradeSetup:
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
        breakeven_price=318.68,
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
        rationale="Clean breakout",
        setup_type="breakout",
        robinhood_instructions="Buy to open 6 AAPL 07/20/2026 310 Call",
    )
    defaults.update(overrides)
    return OptionTradeSetup(**defaults)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("DAILY_LOSS_LIMIT", "1500")
    monkeypatch.setenv("MAX_POSITION_SIZE_PCT", "50")
    monkeypatch.setenv("DAILY_TRADE_LIMIT", "5")
    monkeypatch.setenv("OPTION_MAX_SPREAD_PCT", "15")
    monkeypatch.setenv("OPTION_MIN_OPEN_INTEREST", "50")
    monkeypatch.setenv("OPTION_MIN_DTE", "7")
    monkeypatch.setenv("OPTION_MAX_DTE", "21")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("DYNAMO_TABLE_NAME", TABLE_NAME)


@pytest.fixture
def dynamo_table():
    with mock_aws():
        client = boto3.resource("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "trade_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "trade_id", "AttributeType": "S"},
                {"AttributeName": "status", "AttributeType": "S"},
                {"AttributeName": "date", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "status-date-index",
                    "KeySchema": [
                        {"AttributeName": "status", "KeyType": "HASH"},
                        {"AttributeName": "date", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield


def _open_and_fill(setup, fill_price, cash=100_000.0):
    trade = paper_trading_service.open_trade(
        setup, cash=cash, trading_mode="paper", now=MARKET_OPEN_TIME
    )
    paper_trading_service.fill_pending_order(trade.trade_id, fill_price)
    return trade


def test_price_monitor_closes_equity_and_option_independently(dynamo_table, monkeypatch):
    equity_trade = _open_and_fill(_make_equity_setup(), 100.0)
    option_trade = _open_and_fill(_make_option_setup(), 8.68)

    monkeypatch.setattr(
        schwab_service, "get_batch_quotes", lambda tickers: [{"ticker": "NVDA", "price": 104.0}]
    )
    monkeypatch.setattr(
        schwab_service,
        "get_option_quotes",
        lambda symbols: [{"option_symbol": "AAPL  260720C00310000", "price": 6.51}],
    )

    result = cache_service.run_price_monitor()
    assert result["closed"] == 2

    equity_record = dynamo_service.get_trade(equity_trade.trade_id)
    option_record = dynamo_service.get_trade(option_trade.trade_id)
    assert equity_record["close_reason"] == "target_hit"
    assert option_record["close_reason"] == "stop_hit"


def test_price_monitor_option_uses_premium_not_underlying_price(dynamo_table, monkeypatch):
    """An option trade must be priced off its own premium quote, not the
    underlying ticker's price — even if a same-ticker equity quote exists."""
    option_trade = _open_and_fill(_make_option_setup(), 8.68)

    # Underlying AAPL stock price is nowhere near target/stop, but the
    # option's own premium is at target — only the option quote should matter.
    monkeypatch.setattr(
        schwab_service, "get_batch_quotes", lambda tickers: [{"ticker": "AAPL", "price": 316.98}]
    )
    monkeypatch.setattr(
        schwab_service,
        "get_option_quotes",
        lambda symbols: [{"option_symbol": "AAPL  260720C00310000", "price": 13.02}],
    )

    result = cache_service.run_price_monitor()
    assert result["closed"] == 1
    record = dynamo_service.get_trade(option_trade.trade_id)
    assert record["close_reason"] == "target_hit"


def test_end_of_day_force_closes_mixed_equity_and_option_trades(dynamo_table, monkeypatch):
    equity_trade = _open_and_fill(_make_equity_setup(), 100.0)
    option_trade = _open_and_fill(_make_option_setup(), 8.68)

    monkeypatch.setattr(
        schwab_service, "get_batch_quotes", lambda tickers: [{"ticker": "NVDA", "price": 101.5}]
    )
    monkeypatch.setattr(
        schwab_service,
        "get_option_quotes",
        lambda symbols: [{"option_symbol": "AAPL  260720C00310000", "price": 9.50}],
    )

    result = cache_service.run_end_of_day()
    assert result["paper_closed"] == 2

    equity_record = dynamo_service.get_trade(equity_trade.trade_id)
    option_record = dynamo_service.get_trade(option_trade.trade_id)
    assert equity_record["close_reason"] == "eod_close"
    assert option_record["close_reason"] == "eod_close"
    assert option_record["exit_price"] == 9.50
