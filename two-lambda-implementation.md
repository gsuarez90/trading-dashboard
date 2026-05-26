# Two-Lambda Implementation Guide

Implements Option 1 from `portfolio-mode-separation.md`: separate public (synthetic) and private (live Robinhood) Lambda functions with IAM-level isolation. The private API is protected by a shared secret validated in FastAPI middleware.

**Outcome:**
- `ait.gsuarez.dev` → Public API Gateway → `TradingDashboardFunction` (synthetic, no Robinhood IAM)
- `degen.gsuarez.dev` → Private API Gateway → `TradingDashboardPrivateFunction` (live, Robinhood IAM)
- Public Lambda is IAM-blocked from Robinhood credentials at the policy level
- Private API requires `x-api-key` header on every request; invalid key returns 401

**What does NOT change:** Porkbun, Cloudflare DNS, Cloudflare Access, CloudFront distributions, S3 buckets, DynamoDB, GitHub OIDC role. All frontend domain names and CF Access configuration remain identical.

---

## Implementation Status

Backend code changes are complete and committed. AWS infrastructure (Steps 1–8) is pending.

| Item | Status |
|------|--------|
| `cache_service.py` — `get_cached_live_briefing()`, `store_live_briefing()`, `run_live_briefing_refresh()` | ✅ Done |
| `ai.py` — `get_briefing()` branches on `PORTFOLIO_MODE`, returns cache-or-null on both paths | ✅ Done |
| `main.py` — `refresh_live_briefing_handler`, `x-api-key` added to CORS `allow_headers` | ✅ Done |
| Pre-Task — Investigate portfolio null values on first load | ✅ Done — root cause: `_write(token)` missing `**kwargs` caused TypeError on Schwab token refresh, silently aborting `_enrich_positions()`. Fixed in commit `be30e97`. |
| Step 1 — Generate UUID API key, store in SSM | ⬜ Pending |
| Step 2 — `template.yaml` IAM split + private function + DailyRefreshLiveBriefingFunction | ⬜ Pending |
| Step 3 — `main.py` API key middleware | ⬜ Pending |
| Step 4a — `frontend/src/utils/api.js` — `apiFetch` utility with trailing-slash strip | ✅ Done |
| Step 4b — Update 8 components to use `apiFetch` | ⬜ Pending — all 8 components still use `const API = import.meta.env.VITE_API_URL` |
| Step 5 — `deploy.yml` `VITE_API_KEY` line | ⬜ Pending |
| Step 6 — GitHub Secrets | ⬜ Pending |
| Step 7 — `sam deploy` + capture private API URL | ⬜ Pending |
| Step 8 — Verification | ⬜ Pending |

---

## Data Flow: Public vs Private

What each URL actually calls, what's real, and what's static — broken down by service and endpoint.

### Summary

| Data | Public URL (synthetic) | Private URL (live) |
|------|----------------------|-------------------|
| Portfolio — cash & equity | **Static**: $31,485.40 cash / $82,000 equity | **Live**: real Robinhood account balance |
| Portfolio — positions | **Static**: NVDA 10sh, MSFT 25sh, AAPL 30sh, AMZN 15sh, GOOGL 20sh (fictional avg costs) | **Live**: real Robinhood holdings |
| Position current prices | **Real**: Schwab batch quote API called for the 5 synthetic tickers | **Real**: Schwab batch quote API called for real holdings |
| Scanner / top movers | **Real**: DynamoDB cache (Schwab data written by DailyRefreshFunction at 9:35 AM) | **Real**: same DynamoDB cache |
| Sentiment scores | **Real**: DynamoDB cache (Finnhub data written by DailyRefreshFunction) | **Real**: same DynamoDB cache |
| Morning briefing | **Real**: DynamoDB cache (`"briefing"` key, Claude-generated at 9:35 AM by `DailyRefreshFunction`) | **Real**: DynamoDB cache (`"briefing_live"` key, Claude-generated at 9:35 AM by `DailyRefreshLiveBriefingFunction` with real Robinhood context) |
| Paper trades | **Real**: shared DynamoDB table | **Real**: same shared DynamoDB table |
| Guardrail events | **Real**: shared DynamoDB table | **Real**: same shared DynamoDB table |
| Chat (Claude) | **Real API call**: Claude reasons about synthetic portfolio + real market data | **Real API call**: Claude reasons about live Robinhood portfolio + real market data |
| Suggest-trades (Claude) | **Real API call**: suggestions based on synthetic cash/positions | **Real API call**: suggestions based on real cash/positions |
| Robinhood credentials | **Never accessed** (IAM blocked) | **Fetched from Secrets Manager** at cold start |

---

### Portfolio

**Public (`synthetic_portfolio.py`):**

