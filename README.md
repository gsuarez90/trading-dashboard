# AI Trading Dashboard

A personal AI-powered trading assistant that runs your daily workflow — morning market briefing, live scanner, sentiment analysis, paper trade logging, and conversational trade suggestions — all from a single dashboard. Built for one person, on real market data, with guardrails that prevent bad habits before live money is involved.

This is not a SaaS product. There are no other users, no subscriptions, no shared infrastructure. Every design decision optimizes for one thing: helping a single retail trader build a disciplined, data-driven daily process before switching from paper to live trading.

The app runs in two modes simultaneously. The **public version** uses a synthetic (fake) portfolio and is open to anyone — it demonstrates the tooling without exposing real account data. The **private version** connects to a real brokerage account and is locked behind Cloudflare Access, which blocks everyone except the owner via an email one-time-PIN login. Same code, same backend, different `PORTFOLIO_MODE` environment variable baked into the frontend build.

The philosophy: paper trade on real Schwab market data until the numbers prove it works — win rate above 55%, reward-to-risk above 1.5, beating the S&P 500 more than 60% of days. Claude assists with briefings, context, and suggestions, but never places orders. Every trade decision is manual. The guardrail system enforces rules automatically so discipline isn't optional on a bad day.

---

## Tech Stack

### Frontend

| Technology | Role |
|-----------|------|
| **React** | UI framework — components, state, rendering |
| **Vite** | Build tool — instant dev server via native ES modules; `npm run build` bundles for production |
| **AWS S3** | Hosts the built frontend files (two buckets: public and private) |
| **AWS CloudFront** | CDN — serves frontend files from edge locations worldwide, handles HTTPS |

React builds the interface as components (reusable pieces of UI). Vite is what runs and packages those components — it's significantly faster than older tools like Create React App because it doesn't bundle everything upfront during development. For production, `npm run build` outputs static HTML/CSS/JS files that get uploaded to S3 and distributed via CloudFront.

### Backend

| Technology | Role |
|-----------|------|
| **FastAPI** | Python web framework — handles HTTP requests, validates inputs, returns JSON |
| **Mangum** | Adapter — translates API Gateway's event format into something FastAPI understands |
| **AWS Lambda** | Serverless compute — runs the backend code on demand, no server to maintain |
| **AWS API Gateway (HTTP API)** | Receives HTTP requests from the internet and routes them to Lambda |
| **uvicorn** | Local dev only — runs FastAPI as a regular web server on port 8000 |

In production, a user's browser sends an HTTP request → API Gateway receives it → triggers Lambda → Lambda runs the FastAPI app (via Mangum) → returns a JSON response. In local dev, uvicorn replaces API Gateway + Lambda entirely and runs FastAPI directly. Mangum is the glue: an adapter is a translator that converts one thing's event format into another's without changing the underlying logic.

### Data & Storage

| Technology | What it stores |
|-----------|---------------|
| **AWS DynamoDB** | Trades, cache items (scanner/sentiment/briefing), guardrail events |
| **AWS SSM Parameter Store** | Non-secret config: trading mode, daily goal, loss limit, trade limits |
| **AWS Secrets Manager** | Sensitive credentials: Schwab OAuth token, Robinhood username/password, API keys |

DynamoDB is a NoSQL database — meaning data is stored as flexible key-value documents rather than rigid tables with fixed columns. This fits well here because trade records have many optional fields (not every trade has an exit price yet), and cache items look completely different from trade records but can share the same table.

SSM Parameter Store (Systems Manager) is AWS's service for storing configuration values. SecureString parameters are encrypted at rest using KMS (Key Management Service — AWS's encryption key service). Secrets Manager is for true secrets — credentials that need tighter IAM controls and potentially auto-rotation.

### External APIs

| Service | Purpose |
|---------|---------|
| **Schwab API** (`schwab-py`) | Real-time quotes, top movers across major indexes, OHLCV price history |
| **Finnhub** | News headlines for sentiment scoring |
| **Anthropic Claude API** | Morning briefing generation, conversational chat, structured trade suggestions |

The Schwab connection requires an OAuth token (like a session key) that the `schwab-py` library manages automatically — it refreshes the token when it expires and writes the updated token back to Secrets Manager.

### Infrastructure & Security

| Technology | Role |
|-----------|------|
| **AWS SAM** (`template.yaml`) | IaC — Infrastructure as Code. Describes the entire AWS stack in one YAML file |
| **GitHub Actions** (`deploy.yml`) | CI/CD — Continuous Deployment. Deploys automatically on every push to `main` |
| **Cloudflare** | Sits in front of CloudFront: rate limiting, DDoS protection, bot blocking |
| **Cloudflare Access** | Auth layer for the private version — email one-time-PIN login wall |

