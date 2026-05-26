# Claude Code Kickoff Prompt — AI Trading Dashboard (Final v5, updated 2026-05-26)

## Project Overview
Build a personal AI-assisted stock trading dashboard using FastAPI, the Anthropic Claude API, and a 100% AWS infrastructure stack. The app is a single-user portfolio tool that:
- Scans stocks daily and analyzes news sentiment
- Provides a conversational interface where the user asks Claude to generate trade suggestions targeting a daily cash P&L goal
- Tracks paper trades against real market prices during the validation period
- Validates paper trade performance against market benchmarks
- Runs analytics and probability modeling on trade history
- Serves as a public portfolio demo for professional visibility

**The app is an analysis and tracking tool — not an execution tool.**
All live trades are placed manually by the user in the Robinhood app.

---

## Current Status (as of 2026-05-26)

**Phase 1 is complete.** The app is live at two URLs:
- `your-public-domain.com` — public demo (synthetic portfolio, anyone can view)
- `your-private-domain.com` — private personal URL (Cloudflare Access email OTP gate)

**In progress:** Two-Lambda infrastructure split (`two-lambda-implementation.md`). Both URLs currently route to the same Lambda with `PORTFOLIO_MODE=synthetic`. The split will give each URL its own Lambda with IAM-level Robinhood access control. Backend code is complete; AWS infrastructure changes (Steps 1–3 of 8 done locally, Steps 4–8 pending deploy).

---

## Full Architecture

```
Public version (your-public-domain.com):
  Porkbun DNS → Cloudflare (rate limiting, DDoS) → CloudFront
    → S3 (React frontend — trading-dashboard-public)
      → Lambda Function URL
        → TradingDashboardFunction (FastAPI, PORTFOLIO_MODE=synthetic)
          → DynamoDB, Secrets Manager (Schwab only), SSM

Personal version (your-private-domain.com):
  Porkbun DNS → Cloudflare Access (email OTP) → CloudFront
    → S3 (React frontend — trading-dashboard-private)
      → Lambda Function URL (x-api-key header required)
        → TradingDashboardPrivateFunction (FastAPI, PORTFOLIO_MODE=live)
          → DynamoDB, Secrets Manager (Schwab + Robinhood), SSM
```

**Two Lambda functions from one codebase** (`CodeUri: backend/`). IAM policies enforce the isolation — the public Lambda's execution role has no path to Robinhood credentials.

100% AWS infrastructure. One account, one bill, one ecosystem.

---

## Full Product Roadmap

```
Phase 1 — Build + Paper Trade (4-6 weeks) ✅ COMPLETE (built not fully complete in terms of data collection)
  Core app built and running
  Paper trades against real Schwab market data
  Basic performance tracking
  Establish daily workflow and 3:45pm alarm habit
  Goal: prove the system works mechanically

Phase 2 — Validation + Analytics + SageMaker Init (6-8 weeks)
  Validation layer: SPY benchmark, random baseline, slippage simulation
  AWS Analytics: Monte Carlo, conditions analysis, P&L distribution,
    Kelly Criterion, equity curves (Pandas/NumPy/SciPy/Plotly in Lambda)
  SageMaker pipeline starts ingesting trade data immediately
  Initial ML model trains — observe predictions, do not act on them yet
  Second paper trading cycle with all layers active
  MATLAB optional for offline deep analysis
  Refine Claude prompts and guardrails based on findings
  Goal: validate Claude's edge is real, identify optimal conditions

Phase 3 — Live Trading Small Size + SageMaker Observation (2-4 weeks)
  25% of normal position sizes
  Manual execution via Robinhood app
  SageMaker predictions visible on suggestion cards — observe only
  Compare ML predictions vs actual outcomes (calibration)
  Compare live results to validated paper results
  Goal: build live track record, calibrate ML model

Phase 4 — Full Live Trading + SageMaker Active (ongoing)
  Full position sizes
  SageMaker predictions integrated into Claude context
  ML actively influences trade suggestions
  Alpaca auto-execution option
  Continuous improvement loop
  Goal: optimized, data-driven daily trading system
```

---

## Mode Dimensions

