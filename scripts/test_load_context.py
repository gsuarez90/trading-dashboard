"""
Diagnostic script — measures load_context() component latency.

Run locally with venv active:
  python scripts/test_load_context.py

What it tests:
  1. DynamoDB cache state — is scanner/sentiment cache fresh?
  2. Each fetch call timed individually (portfolio, scanner, movers, sentiment)
  3. Full load_context() end-to-end time
  4. Compares cached path vs live path for movers and sentiment

This confirms (or refutes) the diagnosis that live Schwab/Finnhub calls in
_fetch_movers() and _fetch_sentiment() push cold Lambda over the 29s API Gateway limit.
"""

import os
import sys
import time
from pathlib import Path

# Allow importing backend services
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

# Warn immediately if DynamoDB is not configured — all cache checks will error
# and fall back to live Schwab/Finnhub calls, making the test useless for cache validation.
if not os.environ.get("DYNAMO_TABLE_NAME"):
    print("⚠  WARNING: DYNAMO_TABLE_NAME not set in backend/.env.local")
    print("   Add: DYNAMO_TABLE_NAME=trading-dashboard")
    print("   Without it, all DynamoDB cache checks error → live API fallback → misleading timings.\n")

from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

def fmt(elapsed: float) -> str:
    return f"{elapsed:.2f}s"

def section(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print('─' * 60)


# ── 1. DynamoDB cache state ────────────────────────────────────────────────────

section("1. DynamoDB cache state")

from services import dynamo_service
from services.context_loader import _cache_is_fresh, _prev_weekday

for key in ("scanner", "sentiment", "briefing"):
    t0 = time.time()
    try:
        data, cached_at = dynamo_service.get_cache(key)
        elapsed = time.time() - t0
        if data is None:
            print(f"  {key:12s}: MISSING  ({fmt(elapsed)})")
        else:
            fresh = _cache_is_fresh(cached_at) if cached_at else False
            count = len(data) if isinstance(data, list) else "dict"
            print(f"  {key:12s}: {'FRESH ✓' if fresh else 'STALE ✗'}  cached_at={cached_at}  items={count}  ({fmt(elapsed)})")
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  {key:12s}: ERROR — {e}  ({fmt(elapsed)})")


# ── 2. Individual fetch timings ────────────────────────────────────────────────

section("2. Individual fetch timings (each call in isolation)")

from services import market_data_service, finnhub_service, portfolio_factory, schwab_service
from services.context_loader import _get_watchlist, _cached_scanner_results, _cached_sentiment

tickers = _get_watchlist()
print(f"  watchlist ({len(tickers)} tickers): {tickers[:5]}{'...' if len(tickers) > 5 else ''}")

calls = [
    ("portfolio (live)",     lambda: portfolio_factory.get_provider().get_portfolio()),
    ("scanner (DDB cache)",  lambda: _cached_scanner_results(min_change_pct=2.0)),
    ("movers (DDB cache)",   lambda: _cached_scanner_results(min_change_pct=0)),
    ("movers (live Schwab)", lambda: market_data_service.get_previous_day_movers(tickers, limit=10)),
    ("sentiment (DDB cache)",lambda: _cached_sentiment()),
    ("sentiment (live Finnhub)", lambda: finnhub_service.score_batch_sentiment(tickers[:5])),
    ("trades (DDB)",         lambda: dynamo_service.get_trades_by_date(datetime.now(tz=ET).strftime("%Y-%m-%d"))),
    ("guardrail events (DDB)",lambda: dynamo_service.get_guardrail_events_by_date(datetime.now(tz=ET).strftime("%Y-%m-%d"))),
]

for label, fn in calls:
    t0 = time.time()
    try:
        result = fn()
        elapsed = time.time() - t0
        count = len(result) if result and hasattr(result, "__len__") else ("None" if result is None else "ok")
        print(f"  {label:30s}: {fmt(elapsed)}  → {count}")
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  {label:30s}: {fmt(elapsed)}  → ERROR: {e}")


# ── 3. Full load_context() timing ─────────────────────────────────────────────

section("3. Full load_context() end-to-end")

from services.context_loader import load_context

t0 = time.time()
try:
    ctx = load_context()
    elapsed = time.time() - t0
    print(f"  load_context() completed in {fmt(elapsed)}")
    print(f"  scanner_results : {len(ctx.scanner_results)} items")
    print(f"  top_movers      : {len(ctx.top_movers)} items")
    print(f"  sentiment       : {len(ctx.sentiment)} items")
    print(f"  positions       : {len(ctx.portfolio.get('positions', []))} items")
    print(f"  trades_today    : {len(ctx.trades_today)} items")
except Exception as e:
    elapsed = time.time() - t0
    print(f"  load_context() FAILED after {fmt(elapsed)}: {e}")


# ── 4. Summary ─────────────────────────────────────────────────────────────────

section("4. Summary")
print("""
  The 29s API Gateway ceiling is reached when:
    cold start (~6s) + load_context + Claude (~20s) > 29s

  load_context budget to stay safe: < 3s

  If movers (live) or sentiment (live) each take > 1s, they are the bottleneck.
  If DDB cache hits return in < 0.1s, caching them fixes the issue.
""")