SAM (Serverless Application Model) means you never click around the AWS console to create resources — `template.yaml` is the single source of truth for what exists in AWS. Running `sam deploy` creates or updates everything. CI/CD means the deployment is automated: push code to GitHub, GitHub Actions runs `sam build && sam deploy` and syncs both frontends to S3 without any manual steps.

---

## Repository Structure

```
myAITradingApp/
│
├── backend/                          # FastAPI app — Lambda in production, uvicorn locally
│   ├── main.py                       # App entry point — registers all routers, defines Lambda handlers
│   │
│   ├── routers/                      # HTTP endpoint definitions — one file per feature area
│   │   ├── ai.py                     # GET /ai/briefing, GET /ai/sentiment, POST /ai/chat, POST /ai/suggest-trades
│   │   ├── scanner.py                # GET /scanner/movers, GET /scanner/results
│   │   ├── portfolio.py              # GET /portfolio/, GET /portfolio/cash
│   │   ├── paper_trading.py          # POST /paper-trades/, GET /paper-trades/, POST /{id}/close
│   │   ├── live_tracking.py          # GET /live-trades/, POST /live-trades/{id}/exit
│   │   ├── guardrails.py             # GET /guardrails/status, GET /guardrails/events, POST /guardrails/kill-switch
│   │   ├── market.py                 # Market data utility endpoints (quotes, news)
│   │   └── sentiment.py              # Legacy batch sentiment endpoint
│   │
│   ├── services/                     # Business logic — routers call these, never the reverse
│   │   ├── cache_service.py          # DynamoDB cache reads + all 3 Lambda scheduled job implementations
│   │   ├── claude_service.py         # Anthropic API calls — morning_briefing, chat, suggest_trades
│   │   ├── context_loader.py         # Assembles DailyContext — the full market snapshot sent to Claude
│   │   ├── dynamo_service.py         # All DynamoDB reads/writes — trades, cache, guardrail events
│   │   ├── finnhub_service.py        # Finnhub news fetch + VADER sentiment scoring
│   │   ├── guardrail_service.py      # 8 guardrail checks + status dashboard + kill switch
│   │   ├── live_tracking_service.py  # Live trade management (Phase 3)
│   │   ├── market_data_service.py    # Thin wrapper — delegates all calls to schwab_service
│   │   ├── paper_trading_service.py  # open_trade, close_trade, get_daily_summary
│   │   ├── portfolio_factory.py      # Selects robinhood_service or synthetic_portfolio by PORTFOLIO_MODE
│   │   ├── robinhood_service.py      # Live portfolio data from Robinhood (PORTFOLIO_MODE=live)
│   │   ├── schwab_service.py         # Schwab OAuth client — quotes, movers, price history
│   │   ├── ssm_service.py            # Runtime SSM SecureString fetch — API keys cached per Lambda container
│   │   └── synthetic_portfolio.py    # Fake portfolio data for public demo (no credentials needed)
│   │
│   ├── models/
│   │   └── schemas.py                # Pydantic data models — TradeSetup, PaperTrade, TradeSuggestionResponse
│   │
│   ├── tests/                        # Automated tests — run in CI on every pull request
│   │   ├── test_guardrails.py        # 14 guardrail tests — the hard gate before live trading
│   │   ├── test_paper_trading.py     # Paper trade open/close/summary tests
│   │   ├── test_live_tracking.py     # Live tracking tests
│   │   ├── test_dynamo_service.py    # DynamoDB service tests (mocked with moto)
│   │   └── test_schwab_service.py    # Schwab service integration tests
│   │
│   └── requirements.txt              # Python package dependencies
│
├── frontend/                         # React app — same source, two different production builds
│   └── src/
│       ├── App.jsx                   # Root component — assembles all panels into the dashboard
│       └── components/
│           ├── DailySummaryPanel.jsx   # Morning briefing — Claude's daily market analysis
│           ├── ScannerPanel.jsx        # Top movers table — auto-refreshes every 60 seconds
│           ├── PortfolioView.jsx       # Live positions with unrealized P&L — auto-refreshes every 90s
│           ├── SentimentFeed.jsx       # Bullish/bearish/neutral sentiment scores per ticker
│           ├── ChatPanel.jsx           # Conversational AI + trade suggestion cards + Paper Trade button
│           ├── PaperTradingPanel.jsx   # 3-tab panel: Open / History / Summary for paper trades
│           ├── LiveTrackingPanel.jsx   # Same 3-tab structure for live trades + mode notice banner
│           └── GuardrailsPanel.jsx     # Status cards for all 8 guardrails + events log + kill switch
│
├── cloudflare/
│   └── setup.md                      # Step-by-step Cloudflare DNS + Access configuration guide
│
├── .github/workflows/
│   ├── deploy.yml                    # On push to main: sam deploy + both S3 frontend syncs
│   ├── lint.yml                      # On PR: black + isort formatting checks
│   └── test-guardrails.yml           # On PR: runs all 14 guardrail tests
│
├── scripts/
│   ├── start.sh                      # Local dev startup — activates venv, loads .env.local, starts backend + frontend
│   └── schwab_auth.py                # One-time OAuth flow to generate schwab_token.json for local dev
│
├── template.yaml                     # SAM template — defines every AWS resource
├── samconfig.toml                    # SAM deploy defaults (region, stack name)
├── .env.example                      # Documents all required variables — safe to commit
├── .env.local                        # Your actual values — gitignored, never committed
└── notes.md                          # Running dev notes — architecture explanations, setup guides
```

