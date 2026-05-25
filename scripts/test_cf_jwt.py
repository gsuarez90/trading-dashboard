"""
Diagnostic script — test CF Access JWT validation logic before wiring into Lambda.

Run with venv active from repo root:
  python scripts/test_cf_jwt.py

Requires:
  pip install "PyJWT[cryptography]"

To get a real CF JWT for full validation (steps 3 & 4):
  1. Visit https://degen.gsuarez.dev in your browser (must pass CF Access login)
  2. DevTools → Application → Cookies → copy the value of CF_Authorization
  3. Set it before running:
       $env:CF_JWT = "eyJ..."
  Steps 1–2 (JWKS connectivity) run without a token.
"""

import base64
import json
import os
import sys
import time

try:
    import jwt
    from jwt import PyJWKClient
except ImportError:
    print('✗  PyJWT not installed. Run: pip install "PyJWT[cryptography]"')
    sys.exit(1)

try:
    import httpx
except ImportError:
    print("✗  httpx not installed. Run: pip install httpx")
    sys.exit(1)

CF_TEAM_DOMAIN = "withered-papi-00f9.cloudflareaccess.com"
CF_AUD = "12b66ac9cba3d4779c964abbddb5db9d36c272f2e1327ac1a2cb7a5248f83aca"
JWKS_URL = f"https://{CF_TEAM_DOMAIN}/cdn-cgi/access/certs"


def section(title):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print("─" * 60)


def decode_part(p):
    p += "=" * (-len(p) % 4)
    return json.loads(base64.urlsafe_b64decode(p))


# ── 1. JWKS endpoint reachability ─────────────────────────────────────────────
section("1. JWKS fetch")
t0 = time.time()
try:
    resp = httpx.get(JWKS_URL, timeout=10)
    elapsed = time.time() - t0
    print(f"  HTTP {resp.status_code} in {elapsed:.2f}s")
    jwks = resp.json()
    keys = jwks.get("keys", [])
    print(f"  Keys returned: {len(keys)}")
    for k in keys:
        print(f"    kid={k.get('kid', '?')[:20]}...  alg={k.get('alg', '?')}  use={k.get('use', '?')}")
    if keys:
        print("  ✓  JWKS endpoint reachable and returning keys")
    else:
        print("  ✗  No keys returned — check team domain")
        sys.exit(1)
except Exception as e:
    print(f"  ✗  JWKS fetch failed: {type(e).__name__}: {e}")
    sys.exit(1)


# ── 2. PyJWKClient init ───────────────────────────────────────────────────────
section("2. PyJWKClient init")
try:
    jwks_client = PyJWKClient(JWKS_URL)
    # Warm the cache — fetches keys now so cold-start latency is predictable
    t0 = time.time()
    _ = jwks_client.get_jwk_set()
    elapsed = time.time() - t0
    print(f"  Key cache warmed in {elapsed:.2f}s")
    print("  ✓  PyJWKClient ready")
except Exception as e:
    print(f"  ✗  PyJWKClient failed: {type(e).__name__}: {e}")
    sys.exit(1)


# ── 3. Real JWT validation ────────────────────────────────────────────────────
section("3. Real JWT validation")
token = os.environ.get("CF_JWT", "").strip()

if not token:
    print("  CF_JWT not set — skipping live validation.")
    print("\n  To run this section:")
    print("    1. Visit https://degen.gsuarez.dev (log in via CF Access)")
    print("    2. DevTools → Application → Cookies → copy CF_Authorization value")
    print('    3. $env:CF_JWT = "eyJ..."')
    print("    4. Re-run this script")
else:
    # Inspect claims without validation first
    try:
        parts = token.split(".")
        header = decode_part(parts[0])
        payload = decode_part(parts[1])
        print(f"  Header  : alg={header.get('alg')}  kid={str(header.get('kid', '?'))[:20]}...")
        print(f"  Claims  :")
        print(f"    iss : {payload.get('iss', '?')}")
        aud = payload.get('aud', '?')
        print(f"    aud : {aud[:20]}..." if isinstance(aud, str) and len(aud) > 20 else f"    aud : {aud}")
        print(f"    sub : {payload.get('sub', '?')}")
        print(f"    email : {payload.get('email', '(not present)')}")
        exp = payload.get("exp")
        if exp:
            remaining = exp - time.time()
            if remaining > 0:
                print(f"    exp : valid for {remaining / 60:.0f} more minutes  ✓")
            else:
                print(f"    exp : EXPIRED {abs(remaining) / 60:.0f} min ago  ✗  — get a fresh token")
    except Exception as e:
        print(f"  ✗  Could not inspect token: {e}")

    # Full cryptographic validation
    print()
    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        validated = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=CF_AUD,
        )
        print("  ✓  Signature valid (RS256, signed by CF private key)")
        print("  ✓  AUD matches expected value")
        print("  ✓  Token not expired")
        print("  ✓  Full validation passed — this is exactly what the middleware will do")
    except jwt.ExpiredSignatureError:
        print("  ✗  Token expired — get a fresh one from the browser")
    except jwt.InvalidAudienceError:
        print(f"  ✗  AUD mismatch — token aud does not match configured value")
    except jwt.InvalidSignatureError:
        print("  ✗  Signature invalid")
    except Exception as e:
        print(f"  ✗  Validation failed: {type(e).__name__}: {e}")


# ── 4. Rejection tests ────────────────────────────────────────────────────────
section("4. Rejection tests")

if not token:
    print("  Skipped — set CF_JWT to run rejection tests")
else:
    # Wrong AUD
    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        jwt.decode(token, signing_key.key, algorithms=["RS256"], audience="wrong-aud-" + "0" * 54)
        print("  ✗  Wrong AUD — should have been rejected but passed")
    except jwt.InvalidAudienceError:
        print("  ✓  Wrong AUD → InvalidAudienceError")
    except jwt.ExpiredSignatureError:
        print("  ~  Wrong AUD skipped (token already expired)")
    except Exception as e:
        print(f"  ✓  Wrong AUD → {type(e).__name__}")

    # Tampered payload (signature mismatch)
    try:
        parts = token.split(".")
        last_char = parts[1][-1]
        tampered = parts[1][:-1] + ("A" if last_char != "A" else "B")
        tampered_token = f"{parts[0]}.{tampered}.{parts[2]}"
        signing_key = jwks_client.get_signing_key_from_jwt(tampered_token)
        jwt.decode(tampered_token, signing_key.key, algorithms=["RS256"], audience=CF_AUD)
        print("  ✗  Tampered payload — should have been rejected but passed")
    except Exception as e:
        print(f"  ✓  Tampered payload → {type(e).__name__}")

    # Empty token
    try:
        jwks_client.get_signing_key_from_jwt("")
        print("  ✗  Empty token — should have been rejected")
    except Exception as e:
        print(f"  ✓  Empty token → {type(e).__name__}")

    # Random string (not a JWT)
    try:
        jwks_client.get_signing_key_from_jwt("not.a.jwt")
        print("  ✗  Garbage token — should have been rejected")
    except Exception as e:
        print(f"  ✓  Garbage token → {type(e).__name__}")


# ── Summary ───────────────────────────────────────────────────────────────────
section("Summary")
if token:
    print("  Sections 1–4 complete.")
    print("  If all lines show ✓, the validation logic is correct and ready to wire in.")
else:
    print("  Sections 1–2 complete (no CF_JWT set).")
    print("  Set CF_JWT and re-run to complete sections 3–4.")