**Portfolio Mode:**
- `live` — real Robinhood cash balance via robin_stocks (read-only)
- `synthetic` — static fictional portfolio using real Schwab prices (cloud demo)

**Trading Mode:**
- `paper` — simulated trades tracked against real market prices
- `live` — manually placed trades logged and tracked

**Trade Scope:**
- `holdings_only` — Claude only suggests trades using stocks already owned
- `open` — Claude suggests from daily scanner
- `both` — Claude considers both

**Profit Mode:**
- `cash_intraday` — all positions opened and closed same day
- `swing` — positions can be held overnight
- `holdings` — trade around existing positions

**Recommended starting config:**
```
PORTFOLIO_MODE=live       (private Lambda only — set per-function in template.yaml)
TRADING_MODE=paper
TRADE_SCOPE=holdings_only
PROFIT_MODE=cash_intraday
DAILY_GOAL=100
```

---

## Tech Stack

### Phase 1 — Core (all built)
- **Backend**: Python 3.13, FastAPI, Mangum (Lambda adapter)
- **AI Layer**: Anthropic Claude API (`claude-sonnet-4-6`) — do not downgrade
- **Market Data**: Schwab API (OAuth, `schwab_service.py`) — replaced Polygon.io
- **News/Sentiment**: Finnhub (free tier, `finnhub_service.py`)
- **Portfolio read**: robin_stocks via `robinhood_service.py` (read-only, no order placement)
- **Portfolio synthetic**: `synthetic_portfolio.py` — static dict, real Schwab prices applied
- **Paper Trading**: Internal engine, DynamoDB persistence (`paper_trading_service.py`)
- **Database**: DynamoDB (AWS free tier, single table `trading-dashboard`)
- **Frontend hosting**: AWS S3 + CloudFront (two buckets, two distributions)
- **Backend hosting**: AWS Lambda (Function URLs, no 29s ceiling) + API Gateway (legacy, kept for rollback)
- **Scheduler**: AWS EventBridge (5 Lambda functions total)
- **Security/Routing**: Cloudflare (rate limiting, DDoS, Access auth)
- **CI/CD**: GitHub Actions (OIDC role, three parallel jobs)
- **IaC**: AWS SAM (`template.yaml` at repo root)

### Phase 2 additions
- **Validation**: `validation_service.py`
- **Analytics**: Lambda + Pandas + NumPy + SciPy + Scikit-learn + Plotly
- **Chart storage**: S3 bucket (Plotly HTML charts)
- **ML**: SageMaker Data Wrangler + Serverless Inference

### Phase 4 additions
- **Auto-execution**: Alpaca API (commission-free, official algorithmic trading)

---

## robin_stocks — Read Only
Reads: cash balance, stock positions, cost basis, unrealized P&L
Never: places orders, cancels orders, any write operations
Zero Robinhood ToS risk.

**Phase 4 option:** Alpaca as execution layer.
Official API, commission-free, designed for algorithmic trading.
Slots in as drop-in replacement without restructuring the codebase.

---

## AWS Backend — Always On

```
9:35am ET     DailyRefreshFunction (synthetic briefing — public Lambda)
              Schwab movers + Finnhub sentiment → DynamoDB cache ("scanner", "sentiment")
              Claude morning briefing → DynamoDB cache ("briefing", synthetic portfolio context)

9:35am ET     DailyRefreshLiveBriefingFunction (live briefing — private Lambda)
              Runs concurrently with DailyRefreshFunction
              Claude morning briefing → DynamoDB cache ("briefing_live", real Robinhood context)

9:30am ET     PriceMonitorFunction starts (market hours)
              Every 1 min — checks open paper/live trades
              Auto-closes trades hitting target or stop via Schwab

3:45pm ET     EndOfDayFunction
              Auto-closes remaining open paper trades at market price
              Flags open live trades → dashboard alert for manual close

5:00pm ET     PriceMonitorFunction stops

Nightly       AnalyticsFunction (Phase 2+ — stub only, not active)
              Validation, Monte Carlo, conditions analysis
              Plotly charts → S3
              Results → DynamoDB
```

**Cache behavior:** `DailyRefreshFunction` writes scanner/sentiment/briefing to DynamoDB at 9:35am ET. Both public and private Lambdas read from this cache on every request. Cache freshness is ET-date-based — stale if no entry for today. On cache miss, `load_context()` falls back to live Schwab/Finnhub calls.