---

## How the App Starts (Local Dev)

Run from the repo root:

```bash
bash scripts/start.sh
```

Then open `http://localhost:5173` in your browser.

Here is what the script does, in order:

**1. Activate the Python virtual environment**
If `VIRTUAL_ENV` is not already set, the script sources `backend/.venv/Scripts/activate`. This adds the venv's Python and all installed packages (FastAPI, schwab-py, boto3, etc.) to the shell's PATH. Without this, the system Python would be used and none of the dependencies would be found.

**2. Load `.env.local`**
The script uses `set -a` (auto-export) and `source .env.local` to load every variable as an environment variable available to all child processes. This is how `SCHWAB_CLIENT_ID`, `ANTHROPIC_API_KEY`, `PORTFOLIO_MODE`, and all other config values reach the Python process.

**3. Start uvicorn in the background**
```bash
uvicorn main:app --reload --port 8000
```
`--reload` means uvicorn watches Python files and restarts automatically when any file changes. The `&` runs it in the background so the script continues. The process ID is saved to cleanly kill uvicorn when the script exits.

**4. Wait for the backend to be ready**
The script polls `GET http://localhost:8000/health` in a loop, sleeping 1 second between attempts. This prevents Vite from starting before the backend can accept requests.

**5. Start Vite (blocks until Ctrl+C)**
```bash
cd frontend && npm run dev
```
Vite starts on port 5173. Any request to `/api/*` is proxied through Vite to `http://localhost:8000`, so the frontend can call `fetch('/api/portfolio/')` without hard-coding the backend URL. In production, the real API Gateway URL is baked into the Vite build via `VITE_API_URL`.

**6. Clean up**
When Ctrl+C is pressed, the signal goes to the whole process group. Uvicorn shuts down gracefully. This is what the "Shutting down / Application shutdown complete" messages in the terminal indicate — a clean stop, not a crash.

**What `main.py` does on startup:**
- Calls `load_dotenv()` which reads `.env.local` — this is a no-op in Lambda because Lambda injects environment variables directly
- Registers all 8 routers under their URL prefixes (`/scanner`, `/portfolio`, `/ai`, etc.)
- Calls `dynamo_service.ensure_table_exists()` in a `try/except` to create the DynamoDB table if needed (non-fatal)
- Creates the Mangum `handler` object that Lambda calls for every HTTP request

---

## Feature Flows

This section traces every feature from the moment you interact with the UI to the final result. File names and function names are included so you can find the code when something breaks.

---

### 1. Morning Briefing

```
Trigger:     Page loads — DailySummaryPanel mounts automatically
Frontend:    DailySummaryPanel.jsx
             useEffect → GET /api/ai/briefing on mount

Backend:     routers/ai.py → get_briefing()
               └─ cache_service.get_cached_briefing()
                    └─ dynamo_service.get_cache("briefing")
                    └─ Checks: cached_at date == today (ET timezone)

Cache HIT:   Returns {briefing, date} from DynamoDB — no Claude API call
             Minutes remaining computed live (changes through the day, not cached)

Cache MISS:  context_loader.load_context() — assembles full market snapshot
               └─ claude_service.morning_briefing(ctx) — Anthropic API call
               └─ dynamo_service.put_cache("briefing", {briefing, date})
               └─ Returns result

Response:    Briefing text displayed as a formatted paragraph
             "X min left" badge shown when market is open
Error path:  "Error: <server detail>" shown in the panel
```

The briefing is generated once per day. After the first page load triggers a Claude call and caches the result, every subsequent load — including after backend restarts — reads from DynamoDB without touching the Claude API. In production, the 7am scheduled job pre-generates the briefing before anyone visits.

---

### 2. Scanner — Top Movers