`load_context()` calls `portfolio_factory.get_provider()` → returns `synthetic_portfolio` → `get_portfolio()` returns a hardcoded in-memory dict:

```python
{
    "cash": 31485.40,
    "equity": 82000.00,
    "positions": [
        {"ticker": "NVDA", "shares": 10.0, "avg_cost": 115.00, "current_price": None},
        {"ticker": "MSFT", "shares": 25.0, "avg_cost": 380.00, "current_price": None},
        {"ticker": "AAPL", "shares": 30.0, "avg_cost": 175.00, "current_price": None},
        {"ticker": "AMZN", "shares": 15.0, "avg_cost": 185.00, "current_price": None},
        {"ticker": "GOOGL", "shares": 20.0, "avg_cost": 165.00, "current_price": None},
    ]
}
```

`current_price` is `None` on return from `get_portfolio()` — it gets filled in by `_enrich_positions()` via the Schwab batch quotes call that follows.

No network call. Returns instantly.

**Private (`robinhood_service.py`):**

`get_portfolio()` calls `_login()` (Robinhood API, MFA on cold container) then calls Robinhood for profile data and open positions. Returns your actual account cash, equity, and real holdings.

**Position enrichment — both modes:**

After the portfolio is fetched, `_enrich_positions()` calls `schwab_service.get_batch_quotes(tickers)` with the position tickers to get real current prices. This is a **real Schwab API call** in both modes. On synthetic mode, Schwab is called for `["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL"]` — so the P&L shown on the public URL reflects real current prices applied to fictional position sizes.

---

### Scanner and Top Movers

Both Lambdas read from the same DynamoDB cache key `"scanner"`. The data was written by `DailyRefreshFunction` at 9:35 AM ET by calling `schwab_service.get_previous_day_movers()` — real Schwab market data.

If the cache is stale (weekend, before 9:35 AM, or cache miss), `load_context()` falls back to a live `schwab_service` call. This is the same behavior in both modes — neither Lambda has any synthetic fallback for scanner data.

---

### Sentiment

Same pattern as scanner. Both Lambdas read from `"sentiment"` in DynamoDB, written by `DailyRefreshFunction` via `finnhub_service.score_batch_sentiment()`. Real Finnhub data in both modes. Live fallback if cache is stale.

---

### Morning Briefing

Both Lambdas read from `"briefing"` in DynamoDB — a Claude-generated text block written by `DailyRefreshFunction`. Neither Lambda generates a new briefing on demand; if no cache exists, the `/ai/briefing` endpoint returns `{"briefing": null}` and the UI shows the market-closed message.

**Public URL:** The briefing comes from `DailyRefreshFunction` via the `"briefing"` DynamoDB cache key. `DailyRefreshFunction` has `PORTFOLIO_MODE=synthetic` (it only gets `SchwabSecretsPolicy`, not `RobinhoodSecretsPolicy`), so the cached briefing always uses fictional portfolio holdings. It is primarily useful for its market overview — scanner, movers, sentiment — rather than personalized account commentary.

**Private URL:** The briefing uses a separate `"briefing_live"` DynamoDB cache key. The endpoint behavior is identical to the public path: check cache, return it if fresh, return `{"briefing": null}` if missing. The frontend's existing market-closed handling applies on both URLs.

`DailyRefreshFunction` writes the synthetic `"briefing"` cache as before. `DailyRefreshLiveBriefingFunction` (added in Step 2g) runs on the same `cron(35 13 ? * MON-FRI *)` schedule, calls `run_live_briefing_refresh()`, and writes `"briefing_live"` with real Robinhood portfolio context.

Both endpoints return cache-or-null with no on-demand generation — same pattern on both URLs.

---

### Chat and Suggest-Trades

Both are real Claude API calls (`claude-sonnet-4-6`). The difference is the portfolio slice of the context passed to Claude:

**Public (what Claude sees):**
```
portfolio: { cash: $31,485, positions: [NVDA 10sh, MSFT 25sh, AAPL 30sh, ...] }  ← synthetic
scanner_results: [real movers from DDB cache]
sentiment: [real Finnhub scores from DDB cache]
trades_today: [real paper trades from DDB]
```

