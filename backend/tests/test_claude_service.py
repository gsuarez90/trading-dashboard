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
from services.context_loader import DailyContext


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


def test_required_underlying_move_matches_linear_when_gamma_absent():
    assert claude_service._required_underlying_move(3.0, 0.5, None) == 6.0
    assert claude_service._required_underlying_move(3.0, 0.5, 0) == 6.0


def test_required_underlying_move_falls_back_to_linear_on_negative_discriminant():
    # gamma large enough relative to delta/premium_change that the quadratic
    # has no real root — the model's own signal to fall back rather than guess
    assert claude_service._required_underlying_move(-100.0, 0.1, 10.0) == -1000.0


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


def test_compute_option_target_price_adds_gamma_correction_when_available():
    setup = {
        "ticker": "AAPL",
        "option_symbol": "AAPL  260720C00310000",
        "entry_price": 8.68,
        "target_price": 999.0,
    }
    tool_cache = {
        "technical_indicators": {"AAPL": {"orh": 320.0, "orl": 316.0}},
        "option_chains": {
            "AAPL": [{"symbol": "AAPL  260720C00310000", "delta": 0.5, "gamma": 0.05}]
        },
    }
    # expected_underlying_move = 4.0 (range_multiple=1.0, no rvol data)
    # linear premium move = 4.0 * 0.5 = 2.0
    # gamma correction = 0.5 * 0.05 * 4.0^2 = 0.4 -> total premium move = 2.4
    assert claude_service._compute_option_target_price(setup, tool_cache) == 11.08


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


# ── Morning briefing: shrunk to 3 short paragraphs (2026-07-15) — the old
# "top setups"/"holdings overlap" sections leaned on opening-range/RVOL
# indicators that are still too fresh in the first few minutes to usefully
# qualify anything, and inflated both prompt and completion tokens ──────────


def test_build_briefing_system_limits_to_three_paragraphs():
    system = claude_service._build_briefing_system("cash_intraday", "holdings_only", 100)
    assert "1. Overall market conditions and intraday volatility today" in system
    assert "2. Whether today supports the $100 goal safely" in system
    assert "3. Honest assessment" in system
    assert "4." not in system


def test_build_briefing_system_drops_setup_qualification_language():
    system = claude_service._build_briefing_system("cash_intraday", "holdings_only", 100)
    for term in (
        "bounce_setup",
        "pullback_setup",
        "breakdown_setup",
        "pulldown_setup",
        "long PUT candidate",
        "structure to avoid",
    ):
        assert term not in system


def _fake_daily_context(**overrides) -> DailyContext:
    ctx = DailyContext(
        date="2026-07-15",
        cash=5000.0,
        portfolio={
            "cash": 5000.0,
            "equity": 12000.0,
            "positions": [{"ticker": "AAPL", "shares": 10}],
        },
        scanner_results=[{"ticker": "NVDA", "change_pct": 3.2}],
        top_movers=[{"ticker": "NVDA", "change_pct": 3.2}],
        sentiment=[{"ticker": "NVDA", "score": 0.5}],
        technical_indicators={"NVDA": {"orh": 120.0, "orl": 118.0, "bounce_setup": True}},
        trades_today=[{"ticker": "NVDA", "status": "closed", "realized_pnl": 42.0}],
        realized_pnl_today=42.0,
        trade_count_today=1,
        guardrail_status={"daily_loss_limit": False},
        guardrail_events=[{"ticker": "NVDA", "rule": "reward_risk_minimum"}],
        minutes_remaining=200,
        trading_mode="paper",
        profit_mode="cash_intraday",
        trade_scope="open",
        daily_goal=100.0,
    )
    for k, v in overrides.items():
        setattr(ctx, k, v)
    return ctx


def test_briefing_payload_drops_technical_indicators_and_itemized_lists():
    """These fields only ever fed the now-removed "top setups"/"holdings
    overlap"/"key risks" sections — technical_indicators in particular is by
    far the largest piece of the full context (per-ticker opening-range/RVOL/
    setup booleans), and the trimmed 3-paragraph briefing never discusses
    individual tickers or setups."""
    payload = claude_service._briefing_payload(_fake_daily_context())
    assert "technical_indicators" not in payload
    assert "positions" not in payload["portfolio"]
    assert "trades_today" not in payload
    assert "guardrail_events" not in payload


