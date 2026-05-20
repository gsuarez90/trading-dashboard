"""
Live tracking service tests — log, exit, P&L, mode guard, summary filtering.
"""

import uuid
from datetime import datetime

import boto3
import pytest
from moto import mock_aws

from models.schemas import PaperTrade, TradeSetup
from services import dynamo_service, live_tracking_service

TABLE_NAME = "trading-dashboard-test"
TODAY = "2026-05-20"
MARKET_OPEN_TIME = datetime(2026, 5, 20, 10, 0, 0)  # Tuesday 10:00am ET


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_setup(**overrides) -> TradeSetup:
    defaults = dict(
        ticker="NVDA",
        direction="long",
        trade_type="intraday_cash",
        profit_mode="cash_intraday",
        entry_price=120.0,
        target_price=124.0,
        stop_loss=118.0,
        shares=8,  # position = $960 = 9.6% of $10k (under 20% cap)
        expected_gain=32.0,
        max_loss=16.0,
        reward_risk_ratio=2.0,
        confidence="high",
        rationale="Momentum breakout",
        setup_type="breakout",
        uses_existing_holding=False,
        cost_basis=None,
        current_unrealized_pnl=None,
        avg_daily_range_pct=3.0,
        robinhood_instructions="Buy 8 NVDA at market",
        ml_probability=None,
        ml_calibration_note=None,
    )
    defaults.update(overrides)
    return TradeSetup(**defaults)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "live")
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


def test_log_trade_creates_live_record(dynamo_table):
    trade = live_tracking_service.log_trade(_make_setup(), cash=10_000.0, now=MARKET_OPEN_TIME)
    record = dynamo_service.get_trade(trade.trade_id)
    assert record is not None
    assert record["mode"] == "live"
    assert record["status"] == "open"
    assert record["ticker"] == "NVDA"
    assert record["date"] == TODAY


def test_log_trade_requires_live_mode(dynamo_table, monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "paper")
    with pytest.raises(ValueError, match="TRADING_MODE=live"):
        live_tracking_service.log_trade(_make_setup(), cash=10_000.0, now=MARKET_OPEN_TIME)


def test_log_trade_blocked_by_guardrail(dynamo_table):
    # position = 120 * 25 = $3,000 > 20% of $10k = $2,000
    with pytest.raises(ValueError, match="position_size_cap"):
        live_tracking_service.log_trade(_make_setup(shares=25), cash=10_000.0, now=MARKET_OPEN_TIME)


def test_log_exit_calculates_pnl(dynamo_table):
    trade = live_tracking_service.log_trade(_make_setup(), cash=10_000.0, now=MARKET_OPEN_TIME)
    result = live_tracking_service.log_exit(
        trade.trade_id, exit_price=124.0, close_reason="target_hit"
    )
    assert result["status"] == "closed"
    assert result["realized_pnl"] == 32.0  # (124 - 120) * 8
    assert result["close_reason"] == "target_hit"


def test_log_exit_rejects_paper_trade(dynamo_table):
    paper_trade = PaperTrade(
        trade_id=str(uuid.uuid4()),
        date=TODAY,
        ticker="AAPL",
        direction="long",
        trade_type="intraday_cash",
        shares=10,
        entry_price=100.0,
        target_price=104.0,
        stop_loss=98.0,
        expected_gain=40.0,
        max_loss=20.0,
        reward_risk_ratio=2.0,
        confidence="high",
        rationale="test",
        setup_type="breakout",
        entry_time="2026-05-20T10:00:00",
        status="open",
        mode="paper",
    )
    dynamo_service.put_trade(paper_trade)
    with pytest.raises(ValueError, match="paper trade"):
        live_tracking_service.log_exit(paper_trade.trade_id, exit_price=104.0)


def test_live_summary_excludes_paper_trades(dynamo_table):
    # One live trade, one paper trade — summary should only count the live one
    live_trade = live_tracking_service.log_trade(_make_setup(), cash=10_000.0, now=MARKET_OPEN_TIME)
    dynamo_service.put_trade(
        PaperTrade(
            trade_id=str(uuid.uuid4()),
            date=TODAY,
            ticker="AAPL",
            direction="long",
            trade_type="intraday_cash",
            shares=10,
            entry_price=100.0,
            target_price=104.0,
            stop_loss=98.0,
            expected_gain=40.0,
            max_loss=20.0,
            reward_risk_ratio=2.0,
            confidence="high",
            rationale="test",
            setup_type="breakout",
            entry_time="2026-05-20T10:00:00",
            status="closed",
            mode="paper",
            realized_pnl=40.0,
            close_reason="target_hit",
        )
    )
    live_tracking_service.log_exit(live_trade.trade_id, exit_price=124.0)

    summary = live_tracking_service.get_live_summary(TODAY)
    assert summary.realized_pnl == 32.0  # only live trade P&L, not paper's $40
    assert summary.trading_mode == "live"
    assert summary.open_positions == 0
