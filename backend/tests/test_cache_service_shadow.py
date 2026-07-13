"""
Tests for cache_service.py's Phase 0 shadow-trade monitoring (Build Order
step 8): _monitor_shadow_option_trades() (every-minute target/stop check)
and _close_shadow_trades_eod() (3:45pm force-close).
"""

import boto3
import pytest
from moto import mock_aws

from models.schemas import OptionTradeSetup
from services import cache_service, dynamo_service, paper_trading_service, schwab_service

TABLE_NAME = "trading-dashboard-test"


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
def aws_env(monkeypatch):
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


def test_monitor_shadow_option_trades_no_trades_returns_zero(dynamo_table):
    assert cache_service._monitor_shadow_option_trades() == 0


def test_monitor_shadow_option_trades_closes_on_target_hit(dynamo_table, monkeypatch):
    trade = paper_trading_service.log_shadow_trade(_make_option_setup())
    monkeypatch.setattr(
        schwab_service,
        "get_option_quotes",
        lambda symbols: [{"option_symbol": trade.option_symbol, "price": 13.02}],
    )

    closed = cache_service._monitor_shadow_option_trades()
    assert closed == 1

    record = dynamo_service.get_trade(trade.trade_id)
    assert record["status"] == "shadow_closed"
    assert record["close_reason"] == "target_hit"


def test_monitor_shadow_option_trades_closes_on_stop_hit(dynamo_table, monkeypatch):
    trade = paper_trading_service.log_shadow_trade(_make_option_setup())
    monkeypatch.setattr(
        schwab_service,
        "get_option_quotes",
        lambda symbols: [{"option_symbol": trade.option_symbol, "price": 6.51}],
    )

    closed = cache_service._monitor_shadow_option_trades()
    assert closed == 1
    record = dynamo_service.get_trade(trade.trade_id)
    assert record["close_reason"] == "stop_hit"


def test_monitor_shadow_option_trades_leaves_open_between_target_and_stop(
    dynamo_table, monkeypatch
):
    trade = paper_trading_service.log_shadow_trade(_make_option_setup())
    monkeypatch.setattr(
        schwab_service,
        "get_option_quotes",
        lambda symbols: [{"option_symbol": trade.option_symbol, "price": 9.50}],
    )

    closed = cache_service._monitor_shadow_option_trades()
    assert closed == 0
    record = dynamo_service.get_trade(trade.trade_id)
    assert record["status"] == "shadow_open"


def test_monitor_shadow_option_trades_survives_quote_failure(dynamo_table, monkeypatch):
    paper_trading_service.log_shadow_trade(_make_option_setup())

    def boom(symbols):
        raise RuntimeError("Schwab down")

    monkeypatch.setattr(schwab_service, "get_option_quotes", boom)
    assert cache_service._monitor_shadow_option_trades() == 0


def test_close_shadow_trades_eod_force_closes_everything(dynamo_table, monkeypatch):
    trade = paper_trading_service.log_shadow_trade(_make_option_setup())
    # price sits between target and stop — EOD should still force-close it
    monkeypatch.setattr(
        schwab_service,
        "get_option_quotes",
        lambda symbols: [{"option_symbol": trade.option_symbol, "price": 9.50}],
    )

    closed = cache_service._close_shadow_trades_eod()
    assert closed == 1
    record = dynamo_service.get_trade(trade.trade_id)
    assert record["status"] == "shadow_closed"
    assert record["close_reason"] == "eod_close"


def test_close_shadow_trades_eod_falls_back_to_entry_price_on_quote_failure(
    dynamo_table, monkeypatch
):
    trade = paper_trading_service.log_shadow_trade(_make_option_setup())

    def boom(symbols):
        raise RuntimeError("Schwab down")

    monkeypatch.setattr(schwab_service, "get_option_quotes", boom)
    closed = cache_service._close_shadow_trades_eod()
    assert closed == 1
    record = dynamo_service.get_trade(trade.trade_id)
    assert record["exit_price"] == trade.entry_price
    assert record["realized_pnl"] == 0.0


def test_run_price_monitor_includes_shadow_closed_count(dynamo_table, monkeypatch):
    trade = paper_trading_service.log_shadow_trade(_make_option_setup())
    monkeypatch.setattr(
        schwab_service,
        "get_option_quotes",
        lambda symbols: [{"option_symbol": trade.option_symbol, "price": 13.02}],
    )
    result = cache_service.run_price_monitor()
    assert result["shadow_closed"] == 1


def test_run_end_of_day_includes_shadow_closed_count(dynamo_table, monkeypatch):
    trade = paper_trading_service.log_shadow_trade(_make_option_setup())
    monkeypatch.setattr(
        schwab_service,
        "get_option_quotes",
        lambda symbols: [{"option_symbol": trade.option_symbol, "price": 9.50}],
    )
    result = cache_service.run_end_of_day()
    assert result["shadow_closed"] == 1