Claude gives advice about the fictional portfolio. Suggestions like "you have $31k in cash available" or "your NVDA position is up X%" use the fake numbers. The market data context (what's moving, sentiment) is real.

**Private (what Claude sees):**
```
portfolio: { cash: $XX,XXX actual, positions: [your real holdings] }  ← live Robinhood
scanner_results: [same real movers from DDB cache]
sentiment: [same real Finnhub scores from DDB cache]
trades_today: [same paper trades from DDB]
```

Claude gives advice about your real account. "You have $X in cash" and "your position in Y is at a $Z unrealized gain" are accurate.

---

### Paper Trades and Guardrails

Both Lambdas write to and read from the **same DynamoDB table**. There is no separation between public and private here. If you enter a paper trade from the public URL, it appears on the private URL and vice versa. Guardrail events are also shared.

This is intentional and has no user-visible consequence: the paper trading card and live tracking card are **not rendered on the public URL** (`ait.gsuarez.dev`). The public frontend does not include those components. The shared DynamoDB table is an implementation detail — no code changes are needed based on this fact, and the two-Lambda implementation does not alter it.

---

### DailyRefreshFunction and DailyRefreshLiveBriefingFunction

Two separate Lambdas run at 9:35 AM ET on weekdays. Neither is tied to the API.

**`DailyRefreshFunction`** (`SchwabSecretsPolicy` only, `PORTFOLIO_MODE=synthetic`):

| Step | Service called | Data written to DDB |
|------|---------------|-------------------|
| Get watchlist | Schwab movers API (market hours) or `_DEFAULT_TICKERS` | — |
| Scanner | `schwab_service.get_previous_day_movers()` | `"scanner"` cache key |
| Sentiment | `finnhub_service.score_batch_sentiment()` | `"sentiment"` cache key |
| Briefing | `load_context()` + `claude_service.morning_briefing()` | `"briefing"` cache key |

**`DailyRefreshLiveBriefingFunction`** (`SchwabSecretsPolicy` + `RobinhoodSecretsPolicy`, `PORTFOLIO_MODE=live`):

| Step | Service called | Data written to DDB |
|------|---------------|-------------------|
| Briefing | `load_context()` with real Robinhood portfolio + `claude_service.morning_briefing()` | `"briefing_live"` cache key |

The two functions run concurrently at 9:35 AM. Scanner and sentiment are written once by `DailyRefreshFunction` and shared by both public and private Lambdas. Each URL gets its own briefing cache key with portfolio context appropriate to its mode.

---

## Pre-Task — Portfolio Null Values on First Load

**Symptom:** On first load of `ait.gsuarez.dev`, the portfolio card shows `Price`, `Unrealized P&L`, and `%` as null/blank. After the first auto-refresh cycle the values populate correctly and stay populated.

**Why this matters before the two-Lambda work:** The private URL will show the same component with real Robinhood data. If the root cause is in `_enrich_positions()` or the Schwab batch quotes call, it affects both URLs equally. Better to fix it against the public URL (where it's reproducible and safe to debug) before adding live portfolio complexity.

**Likely root causes to investigate (in order of probability):**

1. **`_enrich_positions()` failing silently on cold Lambda** — `schwab_service.get_batch_quotes()` throws an exception on the first call (e.g., token not yet loaded, Schwab client not yet initialized), the exception is swallowed, and positions are returned with `current_price: None`. The second call succeeds because the Schwab client singleton is now warm.

2. **Frontend renders before the fetch resolves** — The portfolio component renders an initial empty/null state and doesn't handle `current_price: null` gracefully, showing blank instead of a loading indicator. The auto-refresh re-renders with populated data.

3. **`load_context()` Round 2 race condition** — `_enrich_positions()` runs in Round 2 of the `ThreadPoolExecutor`. If the portfolio endpoint returns the Round 1 result before Round 2 completes, prices are still None.

**Investigation steps:**

```powershell
# 1. Check if _enrich_positions() is throwing on cold start
# Open CloudWatch, filter public Lambda logs for first invocation of the day:
aws logs filter-log-events `
  --log-group-name "/aws/lambda/trading-dashboard-TradingDashboardFunction-XXXX" `
  --filter-pattern "enrich" `
  --limit 20

# 2. Hit the portfolio endpoint directly and check the response
$PUBLIC_URL = "https://YOUR-PUBLIC-API-URL"
curl "$PUBLIC_URL/portfolio/?mode=synthetic" | python -m json.tool

# 3. Hit it a second time immediately after — if prices now populate, the
#    Schwab client cold-start theory is confirmed
curl "$PUBLIC_URL/portfolio/?mode=synthetic" | python -m json.tool
```

**Expected fix direction:** If it's a cold-start Schwab failure, add a retry or null-guard in `_enrich_positions()` so it returns whatever prices it could fetch rather than propagating an exception. If it's a frontend render issue, add a loading/null state to the price and P&L columns so they show `—` instead of blank until data arrives.

**Update this section with findings before proceeding to Step 1.**

---

## Pre-Flight

Have these ready before starting:

- AWS CLI configured (`aws sts get-caller-identity` works)
- SAM CLI installed (`sam --version` works)
- Venv active in the repo root
- Access to GitHub repo Settings → Secrets
- The current `sam deploy` outputs (run `aws cloudformation describe-stacks --stack-name trading-dashboard --query "Stacks[0].Outputs"` to retrieve them)

---

## Step 1 — Generate the Private API Key

This key is a shared secret between the private Lambda and the private frontend build. Generate a random UUID:

```powershell
[System.Guid]::NewGuid().ToString()
```

Copy the output (e.g., `a3f8c1d2-4e5b-6789-abcd-ef0123456789`). You will use this value in Steps 2, 6, and 7. Treat it like a password — do not commit it anywhere.

Store it in SSM as a SecureString:

```powershell
aws ssm put-parameter `
  --name "/trading-app/private-api-key" `
  --value "YOUR-UUID-HERE" `
  --type "SecureString" `
  --description "Shared secret for private API Gateway authentication"
```

---

## Step 2 — `template.yaml` Changes

This is the largest change. Make the following edits in order.

### 2a. Split `SecretsPolicy` into two policies

Replace the single `SecretsPolicy` with two scoped policies. This is the core of the IAM isolation — the public Lambda will only receive `SchwabSecretsPolicy`.

**Remove:**
```yaml
SecretsPolicy:
  Type: AWS::IAM::ManagedPolicy
  Properties:
    PolicyDocument:
      Version: '2012-10-17'
      Statement:
        - Effect: Allow
          Action:
            - secretsmanager:GetSecretValue
            - secretsmanager:PutSecretValue
          Resource:
            - !Ref SchwabTokenSecret
            - !Sub 'arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:/trading-app/robinhood-credentials*'
            - !Ref RobinhoodSessionSecret
```

> **Why the ARN pattern instead of `!Ref`:** `RobinhoodCredentials` was removed from CloudFormation management so that `sam deploy` can never reset the secret value to the placeholder again (`DeletionPolicy: Retain` registered, then resource removed). The secret still exists in AWS — it's just no longer CF-owned. IAM policies reference it by hardcoded ARN with a trailing `*` to match the 6-character random suffix Secrets Manager appends to all secret ARNs.

**Replace with:**
```yaml
SchwabSecretsPolicy:
  Type: AWS::IAM::ManagedPolicy
  Properties:
    PolicyDocument:
      Version: '2012-10-17'
      Statement:
        - Effect: Allow
          Action:
            - secretsmanager:GetSecretValue
            - secretsmanager:PutSecretValue
          Resource:
            - !Ref SchwabTokenSecret

RobinhoodSecretsPolicy:
  Type: AWS::IAM::ManagedPolicy
  Properties:
    PolicyDocument:
      Version: '2012-10-17'
      Statement:
        - Effect: Allow
          Action:
            - secretsmanager:GetSecretValue
          Resource:
            - !Sub 'arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:/trading-app/robinhood-credentials*'
        - Effect: Allow
          Action:
            - secretsmanager:GetSecretValue
            - secretsmanager:PutSecretValue
          Resource:
            - !Ref RobinhoodSessionSecret
```

> **Gap vs. original plan:** The original plan only covered `RobinhoodCredentials`. `robinhood_service._restore_session()` needs `GetSecretValue` on `RobinhoodSessionSecret` and `_save_session()` needs `PutSecretValue` on it. Without this, session token persistence fails with `AccessDeniedException` and every private Lambda cold start requires a full re-login.

### 2b. Update `TradingHttpApi`

No name change — keeping this as the public API Gateway avoids recreating the resource and changing `PUBLIC_API_URL`. No edits needed here.

### 2c. Update `TradingDashboardFunction` (public)

Remove `SecretsPolicy` and replace with `SchwabSecretsPolicy`. The public Lambda now has zero IAM path to Robinhood credentials.

**Before:**
```yaml
TradingDashboardFunction:
  Type: AWS::Serverless::Function
  Properties:
    Handler: main.handler
    MemorySize: 1536
    Policies:
      - !Ref DynamoPolicy
      - !Ref SecretsPolicy
      - !Ref SsmApiKeysPolicy
```

**After:**
```yaml
TradingDashboardFunction:
  Type: AWS::Serverless::Function
  Properties:
    Handler: main.handler
    MemorySize: 1536
    Policies:
      - !Ref DynamoPolicy
      - !Ref SchwabSecretsPolicy
      - !Ref SsmApiKeysPolicy
```

### 2d. Add `TradingDashboardPrivateFunction`

Add this resource after the existing `TradingDashboardFunction` block. Uses a Lambda Function URL (same as the public Lambda) — no API Gateway needed. The private API key validation is handled by FastAPI middleware in Step 3, not at the gateway layer.

```yaml
TradingDashboardPrivateFunction:
  Type: AWS::Serverless::Function
  Properties:
    Handler: main.handler
    Timeout: 120
    MemorySize: 1536
    FunctionUrlConfig:
      AuthType: NONE
    Environment:
      Variables:
        PORTFOLIO_MODE: live
        PRIVATE_API_KEY: !Sub '{{resolve:ssm:/trading-app/private-api-key}}'
    Policies:
      - !Ref DynamoPolicy
      - !Ref SchwabSecretsPolicy
      - !Ref RobinhoodSecretsPolicy
      - !Ref SsmApiKeysPolicy
```

### 2e. Add `DailyRefreshLiveBriefingFunction`

Add this after the `DailyRefreshFunction` block. It runs on the same cron, calls `refresh_live_briefing_handler`, and gets both Schwab and Robinhood access so `load_context()` fetches the real portfolio:

```yaml
DailyRefreshLiveBriefingFunction:
  Type: AWS::Serverless::Function
  Properties:
    Handler: main.refresh_live_briefing_handler
    Timeout: 120
    MemorySize: 1536
    Environment:
      Variables:
        PORTFOLIO_MODE: live
    Policies:
      - !Ref DynamoPolicy
      - !Ref SchwabSecretsPolicy
      - !Ref RobinhoodSecretsPolicy
      - !Ref SsmApiKeysPolicy
    Events:
      DailyTrigger:
        Type: Schedule
        Properties:
          Schedule: cron(35 13 ? * MON-FRI *)
```

### 2f. Update scheduled functions — remove Robinhood access

`PriceMonitorFunction`, `EndOfDayFunction`, `DailyRefreshFunction`, and `AnalyticsFunction` all use `SecretsPolicy` today. Replace it with `SchwabSecretsPolicy` on each. These functions use Schwab for price quotes and token management, but never call Robinhood.

For each of the four scheduled functions, change:
```yaml
Policies:
  - !Ref DynamoPolicy
  - !Ref SecretsPolicy
  - !Ref SsmApiKeysPolicy
```
to:
```yaml
Policies:
  - !Ref DynamoPolicy
  - !Ref SchwabSecretsPolicy
  - !Ref SsmApiKeysPolicy
```

### 2g. Update `Outputs`

Add a `PrivateFunctionUrl` output alongside the existing `FunctionUrl`:

```yaml
PrivateFunctionUrl:
  Description: Private Lambda Function URL — use for PRIVATE_API_URL GitHub secret
  Value: !GetAtt TradingDashboardPrivateFunctionUrl.FunctionUrl
```

`FunctionUrl` (public) already exists from the Lambda Function URL migration. `ApiUrl` (legacy API Gateway) can be removed once the two-Lambda deploy is verified.

---

## Step 3 — `backend/main.py` Changes

Add a FastAPI middleware that validates the `x-api-key` header on the private Lambda. The middleware only activates when `PRIVATE_API_KEY` is set in the environment — so the public Lambda (which has no such env var) runs with zero overhead.

Add this block after the `app.add_middleware(CORSMiddleware, ...)` call and before `dynamo_service.ensure_table_exists()`:

> **Before adding:** check that `import os`, `from fastapi import Request`, and `from fastapi.responses import JSONResponse` are not already present at the top of `main.py`. They likely are — only add what is missing.

```python
import os
from fastapi import Request
from fastapi.responses import JSONResponse

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

**Why:** OPTIONS requests are pre-flight CORS checks — browsers send these before the real request and they must not require auth. The `/health` path is excluded so AWS health checks and your own diagnostics still work.

---

## Step 4 — Frontend: Central API Utility

Currently every component has its own `const API = import.meta.env.VITE_API_URL || '/api'` and calls `fetch()` directly. Create a single utility that injects the `x-api-key` header whenever `VITE_API_KEY` is set (private build only).

### 4a. Create `frontend/src/utils/api.js`

```javascript
const BASE = import.meta.env.VITE_API_URL || '/api'
const KEY  = import.meta.env.VITE_API_KEY  || ''

const defaultHeaders = KEY ? { 'x-api-key': KEY } : {}

export function apiFetch(path, options = {}) {
  const headers = { ...defaultHeaders, ...(options.headers || {}) }
  return fetch(`${BASE}${path}`, { ...options, headers })
}

export const API = BASE
```

### 4b. Update each component

In every component below, make two changes:
1. Replace `const API = import.meta.env.VITE_API_URL || '/api'` with the import line
2. Replace every `fetch(\`${API}/...`)` with `apiFetch('/...')`

> **Line numbers are approximate** — they were written before several edits this session. Read each file to find the actual locations rather than jumping directly to the listed line numbers.

**`ChatPanel.jsx`**
```javascript
// Remove:
const API = import.meta.env.VITE_API_URL || '/api'

// Add at top:
import { apiFetch } from '../utils/api'

// Replace all fetch(`${API}/...) with apiFetch('/...')
// Line ~23:  fetch(`${API}/paper-trades/`, ...)       → apiFetch('/paper-trades/', ...)
// Line ~142: fetch(`${API}/ai/suggest-trades`, ...)   → apiFetch('/ai/suggest-trades', ...)
// Line ~239: fetch(`${API}/ai/chat`, ...)             → apiFetch('/ai/chat', ...)
```

**`DailySummaryPanel.jsx`**
```javascript
// Remove: const API = import.meta.env.VITE_API_URL || '/api'
// Add:    import { apiFetch } from '../utils/api'
// Line ~15: fetch(`${API}/ai/briefing`) → apiFetch('/ai/briefing')
```

**`ScannerPanel.jsx`**
```javascript
// Remove: const API = import.meta.env.VITE_API_URL || '/api'
// Add:    import { apiFetch } from '../utils/api'
// Line ~15: fetch(`${API}/scanner/movers`) → apiFetch('/scanner/movers')
```

**`PortfolioView.jsx`**
```javascript
// Remove: const API = import.meta.env.VITE_API_URL || '/api'
// Add:    import { apiFetch } from '../utils/api'
// Line ~15: fetch(`${API}/portfolio/?mode=${MODE}`, ...) → apiFetch(`/portfolio/?mode=${MODE}`, ...)
```

**`SentimentFeed.jsx`**
```javascript
// Remove: const API = import.meta.env.VITE_API_URL || '/api'
// Add:    import { apiFetch } from '../utils/api'
// Line ~17: fetch(`${API}/ai/sentiment`) → apiFetch('/ai/sentiment')
```

**`GuardrailsPanel.jsx`**
```javascript
// Remove: const API = import.meta.env.VITE_API_URL || '/api'
// Add:    import { apiFetch } from '../utils/api'
// Line ~135: fetch(`${API}/guardrails/kill-switch?confirmed=true`, ...) → apiFetch('/guardrails/kill-switch?confirmed=true', ...)
// Line ~192: fetch(`${API}/guardrails/status`, ...)  → apiFetch('/guardrails/status', ...)
// Line ~193: fetch(`${API}/guardrails/events`, ...)  → apiFetch('/guardrails/events', ...)
```

**`PaperTradingPanel.jsx`**
```javascript
// Remove: const API = import.meta.env.VITE_API_URL || '/api'
// Add:    import { apiFetch } from '../utils/api'
// Line ~98:  fetch(`${API}/paper-trades/${trade.trade_id}/close`, ...) → apiFetch(`/paper-trades/${trade.trade_id}/close`, ...)
// Line ~314: fetch(`${API}/paper-trades/`, ...)         → apiFetch('/paper-trades/', ...)
// Line ~315: fetch(`${API}/paper-trades/pending`, ...)  → apiFetch('/paper-trades/pending', ...)
// Line ~316: fetch(`${API}/paper-trades/summary`, ...)  → apiFetch('/paper-trades/summary', ...)
```

**`LiveTrackingPanel.jsx`**
```javascript
// Remove: const API = import.meta.env.VITE_API_URL || '/api'
// Add:    import { apiFetch } from '../utils/api'
// Line ~113: fetch(`${API}/live-trades/${trade.trade_id}/exit`, ...) → apiFetch(`/live-trades/${trade.trade_id}/exit`, ...)
// Line ~277: fetch(`${API}/live-trades/`, ...)          → apiFetch('/live-trades/', ...)
// Line ~278: fetch(`${API}/live-trades/summary`, ...)   → apiFetch('/live-trades/summary', ...)
```

---

## Step 5 — GitHub Actions Workflow

Edit `.github/workflows/deploy.yml`. One change only — add `VITE_API_KEY` to the private frontend build step:

```yaml
- name: Build private frontend
  run: cd frontend && npm ci && npm run build
  env:
    VITE_API_URL: ${{ secrets.PRIVATE_API_URL }}
    VITE_PORTFOLIO_MODE: live
    VITE_API_KEY: ${{ secrets.PRIVATE_API_KEY }}    # ← add this line
```

No other changes to the workflow file.

---

## Step 6 — GitHub Secrets

Go to: **GitHub repo → Settings → Secrets and variables → Actions**

### Add new secret:
| Name | Value |
|------|-------|
| `PRIVATE_API_KEY` | The UUID you generated in Step 1 |

### Update after deploy (Step 7 outputs the new URL):
| Name | New value |
|------|-----------|
| `PRIVATE_API_URL` | Private API Gateway URL from SAM deploy output (`PrivateApiUrl`) |

`PUBLIC_API_URL` does **not** change — the public API Gateway (`TradingHttpApi`) keeps the same URL.

---

## Pre-Step 7 — Seed Robinhood Session Token into Secrets Manager

The `/trading-app/robinhood-session` secret must contain a valid session token before the first private Lambda cold start. Without it, `_restore_session()` finds nothing and `_login()` attempts a fresh Robinhood login — which requires interactive MFA that Lambda cannot provide.

**Check first:** If you completed an MFA login via the private URL today, `_save_session()` already wrote a fresh token to this secret. Verify:

```powershell
aws secretsmanager get-secret-value --secret-id /trading-app/robinhood-session `
  --query SecretString --output text | python -c "import sys,json; d=json.load(sys.stdin); print('token present:', bool(d.get('token')))"
```

If `token present: True`, skip this step — the secret is already seeded.

**If the secret is empty or missing**, seed from your local pickle file. Use `ConvertTo-Json` via a temp file to avoid JSON encoding issues with base64 padding characters:

```powershell
$tokenBytes = [System.IO.File]::ReadAllBytes("$env:USERPROFILE\.tokens\robinhood.pickle")
$tokenB64 = [Convert]::ToBase64String($tokenBytes)
$secret = @{ token = $tokenB64 } | ConvertTo-Json -Compress
$tmp = "$env:TEMP\rh_session.json"
[System.IO.File]::WriteAllText($tmp, $secret)
aws secretsmanager put-secret-value `
  --secret-id /trading-app/robinhood-session `
  --secret-string "file://$tmp"
Remove-Item $tmp
```

After this, the private Lambda's first cold start will restore the session and skip the MFA flow. The Lambda overwrites the secret with a fresh token after each successful login via `_save_session()`.

> **Token expiry:** The `device_token` inside the pickle is permanent. The `access_token` expires in 24h but `robin_stocks` handles refresh automatically using the stored refresh token. You only need to re-seed manually if the device is deregistered or the token file is lost.

---

## Step 7 — Deploy

### 7a. Run `sam deploy` from repo root

```powershell
sam build && sam deploy --no-confirm-changeset
```

SAM will show a changeset preview. Expect to see:
- `SecretsPolicy` → DELETE
- `SchwabSecretsPolicy` → ADD
- `RobinhoodSecretsPolicy` → ADD
- `TradingDashboardFunction` → MODIFY (policy change)
- `TradingDashboardPrivateFunction` → ADD
- `TradingDashboardPrivateFunctionUrl` → ADD
- `DailyRefreshLiveBriefingFunction` → ADD
- All other scheduled functions → MODIFY (policy change)

Estimated deploy time: 3–5 minutes.

### 7b. Capture the new private API URL

After deploy completes:

```powershell
aws cloudformation describe-stacks `
  --stack-name trading-dashboard `
  --query "Stacks[0].Outputs[?OutputKey=='PrivateFunctionUrl'].OutputValue" `
  --output text
```

Copy this URL — you'll paste it into `PRIVATE_API_URL` in GitHub Secrets (Step 6).

### 7c. Update `PRIVATE_API_URL` in GitHub Secrets

Paste the URL from 7b into the `PRIVATE_API_URL` secret. This is the only GitHub secret update required immediately after deploy.

---

## Step 8 — Post-Deploy Verification

Run these checks in order. Each one confirms a different layer of the implementation.

### 8a. Confirm Lambda environment variables

```powershell
# Public Lambda — should show PORTFOLIO_MODE=synthetic, no PRIVATE_API_KEY
aws lambda get-function-configuration `
  --function-name trading-dashboard-TradingDashboardFunction-XXXX `
  --query "Environment.Variables" --output json

# Private Lambda — should show PORTFOLIO_MODE=live, PRIVATE_API_KEY present
aws lambda get-function-configuration `
  --function-name trading-dashboard-TradingDashboardPrivateFunction-XXXX `
  --query "Environment.Variables" --output json
```

### 8b. Confirm IAM isolation — public Lambda cannot reach Robinhood

```powershell
# Should return AccessDeniedException for RobinhoodCredentials
aws lambda get-policy `
  --function-name trading-dashboard-TradingDashboardFunction-XXXX
```

Or more directly — invoke the public Lambda with a synthetic portfolio request and confirm no Robinhood calls appear in CloudWatch logs for `/aws/lambda/trading-dashboard-TradingDashboardFunction-*`.

### 8c. Test public API — no key required, synthetic portfolio

```powershell
$PUBLIC_URL = (aws cloudformation describe-stacks `
  --stack-name trading-dashboard `
  --query "Stacks[0].Outputs[?OutputKey=='PublicApiUrl'].OutputValue" `
  --output text)

