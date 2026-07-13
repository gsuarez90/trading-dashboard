"""
Tests for the options pivot's Phase 0 shadow-trade path (Build Order step 8,
intraday-options-pivot-plan.md §7): logging, closing, and — most
importantly — isolation from the real guardrail/dashboard queries.
"""

import boto3
import pytest
from moto import mock_aws

from models.schemas import OptionTradeSetup, PaperTrade
from services import dynamo_service, paper_trading_service

TABLE_NAME = "trading-dashboard-test"
TODAY = "2026-07-13"


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


def _make_equity_trade(**overrides) -> PaperTrade:
    defaults = dict(
        trade_id="equity-1",
        date=TODAY,
        ticker="NVDA",
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
        status="open",
        mode="paper",
    )
    defaults.update(overrides)
    return PaperTrade(**defaults)


# ── Logging ────────────────────────────────────────────────────────────────────


def test_log_shadow_trade_creates_shadow_open_record(dynamo_table):
    trade = paper_trading_service.log_shadow_trade(_make_option_setup())
    record = dynamo_service.get_trade(trade.trade_id)
    assert record is not None
    assert record["status"] == "shadow_open"
    assert record["mode"] == "shadow"
    assert record["instrument_type"] == "option"
    assert record["option_symbol"] == "AAPL  260720C00310000"
    assert record["multiplier"] == 100


def test_log_shadow_trades_batch(dynamo_table):
    setups = [_make_option_setup(), _make_option_setup(ticker="TSLA", option_type="put")]
    logged = paper_trading_service.log_shadow_trades(setups)
    assert len(logged) == 2


def test_log_shadow_trades_is_best_effort(dynamo_table, monkeypatch):
    """One bad record must not prevent the rest from logging."""

    calls = {"n": 0}
    real_log = paper_trading_service.log_shadow_trade

    def flaky(setup, now=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("boom")
        return real_log(setup, now)

    monkeypatch.setattr(paper_trading_service, "log_shadow_trade", flaky)
    logged = paper_trading_service.log_shadow_trades(
        [_make_option_setup(), _make_option_setup(ticker="TSLA")]
    )
    assert len(logged) == 1


# ── Closing ────────────────────────────────────────────────────────────────────


def test_close_shadow_trade_computes_pnl_with_multiplier(dynamo_table):
    trade = paper_trading_service.log_shadow_trade(_make_option_setup())
    result = paper_trading_service.close_shadow_trade(trade.trade_id, 13.02, "target_hit")
    assert result["status"] == "shadow_closed"
    assert result["realized_pnl"] == round((13.02 - 8.68) * 6 * 100, 2)


def test_close_shadow_trade_already_closed_raises(dynamo_table):
    trade = paper_trading_service.log_shadow_trade(_make_option_setup())
    paper_trading_service.close_shadow_trade(trade.trade_id, 13.02, "target_hit")
    with pytest.raises(ValueError, match="already closed"):
        paper_trading_service.close_shadow_trade(trade.trade_id, 6.0, "stop_hit")


def test_close_shadow_trade_not_found_raises(dynamo_table):
    with pytest.raises(ValueError, match="not found"):
        paper_trading_service.close_shadow_trade("nonexistent", 10.0, "target_hit")


def test_close_shadow_trade_never_touches_cumulative_pnl(dynamo_table):
    """Unlike close_trade(), closing a shadow trade must not affect the real
    cumulative paper P&L stat shown on the dashboard."""
    trade = paper_trading_service.log_shadow_trade(_make_option_setup())
    paper_trading_service.close_shadow_trade(trade.trade_id, 13.02, "target_hit")
    assert dynamo_service.get_paper_pnl_cumulative() == 0.0


# ── Isolation from real guardrail/dashboard queries ───────────────────────────


def test_shadow_trades_excluded_from_get_open_trades(dynamo_table):
    dynamo_service.put_trade(_make_equity_trade())
    paper_trading_service.log_shadow_trade(_make_option_setup())

    open_trades = dynamo_service.get_open_trades()
    assert len(open_trades) == 1
    assert open_trades[0]["ticker"] == "NVDA"


def test_shadow_trades_excluded_from_get_trades_by_date(dynamo_table):
    dynamo_service.put_trade(_make_equity_trade())
    paper_trading_service.log_shadow_trade(_make_option_setup(), now=None)

    trades = dynamo_service.get_trades_by_date(TODAY)
    tickers = [t["ticker"] for t in trades]
    assert "AAPL" not in tickers
    assert "NVDA" in tickers


def test_shadow_trades_excluded_from_realized_pnl_and_trade_count(dynamo_table):
    """The whole point of the shadow_open/shadow_closed status namespace —
    calibration data must never leak into real daily_loss_limit /
    daily_trade_limit enforcement."""
    shadow_trade = paper_trading_service.log_shadow_trade(_make_option_setup())
    paper_trading_service.close_shadow_trade(shadow_trade.trade_id, 50.0, "target_hit")  # huge PnL

    assert dynamo_service.get_realized_pnl_today(TODAY) == 0.0
    assert dynamo_service.get_trade_count_today(TODAY) == 0


def test_get_shadow_open_trades_only_returns_shadow_status(dynamo_table):
    dynamo_service.put_trade(_make_equity_trade())
    shadow_trade = paper_trading_service.log_shadow_trade(_make_option_setup())

    shadow_open = dynamo_service.get_shadow_open_trades()
    assert len(shadow_open) == 1
    assert shadow_open[0]["trade_id"] == shadow_trade.trade_id


def test_close_trade_multiplier_scales_option_pnl(dynamo_table):
    """close_trade() (the real, non-shadow path) also needs the multiplier
    fix — future-proofing for when real option trades exist post-Phase 2."""
    trade = PaperTrade(
        trade_id="opt-real-1",
        date=TODAY,
        instrument_type="option",
        multiplier=100,
        ticker="AAPL",
        direction="long",
        trade_type="intraday_cash",
        shares=6,
        entry_price=8.68,
        target_price=13.02,
        stop_loss=6.51,
        expected_gain=0.0,
        max_loss=0.0,
        reward_risk_ratio=0.0,
        confidence="high",
        rationale="test",
        setup_type="breakout",
        status="open",
        mode="paper",
    )
    dynamo_service.put_trade(trade)
    result = paper_trading_service.close_trade("opt-real-1", 13.02, "target_hit")
    assert result["realized_pnl"] == round((13.02 - 8.68) * 6 * 100, 2)