---

## Secrets Architecture

```
SSM Parameter Store (plain String — resolved by CloudFormation at deploy time):
  /trading-app/portfolio-mode       → synthetic  (public Lambda SSM default; private Lambda overrides to "live" in template.yaml)
  /trading-app/trading-mode         → paper
  /trading-app/profit-mode          → cash_intraday
  /trading-app/trade-scope          → holdings_only
  /trading-app/daily-goal           → 100
  /trading-app/daily-loss-limit     → 200
  /trading-app/daily-trade-limit    → 3
  /trading-app/max-position-size-pct → 20

SSM Parameter Store (SecureString — fetched at Lambda cold start by ssm_service.py):
  /trading-app/anthropic-key        → Anthropic API key
  /trading-app/finnhub-key          → Finnhub API key
  /trading-app/schwab-client-id     → Schwab OAuth client ID
  /trading-app/schwab-client-secret → Schwab OAuth client secret
  /trading-app/private-api-key      → UUID shared secret (x-api-key header for private Lambda)

Secrets Manager (DeletionPolicy: Retain on all — sam deploy never resets values):
  /trading-app/schwab-token         → Schwab OAuth token JSON (written/rotated by schwab_service.py)
  /trading-app/robinhood-session    → Robinhood session pickle base64 (written by robinhood_service._save_session())
  /trading-app/robinhood-credentials → {"username": "...", "password": "..."} — NOT CF-managed
                                        (removed from template.yaml to prevent sam deploy resets)
```

**IAM policy split:**
- `SchwabSecretsPolicy` — GetSecretValue + PutSecretValue on Schwab token only. Assigned to public Lambda and all scheduled functions.
- `RobinhoodSecretsPolicy` — GetSecretValue on robinhood-credentials, GetSecretValue + PutSecretValue on robinhood-session. Assigned to private Lambda and DailyRefreshLiveBriefingFunction only.

---

## S3 + CloudFront Frontend Hosting

### Two S3 buckets — one per deployment:
```
trading-dashboard-public   → your-public-domain.com (public demo)
trading-dashboard-private  → your-private-domain.com (personal)
```

### CloudFront distributions — one per bucket:
- SSL via AWS Certificate Manager (free)
- Global CDN distribution
- Cache invalidation on every deploy

### CI/CD — GitHub Actions builds and deploys:
```yaml
# Three parallel jobs: backend, frontend-public, frontend-private
# Authentication: GitHub OIDC → IAM role (no long-lived access keys)

# backend job
- sam build && sam deploy --no-confirm-changeset --no-fail-on-empty-changeset

# frontend-public job (runs after backend)
- name: Build public frontend
  run: cd frontend && npm ci && npm run build
  env:
    VITE_API_URL: ${{ secrets.PUBLIC_API_URL }}
    VITE_PORTFOLIO_MODE: synthetic
    # No VITE_API_KEY — public Lambda requires no auth header
- aws s3 sync frontend/dist s3://trading-dashboard-public --delete
- aws cloudfront create-invalidation --distribution-id ${{ secrets.PUBLIC_CF_DIST_ID }} --paths "/*"

# frontend-private job (runs after backend)
- name: Build private frontend
  run: cd frontend && npm ci && npm run build
  env:
    VITE_API_URL: ${{ secrets.PRIVATE_API_URL }}
    VITE_PORTFOLIO_MODE: live
    VITE_API_KEY: ${{ secrets.PRIVATE_API_KEY }}    # injects x-api-key header on all requests
- aws s3 sync frontend/dist s3://trading-dashboard-private --delete
- aws cloudfront create-invalidation --distribution-id ${{ secrets.PRIVATE_CF_DIST_ID }} --paths "/*"
```

**Note:** `VITE_API_KEY` line is pending (Step 5 of two-lambda implementation). `deploy.yml` does not yet include it.

Every push to `main` (touching `backend/`, `frontend/`, `template.yaml`, or `samconfig.toml`) deploys both versions automatically.

---

## Cloudflare Configuration