```
Trigger:     Page loads + every 60 seconds (only when browser tab is visible)
Frontend:    ScannerPanel.jsx
             useEffect on mount + setInterval with document.visibilityState check
             GET /api/scanner/movers

Backend:     routers/scanner.py → get_movers()
               └─ cache_service.get_cached_scanner(limit=20)
                    └─ dynamo_service.get_cache("scanner") → checks freshness

Cache HIT:   Returns cached mover list immediately

Cache MISS:  context_loader._get_watchlist()
               1. Schwab movers: get_dynamic_watchlist() — top movers across SPX, Nasdaq, Dow
               2. Falls back to static 14-ticker list if Schwab unavailable
             schwab_service.get_previous_day_movers(tickers, limit=20)
               └─ Schwab GET /quotes for all tickers in one call
               └─ Filters: price >= $5, volume >= 500K
               └─ Sorts by absolute % change descending

Response:    Table: ticker, price, % change (green/red), volume, high, low
             Manual Refresh button at top right
Error path:  "Error: <server detail>" — shows actual reason (e.g. "401 Unauthorized" = Schwab token issue)
```

The visibility gate (`document.visibilityState === 'visible'`) pauses polling when the browser tab is in the background, reducing unnecessary Schwab API calls.

---

### 3. Portfolio

```
Trigger:     Page loads + every 90 seconds (visibility-gated)
Frontend:    PortfolioView.jsx
             GET /api/portfolio/

Backend:     routers/portfolio.py → get_portfolio()
               └─ portfolio_factory.get_provider()
                    PORTFOLIO_MODE=live      → robinhood_service.get_portfolio()
                    PORTFOLIO_MODE=synthetic → synthetic_portfolio.get_portfolio()
               └─ _enrich_positions(positions)
                    └─ schwab_service.get_batch_quotes([all tickers]) — one batch call
                    └─ Computes per position: current_price, unrealized_pnl, unrealized_pnl_pct

Response:    Cash balance + table: ticker, shares, avg cost, current price, unrealized P&L + %
             P&L values colored green (profit) / red (loss)
Error path:  Error shown inline; if Schwab enrichment fails, positions still show but price = "—"
```

`portfolio_factory.py` is the switch between real and demo data — it reads `PORTFOLIO_MODE` at request time, so changing the mode in `.env.local` and restarting takes effect immediately.

---

### 4. Sentiment Feed

```
Trigger:     Page loads
Frontend:    SentimentFeed.jsx
             GET /api/ai/sentiment

Backend:     routers/ai.py → get_sentiment()
               └─ cache_service.get_cached_sentiment()
                    └─ dynamo_service.get_cache("sentiment") → checks freshness

Cache HIT:   Returns cached sentiment scores

Cache MISS:  context_loader.load_context()
               └─ _get_watchlist() → Schwab movers
               └─ Portfolio position tickers added to sentiment_tickers
               └─ finnhub_service.score_batch_sentiment(tickers)
                    └─ For each ticker: fetch 3-day news headlines from Finnhub
                    └─ VADER scores each headline (-1.0 to +1.0)
                    └─ Averages all scores → compound score + label

Response:    List of tickers with: score, label (bullish/bearish/neutral), article count
             ≥ +0.05 = bullish  |  ≤ -0.05 = bearish  |  between = neutral
Error path:  Empty list; panel renders nothing rather than crashing
```

VADER (Valence Aware Dictionary and sEntiment Reasoner) is a rule-based model trained on social media text — it scores each headline without needing to call an AI API. Sentiment runs on the same tickers as the scanner plus portfolio holdings, so it always reflects what's relevant today.

---

### 5. Chat

```
Trigger:     User types a message and hits Send
Frontend:    ChatPanel.jsx
             POST /api/ai/chat with {message: "..."}

Backend:     routers/ai.py → chat(request)
               └─ context_loader.load_context() — assembles full daily snapshot:
                    portfolio positions + cash
                    top movers (Schwab)
                    sentiment scores (Finnhub/VADER)
                    today's trades from DynamoDB
                    realized P&L and trade count today
                    current guardrail status
                    today's guardrail events
                    minutes remaining in session
               └─ claude_service.chat(ctx, message)
                    └─ Builds system prompt embedding all context fields
                    └─ Anthropic API call → conversational reply

Response:    Claude's reply in a chat bubble
Error path:  "Chat failed: <reason>" shown in chat area
```

Claude receives the complete market context on every message — it knows your positions, movers, how much P&L you've made/lost today, and what guardrails have fired. This is why it can answer "should I add to my NVDA position?" with real situational awareness.

---

### 6. Trade Suggestions

```
Trigger:     User clicks "Suggest Trades" in ChatPanel
Frontend:    ChatPanel.jsx
             POST /api/ai/suggest-trades with
             {message: "Suggest trades based on today's context.", allow_loss: false}

Backend:     routers/ai.py → suggest_trades(request)
               └─ context_loader.load_context() — same full snapshot as chat
               └─ claude_service.suggest_trades(ctx, message, allow_loss)
                    └─ Anthropic API call with structured output schema
                    └─ Claude returns list of TradeSetup objects:
                         ticker, direction (long/short), trade_type
                         entry_price, target_price, stop_loss, shares
                         expected_gain, max_loss, reward_risk_ratio (min 1.5)
                         confidence, rationale, setup_type
                         robinhood_instructions (plain English order steps)

Response:    Each suggestion as a card showing all trade parameters
             Recommended trade highlighted; R/R and confidence displayed per card
Error path:  "Trade suggestion failed: <reason>" error message
```