def test_briefing_payload_keeps_fields_the_three_paragraphs_need():
    payload = claude_service._briefing_payload(_fake_daily_context())
    assert payload["scanner_results"] == [{"ticker": "NVDA", "change_pct": 3.2}]
    assert payload["top_movers"] == [{"ticker": "NVDA", "change_pct": 3.2}]
    assert payload["sentiment"] == [{"ticker": "NVDA", "score": 0.5}]
    assert payload["portfolio"] == {"cash": 5000.0, "equity": 12000.0}
    assert payload["realized_pnl_today"] == 42.0
    assert payload["trade_count_today"] == 1
    assert payload["guardrail_status"] == {"daily_loss_limit": False}
    assert payload["minutes_remaining"] == 200
    assert payload["daily_goal"] == 100.0


# ── Hit-probability calc (2026-07-14): double-barrier touch probability
# (target BEFORE stop, not just "does it ever reach target"), informational
# only, populates the Phase 2 ml_probability field. The two-barrier exit
# probability is solved via an implicit finite-difference PDE scheme (see
# _pde_hit_upper_before_lower), not a hand-derived closed form — cross-
# validated against a continuity-corrected Monte Carlo simulation for both
# call and put directions before landing here (all within MC sampling noise,
# see conversation/equations-reference.md for the validation script). ────────


def _call_setup(**overrides):
    setup = {
        "ticker": "NOW",
        "option_symbol": "NOW   260724C00107000",
        "instrument_type": "option",
        "entry_price": 6.47,
        "target_price": 10.56,
        "stop_loss": 4.29,
        "underlying_price_at_entry": 107.0,
    }
    setup.update(overrides)
    return setup


def _call_tool_cache(delta=0.54, iv=100.0, gamma=None):
    contract = {"symbol": "NOW   260724C00107000", "delta": delta, "implied_volatility": iv}
    if gamma is not None:
        contract["gamma"] = gamma
    return {"option_chains": {"NOW": [contract]}}


def test_compute_option_hit_probability_matches_pde_validated_value():
    # Real NOW $107 call numbers from earlier in the session (entry/target/stop
    # all real trade values). PDE result cross-validated against Monte Carlo.
    p = claude_service._compute_option_hit_probability(
        _call_setup(), _call_tool_cache(), minutes_remaining=200
    )
    assert p == 0.1238


def test_compute_option_hit_probability_increases_with_more_time_remaining():
    # Not guaranteed in general for a double-barrier calc (more time helps
    # BOTH barriers) — holds here because target is far enough from stop that
    # more time still net-favors reaching target first for this setup.
    p_30 = claude_service._compute_option_hit_probability(
        _call_setup(), _call_tool_cache(), minutes_remaining=30
    )
    p_200 = claude_service._compute_option_hit_probability(
        _call_setup(), _call_tool_cache(), minutes_remaining=200
    )
    p_390 = claude_service._compute_option_hit_probability(
        _call_setup(), _call_tool_cache(), minutes_remaining=390
    )
    assert p_30 < p_200 < p_390


def test_compute_option_hit_probability_accounts_for_stop_not_just_target():
    """Regression: the old single-barrier calc only asked "does it ever reach
    target," ignoring the very real chance of getting stopped out first. A
    tighter stop (same target, same everything else) must lower the
    probability, since more of the target-reaching paths now get cut off by
    the closer stop along the way."""
    wide_stop = claude_service._compute_option_hit_probability(
        _call_setup(stop_loss=1.0), _call_tool_cache(), minutes_remaining=200
    )
    tight_stop = claude_service._compute_option_hit_probability(
        _call_setup(stop_loss=5.5), _call_tool_cache(), minutes_remaining=200
    )
    assert tight_stop < wide_stop


def test_compute_option_hit_probability_accounts_for_gamma_when_available():
    """Gamma is a convexity tailwind for a long option in both directions: it
    shrinks the underlying move needed to reach target (cheaper to get there)
    and grows the move needed to reach stop (cushions the loss), so a realistic
    positive gamma should raise the hit-target-first probability relative to
    the gamma-blind (linear delta-only) calc."""
    p_no_gamma = claude_service._compute_option_hit_probability(
        _call_setup(), _call_tool_cache(), minutes_remaining=200
    )
    p_with_gamma = claude_service._compute_option_hit_probability(
        _call_setup(), _call_tool_cache(gamma=0.01), minutes_remaining=200
    )
    assert p_no_gamma == 0.1238
    assert p_with_gamma == 0.1475
    assert p_with_gamma > p_no_gamma