### Public version (your-public-domain.com):
- DNS CNAME → CloudFront distribution URL (via Porkbun registrar)
- Rate limiting: 30 requests/min per IP → block 1 hour
- Bot Fight Mode: on
- DDoS protection: on (automatic, free)

### Personal version (your-private-domain.com):
- DNS CNAME → CloudFront distribution URL (via Porkbun registrar)
- Cloudflare Access application:
  - Authentication: One-time PIN to owner email
  - Policy: allow owner email address only
  - Everyone else: blocked
- No rate limiting needed (personal use only)

---

## Project Structure
```
trading-dashboard/
├── backend/
│   ├── main.py                          # FastAPI app + all Lambda handlers
│   ├── routers/
│   │   ├── ai.py                        # Briefing + chat + suggestions
│   │   ├── guardrails.py
│   │   ├── live_tracking.py
│   │   ├── market.py
│   │   ├── paper_trading.py
│   │   ├── portfolio.py
│   │   ├── scanner.py
│   │   └── sentiment.py
│   ├── services/
│   │   ├── cache_service.py             # DynamoDB cache read/write + scheduled handlers
│   │   ├── claude_service.py            # claude-sonnet-4-6 API calls
│   │   ├── context_loader.py            # full daily context assembly (called before every Claude call)
│   │   ├── dynamo_service.py
│   │   ├── finnhub_service.py
│   │   ├── guardrail_service.py         # 8 guardrails, same code path paper+live
│   │   ├── live_tracking_service.py
│   │   ├── market_data_service.py
│   │   ├── paper_trading_service.py
│   │   ├── portfolio_factory.py         # switches provider based on PORTFOLIO_MODE
│   │   ├── robinhood_service.py         # read-only, session token via Secrets Manager
│   │   ├── schwab_service.py            # OAuth client singleton, batch quotes, movers
│   │   ├── ssm_service.py               # fetches SecureString params at cold start
│   │   └── synthetic_portfolio.py       # static dict, fictional holdings
│   ├── models/
│   │   └── schemas.py
│   ├── tests/
│   │   └── test_guardrails.py           # 14 tests — all passing (Phase 1 gate)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ChatPanel.jsx            # suggest-trades + chat + paper trade entry
│   │   │   ├── DailySummaryPanel.jsx    # morning briefing
│   │   │   ├── GuardrailsPanel.jsx
│   │   │   ├── LiveTrackingPanel.jsx
│   │   │   ├── PaperTradingPanel.jsx
│   │   │   ├── PortfolioView.jsx
│   │   │   ├── ScannerPanel.jsx
│   │   │   └── SentimentFeed.jsx
│   │   ├── utils/
│   │   │   └── api.js                   # apiFetch() — injects x-api-key on private build
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── package.json
│   └── vite.config.js
├── .github/
│   └── workflows/
│       └── deploy.yml
├── template.yaml                        # AWS SAM template — at repo root, NOT in backend/
├── samconfig.toml                       # SAM deploy config — at repo root
├── two-lambda-implementation.md         # active implementation plan (in progress)
├── .env.local                           # gitignored — local dev secrets
└── README.md
```

---

## Lambda Functions (template.yaml)

| Function | Handler | Trigger | Policies | Notes |
|----------|---------|---------|----------|-------|
| `TradingDashboardFunction` | `main.handler` | Lambda Function URL + API Gateway | Dynamo + SchwabSecrets + SsmApiKeys | Public, `PORTFOLIO_MODE=synthetic` from SSM |
| `TradingDashboardPrivateFunction` | `main.handler` | Lambda Function URL | Dynamo + SchwabSecrets + RobinhoodSecrets + SsmApiKeys | Private, `PORTFOLIO_MODE=live` hardcoded, `PRIVATE_API_KEY` from SSM |
| `PriceMonitorFunction` | `main.price_monitor_handler` | EventBridge every 1 min (9:00–4:59pm ET) | Dynamo + SchwabSecrets + SsmApiKeys | Auto-closes paper trades at target/stop |
| `EndOfDayFunction` | `main.end_of_day_handler` | EventBridge 3:45pm ET | Dynamo + SchwabSecrets + SsmApiKeys | Closes all open paper trades |
| `DailyRefreshFunction` | `main.refresh_handler` | EventBridge 9:35am ET Mon-Fri | Dynamo + SchwabSecrets + SsmApiKeys | Scanner + sentiment + synthetic briefing → DDB |
| `DailyRefreshLiveBriefingFunction` | `main.refresh_live_briefing_handler` | EventBridge 9:35am ET Mon-Fri | Dynamo + SchwabSecrets + RobinhoodSecrets + SsmApiKeys | Live briefing with real Robinhood context → DDB |
| `AnalyticsFunction` | `main.analytics_handler` | EventBridge nightly | Dynamo + SsmApiKeys | Phase 2 stub — not active |