Claude's suggestions are structured data validated by Pydantic — not free text. Every suggestion includes plain-English Robinhood instructions because the app never places orders directly. You execute manually.

---

### 7. Paper Trade Submission

```
Trigger:     User clicks "Paper Trade" on a suggestion card
Frontend:    ChatPanel.jsx → paperTrade(trade, allowLoss)
             POST /api/paper-trades/ with {setup: TradeSetup, allow_loss: false}

Backend:     routers/paper_trading.py → open_trade(request)
               └─ portfolio_factory.get_provider().get_cash() — current buying power
               └─ paper_trading_service.open_trade(setup, cash, trading_mode, allow_loss)
                    └─ dynamo_service.get_realized_pnl_today(today)
                    └─ dynamo_service.get_trade_count_today(today)
                    └─ guardrail_service.check_all(setup, ctx) — all 8 checks run

                    If blocked:
                      dynamo_service.log_guardrail_event(ticker, rules, messages, date)
                      Raises ValueError → 400 response with detail message

                    If all pass:
                      Creates PaperTrade with UUID trade_id, status="open"
                      dynamo_service.put_trade(trade) — writes to DynamoDB
                      Returns PaperTrade object

Response:    Button shows "✓ Paper Trade Logged" and stays disabled (prevents double-submit)
Error path:  Inline error on the card showing which guardrail fired and why
```

The guardrail check runs on every submission — paper or live. If a guardrail fires, the event is logged to DynamoDB, appears in GuardrailsPanel, and is included in Claude's context on the next chat message.

---

### 8. Guardrails Panel

```
Trigger:     Page loads + every 60 seconds (visibility-gated)
Frontend:    GuardrailsPanel.jsx — two parallel fetches:
             GET /api/guardrails/status
             GET /api/guardrails/events

Status fetch:
  routers/guardrails.py → get_status()
    └─ Reads today's realized P&L and trade count from DynamoDB
    └─ guardrail_service.get_status(ctx) — evaluates each guardrail live

Events fetch:
  routers/guardrails.py → get_events()
    └─ dynamo_service.get_guardrail_events_by_date(today) — DynamoDB GSI query
    └─ Returns newest-first

Response:    4 status cards:
               Market session (open/closed, current ET time)
               Intraday window (open until 3pm ET)
               Daily P&L ($X realized of -$200 limit)
               Trades today (X of 3 limit)
             Events log: ticker + rules triggered per event (e.g. "NVDA — market_hours_lock")
             Red badge on panel header showing event count

Kill switch (two-step confirm):
  "Activate Kill Switch" → "Confirm — Close All" + "Cancel"
  POST /api/guardrails/kill-switch?confirmed=true
    └─ guardrail_service.trigger_kill_switch(confirmed=True, trading_mode)
         └─ dynamo_service.get_open_trades()
         └─ Paper trades: status="closed", close_reason="kill_switch"
         └─ Live trades: flagged_for_manual_close=True (you close these in Robinhood)
```

---

### 9. Paper Trading Panel

```
Trigger:     Panel expands (loads on first expand)
Frontend:    PaperTradingPanel.jsx — 3 tabs

Open tab:    GET /api/paper-trades/?date=today
               └─ dynamo_service.get_trades_by_date(today) → filters open
             Shows: ticker, direction, entry, target, stop
             Close button: POST /api/paper-trades/{id}/close
               with {exit_price, close_reason}
               └─ paper_trading_service.close_trade()
               └─ Computes realized P&L: (exit - entry) × shares (reversed for short)
               └─ Updates DynamoDB: status="closed", exit_price, realized_pnl

History tab: Same fetch, shows closed trades with entry/exit/P&L per trade

Summary tab: GET /api/paper-trades/summary?date=today
               └─ paper_trading_service.get_daily_summary(today, trading_mode)
             Shows: total realized P&L vs daily goal ($100), open position count,
                    time the goal was first hit (if applicable)
```

---

### 10. Live Tracking Panel

```
Trigger:     Panel expands
Frontend:    LiveTrackingPanel.jsx — same 3-tab structure as PaperTradingPanel
             Fetches from GET /api/live-trades/

Mode notice: If TRADING_MODE != "live", amber banner:
             "Live tracking is in paper mode — switch TRADING_MODE=live to track real trades"

Close form:  POST /api/live-trades/{id}/exit
             (app never auto-closes live trades — requires manual Robinhood action first)
```

---

### 11. Price Monitor (Scheduled — Every 5 Minutes)

