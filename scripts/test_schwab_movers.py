"""
Diagnostic script — run locally with venv active from repo root:
  python scripts/test_schwab_movers.py

Measures Schwab movers API response time and outcome for each index.
Tells us whether get_dynamic_watchlist() hangs or fails fast outside market hours.

Expected results:
  < 2s per call  → API fails fast; fix is precautionary but still correct
  10–30s per call → API hangs; confirms the 503 root cause
  HTTP 200, 0 movers → API works on weekends, just returns empty (no hang)
"""
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

import schwab
from services.schwab_service import _get_client

INDEXES = [
    schwab.client.Client.Movers.Index.SPX,
    schwab.client.Client.Movers.Index.COMPX,
    schwab.client.Client.Movers.Index.DJI,
]
INDEX_NAMES = ["SPX", "COMPX", "DJI"]

print("Initializing Schwab client…")
client = _get_client()
print("Client ready. Testing movers API…\n")

total = 0.0
for idx, name in zip(INDEXES, INDEX_NAMES):
    t0 = time.time()
    try:
        resp = client.get_movers(
            idx,
            sort_order=schwab.client.Client.Movers.SortOrder.PERCENT_CHANGE_UP,
        )
        elapsed = time.time() - t0
        total += elapsed
        print(f"{name}: HTTP {resp.status_code} in {elapsed:.2f}s")
        data = resp.json()
        screeners = data.get("screeners", data) if isinstance(data, dict) else data
        count = len(screeners) if isinstance(screeners, list) else "?"
        print(f"  → {count} movers returned")
        if count and isinstance(screeners, list):
            sample = screeners[0]
            print(f"  → sample: {sample.get('symbol') or sample.get('ticker', '?')} "
                  f"@ {sample.get('lastPrice') or sample.get('price', '?')}")
    except Exception as e:
        elapsed = time.time() - t0
        total += elapsed
        print(f"{name}: Exception after {elapsed:.2f}s — {type(e).__name__}: {e}")

print(f"\nTotal time for 3 calls: {total:.2f}s")
if total > 15:
    print("⚠  HANG CONFIRMED — calls are blocking. The market-hours gate fix is critical.")
elif total < 3:
    print("✓  Calls fail fast. Fix is precautionary but still correct to remove unnecessary calls.")
else:
    print("⚠  Moderate latency. Fix still recommended.")

# ── Market hours ──────────────────────────────────────────────────────────────
print("\n--- get_market_hours ---")
t0 = time.time()
try:
    resp = client.get_market_hours(
        [schwab.client.Client.MarketHours.Market.EQUITY]
    )
    elapsed = time.time() - t0
    print(f"HTTP {resp.status_code} in {elapsed:.2f}s")
    import json
    data = resp.json()
    print(json.dumps(data, indent=2))
except Exception as e:
    elapsed = time.time() - t0
    print(f"Exception after {elapsed:.2f}s — {type(e).__name__}: {e}")

# ── next_open_date forward query (Option A) ───────────────────────────────────
print("\n--- next_open_date forward query ---")
print("Querying Schwab forward day-by-day until isOpen=true...\n")
total_next = 0.0
next_open = None
check = date.today()
for i in range(10):
    check += timedelta(days=1)
    t0 = time.time()
    try:
        resp = client.get_market_hours(
            [schwab.client.Client.MarketHours.Market.EQUITY],
            date=check,
        )
        elapsed = time.time() - t0
        total_next += elapsed
        raw = resp.json()
        equity = next(iter(raw.get("equity", {}).values()), {})
        is_open = equity.get("isOpen", False)
        print(f"  {check}  HTTP {resp.status_code}  isOpen={is_open}  ({elapsed:.2f}s)")
        if is_open:
            next_open = check
            break
    except Exception as e:
        elapsed = time.time() - t0
        total_next += elapsed
        print(f"  {check}  Exception after {elapsed:.2f}s — {type(e).__name__}: {e}")
        break

print(f"\n  Total time : {total_next:.2f}s across {i + 1} call(s)")
if next_open:
    print(f"  next_open  : {next_open}  ✓")
    if total_next < 2.0:
        print("  Latency    : acceptable for /market/status endpoint")
    else:
        print("  ⚠  Latency may be noticeable — consider caching /market/status response")
else:
    print("  ✗  No open date found within 10 days")


# ── _write callback signature check ──────────────────────────────────────────
print("\n--- _write callback signature ---")
src = Path(__file__).parent.parent / "backend/services/schwab_service.py"
text = src.read_text()
if re.search(r'def _write\(token,\s*\*\*kwargs\)', text):
    print("✓  _write accepts **kwargs — token refresh will not throw TypeError")
else:
    print("✗  _write missing **kwargs — token refresh WILL fail with TypeError")


# ── Option A end-to-end: get_market_status() via service layer ────────────────
print("\n--- Option A: get_market_status() service call ---")
from services.schwab_service import get_market_status, _fetch_today_status

t0 = time.time()
try:
    today_status = _fetch_today_status()
    elapsed = time.time() - t0
    print(f"_fetch_today_status()  →  {elapsed:.2f}s")
    print(f"  is_open : {today_status['is_open']}")
    print(f"  date    : {today_status.get('date')}")
except Exception as e:
    print(f"_fetch_today_status() FAILED: {type(e).__name__}: {e}")

t0 = time.time()
try:
    status = get_market_status()
    elapsed = time.time() - t0
    print(f"\nget_market_status()    →  {elapsed:.2f}s")
    print(f"  is_open        : {status['is_open']}")
    print(f"  date           : {status.get('date')}")
    print(f"  next_open_date : {status.get('next_open_date')}")
    if status.get('next_open_date'):
        print("  ✓  Option A fully functional — next_open_date returned")
    else:
        print("  ✗  next_open_date missing — forward query may have failed")
    if elapsed < 3.0:
        print(f"  ✓  Total latency acceptable ({elapsed:.2f}s)")
    else:
        print(f"  ⚠  Latency high ({elapsed:.2f}s) — consider caching /market/status")
except Exception as e:
    print(f"get_market_status() FAILED: {type(e).__name__}: {e}")