All functions: Python 3.13, `CodeUri: backend/`, globals inject SSM-resolved env vars.

---

## Schemas (`models/schemas.py`)

```python
class TradeSetup(BaseModel):
    ticker: str
    direction: str                    # "long" | "short"
    trade_type: str                   # "intraday_cash" | "swing" | "partial_trim"
    profit_mode: str
    entry_price: float
    target_price: float
    stop_loss: float
    shares: int
    expected_gain: float
    max_loss: float
    reward_risk_ratio: float          # minimum 1.5
    confidence: str                   # "high" | "medium" | "low"
    rationale: str
    setup_type: str
    uses_existing_holding: bool
    cost_basis: float | None
    current_unrealized_pnl: float | None
    avg_daily_range_pct: float | None
    robinhood_instructions: str       # plain english steps for manual placement
    ml_probability: float | None      # Phase 2
    ml_calibration_note: str | None   # Phase 2

class TradeSuggestionResponse(BaseModel):
    goal: float
    profit_mode: str
    trade_scope: str
    suggestions: list[TradeSetup]
    risk_note: str
    market_conditions: str
    intraday_viability: str | None
    recommended: TradeSetup | None
    guardrails_checked: list[str]
    any_guardrail_triggered: bool

class DailyCashSummary(BaseModel):
    date: str
    goal: float
    realized_pnl: float
    open_positions: int
    goal_hit: bool
    goal_hit_time: str | None
    settlement_note: str
    trading_mode: str

class ValidationResult(BaseModel):      # Phase 2
    date: str
    paper_pnl: float
    spy_equivalent_pnl: float
    random_baseline_pnl: float
    slippage_adjusted_pnl: float
    claude_beat_spy: bool
    claude_beat_random: bool
    slippage_cost: float
    market_regime: str

class AnalyticsResult(BaseModel):       # Phase 2
    date_range: str
    monte_carlo_runs: int
    prob_hit_daily_goal: float
    prob_net_positive_month: float
    expected_monthly_pnl: float
    fifth_percentile_monthly: float
    ninetyfifth_percentile_monthly: float
    win_rate: float
    avg_win: float
    avg_loss: float
    expectancy_per_trade: float
    sharpe_ratio: float
    max_drawdown: float
    longest_losing_streak: int
    kelly_criterion_pct: float
    best_conditions: dict
    worst_conditions: dict
    equity_curve_chart_url: str
    pnl_distribution_chart_url: str
```

---

## Guardrails — 8 Rules, Same Code Path Paper and Live

1. Daily Loss Limit (default $200)
2. Max Position Size (default 20% of cash)
3. Cost Basis Protection (no selling below basis unless allow_loss=true)
4. Reward/Risk Minimum (no suggestion below 1.5)
5. Daily Trade Limit (default 3)
6. Market Hours Lock (9:30am-4pm ET only)
7. Buying Power Check (verify cash/shares before suggestion)
8. Kill Switch (closes paper trades, flags live trades for manual close)

### 14 Guardrail Tests — all passing, required before TRADING_MODE=live
```python
def test_daily_loss_limit_blocks_new_trades()
def test_daily_loss_limit_does_not_trigger_prematurely()
def test_position_size_cap_enforced_server_side()
def test_cost_basis_protection_blocks_loss_suggestion()
def test_cost_basis_protection_allows_with_flag()
def test_kill_switch_closes_all_open_paper_trades()
def test_kill_switch_flags_live_trades_for_manual_close()
def test_kill_switch_requires_confirmation()
def test_reward_risk_minimum_rejects_bad_suggestions()
def test_market_hours_lock_prevents_after_hours_suggestions()
def test_intraday_suggestion_blocked_under_60_min_remaining()
def test_daily_trade_limit_blocks_at_threshold()
def test_buying_power_check_blocks_oversized_suggestion()
def test_guardrails_same_code_path_paper_and_live()
```

