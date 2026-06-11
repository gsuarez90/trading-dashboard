"""
Robinhood session re-authentication script.
Run this when the Robinhood session is expired (portfolio shows fetch errors,
or CloudWatch shows 'Authentication may be expired' in TradingDashboardPrivateFunction).

Usage (from repo root, with venv active):
    $env:RH_MFA_CODE = "123456"   # PowerShell — set to your current TOTP code first
    python scripts/robinhood_reauth.py

Steps performed automatically:
  1. Logs in to Robinhood with your credentials + MFA code
  2. Uploads the fresh session token to Secrets Manager (/trading-app/robinhood-session)
  3. Forces a cold start on TradingDashboardPrivateFunction so it picks up the new token
"""

import base64
import json
import os
import sys
import time
from pathlib import Path

import boto3
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
import robin_stocks.robinhood as rh

SESSION_SECRET_ID = "/trading-app/robinhood-session"
STACK_NAME = "trading-dashboard"
PRIVATE_LOGICAL_ID = "TradingDashboardPrivateFunction"

# robin_stocks writes the token here on Windows (Lambda redirects HOME=/tmp instead)
TOKEN_FILE = Path(os.path.expanduser("~/.tokens/robinhood.pickle"))


def _private_function_name() -> str:
    cf = boto3.client("cloudformation")
    paginator = cf.get_paginator("list_stack_resources")
    for page in paginator.paginate(StackName=STACK_NAME):
        for r in page["StackResourceSummaries"]:
            if r["LogicalResourceId"] == PRIVATE_LOGICAL_ID:
                return r["PhysicalResourceId"]
    raise RuntimeError(f"{PRIVATE_LOGICAL_ID} not found in stack {STACK_NAME!r}")


def main():
    username = os.environ.get("ROBINHOOD_USERNAME")
    password = os.environ.get("ROBINHOOD_PASSWORD")
    mfa_code = os.environ.get("RH_MFA_CODE", "").strip()

    if not username or not password:
        print("✗  ROBINHOOD_USERNAME / ROBINHOOD_PASSWORD not found in .env.local")
        sys.exit(1)
    if not mfa_code:
        print("✗  RH_MFA_CODE not set.")
        print("   $env:RH_MFA_CODE = '123456'   then re-run")
        sys.exit(1)

    # ── Step 1: Login ─────────────────────────────────────────────────────────
    print("\nStep 1 — Logging in to Robinhood...")
    t0 = time.time()
    try:
        rh.login(
            username=username,
            password=password,
            expiresIn=86400,
            store_session=True,
            mfa_code=mfa_code,
        )
        elapsed = time.time() - t0
        profile = rh.load_portfolio_profile()
        equity = profile.get("equity", "?") if profile else "?"
        print(f"  ✓  Authenticated in {elapsed:.2f}s — equity: ${equity}")
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  ✗  Login failed after {elapsed:.2f}s: {type(e).__name__}: {e}")
        sys.exit(1)

    # ── Step 2: Upload session token to Secrets Manager ───────────────────────
    print("\nStep 2 — Uploading session token to Secrets Manager...")
    if not TOKEN_FILE.exists():
        print(f"  ✗  Token file not found at {TOKEN_FILE}")
        print("     robin_stocks may have written it elsewhere — check your HOME setting")
        sys.exit(1)

    with open(TOKEN_FILE, "rb") as f:
        token_b64 = base64.b64encode(f.read()).decode()

    sm = boto3.client("secretsmanager")
    sm.put_secret_value(
        SecretId=SESSION_SECRET_ID,
        SecretString=json.dumps({"token": token_b64}),
    )
    print(f"  ✓  Uploaded to {SESSION_SECRET_ID}")

    # ── Step 3: Force cold start on TradingDashboardPrivateFunction ───────────
    print("\nStep 3 — Forcing cold start on TradingDashboardPrivateFunction...")
    try:
        fn_name = _private_function_name()
        lam = boto3.client("lambda")
        lam.update_function_configuration(
            FunctionName=fn_name,
            Description=f"rh-reauth-{int(time.time())}",
        )
        print(f"  ✓  Recycled: {fn_name}")
    except Exception as e:
        print(f"  ⚠  Cold start failed: {e}")
        print("     Token is uploaded — manually redeploy or touch an env var to force restart")

    print("\nDone. Wait ~15 seconds, then refresh the private dashboard.")


if __name__ == "__main__":
    main()