# Health check
curl "$PUBLIC_URL/health"

# Should return synthetic portfolio (static data, no Robinhood)
curl "$PUBLIC_URL/portfolio/?mode=synthetic"
```

### 8d. Test private API — key required

```powershell
$PRIVATE_URL = "YOUR-PRIVATE-API-URL-FROM-STEP-7b"
$KEY = "YOUR-UUID-FROM-STEP-1"

# Without key — should return 401
curl "$PRIVATE_URL/health"

# With key — should return ok
curl -H "x-api-key: $KEY" "$PRIVATE_URL/health"

# With key — should return live portfolio (Robinhood data)
curl -H "x-api-key: $KEY" "$PRIVATE_URL/portfolio/?mode=live"
```

### 8e. Trigger the frontend deploy

Push any trivial change to main (or manually trigger the workflow) to rebuild both frontends:
- Public build: `VITE_API_KEY` not set → no `x-api-key` header on requests → works against public Lambda
- Private build: `VITE_API_KEY` set → all requests include `x-api-key` header → routes to private Lambda

### 8f. End-to-end browser test

**Public URL (`ait.gsuarez.dev`):**
- [ ] Chat responds ✓
- [ ] Get Suggestions responds ✓
- [ ] Portfolio shows synthetic data (static positions) ✓
- [ ] No Robinhood login in CloudWatch logs for public Lambda ✓

**Private URL (`degen.gsuarez.dev`):**
- [ ] Chat responds ✓
- [ ] Get Suggestions responds ✓
- [ ] Portfolio shows live Robinhood data ✓
- [ ] CloudWatch logs for private Lambda show Robinhood login on cold start ✓

---

## Porkbun

**No changes required.**

Porkbun is your domain registrar. The nameservers are already pointed at Cloudflare. Nothing about this implementation changes your domain registration or nameserver configuration.

---

## Cloudflare

**No DNS changes required.** The frontend domains (`ait.gsuarez.dev`, `degen.gsuarez.dev`) still point to the same CloudFront distributions. API Gateway URLs are direct AWS endpoints used internally in the frontend build — they are not Cloudflare DNS records.

**No Cloudflare Access changes required.** The CF Access application protecting `degen.gsuarez.dev` remains exactly as configured. The private frontend still loads behind email OTP. The private API URL is not exposed in DNS.

**CORS:** `main.py` already lists both frontend origins in `allow_origins`. Both Lambdas share the same code, so CORS configuration is identical on both. No changes needed.

---

## Rollback Plan

If the deploy breaks the public URL:

```powershell
# Immediately restore working Lambda env var
aws lambda update-function-configuration `
  --function-name trading-dashboard-TradingDashboardFunction-XXXX `
  --environment "Variables={PORTFOLIO_MODE=synthetic,...all other vars...}"