```
Trigger:     AWS EventBridge: cron(*/5 13-20 ? * MON-FRI *)
             Every 5 min, Mon–Fri, 9:30am–4pm ET

Lambda:      main.py → price_monitor_handler()
               └─ cache_service.run_price_monitor()
                    └─ dynamo_service.get_open_trades() — all status="open" trades
                    └─ schwab_service.get_batch_quotes([all open tickers]) — one call
                    └─ For each trade:
                         long  + price >= target → close_reason = "target_hit"
                         long  + price <= stop   → close_reason = "stop_hit"
                         short + price <= target → close_reason = "target_hit"
                         short + price >= stop   → close_reason = "stop_hit"
                         Paper: paper_trading_service.close_trade(id, price, reason)
                         Live:  dynamo_service.update_trade(id, {flagged_for_manual_close: True})

Returns:     {checked: N, closed: N, flagged: N}
```

Live trades are never auto-closed — they get flagged with the trigger reason and price so you can act in Robinhood.

---

### 12. Daily Refresh (Scheduled — 7:00am ET)

```
Trigger:     AWS EventBridge: cron(0 12 * * ? *)  — daily at 12:00 UTC = 7:00am ET

Lambda:      main.py → refresh_handler()
               └─ cache_service.run_daily_refresh()
                    └─ context_loader._get_watchlist() → Schwab movers
                    └─ schwab_service.get_previous_day_movers(tickers, limit=50)
                         └─ dynamo_service.put_cache("scanner", movers)
                    └─ finnhub_service.score_batch_sentiment(top 15 movers)
                         └─ dynamo_service.put_cache("sentiment", scores)
                    └─ context_loader.load_context()
                    └─ claude_service.morning_briefing(ctx) — Anthropic API call
                         └─ dynamo_service.put_cache("briefing", {briefing, date})

Returns:     {refreshed_at, scanner_count, sentiment_count, briefing_cached, errors}
```

This is the only automatic Claude API call each day. After this runs, all three caches are warm — the first page load of the day is instant with no external API calls.

---

### 13. End of Day (Scheduled — 3:45pm ET)

```
Trigger:     AWS EventBridge: cron(45 20 ? * MON-FRI *)  — Mon–Fri at 20:45 UTC = 3:45pm ET

Lambda:      main.py → end_of_day_handler()
               └─ cache_service.run_end_of_day()
                    └─ dynamo_service.get_open_trades()
                    └─ schwab_service.get_batch_quotes([open tickers]) → last prices
                    └─ Paper trades: close_trade(id, last_price, "eod_close")
                    └─ Live trades: update_trade(id, {flagged_for_manual_close: True})

Returns:     {paper_closed: N, live_flagged: N}
```

---

## Data Model

Everything lives in a single DynamoDB table named `trading-dashboard`. Three types of items share this table, distinguished by their `status` field.

### Table keys

| Field | Type | Role |
|-------|------|------|
| `trade_id` | String | **Hash key** — UUID for trades, `"cache#<key>"` for cache items |
| `status` | String | **GSI hash key** — `open`, `closed`, `live`, `guardrail_event`, `cache` |
| `date` | String | **GSI range key** — `YYYY-MM-DD` for trades/events, ISO timestamp for cache |

### What is a GSI?

A GSI (Global Secondary Index) is a secondary access path on a DynamoDB table. Without it, finding "all open trades from today" requires scanning every row in the table. The GSI lets the app run an efficient query: `status = "open" AND date = "2026-05-21"` — regardless of how large the table grows.

### Trade items

Written by `paper_trading_service.open_trade()` and `dynamo_service.put_trade()`. Key fields: `ticker`, `direction` (`long`/`short`), `entry_price`, `target_price`, `stop_loss`, `shares`, `status` (`open`/`closed`), `mode` (`paper`/`live`), `realized_pnl` (null until closed), `close_reason` (`target_hit`/`stop_hit`/`manual`/`eod_close`/`kill_switch`).

### Cache items

`trade_id` = `"cache#scanner"`, `"cache#sentiment"`, or `"cache#briefing"`. The payload is stored as a JSON string. Written by `dynamo_service.put_cache()`, read by `dynamo_service.get_cache()`.

Freshness check in `cache_service._cache_is_fresh(cached_at)`: parses `cached_at` as an ISO timestamp, converts to Eastern Time, returns `True` only if it matches today's ET date. Cache is never invalidated mid-day — it simply becomes stale at midnight ET.

### Guardrail event items

`status = "guardrail_event"`. Written by `dynamo_service.log_guardrail_event()` whenever a trade attempt is blocked. Fields: `ticker`, `rules_triggered` (list), `messages` (list of human-readable reasons), `date`, `timestamp`. Queried via GSI by `dynamo_service.get_guardrail_events_by_date(date)`.