---

## AI System Prompts

### Morning Briefing
```
You are a personal trading analyst assistant for a retail day trader.
You will receive a JSON payload containing: scanner results, top intraday
movers, sentiment scores, portfolio holdings with cost basis and unrealized
P&L, available cash balance, logged trades today, realized P&L today,
guardrail status, and minutes remaining in the trading session.

Current settings:
- Profit mode: {profit_mode}
- Trade scope: {trade_scope}
- Daily goal: ${goal_dollars}

Produce a concise morning briefing:
1. Overall market conditions and intraday volatility today
2. Whether today supports the ${goal_dollars} goal safely
3. Top setups — constrained to trade_scope
4. Key risks
5. Holdings overlapping with today's setups
6. Honest assessment — if today looks poor for trading, say so

If profit_mode is cash_intraday, assess average daily range viability.
Never suggest selling below cost basis unless allow_loss is true.
Plain text only, no markdown.
```

### Chat / Trade Suggestion
```
You are a personal trading analyst assistant. Full daily context is in
the payload including scanner results, intraday movers, sentiment,
portfolio with cost basis, cash balance, trade history, realized P&L,
guardrail status, and minutes remaining in session.

Current settings:
- Profit mode: {profit_mode}
- Trade scope: {trade_scope}
- Daily goal: ${goal_dollars}

When generating trade suggestions:
- Respect trade_scope strictly
- Respect profit_mode:
  * cash_intraday: entry AND exit must happen today. Only suggest stocks
    with sufficient avg_daily_range_pct. Do not suggest with < 60 min left.
  * swing: overnight holds acceptable
  * holdings: partial trims and rebuys only
- Calculate position sizes from available cash and shares owned
- Only suggest reward/risk >= 1.5
- Always state stop loss clearly
- Never suggest selling below cost basis unless allow_loss is true
- Populate robinhood_instructions with exact plain english steps including
  the 3:45pm alarm reminder
- Return TradeSuggestionResponse JSON exactly
- If no clean setup exists return recommended: null

Never force a trade to hit the goal by taking disproportionate risk.
```

---

## DynamoDB Single-Table Design

One table (`trading-dashboard`), three item types sharing the same GSI (`status-date-index`):
- **Trades**: `status` = `open` | `closed` | `live`
- **Cache**: `trade_id` = `"cache#scanner"` | `"cache#sentiment"` | `"cache#briefing"` | `"cache#briefing_live"`, `status` = `"cache"`
- **Guardrail events**: `status` = `"guardrail_event"`

Cache freshness is ET-date-based (not TTL). `cache_service._cache_is_fresh()` compares `cached_at` ISO timestamp to today's ET date.

---

## Key Code Patterns

### Backend layer contract
Routers call services. Services never call routers. `context_loader.load_context()` is the single assembly point for the full market snapshot — called before every Claude API interaction (briefing, chat, suggest-trades).

### Portfolio factory
```python
# backend/services/portfolio_factory.py
def get_provider(mode: str | None = None):
    resolved = (mode or os.environ.get("PORTFOLIO_MODE", "synthetic")).lower()
    if resolved == "live":
        from services import robinhood_service
        return robinhood_service
    from services import synthetic_portfolio
    return synthetic_portfolio
```

### Schwab client singleton
`schwab_service._get_client()` initializes once per process. Lambda: token read/write via Secrets Manager (`SCHWAB_TOKEN_SECRET_ARN` env var). Local dev: token file at `backend/schwab_token.json` (gitignored).

### API key middleware (private Lambda only)
```python
# backend/main.py
_PRIVATE_API_KEY = os.environ.get("PRIVATE_API_KEY")

if _PRIVATE_API_KEY:
    @app.middleware("http")
    async def require_api_key(request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path == "/health":
            return await call_next(request)
        if request.headers.get("x-api-key") != _PRIVATE_API_KEY:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
        return await call_next(request)
```
Inert on the public Lambda (no `PRIVATE_API_KEY` env var set).