```

If the SAM deploy itself fails mid-way, CloudFormation will automatically roll back the changeset — the existing stack is restored to its previous state. No manual intervention needed.

---

## Post-Deploy Enhancement — Get Suggestions: Include Top Movers

**Context:** Top movers data from the scanner is already passed to Claude in every `suggest_trades()` call via `load_context()` → `scanner_results`. Claude can see them but is currently restricted from acting on them by the `TRADE_SCOPE=holdings_only` SSM parameter, which limits suggestions to existing portfolio holdings only.

**What to change after Step 8 is verified:**

1. Update the SSM parameter:
   ```powershell
   aws ssm put-parameter `
     --name "/trading-app/trade-scope" `
     --value "all" `
     --type "String" `
     --overwrite
   ```
   (Or use a new value like `holdings_and_movers` if the prompt already handles it — check `claude_service.py` `suggest_trades()` prompt for valid `TRADE_SCOPE` values before changing.)

2. Verify the prompt in `claude_service.py` surfaces the top movers as candidates when `TRADE_SCOPE` is not `holdings_only`. If it only lists position tickers as eligible, the prompt may need a small update to also enumerate the top 3–5 movers from `scanner_results` as potential new entries.

3. Test on the private URL — "Get Suggestions" should now include new-entry candidates from the scanner alongside existing holdings.

**Why this is a post-deploy item:** This is a prompt/config change, not infrastructure. Do it after the two-lambda deploy is confirmed working so portfolio data is real before tuning the suggestion behavior.

---

## Key Rotation

When you need to rotate the private API key:

1. Generate a new UUID
2. Update SSM: `aws ssm put-parameter --name "/trading-app/private-api-key" --value "NEW-UUID" --overwrite`
3. Update GitHub Secret `PRIVATE_API_KEY` to the new UUID
4. Run `sam deploy` (rebakes the key into the private Lambda env var)
5. Trigger a frontend deploy (rebuilds private frontend with new key in bundle)

The old key stops working as soon as the Lambda env var is updated by `sam deploy`.
