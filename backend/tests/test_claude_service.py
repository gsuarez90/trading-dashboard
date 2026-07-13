"""
Tests for the options pivot's claude_service.py additions (Build Order step
7): config-gated prompt/tool assembly and the get_option_chain tool routing.
Options are the primary cash_intraday expression by default
(INCLUDE_OPTIONS_SUGGESTIONS defaults true) — the flag is an emergency kill
switch back to the original equity-only behavior, not a staged rollout.

Claude's actual LLM behavior (schema reliability, suggestion quality) is
intentionally not unit-tested here — that's what the live spike scripts
(scripts/test_option_schema_union_live.py) are for. These tests only cover
the deterministic, non-LLM Python logic around it.
"""

import pytest

from services import claude_service


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("INCLUDE_OPTIONS_SUGGESTIONS", raising=False)


def test_include_options_suggestions_defaults_true():
    assert claude_service._include_options_suggestions() is True


def test_include_options_suggestions_kill_switch(monkeypatch):
    monkeypatch.setenv("INCLUDE_OPTIONS_SUGGESTIONS", "false")
    assert claude_service._include_options_suggestions() is False


def test_build_tools_default_includes_get_option_chain():
    tools = claude_service._build_tools(include_options=True)
    names = [t["name"] for t in tools]
    assert "get_option_chain" in names


def test_build_tools_kill_switch_excludes_get_option_chain():
    tools = claude_service._build_tools(include_options=False)
    names = [t["name"] for t in tools]
    assert "get_option_chain" not in names


def test_build_suggestion_system_default_is_options_primary():
    system = claude_service._build_suggestion_system("cash_intraday", "holdings_only", 100)
    assert "Options as the default cash_intraday expression" in system
    assert "get_option_chain" in system
    # bearish tickers are no longer hard-excluded once options are primary
    assert "If price_below_orl is true, exclude that ticker entirely" not in system


def test_build_suggestion_system_kill_switch_reverts_to_equity_only():
    system = claude_service._build_suggestion_system(
        "cash_intraday", "holdings_only", 100, include_options=False
    )
    assert "Options as the default cash_intraday expression" not in system
    assert "get_option_chain" not in system
    # legacy behavior preserved verbatim
    assert "If price_below_orl is true, exclude that ticker entirely" in system


def test_build_suggestion_system_mentions_breakdown_and_pulldown_setup():
    """Bearish-mirror field docs should always be present regardless of the
    options flag — Claude needs them to evaluate breakdown_setup/pulldown_setup
    either way, even under the equity-only kill switch."""
    system = claude_service._build_suggestion_system("cash_intraday", "holdings_only", 100)
    assert "breakdown_setup" in system
    assert "pulldown_setup" in system


def test_build_suggestion_system_mentions_ionz_macro_day_priority():
    system = claude_service._build_suggestion_system("cash_intraday", "holdings_only", 100)
    assert "IONZ macro-day priority" in system


def test_build_submit_suggestions_tool_uses_oneof_when_options_enabled():
    tool = claude_service._build_submit_suggestions_tool(include_options=True)
    suggestions_schema = tool["input_schema"]["properties"]["suggestions"]["items"]
    assert "oneOf" in suggestions_schema
    assert len(suggestions_schema["oneOf"]) == 2


def test_build_submit_suggestions_tool_equity_only_when_kill_switch_off():
    tool = claude_service._build_submit_suggestions_tool(include_options=False)
    suggestions_schema = tool["input_schema"]["properties"]["suggestions"]["items"]
    assert "oneOf" not in suggestions_schema
    assert suggestions_schema is claude_service._TRADE_SETUP_SCHEMA


def test_execute_tool_get_option_chain_routes_to_schwab_service(monkeypatch):
    captured = {}

    def fake_get_option_chain(ticker):
        captured["ticker"] = ticker
        return [{"symbol": "AAPL  260720C00310000", "option_type": "call"}]

    monkeypatch.setattr(claude_service.schwab_service, "get_option_chain", fake_get_option_chain)
    result = claude_service._execute_tool("get_option_chain", {"ticker": "AAPL"})
    assert captured["ticker"] == "AAPL"
    assert result == [{"symbol": "AAPL  260720C00310000", "option_type": "call"}]


def test_guardrail_names_includes_option_checks():
    assert "option_liquidity_check" in claude_service._GUARDRAIL_NAMES
    assert "expiration_proximity" in claude_service._GUARDRAIL_NAMES
    assert len(claude_service._GUARDRAIL_NAMES) == 10
