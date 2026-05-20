"""
Paper trading service tests — open, close, P&L, guardrail blocking, daily summary.
"""

import uuid
from datetime import datetime

import boto3
import pytest
from moto import mock_aws

from models.schemas import PaperTrade, TradeSetup
from services import dynamo_service, paper_trading_service

TABLE_NAME = "trading-dashboard-test"
TODAY = "2026-05-20"
MARKET_OPEN_TIME = datetime(2026, 5, 20, 10, 0, 0)  # Tuesday 10:00am ET — inside market hours


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_setup(**overrides) -> TradeSetup:
    defaults = dict(
        ticker="AAPL",
        direction="long",
        trade_type="intraday_cash",
        profit_mode="cash_intraday",
        entry_price=100.0,
        target_price=104.0,
        stop_loss=98.0,
        shares=10,  # position = $1,000 = 10% of $10k cash (under 20% cap)
        expected_gain=40.0,
        max_loss=20.0,
        reward_risk_ratio=2.0,
        confidence="high",
        rationale="Breakout momentum",
        setup_type="breakout",
        uses_existing_holding=False,
        cost_basis=None,
        current_unrealized_pnl=None,
        avg_daily_range_pct=2.0,
        robinhood_instructions="Buy 10 AAPL at market",
        ml_probability=None,
        ml_calibration_note=None,
    )
    defaults.update(overrides)
    return TradeSetup(**defaults)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("DAILY_LOSS_LIMIT", "200")
    monkeypatch.setenv("MAX_POSITION_SIZE_PCT", "20")
    monkeypatch.setenv("DAILY_TRADE_LIMIT", "3")
    monkeypatch.setenv("DAILY_GOAL", "100")
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


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_open_trade_creates_dynamo_record(dynamo_table):
    trade = paper_trading_service.open_trade(
        _make_setup(), cash=10_000.0, trading_mode="paper", now=MARKET_OPEN_TIME
    )
    record = dynamo_service.get_trade(trade.trade_id)
    assert record is not None
    assert record["ticker"] == "AAPL"
    assert record["status"] == "open"
    assert record["mode"] == "paper"
    assert record["date"] == TODAY


def test_open_trade_blocked_by_daily_loss_limit(dynamo_table):
    dynamo_service.put_trade(
        PaperTrade(
            trade_id=str(uuid.uuid4()),
            date=TODAY,
            ticker="SPY",
            direction="long",
            trade_type="intraday_cash",
            shares=1,
            entry_price=500.0,
            target_price=510.0,
            stop_loss=490.0,
            expected_gain=10.0,
            max_loss=10.0,
            reward_risk_ratio=1.5,
            confidence="medium",
            rationale="test",
            setup_type="breakout",
            entry_time="2026-05-20T10:00:00",
            status="closed",
            mode="paper",
            realized_pnl=-200.0,
            close_reason="stop_hit",
        )
    )
    with pytest.raises(ValueError, match="daily_loss_limit"):
        paper_trading_service.open_trade(
            _make_setup(), cash=10_000.0, trading_mode="paper", now=MARKET_OPEN_TIME
        )


def test_open_trade_blocked_by_position_size(dynamo_table):
    # position = 100 * 25 = $2,500 > 20% of $10k = $2,000
    with pytest.raises(ValueError, match="position_size_cap"):
        paper_trading_service.open_trade(
            _make_setup(shares=25), cash=10_000.0, trading_mode="paper", now=MARKET_OPEN_TIME
        )


def test_close_trade_long_calculates_pnl(dynamo_table):
    trade = paper_trading_service.open_trade(
        _make_setup(), cash=10_000.0, trading_mode="paper", now=MARKET_OPEN_TIME
    )
    result = paper_trading_service.close_trade(
        trade.trade_id, exit_price=104.0, close_reason="target_hit"
    )
    assert result["status"] == "closed"
    assert result["realized_pnl"] == 40.0  # (104 - 100) * 10
    assert result["close_reason"] == "target_hit"


def test_close_trade_stop_hit_gives_negative_pnl(dynamo_table):
    trade = paper_trading_service.open_trade(
        _make_setup(), cash=10_000.0, trading_mode="paper", now=MARKET_OPEN_TIME
    )
    result = paper_trading_service.close_trade(
        trade.trade_id, exit_price=98.0, close_reason="stop_hit"
    )
    assert result["realized_pnl"] == -20.0  # (98 - 100) * 10


def test_close_trade_already_closed_raises(dynamo_table):
    trade = paper_trading_service.open_trade(
        _make_setup(), cash=10_000.0, trading_mode="paper", now=MARKET_OPEN_TIME
    )
    paper_trading_service.close_trade(trade.trade_id, exit_price=104.0)
    with pytest.raises(ValueError, match="already closed"):
        paper_trading_service.close_trade(trade.trade_id, exit_price=105.0)


def test_daily_summary_goal_hit(dynamo_table):
    trade = paper_trading_service.open_trade(
        _make_setup(), cash=10_000.0, trading_mode="paper", now=MARKET_OPEN_TIME
    )
    paper_trading_service.close_trade(trade.trade_id, exit_price=111.0)  # +$110 > $100 goal
    summary = paper_trading_service.get_daily_summary(TODAY, trading_mode="paper")
    assert summary.realized_pnl == 110.0
    assert summary.goal_hit is True
    assert summary.open_positions == 0
    assert summary.goal_hit_time is not None


def test_daily_summary_goal_not_hit(dynamo_table):
    trade = paper_trading_service.open_trade(
        _make_setup(), cash=10_000.0, trading_mode="paper", now=MARKET_OPEN_TIME
    )
    paper_trading_service.close_trade(trade.trade_id, exit_price=101.0)  # +$10 < $100 goal
    summary = paper_trading_service.get_daily_summary(TODAY, trading_mode="paper")
    assert summary.realized_pnl == 10.0
    assert summary.goal_hit is False
    assert summary.goal_hit_time is None
