"""
Tests the strip_trailing_slash middleware in isolation.
No backend services or AWS credentials needed — uses a minimal FastAPI app
that mirrors our setup (redirect_slashes=False + path-stripping middleware).

Run from repo root with venv active:
  python scripts/test_routing.py
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

# ── Minimal app mirroring main.py + our routers ───────────────────────────────

app = FastAPI(redirect_slashes=False)


@app.middleware("http")
async def strip_trailing_slash(request: Request, call_next):
    if request.url.path != "/" and request.url.path.endswith("/"):
        request.scope["path"] = request.url.path.rstrip("/")
    return await call_next(request)


@app.get("/")
def root():
    return {"ok": True}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/portfolio")
def get_portfolio():
    return {"positions": []}


@app.get("/paper-trades")
def list_paper_trades():
    return []


@app.post("/paper-trades")
def open_paper_trade():
    return {}


@app.get("/live-trades")
def list_live_trades():
    return []


@app.post("/live-trades")
def log_live_trade():
    return {}


# ── Test cases ────────────────────────────────────────────────────────────────

client = TestClient(app, raise_server_exceptions=True)

cases = [
    # (method, path, expected_status, label)
    ("GET",  "/portfolio/",       200, "portfolio — Lambda delivers no slash, browser sends slash"),
    ("GET",  "/portfolio",        200, "portfolio — no slash direct"),
    ("GET",  "/health",           200, "health — no slash unaffected"),
    ("GET",  "/health/",          200, "health — trailing slash stripped"),
    ("GET",  "/paper-trades/",    200, "paper-trades GET — trailing slash stripped"),
    ("GET",  "/paper-trades",     200, "paper-trades GET — no slash direct"),
    ("POST", "/paper-trades/",    200, "paper-trades POST — trailing slash stripped"),
    ("POST", "/paper-trades",     200, "paper-trades POST — no slash direct"),
    ("GET",  "/live-trades/",     200, "live-trades GET — trailing slash stripped"),
    ("GET",  "/live-trades",      200, "live-trades GET — no slash direct"),
    ("POST", "/live-trades/",     200, "live-trades POST — trailing slash stripped"),
    ("POST", "/live-trades",      200, "live-trades POST — no slash direct"),
    ("GET",  "/",                 200, "root — never stripped"),
]

print("\nOption A — strip_trailing_slash middleware\n")
passed = 0
for method, path, expected, label in cases:
    if method == "GET":
        r = client.get(path)
    else:
        r = client.post(path)
    ok = r.status_code == expected
    mark = "✓" if ok else "✗"
    status = f"{r.status_code}" if not ok else f"{r.status_code}"
    print(f"  {mark}  {method:<4} {path:<22} → {status}  {label}")
    if ok:
        passed += 1

print(f"\n{passed}/{len(cases)} passed")
if passed == len(cases):
    print("All good — safe to apply middleware to main.py and simplify routers.")
else:
    print("Fix failures before committing.")
