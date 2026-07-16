"""
Diagnostic script — inspect all average-cost-related fields for one position
from Robinhood, plus reconstruct a naive weighted-average cost basis from raw
order history, so we can identify which field (if any) matches the "Average
Cost" shown in the Robinhood app/website.

Same pattern as inspect_rh_cash_fields.py, applied to average_buy_price
instead of cash.

Run from repo root with venv active:
  python scripts/inspect_rh_position_fields.py KEEL

Defaults to KEEL if no ticker is given. If your session token is still fresh,
no MFA needed. Otherwise set your MFA PIN first:
  $env:RH_MFA_CODE = "123456"   (PowerShell)
  export RH_MFA_CODE=123456      (bash)
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

import robin_stocks.robinhood as rh

USERNAME = os.environ.get("ROBINHOOD_USERNAME")
PASSWORD = os.environ.get("ROBINHOOD_PASSWORD")
MFA_CODE = os.environ.get("RH_MFA_CODE", "").strip()
TICKER = (sys.argv[1] if len(sys.argv) > 1 else "KEEL").upper()

if not USERNAME or not PASSWORD:
    print("ERROR: ROBINHOOD_USERNAME / ROBINHOOD_PASSWORD not found in .env.local")
    sys.exit(1)


def section(title):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print("─" * 60)


# ── Login ─────────────────────────────────────────────────────────────────────
section("Login")
login_kwargs = dict(username=USERNAME, password=PASSWORD, expiresIn=86400, store_session=True)
if MFA_CODE:
    login_kwargs["mfa_code"] = MFA_CODE
    print("  Using MFA code from RH_MFA_CODE")
else:
    print("  No RH_MFA_CODE set — attempting token reuse")

try:
    rh.login(**login_kwargs)
    print("  Login OK")
except Exception as e:
    print(f"  Login failed: {e}")
    if not MFA_CODE:
        print("  Tip: set $env:RH_MFA_CODE = '<pin>' and retry")
    sys.exit(1)


# ── Find the position ─────────────────────────────────────────────────────────
section(f"get_open_stock_positions() — locating {TICKER}")
position = None
instrument_url = None
try:
    raw_positions = rh.get_open_stock_positions()
    for pos in raw_positions:
        url = pos.get("instrument")
        if not url:
            continue
        instrument = rh.get_instrument_by_url(url)
        if instrument.get("symbol", "").upper() == TICKER:
            position = pos
            instrument_url = url
            break

    if position is None:
        print(f"  No open position found for {TICKER}. Tickers currently held:")
        for pos in raw_positions:
            url = pos.get("instrument")
            if url:
                try:
                    sym = rh.get_instrument_by_url(url).get("symbol")
                    print(f"    {sym}")
                except Exception:
                    pass
        sys.exit(1)

    print(f"\n  All raw fields for {TICKER} position:")
    for k, v in position.items():
        print(f"    {k:<32} = {v}")
except Exception as e:
    print(f"  ERROR: {e}")
    sys.exit(1)


# ── Candidate avg-cost fields ─────────────────────────────────────────────────
section("Candidate average-cost fields")
candidates = {
    "average_buy_price":          position.get("average_buy_price"),
    "pending_average_buy_price":  position.get("pending_average_buy_price"),
    "intraday_average_buy_price": position.get("intraday_average_buy_price"),
    "quantity":                   position.get("quantity"),
    "intraday_quantity":          position.get("intraday_quantity"),
}
for label, val in candidates.items():
    marker = "  <-- current code uses this" if label == "average_buy_price" else ""
    print(f"    {label:<32} = {val}{marker}")


# ── Raw order history for this ticker ─────────────────────────────────────────
section(f"get_all_stock_orders() — every processed order for {TICKER}")
try:
    all_orders = rh.get_all_stock_orders()
    ticker_orders = [o for o in all_orders if o.get("instrument") == instrument_url]
    ticker_orders.sort(key=lambda o: o.get("created_at") or "")

    print(f"\n  {len(ticker_orders)} order(s) found for {TICKER}:\n")
    filled_buys = []
    filled_sells = []
    for o in ticker_orders:
        side = o.get("side")
        state = o.get("state")
        qty = o.get("cumulative_quantity") or o.get("quantity")
        avg_price = o.get("average_price")
        created = o.get("created_at")
        print(f"    {created}  {side:<5} state={state:<12} qty={qty:<10} avg_price={avg_price}")
        if state == "filled" and avg_price is not None and qty:
            if side == "buy":
                filled_buys.append((float(qty), float(avg_price)))
            elif side == "sell":
                filled_sells.append((float(qty), float(avg_price)))

    print(f"\n  Filled buys: {len(filled_buys)}   Filled sells: {len(filled_sells)}")
    if len(filled_sells) > 0:
        print(
            "  NOTE: sells present — if any buy followed a loss-making sell within "
            "30 days, IRS wash-sale rules require the disallowed loss to be added "
            "back into the cost basis of the replacement shares. The Robinhood app "
            "typically displays wash-sale-adjusted cost; the raw average_buy_price "
            "field from the API may not include that adjustment. This is the most "
            "common cause of an API/app average-cost mismatch for a frequently "
            "traded ticker."
        )

    if filled_buys:
        total_shares = sum(q for q, _ in filled_buys)
        total_cost = sum(q * p for q, p in filled_buys)
        naive_avg = total_cost / total_shares if total_shares else 0
        print(f"\n  Naive weighted-average cost from ALL filled buys (no wash-sale adj): {naive_avg:.4f}")
        print("  (This will NOT match the app if any wash-sale adjustment applies —")
        print("   it's here only to confirm whether average_buy_price is even a plain")
        print("   weighted average of buys, or something else entirely.)")
except Exception as e:
    print(f"  ERROR: {e}")


# ── Summary ────────────────────────────────────────────────────────────────────
section("Summary — compare these to the Average Cost shown in the Robinhood app")
print(f"""
    average_buy_price            = {candidates['average_buy_price']}   <-- current code (robinhood_service.py) uses this
    pending_average_buy_price    = {candidates['pending_average_buy_price']}
    intraday_average_buy_price   = {candidates['intraday_average_buy_price']}

  Open the Robinhood app/website, find {TICKER}, and note its displayed
  "Average Cost". Whichever field above matches is the one to switch to in
  robinhood_service.py:140. If NONE of them match and there are sells in the
  order history above, wash-sale cost-basis adjustment (not exposed by any
  of these fields) is the likely explanation — in that case the fix isn't a
  different field, it's accepting that the API average_buy_price is
  pre-wash-sale-adjustment and can't be made to match the app exactly.
""")
