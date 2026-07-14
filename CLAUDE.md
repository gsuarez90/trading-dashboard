# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

### Local dev (run from repo root)
```bash
bash scripts/start.sh          # starts backend (uvicorn :8000) + frontend (Vite :5173)
```

### Backend only
```bash
source backend/.venv/Scripts/activate   # Git Bash
backend\.venv\Scripts\Activate.ps1      # PowerShell

cd backend
uvicorn main:app --reload --port 8000
```

### Tests (run from `backend/` with venv active)
```bash
pytest tests/test_guardrails.py -v --tb=short    # the 14 guardrail tests (Phase 1 gate)
pytest tests/ -v --tb=short                      # all tests
pytest tests/test_guardrails.py::test_name -v    # single test
```

Tests require `pytest` and `moto` — neither is in `requirements.txt`. Install separately:
```bash
pip install pytest moto
```

### Linting (black line length is 100, not default 88)
```bash
black --line-length=100 backend/
isort backend/
```

### Frontend
```bash
cd frontend && npm ci && npm run build    # production build
cd frontend && npm run dev               # dev server only (no backend)
```

### AWS / SAM
```bash
sam build && sam deploy                  # deploy from repo root (template.yaml is here, not in backend/)
```

---

## Architecture

### Request path (local dev)
Browser → Vite (:5173) → `/api/*` proxy → uvicorn FastAPI (:8000)

### Request path (production)
Browser → Cloudflare → CloudFront → S3 (static frontend)  
Browser → Cloudflare → API Gateway → Lambda (FastAPI via Mangum) → DynamoDB / SSM / Secrets Manager / Schwab / Finnhub / Claude

### Two frontend builds from one source
`VITE_PORTFOLIO_MODE=synthetic` → public S3 bucket (demo, anyone can view)  
`VITE_PORTFOLIO_MODE=live` → private S3 bucket (real account, Cloudflare Access auth)  
Both call the same Lambda/API Gateway endpoint. `portfolio_factory.py` switches provider at runtime based on `PORTFOLIO_MODE` env var.

### Backend layer contract
Routers call services. Services never call routers. `context_loader.load_context()` is the single assembly point for the full market snapshot — it is called before every Claude API interaction (briefing, chat, suggest-trades).

### DynamoDB single-table design
One table (`trading-dashboard`), three item types sharing the same GSI (`status-date-index`):
- Trades: `status` = `open` | `closed` | `live`
- Cache: `trade_id` = `"cache#scanner"` | `"cache#sentiment"` | `"cache#briefing"`, `status` = `"cache"`
- Guardrail events: `status` = `"guardrail_event"`

Cache freshness is ET-date-based (not TTL). `cache_service._cache_is_fresh()` compares `cached_at` ISO timestamp to today's ET date.

### Schwab client singleton
`schwab_service._get_client()` initializes once per process. Lambda: token read/write via Secrets Manager. Local dev: token file at `backend/schwab_token.json` (gitignored). If both Scanner and Portfolio fail simultaneously, the Schwab client is the common failure point — check token freshness.

### Guardrail system
`guardrail_service.check_all(trade, ctx)` runs all 8 checks. Same code path for paper and live. Any triggered rule logs a `guardrail_event` to DynamoDB (appears in `GuardrailsPanel` and in Claude's context on next call). The 14 tests in `test_guardrails.py` are the hard gate before `TRADING_MODE=live`.

### Scheduled Lambda handlers (in `main.py`)
- `refresh_handler` → `cache_service.run_daily_refresh()` — 9:32am ET: Schwab movers + Finnhub sentiment + Claude briefing → DynamoDB cache
- `refresh_live_briefing_handler` → `cache_service.run_live_briefing_refresh()` — 9:36am ET: live-mode Claude briefing (real Robinhood portfolio) → DynamoDB cache
- `price_monitor_handler` → `cache_service.run_price_monitor()` — every 5 min market hours: auto-close paper trades at target/stop
- `end_of_day_handler` → `cache_service.run_end_of_day()` — 3:45pm ET: close all open paper trades, flag live trades

### Claude model
`claude_service.py` uses `claude-sonnet-4-6`. Do not downgrade.

### Environment variables
- Config (non-secret): `PORTFOLIO_MODE`, `TRADING_MODE`, `PROFIT_MODE`, `TRADE_SCOPE`, `DAILY_GOAL`, `DAILY_LOSS_LIMIT`, `DAILY_TRADE_LIMIT`, `MAX_POSITION_SIZE_PCT` — SSM plain params in Lambda, `.env.local` locally
- Secrets: `ANTHROPIC_API_KEY`, `FINNHUB_API_KEY`, `SCHWAB_CLIENT_ID`, `SCHWAB_CLIENT_SECRET` — SSM SecureString in Lambda
- `SCHWAB_TOKEN_SECRET_ARN` — set by SAM, tells `schwab_service` to use Secrets Manager instead of token file
- `DYNAMO_TABLE_NAME` — hardcoded `trading-dashboard` in `template.yaml`, set in `.env.local` locally

### SAM template location
`template.yaml` and `samconfig.toml` are at the **repo root**, not in `backend/`. Run `sam build` and `sam deploy` from repo root.

---

## Commit Messages

Always end every commit message body with both trailers, in this order:
```
Co-Authored-By: gsuarez90 <gsuarez90@users.noreply.github.com>
Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

Maximum supported commit message length is **965 bytes** — keep the full message (body + trailers) under this limit.

---

## Key Constraints

- **Never commit** `.env.local` or `schwab_token.json` — both are gitignored
- **`TRADING_MODE=live`** requires explicit user confirmation — this switches from paper tracking to real trade logging
- **Live trades are never auto-closed** — price monitor and EOD handler flag them; user closes manually in Robinhood
- **black line length is 100** — CI lint check uses `--line-length=100`; default 88 will fail CI
- **`sam build` runs from repo root** — `template.yaml` is there, not in `backend/`
- **`pytest` needs `working-directory: backend`** in CI — service imports (`from services import ...`) only resolve when running from `backend/`
