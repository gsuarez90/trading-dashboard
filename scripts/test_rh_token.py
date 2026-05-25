"""
Diagnostic script — test Robinhood token persistence before changing any code.

Tests three things:
  1. Login succeeds with mfa_code passed directly (no interactive prompt)
  2. Token file is written to /tmp/.tokens/ (Lambda-compatible path)
  3. Token reuse works — restoring the file skips full re-login (no MFA needed)

Run with venv active from repo root:
  python scripts/test_rh_token.py

Set your MFA PIN before running:
  $env:RH_MFA_CODE = "123456"   (PowerShell)
  export RH_MFA_CODE=123456      (bash)
"""

import json
import os
import pickle
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

import robin_stocks.robinhood as rh

# ── Config ────────────────────────────────────────────────────────────────────

USERNAME = os.environ.get("ROBINHOOD_USERNAME")
PASSWORD = os.environ.get("ROBINHOOD_PASSWORD")
MFA_CODE = os.environ.get("RH_MFA_CODE", "").strip()

if not USERNAME or not PASSWORD:
    print("✗  ROBINHOOD_USERNAME / ROBINHOOD_PASSWORD not found in .env.local")
    sys.exit(1)

if not MFA_CODE:
    print("✗  RH_MFA_CODE not set.")
    print("   export RH_MFA_CODE=<your-pin>  then re-run")
    sys.exit(1)

# On Linux/Lambda: HOME redirect to /tmp works via os.environ["HOME"]
# On Windows: expanduser("~") uses USERPROFILE, not HOME — tokens go to the real home dir
# For the test we just find wherever robin_stocks actually wrote the file
TOKEN_DIR  = Path(os.path.expanduser("~/.tokens"))
TOKEN_FILE = TOKEN_DIR / "robinhood.pickle"
TMP_BACKUP = Path(tempfile.gettempdir()) / "robinhood.pickle.backup"

print(f"  Token location: {TOKEN_FILE}")


def section(title):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print("─" * 60)


def logout_and_clear():
    """Wipe the token file to simulate a cold-start container."""
    try:
        rh.logout()
    except Exception:
        pass
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()


# ── 1. Login with mfa_code passed directly ────────────────────────────────────
section("1. Login with mfa_code (no interactive prompt)")
logout_and_clear()

t0 = time.time()
try:
    rh.login(
        username=USERNAME,
        password=PASSWORD,
        expiresIn=86400,
        store_session=True,
        mfa_code=MFA_CODE,
    )
    elapsed = time.time() - t0
    print(f"  rh.login() completed in {elapsed:.2f}s")

    # Confirm we're authenticated
    profile = rh.load_portfolio_profile()
    if profile:
        equity = profile.get("equity", "?")
        print(f"  ✓  Authenticated — portfolio equity: ${equity}")
    else:
        print("  ✗  Login appeared to succeed but profile returned empty")
except Exception as e:
    elapsed = time.time() - t0
    print(f"  ✗  Login failed after {elapsed:.2f}s: {type(e).__name__}: {e}")
    sys.exit(1)


# ── 2. Inspect token file ─────────────────────────────────────────────────────
section("2. Token file inspection")
if TOKEN_FILE.exists():
    size = TOKEN_FILE.stat().st_size
    print(f"  Path : {TOKEN_FILE}")
    print(f"  Size : {size} bytes")
    try:
        with open(TOKEN_FILE, "rb") as f:
            token_data = pickle.load(f)
        if isinstance(token_data, dict):
            keys = list(token_data.keys())
            print(f"  Keys : {keys}")
            # Show expiry if present
            exp = token_data.get("expires_in") or token_data.get("expiry")
            if exp:
                print(f"  Expiry field: {exp}")
        print("  ✓  Token file written and readable")
        # Save a backup for test 3
        shutil.copy2(TOKEN_FILE, TMP_BACKUP)
        print(f"  Backup saved to: {TMP_BACKUP}")
    except Exception as e:
        print(f"  ⚠  Could not inspect token contents: {e}")
        # Still save backup
        backup = TMP_HOME / "robinhood.pickle.backup"
        shutil.copy2(TOKEN_FILE, backup)
else:
    print(f"  ✗  Token file not found at {TOKEN_FILE}")
    print("     robin_stocks may be writing elsewhere — check your HOME setting")
    sys.exit(1)


# ── 3. Token reuse — simulate cold start ─────────────────────────────────────
section("3. Token reuse (cold-start simulation)")
print("  Clearing token file and logging out...")
logout_and_clear()

print("  Restoring token from backup (simulates Secrets Manager restore)...")
TOKEN_DIR.mkdir(parents=True, exist_ok=True)
shutil.copy2(TMP_BACKUP, TOKEN_FILE)
print(f"  Token restored ({TOKEN_FILE.stat().st_size} bytes)")

print("  Calling rh.login() WITHOUT mfa_code...")
t0 = time.time()
try:
    rh.login(
        username=USERNAME,
        password=PASSWORD,
        expiresIn=86400,
        store_session=True,
        # No mfa_code — should reuse stored token
    )
    elapsed = time.time() - t0
    profile = rh.load_portfolio_profile()
    if profile and profile.get("equity"):
        print(f"  ✓  Token reused in {elapsed:.2f}s — no MFA required")
        print(f"  ✓  Portfolio equity: ${profile.get('equity')}")
        print("  ✓  Cold-start restore pattern confirmed working")
    else:
        print(f"  ⚠  Login returned in {elapsed:.2f}s but profile empty — may need MFA")
except Exception as e:
    elapsed = time.time() - t0
    print(f"  ✗  Token reuse failed after {elapsed:.2f}s: {type(e).__name__}: {e}")
    print("     Stored token may be insufficient — MFA will always be required")


# ── 4. Token serialisation (what we'll store in Secrets Manager) ──────────────
section("4. Secrets Manager storage format")
if TOKEN_FILE.exists():
    with open(TOKEN_FILE, "rb") as f:
        raw = f.read()
    import base64
    encoded = base64.b64encode(raw).decode()
    print(f"  Raw pickle size  : {len(raw)} bytes")
    print(f"  Base64 encoded   : {len(encoded)} chars")
    print(f"  ✓  Can be stored as a Secrets Manager SecretString (base64)")
    print(f"  Sample (first 60 chars): {encoded[:60]}...")
else:
    print("  Token file missing — skipping")


# ── Cleanup ───────────────────────────────────────────────────────────────────
section("Summary")
print("  If tests 1–3 all show ✓:")
print("    - mfa_code bypass works → store PIN in existing RH secret")
print("    - token file is portable → store base64 in new SM secret")
print("    - cold-start restore works → no more MFA prompts in Lambda")
print()
print(f"  Backup file at {TMP_BACKUP} can be deleted — it is outside the repo")
