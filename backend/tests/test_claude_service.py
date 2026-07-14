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


def test_get_option_chain_tool_accepts_a_list_of_tickers():
    """Regression: get_option_chain must be batchable across every qualifying
    ticker in one call, not one call per ticker — a per-ticker calling
    pattern exhausted the agentic loop's iteration budget live in production
    on days with several qualifying setups."""
    tools = claude_service._build_tools(include_options=True)
    tool = next(t for t in tools if t["name"] == "get_option_chain")
    props = tool["input_schema"]["properties"]
    assert "tickers" in props
    assert props["tickers"]["type"] == "array"
    assert tool["input_schema"]["required"] == ["tickers"]


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


def test_build_suggestion_system_scopes_200_dollar_heuristic_to_equity_only():
    """Regression: the legacy equity '$200 expected_gain / use as much of the
    cap as available' sizing heuristic was bleeding into option sizing live in
    production (options were maxing out the position_size_cap guardrail
    instead of respecting the $1k-$6k target band). Both must now explicitly
    say which instrument type they apply to."""
    system = claude_service._build_suggestion_system("cash_intraday", "holdings_only", 100)
    assert "EQUITY sizing (applies only to an equity suggestion" in system
    assert "OPTION sizing is completely different and does NOT follow the $200" in system
    assert "the cap is only a backstop, never the target" in system


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


def test_execute_tool_get_option_chain_routes_to_batched_schwab_service(monkeypatch):
    captured = {}

    def fake_get_option_chains(tickers):
        captured["tickers"] = tickers
        return {t: [{"symbol": f"{t}  260720C00310000", "option_type": "call"}] for t in tickers}

    monkeypatch.setattr(claude_service.schwab_service, "get_option_chains", fake_get_option_chains)
    result = claude_service._execute_tool("get_option_chain", {"tickers": ["AAPL", "NVDA"]})
    assert captured["tickers"] == ["AAPL", "NVDA"]
    assert set(result.keys()) == {"AAPL", "NVDA"}


def test_guardrail_names_includes_option_checks():
    assert "option_liquidity_check" in claude_service._GUARDRAIL_NAMES
    assert "expiration_proximity" in claude_service._GUARDRAIL_NAMES
    assert len(claude_service._GUARDRAIL_NAMES) == 10


# ── Regression: instrument_type must be a declared, required schema field ────
# Bug found live (2026-07-13): the tool schemas never declared instrument_type
# as a property, so Claude never included it in its output, and Pydantic's
# discriminated union (TradeSetupAny) couldn't tell suggestions.0 was an
# option — "Unable to extract tag using discriminator 'instrument_type'".
# The discriminator only works if the schema Claude is given actually asks
# for the tag; a default value on the Pydantic model is not enough, because
# discrimination happens before defaults are applied.


def test_trade_setup_schema_declares_instrument_type():
    assert "instrument_type" in claude_service._TRADE_SETUP_SCHEMA["properties"]
    assert claude_service._TRADE_SETUP_SCHEMA["properties"]["instrument_type"]["enum"] == ["equity"]
    assert "instrument_type" in claude_service._TRADE_SETUP_SCHEMA["required"]


def test_option_trade_setup_schema_declares_instrument_type():
    schema = claude_service._OPTION_TRADE_SETUP_SCHEMA
    assert "instrument_type" in schema["properties"]
    assert schema["properties"]["instrument_type"]["enum"] == ["option"]
    assert "instrument_type" in schema["required"]


def test_suggestion_response_round_trip_discriminates_option_from_tool_output():
    """End-to-end proof the discriminator actually works — validates a dict
    shaped exactly like what Claude's forced tool call would return (no
    instrument_type omitted), matching the live bug's INTC example."""
    from models.schemas import OptionTradeSetup, TradeSuggestionResponse

    option_dict = {
        "instrument_type": "option",
        "ticker": "INTC",
        "option_symbol": "INTC  260821C00027000",
        "option_type": "call",
        "strike_price": 27.0,
        "expiration_date": "2026-08-21",
        "days_to_expiration": 14,
        "trade_type": "intraday_cash",
        "profit_mode": "cash_intraday",
        "entry_price": 1.20,
        "target_price": 1.80,
        "stop_loss": 0.78,
        "shares": 20,
        "breakeven_price": 0.0,
        "delta_at_entry": 0.5,
        "implied_volatility_at_entry": 40.0,
        "bid_ask_spread_pct": 5.0,
        "open_interest": 500,
        "volume": 200,
        "underlying_price_at_entry": 27.0,
        "expected_gain": 0.0,
        "max_loss": 0.0,
        "reward_risk_ratio": 0.0,
        "confidence": "medium",
        "rationale": "Clean breakout",
        "setup_type": "breakout",
        "robinhood_instructions": "Buy to open, sell to close immediately.",
    }
    response = TradeSuggestionResponse(
        goal=100.0,
        profit_mode="cash_intraday",
        trade_scope="holdings_only",
        suggestions=[option_dict],
        risk_note="",
        market_conditions="",
        intraday_viability=None,
        recommended=option_dict,
        guardrails_checked=[],
        any_guardrail_triggered=False,
    )
    assert isinstance(response.suggestions[0], OptionTradeSetup)
    assert isinstance(response.recommended, OptionTradeSetup)


