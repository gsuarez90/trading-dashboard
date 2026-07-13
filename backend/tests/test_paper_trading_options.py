"""
Tests for real (not shadow) option trades flowing through the standard
paper-trading lifecycle — options are now the primary cash_intraday
expression, so a suggested call/put must open, fill, and close exactly
like an equity trade via the same open_trade()/close_trade() path.
"""

from datetime import datetime

import boto3
import pytest
from moto import mock_aws

from models.schemas import OptionTradeSetup
from services import dynamo_service, paper_trading_service

TABLE_NAME = "trading-dashboard-test"
TODAY = "2026-07-13"
MARKET_OPEN_TIME = datetime(2026, 7, 13, 10, 0, 0)  # Monday 10:00am ET — inside market hours


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
    monkeypatch.setenv("MAX_POSITION_SIZE_PCT", "20")
    monkeypatch.setenv("DAILY_TRADE_LIMIT", "2")
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


def test_open_trade_persists_option_fields(dynamo_table):
    # 6 contracts * $8.68 * 100 = $5,208 — well under 20% of $50k cash
    trade = paper_trading_service.open_trade(
        _make_option_setup(), cash=50_000.0, trading_mode="paper", now=MARKET_OPEN_TIME
    )
    record = dynamo_service.get_trade(trade.trade_id)
    assert record["status"] == "pending"
    assert record["instrument_type"] == "option"
    assert record["multiplier"] == 100
    assert record["option_symbol"] == "AAPL  260720C00310000"
    assert record["strike_price"] == 310.0
    assert record["days_to_expiration"] == 7


def test_open_trade_blocked_by_option_liquidity_guardrail(dynamo_table):
    with pytest.raises(ValueError, match="option_liquidity_check"):
        paper_trading_service.open_trade(
            _make_option_setup(bid_ask_spread_pct=30.0),
            cash=50_000.0,
            trading_mode="paper",
            now=MARKET_OPEN_TIME,
        )


def test_open_trade_blocked_by_expiration_proximity_guardrail(dynamo_table):
    with pytest.raises(ValueError, match="expiration_proximity"):
        paper_trading_service.open_trade(
            _make_option_setup(days_to_expiration=3),
            cash=50_000.0,
            trading_mode="paper",
            now=MARKET_OPEN_TIME,
        )


def test_fill_and_close_option_trade_scales_pnl_by_multiplier(dynamo_table):
    trade = paper_trading_service.open_trade(
        _make_option_setup(), cash=50_000.0, trading_mode="paper", now=MARKET_OPEN_TIME
    )
    paper_trading_service.fill_pending_order(trade.trade_id, 8.68)
    result = paper_trading_service.close_trade(trade.trade_id, 13.02, "target_hit")
    assert result["realized_pnl"] == round((13.02 - 8.68) * 6 * 100, 2)


def test_option_trade_counts_toward_shared_daily_trade_limit(dynamo_table):
    """Options and equity-fallback trades draw from the same daily_trade_limit
    counter — no separate instrument-type counter (§1, §8 Q7)."""
    t1 = paper_trading_service.open_trade(
        _make_option_setup(), cash=50_000.0, trading_mode="paper", now=MARKET_OPEN_TIME
    )
    paper_trading_service.fill_pending_order(t1.trade_id, 8.68)

    t2 = paper_trading_service.open_trade(
        _make_option_setup(ticker="TSLA", option_symbol="TSLA  260720C00250000"),
        cash=50_000.0,
        trading_mode="paper",
        now=MARKET_OPEN_TIME,
    )
    paper_trading_service.fill_pending_order(t2.trade_id, 8.68)

    # DAILY_TRADE_LIMIT=2 already reached — a third trade of any instrument type is blocked
    with pytest.raises(ValueError, match="daily_trade_limit"):
        paper_trading_service.open_trade(
            _make_option_setup(ticker="NVDA", option_symbol="NVDA  260720C00200000"),
            cash=50_000.0,
            trading_mode="paper",
            now=MARKET_OPEN_TIME,
        )