def test_compute_option_hit_probability_handles_put_direction_via_signed_delta():
    """Puts have negative delta and profit on a DOWN move — the required-move
    formula must use signed (not abs) delta so this resolves correctly without
    a separate call/put branch."""
    put_setup = {
        "ticker": "SQQQ",
        "option_symbol": "SQQQ  260724P00012000",
        "instrument_type": "option",
        "entry_price": 1.20,
        "target_price": 1.50,
        "stop_loss": 0.90,
        "underlying_price_at_entry": 12.0,
    }
    put_cache = {
        "option_chains": {
            "SQQQ": [
                {"symbol": "SQQQ  260724P00012000", "delta": -0.45, "implied_volatility": 100.0}
            ]
        }
    }
    p = claude_service._compute_option_hit_probability(put_setup, put_cache, minutes_remaining=200)
    assert p == 0.2104


def test_compute_option_hit_probability_none_without_minutes_remaining():
    assert (
        claude_service._compute_option_hit_probability(_call_setup(), _call_tool_cache(), None)
        is None
    )
    assert (
        claude_service._compute_option_hit_probability(_call_setup(), _call_tool_cache(), 0) is None
    )


def test_compute_option_hit_probability_none_without_stop_loss():
    setup = _call_setup()
    del setup["stop_loss"]
    p = claude_service._compute_option_hit_probability(
        setup, _call_tool_cache(), minutes_remaining=200
    )
    assert p is None


def test_compute_option_hit_probability_none_without_cached_contract():
    p = claude_service._compute_option_hit_probability(
        _call_setup(), {"option_chains": {}}, minutes_remaining=200
    )
    assert p is None


def test_compute_option_hit_probability_none_without_implied_volatility():
    p = claude_service._compute_option_hit_probability(
        _call_setup(), _call_tool_cache(iv=None), minutes_remaining=200
    )
    assert p is None


def test_compute_option_hit_probability_none_with_zero_delta():
    p = claude_service._compute_option_hit_probability(
        _call_setup(), _call_tool_cache(delta=0), minutes_remaining=200
    )
    assert p is None


def test_apply_hit_probabilities_sets_ml_fields_on_option_not_equity():
    option_setup = _call_setup()
    equity_setup = {"instrument_type": "equity", "ticker": "AAPL"}
    parsed = {"suggestions": [option_setup, equity_setup], "recommended": dict(option_setup)}

    claude_service._apply_hit_probabilities(parsed, _call_tool_cache(), minutes_remaining=200)

    assert parsed["suggestions"][0]["ml_probability"] == 0.1238
    assert "ml_calibration_note" in parsed["suggestions"][0]
    assert "not yet calibrated" in parsed["suggestions"][0]["ml_calibration_note"].lower()
    assert "ml_probability" not in parsed["suggestions"][1]  # equity untouched
    assert parsed["recommended"]["ml_probability"] == 0.1238


def test_apply_hit_probabilities_leaves_ml_probability_unset_when_data_missing():
    option_setup = _call_setup()
    parsed = {"suggestions": [option_setup], "recommended": None}

    claude_service._apply_hit_probabilities(parsed, {"option_chains": {}}, minutes_remaining=200)

    assert "ml_probability" not in parsed["suggestions"][0]


# ── Partial EV (2026-07-15): P(stop) is the mirror of P(target) — same
# validated PDE solver, just called with the barrier roles swapped — and
# P(neither) is free arithmetic (1 - p_target - p_stop) that this partial EV
# doesn't even need, since it assumes $0 P&L for that bucket. See
# equations-reference.md §4b "EV still not built" and the conversation that
# derived this. ───────────────────────────────────────────────────────────


def test_compute_option_barrier_probabilities_matches_pde_validated_values():
    # Same NOW $107 call fixture as the p_target-only tests above — now also
    # asserting the mirrored P(stop) value and that the two don't exceed 1
    # (the remainder is the uncomputed P(neither) bucket).
    probs = claude_service._compute_option_barrier_probabilities(
        _call_setup(), _call_tool_cache(), minutes_remaining=200
    )
    assert probs == (0.1238, 0.4008)
    assert probs[0] + probs[1] < 1.0