---

## Architecture Diagram

### Local Development

```
┌──────────────────────────────────────────────────────────┐
│  Your Machine                                            │
│                                                          │
│  Browser :5173 ──/api/*──▶ Vite proxy ──▶ uvicorn :8000 │
│                                               │          │
│                                          FastAPI app     │
│                                               │          │
│                         ┌─────────────────────┤          │
│                         ▼          ▼           ▼         │
│                    Schwab API  Finnhub API  Claude API   │
│                    (real-time) (news/NLP)  (Anthropic)   │
│                         │                                │
│                         ▼                               │
│                    DynamoDB (AWS) ◀── boto3 ────────────┘│
│                    SSM / Secrets Manager                 │
└──────────────────────────────────────────────────────────┘
  .env.local → all credentials injected via environment variables
```

### Production — Public Version

```
Public user
    │
    ▼
Cloudflare
  ├─ Rate limit: 30 req/min per IP (block 1 hour on exceed)
  ├─ Bot Fight Mode: ON
  └─ DDoS protection: ON (automatic)
    │
    ├──▶ CloudFront ──▶ S3: trading-dashboard-public
    │         (static React files, VITE_PORTFOLIO_MODE=synthetic)
    │
    └──▶ API Gateway ──▶ Lambda (FastAPI + Mangum)
                               │
                    ┌──────────┼────────────┐
                    ▼          ▼            ▼
                DynamoDB    SSM/Secrets  Schwab/Finnhub/Claude
```

### Production — Private Version

```
Owner visits private.yourdomain.com
    │
    ▼
Cloudflare Access
  └─ Shows login page — enter your-email@example.com
  └─ Emails 6-digit PIN → enter PIN → authenticated 24 hours
  └─ Anyone else: blocked entirely, never reaches S3 or Lambda
    │
    ▼
CloudFront ──▶ S3: trading-dashboard-private
                    (same React source, VITE_PORTFOLIO_MODE=live build)
    │
    ▼
API Gateway ──▶ Lambda (same function as public)
                       │
            DynamoDB / SSM / Secrets / Schwab / Finnhub / Claude
```

### Scheduled Jobs

```
EventBridge (daily 7:00am ET)
    └──▶ DailyRefreshFunction → cache_service.run_daily_refresh()
              Schwab movers    ──▶ DynamoDB cache["scanner"]
              Finnhub sentiment ──▶ DynamoDB cache["sentiment"]
              Claude briefing   ──▶ DynamoDB cache["briefing"]

EventBridge (every 5 min, Mon–Fri 9:30am–4pm ET)
    └──▶ PriceMonitorFunction → cache_service.run_price_monitor()
              DynamoDB open trades + Schwab live quotes
              Auto-close paper trades at target/stop
              Flag live trades for manual close

EventBridge (Mon–Fri 3:45pm ET)
    └──▶ EndOfDayFunction → cache_service.run_end_of_day()
              Close all open paper trades at last price
              Flag all open live trades for manual close
```

### CI/CD Pipeline

```
git push → main branch
    │
    ▼
GitHub Actions: .github/workflows/deploy.yml
    │
    ├── job: backend
    │     sam build
    │     sam deploy ──▶ CloudFormation updates:
    │                     Lambda functions
    │                     DynamoDB table
    │                     S3 buckets
    │                     CloudFront distributions
    │                     IAM roles + policies
    │
    ├── job: frontend-public  (runs after backend, parallel with private)
    │     npm ci
    │     npm run build  [VITE_API_URL=PUBLIC_API_URL, VITE_PORTFOLIO_MODE=synthetic]
    │     aws s3 sync frontend/dist → s3://trading-dashboard-public --delete
    │     CloudFront invalidation (clears CDN cache immediately)
    │
    └── job: frontend-private  (runs after backend, parallel with public)
          npm ci
          npm run build  [VITE_API_URL=PRIVATE_API_URL, VITE_PORTFOLIO_MODE=live]
          aws s3 sync frontend/dist → s3://trading-dashboard-private --delete
          CloudFront invalidation
```

Required GitHub repository secrets: `AWS_DEPLOY_ROLE_ARN`, `PUBLIC_API_URL`, `PRIVATE_API_URL`, `PUBLIC_CF_DIST_ID`, `PRIVATE_CF_DIST_ID`.

---

## Guardrails Reference

All 8 guardrails run through `guardrail_service.check_all()` in `backend/services/guardrail_service.py`. The same checks apply to paper and live trades alike.

