"""
Diagnostic script — tests the portfolio card end-to-end flow from outside Lambda.

Simulates what the browser does: sends requests with an Origin header so CORS
headers in the response are visible.

Note on redirect_slashes=False (deployed 2026-05-25):
  Lambda Function URL strips trailing slashes before invoking FastAPI.
  FastAPI redirect_slashes=False means /portfolio (no slash) must be a registered
  route — the "" + "/" double-decorator pattern handles both forms.
  Test 2 (with trailing slash) and Test 6 (without) should both return 200.

Run from repo root with venv active:
  python scripts/test_portfolio_endpoint.py

Reads FUNCTION_URL from env or fetches it from CloudFormation automatically.
"""

import json
import os
import sys
import time
from pathlib import Path

import httpx

# ── Resolve Function URL ──────────────────────────────────────────────────────

def get_function_url() -> str:
    url = os.environ.get("FUNCTION_URL")
    if url:
        return url.rstrip("/")

    print("FUNCTION_URL not set — fetching from CloudFormation...")
    try:
        import boto3
        cf = boto3.client("cloudformation", region_name="us-east-1")
        stacks = cf.describe_stacks(StackName="trading-dashboard")
        outputs = stacks["Stacks"][0].get("Outputs", [])
        for o in outputs:
            if o["OutputKey"] == "FunctionUrl":
                return o["OutputValue"].rstrip("/")
        print("ERROR: FunctionUrl output not found in CloudFormation stack.")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR fetching CloudFormation outputs: {e}")
        print("Set FUNCTION_URL env var manually and retry.")
        sys.exit(1)


BASE = get_function_url()
ORIGIN = "https://ait.gsuarez.dev"

print(f"\nTarget: {BASE}")
print(f"Origin: {ORIGIN}\n")


def section(title):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print("─" * 60)


def show_response(resp: httpx.Response, show_body: bool = True):
    print(f"  Status : {resp.status_code}")
    cors_origin = resp.headers.get("access-control-allow-origin", "MISSING")
    location    = resp.headers.get("location", "")
    content_type = resp.headers.get("content-type", "")
    print(f"  CORS   : access-control-allow-origin = {cors_origin}")
    if location:
        print(f"  Redirect → {location}")
    if show_body and resp.status_code < 400 and "json" in content_type:
        try:
            body = resp.json()
            print(f"  Body   : {json.dumps(body, indent=2)[:800]}")
        except Exception:
            print(f"  Body   : {resp.text[:400]}")
    elif show_body and resp.status_code >= 400:
        print(f"  Error  : {resp.text[:400]}")


# ── 1. Health check ───────────────────────────────────────────────────────────

section("1. Health check")
t0 = time.time()
try:
    r = httpx.get(f"{BASE}/health", headers={"Origin": ORIGIN}, follow_redirects=True)
    print(f"  {time.time() - t0:.2f}s")
    show_response(r)
except Exception as e:
    print(f"  EXCEPTION: {e}")


# ── 2. Portfolio — correct path (single slash) ────────────────────────────────

section("2. Portfolio — correct path (no redirect expected)")
t0 = time.time()
try:
    r = httpx.get(
        f"{BASE}/portfolio/",
        params={"mode": "synthetic"},
        headers={"Origin": ORIGIN},
        follow_redirects=False,
    )
    elapsed = time.time() - t0
    print(f"  {elapsed:.2f}s")
    show_response(r)
except Exception as e:
    print(f"  EXCEPTION: {e}")


# ── 3. Portfolio — double-slash path (redirect test) ─────────────────────────

section("3. Portfolio — double-slash path (simulates trailing-slash URL bug)")
double_slash_url = BASE + "/" + "portfolio/?mode=synthetic"
print(f"  URL: {double_slash_url}")
t0 = time.time()
try:
    r = httpx.get(
        double_slash_url,
        headers={"Origin": ORIGIN},
        follow_redirects=False,
    )
    elapsed = time.time() - t0
    print(f"  {elapsed:.2f}s")
    show_response(r, show_body=False)
    if r.status_code in (301, 307, 308):
        print(f"\n  Following redirect...")
        r2 = httpx.get(
            r.headers["location"],
            headers={"Origin": ORIGIN},
            follow_redirects=False,
        )
        print(f"  After redirect:")
        show_response(r2)
except Exception as e:
    print(f"  EXCEPTION: {e}")


# ── 4. Portfolio — follow redirects (what the browser does) ──────────────────

section("4. Portfolio — follow redirects (browser behaviour)")
t0 = time.time()
try:
    r = httpx.get(
        f"{BASE}/portfolio/",
        params={"mode": "synthetic"},
        headers={"Origin": ORIGIN},
        follow_redirects=True,
        timeout=20,
    )
    elapsed = time.time() - t0
    print(f"  {elapsed:.2f}s")
    show_response(r)
    if r.status_code == 200:
        body = r.json()
        positions = body.get("positions", [])
        null_prices = [p["ticker"] for p in positions if p.get("current_price") is None]
        if null_prices:
            print(f"\n  ⚠  NULL prices for: {null_prices} — Schwab enrichment failed")
        else:
            print(f"\n  ✓  All {len(positions)} positions have prices")
except Exception as e:
    print(f"  EXCEPTION: {e}")


# ── 5. Portfolio — no trailing slash (what Lambda actually delivers) ──────────

section("5. Portfolio — no trailing slash (Lambda strips it)")
t0 = time.time()
try:
    r = httpx.get(
        f"{BASE}/portfolio",
        params={"mode": "synthetic"},
        headers={"Origin": ORIGIN},
        follow_redirects=False,
        timeout=20,
    )
    elapsed = time.time() - t0
    print(f"  {elapsed:.2f}s")
    show_response(r)
    if r.status_code == 200:
        body = r.json()
        positions = body.get("positions", [])
        null_prices = [p["ticker"] for p in positions if p.get("current_price") is None]
        if null_prices:
            print(f"\n  ⚠  NULL prices for: {null_prices} — Schwab enrichment failed")
        else:
            print(f"\n  ✓  All {len(positions)} positions have prices")
except Exception as e:
    print(f"  EXCEPTION: {e}")


# ── 6. CORS preflight (OPTIONS) ───────────────────────────────────────────────

section("6. CORS preflight OPTIONS — /portfolio/")
t0 = time.time()
try:
    r = httpx.options(
        f"{BASE}/portfolio/",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
        follow_redirects=False,
    )
    elapsed = time.time() - t0
    print(f"  {elapsed:.2f}s")
    print(f"  Status : {r.status_code}")
    for h in ["access-control-allow-origin", "access-control-allow-methods",
              "access-control-allow-headers", "access-control-max-age"]:
        print(f"  {h}: {r.headers.get(h, 'MISSING')}")
except Exception as e:
    print(f"  EXCEPTION: {e}")