### Frontend API utility
```javascript
// frontend/src/utils/api.js
const BASE = import.meta.env.VITE_API_URL || '/api'
const KEY  = import.meta.env.VITE_API_KEY  || ''
const defaultHeaders = KEY ? { 'x-api-key': KEY } : {}

export function apiFetch(path, options = {}) {
  const headers = { ...defaultHeaders, ...(options.headers || {}) }
  return fetch(`${BASE}${path}`, { ...options, headers })
}
export const API = BASE
```
All 8 components use `apiFetch()`. Private build injects `VITE_API_KEY` at build time.

---

## Build Order

### Phase 1 ✅ COMPLETE
1. ✅ `main.py` + Mangum handler + health check
2. ✅ `schwab_service.py` + scanner router + movers
3. ✅ `synthetic_portfolio.py` + `robinhood_service.py` + `portfolio_factory.py`
4. ✅ `portfolio.py` router + position enrichment with cost basis
5. ✅ `finnhub_service.py` + sentiment router
6. ✅ `guardrail_service.py` — all 8 guardrails
7. ✅ `tests/test_guardrails.py` — all 14 tests passing
8. ✅ `context_loader.py` — full daily context assembly
9. ✅ `schemas.py` — all Phase 1 models
10. ✅ `claude_service.py` + `/ai/briefing` endpoint
11. ✅ `/ai/chat` + `/ai/suggest-trades` endpoints
12. ✅ `paper_trading_service.py` + paper trading endpoints
13. ✅ `live_tracking_service.py` + live trade logging endpoints
14. ✅ React frontend — scanner, sentiment, portfolio panels
15. ✅ `DailySummaryPanel.jsx`
16. ✅ `ChatPanel.jsx` — suggestion cards + RH instructions
17. ✅ `PaperTradingPanel.jsx` — 3 tabs
18. ✅ `LiveTrackingPanel.jsx`
19. ✅ `GuardrailsPanel.jsx`
20. ✅ DynamoDB caching layer (`cache_service.py`)
21. ✅ AWS SAM deploy — Lambda functions + S3 + CloudFront
22. ✅ GitHub Actions CI/CD — OIDC role, three parallel jobs
23. ✅ Cloudflare DNS + rate limiting (public) + Access auth (private)
24. ✅ README + architecture diagram

### Two-Lambda Infrastructure Split (in progress — see two-lambda-implementation.md)
- ✅ Step 1 — UUID API key generated, stored in SSM as `/trading-app/private-api-key`
- ✅ Step 2 — `template.yaml`: SecretsPolicy split, TradingDashboardPrivateFunction added, DailyRefreshLiveBriefingFunction added
- ✅ Step 3 — `main.py` x-api-key middleware
- ⬜ Step 4b — Migrate 8 frontend components to `apiFetch` (Step 4a done: `utils/api.js` exists)
- ⬜ Step 5 — `deploy.yml` `VITE_API_KEY` line
- ⬜ Step 6 — Add `PRIVATE_API_KEY` GitHub Secret (do before pushing)
- ⬜ Step 7 — `sam deploy`, capture `PrivateFunctionUrl`, update `PRIVATE_API_URL` secret
- ⬜ Step 8 — Verification

### Phase 2
25. `validation_service.py` + validation endpoints
26. `analytics_service.py` + analytics endpoints
27. `sagemaker/feature_engineering.py`
28. `sagemaker/train.py` + initial model training
29. `sagemaker/inference.py` + Serverless endpoint
30. `sagemaker_service.py` — predictions (observe only)
31. Analytics Lambda + S3 charts bucket
32. Weekly SageMaker training EventBridge rule
33. `ValidationPanel.jsx`
34. `AnalyticsPanel.jsx` — 6 tabs + Plotly charts
35. Add `ml_probability` to suggestion cards (labeled calibrating)
36. `tests/test_validation.py` + `tests/test_analytics.py`
37. Second paper trading cycle — 4-6 weeks

### Phase 3
38. Switch TRADING_MODE=live
39. Manual execution via Robinhood, log in LiveTrackingPanel
40. SageMaker calibration tracking
41. 25% position sizes for 2-4 weeks

