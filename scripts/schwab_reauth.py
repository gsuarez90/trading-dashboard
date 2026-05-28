"""
Schwab token re-authentication script.
Run this when the token expires (invalid_grant / unsupported_token_type errors).

Usage (from repo root, with venv active):
    python scripts/schwab_reauth.py

Steps performed automatically after you log in:
  1. Opens browser for Schwab OAuth — log in and authorize
  2. Writes fresh token to backend/schwab_token.json
  3. Uploads token to AWS Secrets Manager (/trading-app/schwab-token)
  4. Forces cold start on all 6 Lambda functions that use the Schwab client
"""

import os
import time
from pathlib import Path

import boto3
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

import schwab

TOKEN_PATH = Path(__file__).resolve().parent.parent / "backend" / "schwab_token.json"
SECRET_NAME = "/trading-app/schwab-token"
STACK_NAME  = "trading-dashboard"

# AnalyticsFunction has no SchwabSecretsPolicy — skip it
SKIP_LOGICAL = {"AnalyticsFunction"}


def _schwab_lambda_names() -> list[str]:
    cf = boto3.client("cloudformation")
    paginator = cf.get_paginator("list_stack_resources")
    names = []
    for page in paginator.paginate(StackName=STACK_NAME):
        for r in page["StackResourceSummaries"]:
            if (
                r["ResourceType"] == "AWS::Lambda::Function"
                and r["LogicalResourceId"] not in SKIP_LOGICAL
            ):
                names.append(r["PhysicalResourceId"])
    return names


def main():
    # ── Step 1: OAuth flow ────────────────────────────────────────────────────
    # Always delete the local token first so easy_client() is forced to open
    # the browser. Without this, it loads the cached local token which may be
    # older than what Secrets Manager already has (Lambda rolls tokens in-place),
    # and uploading a stale token invalidates the newer one Schwab already issued.
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
        print("  Cleared cached local token.")
    print("\nStep 1 — Opening browser for Schwab OAuth...")
    print("  Log in, authorize the app, then return here.\n")
    schwab.auth.easy_client(
        api_key=os.environ["SCHWAB_CLIENT_ID"],
        app_secret=os.environ["SCHWAB_CLIENT_SECRET"],
        callback_url=os.environ.get("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182"),
        token_path=str(TOKEN_PATH),
    )
    print(f"  Token written to {TOKEN_PATH}")

    # ── Step 2: Upload to Secrets Manager ────────────────────────────────────
    print("\nStep 2 — Uploading token to Secrets Manager...")
    sm = boto3.client("secretsmanager")
    sm.put_secret_value(SecretId=SECRET_NAME, SecretString=TOKEN_PATH.read_text())
    print(f"  Uploaded to {SECRET_NAME}")

    # ── Step 3: Force Lambda cold starts ─────────────────────────────────────
    print("\nStep 3 — Forcing cold start on all Schwab Lambda functions...")
    lam = boto3.client("lambda")
    description = f"token-refresh-{int(time.time())}"
    functions = _schwab_lambda_names()
    for name in functions:
        lam.update_function_configuration(FunctionName=name, Description=description)
        print(f"  Recycled: {name}")

    print(f"\nDone. {len(functions)} functions recycled.")
    print("Wait ~30 seconds, then refresh the app.")


if __name__ == "__main__":
    main()
