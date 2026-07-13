"""
Tests for the options pivot's claude_service.py additions (Build Order step
7): config-gated prompt/tool assembly and the get_option_chain tool routing.

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


def test_include_options_suggestions_defaults_false():
    assert claude_service._include_options_suggestions() is False


def test_include_options_suggestions_reads_env_var(monkeypatch):
    monkeypatch.setenv("INCLUDE_OPTIONS_SUGGESTIONS", "true")
    assert claude_service._include_options_suggestions() is True


def test_build_tools_default_excludes_get_option_chain():
    tools = claude_service._build_tools(include_options=False)
    names = [t["name"] for t in tools]
    assert "get_option_chain" not in names


def test_build_tools_with_options_includes_get_option_chain():
    tools = claude_service._build_tools(include_options=True)
    names = [t["name"] for t in tools]
    assert "get_option_chain" in names


def test_build_suggestion_system_default_omits_options_sections():
    system = claude_service._build_suggestion_system("cash_intraday", "holdings_only", 100)
    assert "Shadow option suggestions" not in system
    assert "get_option_chain" not in system
    # legacy behavior preserved verbatim
    assert "If price_below_orl is true, exclude that ticker entirely" in system


def test_build_suggestion_system_with_options_includes_shadow_section():
    system = claude_service._build_suggestion_system(
        "cash_intraday", "holdings_only", 100, include_options=True
    )
    assert "Shadow option suggestions" in system
    assert "get_option_chain" in system
    assert "shadow_option_suggestions" in system
    # bearish tickers no longer hard-excluded when options are enabled
    assert "If price_below_orl is true, exclude that ticker entirely" not in system


def test_build_suggestion_system_mentions_breakdown_and_pulldown_setup():
    """Bearish-mirror field docs should always be present regardless of the
    options flag — Claude needs them to evaluate breakdown_setup/pulldown_setup
    either way (e.g. for future use), even though only options mode acts on them."""
    system = claude_service._build_suggestion_system("cash_intraday", "holdings_only", 100)
    assert "breakdown_setup" in system
    assert "pulldown_setup" in system


def test_build_suggestion_system_mentions_ionz_macro_day_priority():
    system = claude_service._build_suggestion_system("cash_intraday", "holdings_only", 100)
    assert "IONZ macro-day priority" in system


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
