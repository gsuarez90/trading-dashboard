"""
14 guardrail tests — all must pass before TRADING_MODE=live.
These are the hard gate specified in ai-trading-dashboard-kickoff-final-v5.md.
"""

import uuid
from datetime import datetime

import boto3
import pytest
from moto import mock_aws

from models.schemas import PaperTrade, TradeSetup
from services import dynamo_service
from services.guardrail_service import (
    GuardrailContext,
    GuardrailResult,
    check_all,
    trigger_kill_switch,
)

TABLE_NAME = "trading-dashboard-test"
TODAY = "2026-05-20"
MARKET_OPEN_TIME = datetime(2026, 5, 20, 10, 0, 0)  # Tuesday 10:00am ET
AFTER_HOURS_TIME = datetime(2026, 5, 20, 17, 0, 0)  # Tuesday 5:00pm ET
INTRADAY_LATE_TIME = datetime(2026, 5, 20, 15, 1, 0)  # Tuesday 3:01pm ET — < 60 min left


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_valid_trade(**overrides) -> TradeSetup:
    """A trade that passes every guardrail under the default context below."""
    defaults = dict(
        ticker="AAPL",
        direction="long",
        trade_type="intraday_cash",
        profit_mode="cash_intraday",
        entry_price=100.0,
        target_price=104.0,
        stop_loss=98.0,
        shares=10,  # position value = $1,000 = 10% of $10k cash (under 20% cap)
        expected_gain=40.0,
        max_loss=20.0,
        reward_risk_ratio=2.0,
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
    defaults.update(overrides)
    return TradeSetup(**defaults)


def _make_ctx(**overrides) -> GuardrailContext:
    """A context that passes every guardrail by default."""
    defaults = dict(
        cash=10_000.0,
        realized_pnl_today=0.0,
        trade_count_today=0,
        trading_mode="paper",
        allow_loss=False,
        now=MARKET_OPEN_TIME,
    )
    defaults.update(overrides)
    return GuardrailContext(**defaults)


@pytest.fixture(autouse=True)
def guardrail_env(monkeypatch):
    monkeypatch.setenv("DAILY_LOSS_LIMIT", "200")
    monkeypatch.setenv("MAX_POSITION_SIZE_PCT", "20")
    monkeypatch.setenv("DAILY_TRADE_LIMIT", "2")
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


def _seed_trade(mode: str = "paper", status: str = "open") -> str:
    trade_id = str(uuid.uuid4())
    dynamo_service.put_trade(
        PaperTrade(
            trade_id=trade_id,
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
            status=status,
            mode=mode,
        )
    )
    return trade_id


# ── 14 Guardrail Tests ────────────────────────────────────────────────────────


def test_daily_loss_limit_blocks_new_trades():
    ctx = _make_ctx(realized_pnl_today=-200.0)
    result = check_all(_make_valid_trade(), ctx)
    assert not result.allowed
    assert "daily_loss_limit" in result.triggered


def test_daily_loss_limit_does_not_trigger_prematurely():
    ctx = _make_ctx(realized_pnl_today=-199.99)
    result = check_all(_make_valid_trade(), ctx)
    assert "daily_loss_limit" not in result.triggered


def test_position_size_cap_enforced_server_side():
    # cash=$10k, 20% cap=$2k, position=100*21=$2,100 — exceeds cap
    trade = _make_valid_trade(entry_price=100.0, shares=21)
    result = check_all(trade, _make_ctx(cash=10_000.0))
    assert not result.allowed
    assert "position_size_cap" in result.triggered


def test_cost_basis_protection_blocks_loss_suggestion():
    trade = _make_valid_trade(
        uses_existing_holding=True,
        entry_price=95.0,
        cost_basis=100.0,
    )
    result = check_all(trade, _make_ctx())
    assert not result.allowed
    assert "cost_basis_protection" in result.triggered


def test_cost_basis_protection_allows_with_flag():
    trade = _make_valid_trade(
        uses_existing_holding=True,
        entry_price=95.0,
        cost_basis=100.0,
    )
    result = check_all(trade, _make_ctx(allow_loss=True))
    assert "cost_basis_protection" not in result.triggered


def test_kill_switch_closes_all_open_paper_trades(dynamo_table):
    id1 = _seed_trade(mode="paper")
    id2 = _seed_trade(mode="paper")

    result = trigger_kill_switch(confirmed=True, trading_mode="paper")

    assert result["paper_trades_closed"] == 2
    assert result["live_trades_flagged"] == 0
    assert dynamo_service.get_trade(id1)["status"] == "closed"
    assert dynamo_service.get_trade(id1)["close_reason"] == "kill_switch"
    assert dynamo_service.get_trade(id2)["status"] == "closed"


def test_kill_switch_flags_live_trades_for_manual_close(dynamo_table):
    id1 = _seed_trade(mode="live")
    id2 = _seed_trade(mode="live")

    result = trigger_kill_switch(confirmed=True, trading_mode="live")

    assert result["live_trades_flagged"] == 2
    assert result["paper_trades_closed"] == 0
    t1 = dynamo_service.get_trade(id1)
    t2 = dynamo_service.get_trade(id2)
    assert t1["flagged_for_manual_close"] is True
    assert t2["flagged_for_manual_close"] is True
    # Live trades remain open — user must close them manually in Robinhood
    assert t1["status"] == "open"
    assert t2["status"] == "open"


def test_kill_switch_requires_confirmation():
    with pytest.raises(ValueError, match="confirmation"):
        trigger_kill_switch(confirmed=False, trading_mode="paper")


def test_reward_risk_minimum_rejects_bad_suggestions():
    trade = _make_valid_trade(reward_risk_ratio=1.49)
    result = check_all(trade, _make_ctx())
    assert not result.allowed
    assert "reward_risk_minimum" in result.triggered


def test_market_hours_lock_prevents_after_hours_suggestions():
    ctx = _make_ctx(now=AFTER_HOURS_TIME)
    result = check_all(_make_valid_trade(), ctx)
    assert not result.allowed
    assert "market_hours_lock" in result.triggered


def test_intraday_suggestion_blocked_under_60_min_remaining():
    ctx = _make_ctx(now=INTRADAY_LATE_TIME)
    trade = _make_valid_trade(trade_type="intraday_cash")
    result = check_all(trade, ctx)
    assert not result.allowed
    assert "intraday_60min_cutoff" in result.triggered


def test_daily_trade_limit_blocks_at_threshold():
    ctx = _make_ctx(trade_count_today=2)  # at the limit of 3
    result = check_all(_make_valid_trade(), ctx)
    assert not result.allowed
    assert "daily_trade_limit" in result.triggered


def test_buying_power_check_blocks_oversized_suggestion():
    # cash=$1,000, position=100*11=$1,100 — exceeds cash
    trade = _make_valid_trade(entry_price=100.0, shares=11)
    result = check_all(trade, _make_ctx(cash=1_000.0))
    assert not result.allowed
    assert "buying_power_check" in result.triggered


def test_guardrails_same_code_path_paper_and_live():
    # Same bad trade must fail identically for both modes
    trade = _make_valid_trade(reward_risk_ratio=1.0)
    paper_result = check_all(trade, _make_ctx(trading_mode="paper"))
    live_result = check_all(trade, _make_ctx(trading_mode="live"))
    assert paper_result.allowed == live_result.allowed
    assert paper_result.triggered == live_result.triggered
