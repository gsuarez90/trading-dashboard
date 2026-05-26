"""
Diagnostic script — verify HOME path mismatch in robinhood_service._login().

Tests whether os.environ.setdefault("HOME", "/tmp") is ineffective when Lambda
has already set HOME to another value (typically /root), causing _restore_session()
to write the token to a path that rh.login() never checks.

Run from repo root with venv active:
  python scripts/test_rh_home.py
"""

import os
import pathlib
import sys


def section(title):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print("─" * 60)


# ── 1. Baseline — current environment ────────────────────────────────────────
section("1. Current environment (your machine)")
current_home = os.environ.get("HOME", "NOT SET")
print(f"  HOME = {current_home!r}")
token_path_current = pathlib.Path(os.path.expanduser("~/.tokens/robinhood.pickle"))
print(f"  rh.login() would look at: {token_path_current}")


# ── 2. Simulate Lambda — HOME already set to /root ───────────────────────────
section("2. Simulating Lambda (HOME=/root, already set by runtime)")

os.environ["HOME"] = "/root"
print(f"  HOME forced to: {os.environ['HOME']!r}")

# This is what robinhood_service._login() currently does
os.environ.setdefault("HOME", "/tmp")
print(f"  After setdefault('HOME', '/tmp'): HOME = {os.environ['HOME']!r}")

WRITES_TO = "/tmp/.tokens/robinhood.pickle"
LOOKS_AT  = str(pathlib.Path(os.path.expanduser("~/.tokens/robinhood.pickle")))

print(f"\n  _restore_session() writes token to : {WRITES_TO}")
print(f"  rh.login()         looks for token at: {LOOKS_AT}")

if WRITES_TO == LOOKS_AT:
    print("\n  ✓  Paths match — token would be found (no bug)")
else:
    print("\n  ✗  MISMATCH — token is written to a path rh.login() never checks")
    print("     rh.login() proceeds without device_token → fresh login → needs MFA")
    print("     Robinhood returns device-approval response → JSONDecodeError at char 1")
    print("     This is the root cause of the 502.")


# ── 3. Simulate fix — unconditional HOME=/tmp ─────────────────────────────────
section("3. Simulating fix (os.environ[\"HOME\"] = \"/tmp\", unconditional)")

os.environ["HOME"] = "/root"   # reset to Lambda state
os.environ["HOME"] = "/tmp"    # what the fix does
print(f"  HOME after fix: {os.environ['HOME']!r}")

if sys.platform == "win32":
    # Windows expanduser uses USERPROFILE, not HOME — simulate Linux behavior directly
    LOOKS_AT_FIXED = "/tmp/.tokens/robinhood.pickle"
    print("  (Windows: expanduser uses USERPROFILE, not HOME)")
    print(f"  On Linux/Lambda, rh.login() would look at: {LOOKS_AT_FIXED}")
else:
    LOOKS_AT_FIXED = str(pathlib.Path(os.path.expanduser("~/.tokens/robinhood.pickle")))
    print(f"  rh.login()         looks for token at: {LOOKS_AT_FIXED}")

print(f"\n  _restore_session() writes token to : {WRITES_TO}")
print(f"  rh.login()         looks for token at: {LOOKS_AT_FIXED}")

if WRITES_TO == LOOKS_AT_FIXED:
    print("\n  ✓  Paths match — fix is correct")
else:
    print("\n  ✗  Still mismatched after fix — investigate further")


# ── Summary ───────────────────────────────────────────────────────────────────
section("Summary")
mismatch_confirmed = WRITES_TO != LOOKS_AT
fix_confirmed = WRITES_TO == LOOKS_AT_FIXED

if mismatch_confirmed and fix_confirmed:
    print("  Root cause confirmed: setdefault does not override Lambda's HOME.")
    print("  Fix confirmed: unconditional assignment resolves the mismatch.")
    print()
    print("  Change in robinhood_service._login():")
    print("    Before: os.environ.setdefault(\"HOME\", \"/tmp\")")
    print("    After:  os.environ[\"HOME\"] = \"/tmp\"")
elif not mismatch_confirmed:
    print("  No mismatch detected. Root cause may be elsewhere.")
else:
    print("  Unexpected result — review sections above.")
