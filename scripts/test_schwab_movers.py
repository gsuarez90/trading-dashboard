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
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / "backend" / ".env.local")

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