def test_compute_option_barrier_probabilities_put_direction():
    put_setup = {
        "ticker": "SQQQ",
        "option_symbol": "SQQQ  260724P00012000",
        "instrument_type": "option",
        "entry_price": 1.20,
        "target_price": 1.50,
        "stop_loss": 0.90,
        "underlying_price_at_entry": 12.0,
    }
    put_cache = {
        "option_chains": {
            "SQQQ": [
                {"symbol": "SQQQ  260724P00012000", "delta": -0.45, "implied_volatility": 100.0}
            ]
        }
    }
    probs = claude_service._compute_option_barrier_probabilities(
        put_setup, put_cache, minutes_remaining=200
    )
    assert probs == (0.2104, 0.2239)


def test_compute_option_barrier_probabilities_gamma_lowers_stop_probability():
    """Same convexity tailwind noted for p_target should cushion the stop
    side too: realistic positive gamma cushions the loss (grows the move
    needed to reach stop), so it should lower P(stop first) relative to the
    gamma-blind calc, mirroring the p_target increase."""
    p_no_gamma = claude_service._compute_option_barrier_probabilities(
        _call_setup(), _call_tool_cache(), minutes_remaining=200
    )
    p_with_gamma = claude_service._compute_option_barrier_probabilities(
        _call_setup(), _call_tool_cache(gamma=0.01), minutes_remaining=200
    )
    assert p_with_gamma[1] < p_no_gamma[1]


def test_compute_option_barrier_probabilities_none_when_setup_unavailable():
    assert (
        claude_service._compute_option_barrier_probabilities(
            _call_setup(), {"option_chains": {}}, minutes_remaining=200
        )
        is None
    )


def test_compute_option_hit_probability_still_matches_after_refactor():
    """Regression: _compute_option_hit_probability now delegates to
    _compute_option_barrier_probabilities internally — must still return
    just the p_target half, unchanged from before the refactor."""
    p = claude_service._compute_option_hit_probability(
        _call_setup(), _call_tool_cache(), minutes_remaining=200
    )
    assert p == 0.1238


def test_apply_expected_value_sets_fields_on_option_not_equity():
    option_setup = _call_setup(shares=3, multiplier=100)
    equity_setup = {"instrument_type": "equity", "ticker": "AAPL"}
    parsed = {"suggestions": [option_setup, equity_setup], "recommended": dict(option_setup)}

    claude_service._apply_expected_value(parsed, _call_tool_cache(), minutes_remaining=200)

    assert parsed["suggestions"][0]["stop_probability"] == 0.4008
    assert parsed["suggestions"][0]["expected_value"] == -110.22
    assert "not modeled" in parsed["suggestions"][0]["ev_calibration_note"].lower()
    assert "stop_probability" not in parsed["suggestions"][1]  # equity untouched
    assert parsed["recommended"]["expected_value"] == -110.22


def test_apply_expected_value_unset_when_probability_data_missing():
    option_setup = _call_setup(shares=3, multiplier=100)
    parsed = {"suggestions": [option_setup], "recommended": None}

    claude_service._apply_expected_value(parsed, {"option_chains": {}}, minutes_remaining=200)

    assert "expected_value" not in parsed["suggestions"][0]
    assert "stop_probability" not in parsed["suggestions"][0]


def test_apply_expected_value_unset_without_shares():
    option_setup = _call_setup()
    option_setup.pop("shares", None)
    parsed = {"suggestions": [option_setup], "recommended": None}

    claude_service._apply_expected_value(parsed, _call_tool_cache(), minutes_remaining=200)

    assert "expected_value" not in parsed["suggestions"][0]


def test_apply_expected_value_matches_manual_arithmetic():
    """EV = P(target)*expected_gain + P(stop)*(-max_loss), computed from
    entry/target/stop directly (not trusted off setup's own expected_gain/
    max_loss, which aren't validated yet at this point in the pipeline —
    _apply_expected_value runs before Pydantic's _recompute_gain_risk)."""
    option_setup = _call_setup(shares=3, multiplier=100)
    parsed = {"suggestions": [option_setup], "recommended": None}

    claude_service._apply_expected_value(parsed, _call_tool_cache(), minutes_remaining=200)

    p_target, p_stop = 0.1238, 0.4008
    gain_per_contract = 10.56 - 6.47
    loss_per_contract = 6.47 - 4.29
    expected = round(
        p_target * gain_per_contract * 3 * 100 - p_stop * loss_per_contract * 3 * 100, 2
    )
    assert parsed["suggestions"][0]["expected_value"] == expected