### Phase 4
42. ML probability into Claude context (after calibration > 65%)
43. Alpaca integration for auto-execution (optional)
44. Scale to full position sizes

---

## Transition Checklists

### Phase 1 → Phase 2
```
✅ 4-6 weeks paper trading data
✅ Basic win rate and P&L metrics stable
✅ All 14 guardrail tests passing
✅ Daily workflow established
✅ 3:45pm alarm habit consistent
```

### Phase 2 → Phase 3
```
□ Second paper cycle complete (4-6 weeks)
□ Win rate > 55%
□ Avg reward/risk > 1.5
□ Claude beats SPY > 60% of days
□ Claude beats random picks > 60% of days
□ Slippage-adjusted P&L still hits daily goal
□ Monte Carlo: net positive month probability > 70%
□ Conditions analysis reviewed — guardrails refined
□ SageMaker predictions visible in dashboard
□ All 14 guardrail tests still passing
□ Starting at 25% position sizes
```

### Phase 3 → Phase 4
```
□ 2-4 weeks live trading at 25% size
□ Live results align with validated paper results
□ SageMaker calibration score > 65%
□ Comfortable with real money psychological pressure
□ Ready to scale position sizes
```

---

## AWS Services Used (Resume / Portfolio)
```
Compute:      Lambda (7 functions), API Gateway (legacy fallback)
Storage:      S3 (3 buckets), DynamoDB
CDN:          CloudFront (2 distributions)
Scheduler:    EventBridge
Security:     IAM (OIDC deploy role, scoped execution roles), SSM Parameter Store (SecureString), Secrets Manager, KMS
IaC:          SAM (CloudFormation)
CI/CD:        GitHub Actions (OIDC, no long-lived keys)
External:     Cloudflare (DNS, CDN security, Access auth), Porkbun (registrar)
ML:           SageMaker (Phase 2)
```

---

## Estimated Monthly Cost

| Service | Phase 1 | Phase 2 | Phase 3-4 |
|---|---|---|---|
| Lambda + API Gateway | $0 | $0 | $0 |
| DynamoDB | $0 | $0 | $0 |
| S3 (3 buckets) | ~$0 | ~$0.01 | ~$0.01 |
| CloudFront (2 distros) | $0 | $0 | $0 |
| EventBridge | $0 | $0 | $0 |
| SageMaker | $0 | ~$2-5 | ~$5-10 |
| Cloudflare | $0 | $0 | $0 |
| Custom domain | ~$1 | ~$1 | ~$1 |
| **Total** | **~$1/mo** | **~$4-7/mo** | **~$6-12/mo** |

---

## Key Constraints (always enforce)
- **Never commit** `.env.local` or `schwab_token.json` — both gitignored
- **`TRADING_MODE=live`** requires explicit user confirmation before switching
- **Live trades are never auto-closed** — price monitor and EOD handler flag them; user closes manually in Robinhood
- **black line length is 100** — CI lint uses `--line-length=100`; default 88 will fail
- **`sam build` runs from repo root** — `template.yaml` is there, not in `backend/`
- **`pytest` needs `working-directory: backend`** — service imports only resolve from `backend/`
- **`claude-sonnet-4-6`** — do not downgrade the model

---

## Future Considerations

- **Native CloudFormation IaC practice:** SAM generates and deploys CloudFormation under the hood. At some point, consider writing infrastructure directly in native CloudFormation (without SAM abstractions) as a hands-on IaC exercise — useful for AWS SAA-C03 depth and portfolio.
- **Lambda vs. Batch (confirmed: Lambda):** All functions are correctly Lambda. The heaviest is the nightly Analytics Lambda (Phase 2, 5-min timeout, 1024MB). At personal-trader scale, NumPy/Pandas/SciPy operations complete well under the timeout. Only revisit if the Analytics Lambda actually times out in production. SageMaker handles heavy ML training.
- **Trade scope expansion:** `TRADE_SCOPE=holdings_only` currently restricts suggestions to existing holdings. Changing to `open` or `both` will allow Claude to suggest entries from the daily scanner. Do after verifying real portfolio data flows correctly through the private Lambda.
