"""
Smoke tests for dynamo_service using moto (no real AWS required).
"""

import os
import uuid
from datetime import date

import boto3
import pytest
from moto import mock_aws

from models.schemas import PaperTrade
from services import dynamo_service

TABLE_NAME = "trading-dashboard-test"
TODAY = date.today().isoformat()


def _make_trade(**overrides) -> PaperTrade:
    defaults = dict(
        trade_id=str(uuid.uuid4()),
        date=TODAY,
        ticker="AAPL",
        direction="long",
        trade_type="intraday_cash",
        shares=10,
        entry_price=200.00,
        target_price=204.00,
        stop_loss=198.00,
        expected_gain=40.00,
        max_loss=20.00,
        reward_risk_ratio=2.0,
        confidence="high",
        rationale="Strong momentum",
        setup_type="breakout",
        entry_time="2026-05-20T10:00:00",
        status="open",
        mode="paper",
    )
    defaults.update(overrides)
    return PaperTrade(**defaults)


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
        table = client.create_table(
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
        yield table


def test_put_and_get_trade(dynamo_table):
    trade = _make_trade()
    dynamo_service.put_trade(trade)

    result = dynamo_service.get_trade(trade.trade_id)
    assert result is not None
    assert result["ticker"] == "AAPL"
    assert result["entry_price"] == 200.00
    assert result["status"] == "open"


def test_get_open_trades(dynamo_table):
    open_trade = _make_trade()
    closed_trade = _make_trade(status="closed", realized_pnl=40.0)
    dynamo_service.put_trade(open_trade)
    dynamo_service.put_trade(closed_trade)

    open_trades = dynamo_service.get_open_trades()
    assert len(open_trades) == 1
    assert open_trades[0]["trade_id"] == open_trade.trade_id


def test_update_trade_closes_it(dynamo_table):
    trade = _make_trade()
    dynamo_service.put_trade(trade)

    dynamo_service.update_trade(
        trade.trade_id,
        {
            "status": "closed",
            "exit_price": 204.00,
            "exit_time": "2026-05-20T14:30:00",
            "realized_pnl": 40.0,
            "close_reason": "target_hit",
        },
    )

    updated = dynamo_service.get_trade(trade.trade_id)
    assert updated["status"] == "closed"
    assert updated["realized_pnl"] == 40.0
    assert updated["close_reason"] == "target_hit"


def test_get_realized_pnl_today(dynamo_table):
    dynamo_service.put_trade(_make_trade(status="closed", realized_pnl=40.0))
    dynamo_service.put_trade(_make_trade(status="closed", realized_pnl=-20.0))
    dynamo_service.put_trade(_make_trade(status="open"))

    pnl = dynamo_service.get_realized_pnl_today(TODAY)
    assert pnl == 20.0


def test_get_trade_count_today(dynamo_table):
    dynamo_service.put_trade(_make_trade())
    dynamo_service.put_trade(_make_trade())
    dynamo_service.put_trade(_make_trade(date="2026-01-01"))  # different day

    count = dynamo_service.get_trade_count_today(TODAY)
    assert count == 2


def test_get_nonexistent_trade_returns_none(dynamo_table):
    result = dynamo_service.get_trade("nonexistent-id")
    assert result is None
