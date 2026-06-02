"""
Diagnostic script — validates 20-day SMA computation from Schwab daily bar data.

Tests get_daily_bars() for a handful of top-mover tickers, computes SMA manually,
and prints the results for cross-checking against an external source (TradingView, etc.).

Run locally with venv active:
  python scripts/test_sma_indicators.py
"""

import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

from services import schwab_service

# Handful of well-known tickers to validate against — swap these out as needed
TEST_TICKERS = ["NVDA", "AAPL", "TSLA", "SPY", "AMD"]
SMA_PERIOD = 20
# Fetch extra days to account for weekends/holidays landing on non-trading days
FETCH_DAYS = 30


def section(title):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print("─" * 60)


def compute_sma(bars: list[dict], period: int) -> dict | None:
    """Compute SMA from the last `period` daily close prices.

    Returns dict with sma, current price, distance %, and direction.
    Returns None if not enough bars.
    """
    closes = [b["close"] for b in bars]
    if len(closes) < period:
        return None

    sma = round(sum(closes[-period:]) / period, 2)
    current = closes[-1]
    pct = round((current - sma) / sma * 100, 2)

    return {
        "sma_20": sma,
        "current_price": current,
        "price_vs_sma_pct": pct,
        "above_sma": current >= sma,
        "bars_used": len(closes),
    }


section("Fetching daily bars from Schwab")

to_date = date.today().strftime("%Y-%m-%d")
from_date = (date.today() - timedelta(days=FETCH_DAYS)).strftime("%Y-%m-%d")
print(f"  Range: {from_date} → {to_date}  (requesting {FETCH_DAYS} calendar days)")
print(f"  Tickers: {', '.join(TEST_TICKERS)}\n")

results = {}
for ticker in TEST_TICKERS:
    t0 = time.time()
    try:
        bars = schwab_service.get_daily_bars(ticker, from_date, to_date)
        elapsed = time.time() - t0
        indicator = compute_sma(bars, SMA_PERIOD)
        results[ticker] = {"bars": bars, "indicator": indicator, "elapsed": elapsed}
        print(f"  {ticker}: {len(bars)} bars fetched in {elapsed:.2f}s")
    except Exception as e:
        results[ticker] = {"error": str(e)}
        print(f"  {ticker}: ERROR — {e}")

section("20-Day SMA Results")
print(f"  {'Ticker':<8} {'Price':>8} {'SMA-20':>8} {'vs SMA':>8} {'Direction':<10} {'Bars':>5}")
print(f"  {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*10} {'─'*5}")

for ticker, data in results.items():
    if "error" in data:
        print(f"  {ticker:<8} ERROR: {data['error']}")
        continue
    ind = data["indicator"]
    if ind is None:
        print(f"  {ticker:<8} Not enough bars ({len(data['bars'])} returned, need {SMA_PERIOD})")
        continue
    direction = "ABOVE" if ind["above_sma"] else "BELOW"
    sign = "+" if ind["price_vs_sma_pct"] >= 0 else ""
    print(
        f"  {ticker:<8} "
        f"${ind['current_price']:>7.2f} "
        f"${ind['sma_20']:>7.2f} "
        f"{sign}{ind['price_vs_sma_pct']:>6.2f}% "
        f"{direction:<10} "
        f"{ind['bars_used']:>5}"
    )

section("Raw bar sample (last 3 closes for NVDA)")
nvda = results.get("NVDA", {})
if "bars" in nvda and nvda["bars"]:
    for bar in nvda["bars"][-3:]:
        print(f"  {bar['date']}  close=${bar['close']:.2f}  vol={bar['volume']:,}")
else:
    print("  No NVDA data available.")

print()
print("  Cross-check these SMA-20 values against TradingView or Yahoo Finance.")
print("  They should match within a few cents (minor diff if market closed mid-day).")
print()