| Guardrail | What it checks | Triggered when |
|-----------|---------------|----------------|
| `daily_loss_limit` | Total realized P&L today | Losses reach `DAILY_LOSS_LIMIT` ($200 default) |
| `position_size_cap` | Trade value vs available cash | Position exceeds `MAX_POSITION_SIZE_PCT` (20% default) of cash |
| `cost_basis_protection` | Entry price vs avg cost on held positions | Entry is below your cost basis — would realize a loss on a winner. Override with `allow_loss=true` |
| `reward_risk_minimum` | Target gain ÷ max loss | Ratio is below 1.5 |
| `daily_trade_limit` | Trades placed today | `DAILY_TRADE_LIMIT` (3 default) already reached |
| `market_hours_lock` | Current time (ET) | Outside 9:30am–4:00pm ET, Monday–Friday |
| `intraday_60min_cutoff` | Current time for intraday trades | After 3:00pm ET — less than 60 minutes left in session |
| `buying_power_check` | Trade value vs cash balance | Insufficient cash to cover the full position |

**Kill switch:** Two-step confirm in GuardrailsPanel. Immediately closes all open paper trades (`close_reason="kill_switch"`) and sets `flagged_for_manual_close=true` on live trades — those require manual action in Robinhood. The app never auto-closes live positions.

---

## Secrets & Credentials Reference

| Credential | Where stored | How it reaches Lambda | Auto-rotated? |
|-----------|-------------|----------------------|---------------|
| `ANTHROPIC_API_KEY` | SSM SecureString `/trading-app/anthropic-key` | `ssm_service.get_secret()` at runtime (env var fallback for local dev) | No — update SSM manually |
| `FINNHUB_API_KEY` | SSM SecureString `/trading-app/finnhub-key` | Same runtime SSM fetch | No |
| `SCHWAB_CLIENT_ID` | SSM SecureString `/trading-app/schwab-client-id` | Same runtime SSM fetch | No |
| `SCHWAB_CLIENT_SECRET` | SSM SecureString `/trading-app/schwab-client-secret` | Same runtime SSM fetch | No |
| Schwab OAuth token | Secrets Manager `/trading-app/schwab-token` | `schwab_service.py` reads + writes via boto3 at runtime | Yes — `schwab-py` auto-refreshes and writes back |
| Robinhood credentials | Secrets Manager `/trading-app/robinhood-credentials` | `robinhood_service.py` reads via boto3 at runtime | No — update via CLI |

**`.env.local`** — Local dev only. Contains all credentials plus config values. Gitignored — never committed, never deployed. Copy from `.env.example` and fill in your values. The `start.sh` script loads this automatically.

**`.env.example`** — Documents every required variable with empty values. Safe to commit. The reference for what needs to go into SSM/Secrets Manager before the first AWS deploy.

Non-secret config (PORTFOLIO_MODE, TRADING_MODE, DAILY_GOAL, etc.) uses plain SSM parameters resolved at deploy time — the value gets baked into the Lambda environment variable. API key secrets (Anthropic, Finnhub, Schwab client ID/secret) use SSM SecureString and are fetched at **runtime** by `ssm_service.get_secret()` on Lambda cold start, then cached for the container lifetime. Secrets Manager values (Schwab token, Robinhood credentials) are also fetched at runtime — the Lambda always gets the current version, which is why Schwab token auto-rotation works transparently.

---

## Phase Roadmap

### Phase 1 — Paper Trade (current)

Paper trade every day on real Schwab data. Use the morning briefing, scanner, and Claude suggestions to build a daily routine. Track results in DynamoDB. The goal is not profit yet — it's proving the process is repeatable before real money is involved.

**Hard gate before Phase 2:** All 14 tests in `backend/tests/test_guardrails.py` must pass. These verify the safety rails work correctly — they are non-negotiable.

### Phase 2 — Validation Analytics

Add `validation_service.py` to benchmark paper results:
- Win rate > 55% and average reward-to-risk > 1.5
- Claude beats SPY on more than 60% of days
- Claude beats a random trade baseline on more than 60% of days
- Slippage-adjusted P&L still hits the daily goal
- Monte Carlo simulation: probability of a net-positive month > 70%

A SageMaker ML pipeline starts during this phase — it trains on trade history and shows predictions alongside Claude suggestions. Observe only; no action taken on ML signals yet.

### Phase 3 — Live Trading (Small Size)

Switch `TRADING_MODE=live` (requires explicit confirmation — this is the point of no return for real money). Trade at 25% of normal position sizes. Execute manually in Robinhood. SageMaker predictions visible but observe-only.

**Phase 2 → 3 gate:** All five validation criteria above must pass simultaneously before this switch.

### Phase 4 — Full Live Trading + ML Active

Full position sizes. ML predictions feed into Claude's context and suggestions. Optional: Alpaca API for automated order execution (not built — Phase 4 scope).

---

*FastAPI · Python 3.13 · React · Vite · AWS Lambda · API Gateway · DynamoDB · S3 · CloudFront · EventBridge · SAM · GitHub Actions · Schwab API · Finnhub · Anthropic Claude · Cloudflare*