# ── Deterministic profit target (2026-07-14: 15%-of-cash entry sizing +
# opening-range/delta-based target, replacing the $1,000-$6,000 band and the
# "pick a target that keeps reward_risk_ratio >= 1.5" self-reported target) ──


def test_build_suggestion_system_mentions_15_percent_sizing():
    system = claude_service._build_suggestion_system("cash_intraday", "holdings_only", 100)
    assert "15% of available cash" in system
    assert "$1,000-$6,000" not in system


def test_compute_option_target_price_uses_opening_range_and_delta():
    setup = {
        "ticker": "AAPL",
        "option_symbol": "AAPL  260720C00310000",
        "entry_price": 8.68,
        "target_price": 999.0,  # Claude's placeholder — should be overridden
    }
    tool_cache = {
        "technical_indicators": {"AAPL": {"orh": 320.0, "orl": 316.0}},
        "option_chains": {"AAPL": [{"symbol": "AAPL  260720C00310000", "delta": 0.5}]},
    }
    # opening_range_size = 4.0, no rvol data so range_multiple stays 1.0
    # expected_premium_move = 4.0 * 1.0 * 0.5 = 2.0 -> target = 8.68 + 2.0
    assert claude_service._compute_option_target_price(setup, tool_cache) == 10.68


def test_compute_option_target_price_scales_up_with_volume_conviction():
    setup = {
        "ticker": "AAPL",
        "option_symbol": "AAPL  260720C00310000",
        "entry_price": 8.68,
        "target_price": 999.0,
    }
    tool_cache = {
        "technical_indicators": {
            "AAPL": {"orh": 320.0, "orl": 316.0, "rvol": 2.0, "peak_rvol": 2.0}
        },
        "option_chains": {"AAPL": [{"symbol": "AAPL  260720C00310000", "delta": 0.5}]},
    }
    # rvol at its own peak -> conviction=1.0 -> range_multiple = 1.5
    # expected_premium_move = 4.0 * 1.5 * 0.5 = 3.0 -> target = 8.68 + 3.0
    assert claude_service._compute_option_target_price(setup, tool_cache) == 11.68


def test_compute_option_target_price_none_without_technical_indicators():
    setup = {"ticker": "AAPL", "option_symbol": "AAPL  260720C00310000", "entry_price": 8.68}
    tool_cache = {"technical_indicators": {}, "option_chains": {}}
    assert claude_service._compute_option_target_price(setup, tool_cache) is None


def test_compute_option_target_price_none_without_matching_contract_delta():
    setup = {"ticker": "AAPL", "option_symbol": "AAPL  260720C00310000", "entry_price": 8.68}
    tool_cache = {
        "technical_indicators": {"AAPL": {"orh": 320.0, "orl": 316.0}},
        "option_chains": {"AAPL": [{"symbol": "AAPL  260720C00999000", "delta": 0.3}]},
    }
    assert claude_service._compute_option_target_price(setup, tool_cache) is None


def test_apply_profit_targets_overrides_option_but_not_equity():
    option_setup = {
        "instrument_type": "option",
        "ticker": "AAPL",
        "option_symbol": "AAPL  260720C00310000",
        "entry_price": 8.68,
        "target_price": 999.0,
    }
    equity_setup = {
        "instrument_type": "equity",
        "ticker": "NVDA",
        "entry_price": 100.0,
        "target_price": 104.0,
    }
    parsed = {
        "suggestions": [option_setup, equity_setup],
        "recommended": dict(option_setup),
    }
    tool_cache = {
        "technical_indicators": {"AAPL": {"orh": 320.0, "orl": 316.0}},
        "option_chains": {"AAPL": [{"symbol": "AAPL  260720C00310000", "delta": 0.5}]},
    }

    claude_service._apply_profit_targets(parsed, tool_cache)

    assert parsed["suggestions"][0]["target_price"] == 10.68
    assert parsed["suggestions"][1]["target_price"] == 104.0  # equity untouched
    assert parsed["recommended"]["target_price"] == 10.68


def test_apply_profit_targets_falls_back_to_claudes_target_when_data_missing():
    option_setup = {
        "instrument_type": "option",
        "ticker": "AAPL",
        "option_symbol": "AAPL  260720C00310000",
        "entry_price": 8.68,
        "target_price": 13.02,
    }
    parsed = {"suggestions": [option_setup], "recommended": None}
    tool_cache = {"technical_indicators": {}, "option_chains": {}}

    claude_service._apply_profit_targets(parsed, tool_cache)

    assert parsed["suggestions"][0]["target_price"] == 13.02  # unchanged
