# AI Trading Dashboard

My personal trading assistant. Built to run my daily workflow — morning briefing, scanner, sentiment analysis, trade logging, and AI suggestions — without juggling half a dozen tools.

This isn't a SaaS product. It's built for one user (me). Every design decision is about building discipline before putting real money in: paper trade on real Schwab data, prove the process works, then go live.

The app runs as two separate deployments backed by two separate Lambda functions. The **public version** at [ait.gsuarez.dev](https://ait.gsuarez.dev) uses synthetic portfolio data and is open to anyone — its Lambda has no IAM access to live credentials. The **private version** connects to my real brokerage and sits behind Cloudflare Access — email one-time-PIN, no one else gets in. Its Lambda runs with `PORTFOLIO_MODE=live`, has Robinhood IAM access, and requires a shared secret (`x-api-key` header) on every request. Same codebase, two isolated execution environments.

The bar before going live: win rate above 55%, R/R above 1.5, beating SPY more than 60% of days. Claude helps with briefings and suggestions but never touches orders. Every trade is manual. The guardrail system enforces the rules automatically so I can't override them on a bad day.

---

## Live

| Version | URL | Access |
|---------|-----|--------|
| Public demo | [ait.gsuarez.dev](https://ait.gsuarez.dev) | Open to anyone — synthetic portfolio |
| Private dashboard | Not public | Cloudflare Access — email OTP only |

---

## Tech Stack

### Frontend

| Technology | Role |
|-----------|------|
| **React** | UI framework |
| **Vite** | Build tool — dev server + production bundler |
| **AWS S3** | Hosts built frontend files (two buckets: public and private) |
| **AWS CloudFront** | CDN — HTTPS, edge caching |

### Backend

| Technology | Role |
|-----------|------|
| **FastAPI** | Python web framework |
| **Mangum** | Adapter — translates Lambda Function URL events into FastAPI requests |
| **AWS Lambda** | Serverless compute — two separate functions (public + private) |
| **AWS Lambda Function URL** | Direct HTTPS endpoint per Lambda — no API Gateway timeout ceiling |
| **uvicorn** | Local dev only — runs FastAPI on port 8000 |

In production: browser → Lambda Function URL → Lambda → FastAPI (via Mangum). In local dev, uvicorn replaces the Lambda + Function URL entirely.

### Data & Storage

| Technology | What it stores |
|-----------|---------------|
| **AWS DynamoDB** | Trades, cache items (scanner/sentiment/briefing), guardrail events |
| **AWS SSM Parameter Store** | Non-secret config: trading mode, daily goal, loss limit, trade limits |
| **AWS Secrets Manager** | Sensitive credentials: Schwab OAuth token, Robinhood username/password |

### External APIs

| Service | Purpose |
|---------|---------|
| **Schwab API** (`schwab-py`) | Real-time quotes, top movers across major indexes, OHLCV price history |
| **Finnhub** | News headlines for sentiment scoring |
| **Anthropic Claude API** | Morning briefing, conversational chat, structured trade suggestions |

The Schwab connection uses an OAuth token that `schwab-py` manages automatically — it refreshes when expired and writes the updated token back to Secrets Manager.

### Infrastructure & Security

| Technology | Role |
|-----------|------|
| **AWS SAM** (`template.yaml`) | IaC — entire AWS stack defined in one YAML file |
| **GitHub Actions** (`deploy.yml`) | CI/CD — deploys automatically on every push to `main` |
| **Cloudflare** | Sits in front of CloudFront: rate limiting, DDoS protection, bot blocking |
| **Cloudflare Access** | Auth layer for the private version — email one-time-PIN login wall |

SAM means the AWS console is never touched for infrastructure — `template.yaml` is the single source of truth. `sam deploy` creates or updates everything.

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
│   │   ├── claude_service.py         # Anthropic API — morning_briefing, chat, suggest_trades (agentic tool-use loop)
│   │   ├── context_loader.py         # DailyContext (briefing/chat) + build_seed_context() (suggest_trades agentic path)
│   │   ├── dynamo_service.py         # All DynamoDB reads/writes — trades, cache, guardrail events
│   │   ├── finnhub_service.py        # Finnhub news fetch + VADER sentiment scoring
│   │   ├── guardrail_service.py      # 8 guardrail checks + status dashboard + kill switch
│   │   ├── live_tracking_service.py  # Live trade management (Phase 3)
│   │   ├── market_data_service.py    # Thin wrapper — delegates all calls to schwab_service
│   │   ├── paper_trading_service.py  # open_trade, close_trade, get_daily_summary
│   │   ├── portfolio_factory.py      # Selects robinhood_service or synthetic_portfolio by PORTFOLIO_MODE
│   │   ├── robinhood_service.py      # Live portfolio data from Robinhood (PORTFOLIO_MODE=live)
│   │   ├── schwab_service.py         # Schwab OAuth client — quotes, movers, 5-min opening range indicators
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
│   ├── schwab_auth.py                # One-time OAuth flow to generate schwab_token.json for local dev
│   └── backfill_paper_pnl.py         # One-time script — seeds cache#paper_pnl from existing closed trade history
│
├── template.yaml                     # SAM template — defines every AWS resource
├── samconfig.toml                    # SAM deploy defaults (region, stack name)
├── .env.example                      # Documents all required variables — safe to commit
├── .env.local                        # Your actual values — gitignored, never committed
└── notes.md                          # Running dev notes — architecture explanations, setup guides
```

---

## Running Locally

From the repo root:

```bash
bash scripts/start.sh
```

Then open `http://localhost:5173`.

The script activates the Python venv, loads `.env.local`, starts uvicorn on port 8000 in the background, waits for it to be ready, then starts Vite on port 5173. Vite proxies `/api/*` requests to the backend. Ctrl+C kills everything cleanly.

**What `main.py` does on startup:**
- Calls `load_dotenv()` to read `.env.local` (no-op in Lambda — env vars are injected directly)
- Registers all routers under their URL prefixes (`/scanner`, `/portfolio`, `/ai`, etc.)
- Calls `dynamo_service.ensure_table_exists()` in a `try/except` (creates local table if missing — non-fatal in prod since CloudFormation manages it)
- Creates the Mangum `handler` object that Lambda calls for every HTTP request

---

## Feature Flows

Every feature traced from UI interaction to final result. File names and function names included so you can find the code when something breaks.

---

### 1. Morning Briefing

```
Trigger:     Page loads — DailySummaryPanel mounts automatically
Frontend:    DailySummaryPanel.jsx
             useEffect → GET /api/ai/briefing on mount

Backend:     routers/ai.py → get_briefing()
               └─ Checks PORTFOLIO_MODE:
                    synthetic → cache_service.get_cached_briefing()
                                  └─ dynamo_service.get_cache("briefing")
                    live      → cache_service.get_cached_live_briefing()
                                  └─ dynamo_service.get_cache("briefing_live")
               └─ Checks: cached_at date == today (ET timezone)

Cache HIT:   Returns {briefing, date} from DynamoDB — no Claude API call
             Minutes remaining computed live (changes through the day, not cached)

Cache MISS:  Returns {briefing: null} — no on-demand generation
             UI shows market-closed / no-briefing message
             The scheduled DailyRefreshFunction (synthetic) or
             DailyRefreshLiveBriefingFunction (live) writes the cache at 9:35am ET

Response:    Briefing text displayed as a formatted paragraph
             "X min left" badge shown when market is open
Error path:  "Error: <server detail>" shown in the panel
```

The briefing is pre-generated at 9:35am ET by a scheduled Lambda — not generated on demand. This avoids the cold-start + Claude latency on the first page load of the day. Cache misses (before 9:35am, weekends) return null and the UI degrades gracefully.

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

Cache HIT:   DynamoDB holds only the ticker watchlist (symbols, no prices)
             schwab_service.get_previous_day_movers(cached_tickers) — live Schwab call
               └─ Fetches current price, % change, volume for each cached ticker
             Prices are always live — the cache controls *which tickers* to track,
             not the price data itself. Every poll during the session gets fresh quotes.

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

The visibility gate pauses polling when the browser tab is in the background.

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

`portfolio_factory.py` reads `PORTFOLIO_MODE` at request time — changing it in `.env.local` and restarting takes effect immediately.

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

VADER scores headlines without an AI API call. Sentiment runs on the same tickers as the scanner plus current portfolio holdings.

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

Claude gets the full market context on every message — positions, movers, today's P&L, guardrails that fired. This is why it can answer "should I add to my NVDA position?" with actual situational awareness.

---

### 6. Trade Suggestions

```
Trigger:     User clicks "Suggest Trades" in ChatPanel
Frontend:    ChatPanel.jsx
             POST /api/ai/suggest-trades with
             {message: "Suggest trades based on today's context.", allow_loss: false}

Backend:     routers/ai.py → suggest_trades(request)
               └─ context_loader.build_seed_context()
                    Cheap parallel fetch (no market API calls):
                    - portfolio cash (Robinhood/synthetic — one call)
                    - trades_today + guardrail_events (DynamoDB)
                    - env vars: trading_mode, profit_mode, trade_scope, daily_goal
                    - guardrail_status (computed from the above)
                    - minutes_remaining

               └─ claude_service.suggest_trades(seed, message, allow_loss)
                    └─ _agentic_call(system, payload, max_iterations=5)
                         │
                         │  Iteration 1 — Claude calls tools to gather market data:
                         ├─ get_top_movers()
                         │    └─ DDB cache hit → live Schwab quotes for cached tickers
                         │    └─ cache miss  → schwab_service.get_previous_day_movers()
                         │    └─ Returns list of today's top movers (price, change %, vol)
                         │
                         │  Iteration 2 — Claude calls with specific tickers:
                         ├─ get_technical_indicators(tickers=[...movers..., "TQQQ", "IONZ"])
                         │    └─ schwab_service.get_technical_indicators(tickers)
                         │         └─ Fetches 5-min bars for each ticker
                         │         └─ candles[0] = opening 9:30-9:35am candle
                         │         └─ Computes per ticker:
                         │              orh: opening range high (high of first candle)
                         │              orl: opening range low  (low of first candle)
                         │              ema_3, ema_6: EMAs across all 5-min closes
                         │              vwap: cumulative volume-weighted avg price
                         │              bounce_setup: true when EMA(3)>EMA(6) AND
                         │                            price>VWAP AND price>=ORH
                         │
                         ├─ get_portfolio()
                         │    └─ portfolio_factory → positions enriched with current prices
                         │
                         ├─ get_sentiment(tickers=[...candidates...])  [optional]
                         │    └─ DDB cache hit or finnhub_service.score_batch_sentiment()
                         │
                         │  Final iteration — Claude produces JSON:
                         └─ stop_reason="end_turn" → returns structured JSON string

                    └─ _extract_json() + json.loads()
                    └─ TradeSuggestionResponse.model_validate(parsed)
                    └─ Server-side guardrail checks on every suggestion:
                         guardrail_service.check_all(trade, GuardrailContext)
                    └─ If recommended trade fails guardrails:
                         dynamo_service.log_guardrail_event(...)
                         suggestion.recommended = None

Suggestion   Only LONG trades suggested. Valid setup requires bounce_setup=true —
strategy:    price broke above the ORH (Opening Range High) and is holding there
             with EMA(3) > EMA(6) and price above VWAP. Entry at/above ORH; stop
             just below ORL. Tickers where price_below_orl=true are excluded.
             TQQQ and IONZ always included regardless of scanner ranking.
             Minimum reward/risk ratio: 1.5. Daily goal: $400.

Response:    Each suggestion as a card showing all trade parameters
             Recommended trade highlighted; R/R and confidence displayed per card
Error path:  "Trade suggestion failed: <reason>" error message
```

Suggestions are structured Pydantic-validated data, not free text. Claude fetches data on-demand via tools (agentic loop) rather than receiving a pre-built context blob — it calls `get_top_movers` first, then decides which tickers warrant deeper indicator analysis. Every suggestion includes plain-English Robinhood instructions because the app never places orders directly.

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

The guardrail check runs on every submission — paper or live. If a guardrail fires, the event is logged to DynamoDB, appears in GuardrailsPanel, and is included in Claude's context on the next message.

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
             Trades today card shows X of 2 daily limit

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
Trigger:     Page loads — panel mounts automatically (useEffect on mount)
Frontend:    PaperTradingPanel.jsx — 4 tabs: Open / Pending / History / Summary

Open tab:    GET /api/paper-trades/?date=today
               └─ dynamo_service.get_trades_by_date(today) → filters open
             Shows: ticker, direction, entry, target, stop
             Close button: POST /api/paper-trades/{id}/close
               with {exit_price, close_reason}
               └─ paper_trading_service.close_trade()
               └─ Computes realized P&L: (exit - entry) × shares (reversed for short)
               └─ Updates DynamoDB: status="closed", exit_price, realized_pnl
               └─ Atomically increments cache#paper_pnl cumulative counter

Pending tab: GET /api/paper-trades/pending?date=today
               └─ dynamo_service.get_pending_trades_for_date(today)
             Shows unfilled limit orders waiting for price trigger
             Cancel button: POST /api/paper-trades/{id}/cancel
               └─ Sets status="cancelled" (preserved in history, not refetched as open)

History tab: Same fetch as Open tab, shows closed/cancelled/expired trades with entry/exit/P&L

Summary tab: GET /api/paper-trades/summary?date=today
               └─ paper_trading_service.get_daily_summary(today, trading_mode)
             Shows: today's realized P&L vs daily goal, open position count,
                    time goal was first hit (if applicable),
                    all-time cumulative paper P&L (from cache#paper_pnl counter)
```

---

### 10. Live Tracking Panel

```
Trigger:     Page loads — panel mounts automatically (useEffect on mount)
Frontend:    LiveTrackingPanel.jsx — same 4-tab structure as PaperTradingPanel
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

### 12. Daily Refresh (Scheduled — 9:35am ET)

Two Lambdas run concurrently at 9:35am ET on weekdays.

```
Trigger:     AWS EventBridge: cron(35 13 ? * MON-FRI *)  — Mon–Fri at 13:35 UTC = 9:35am ET

Lambda 1:    main.py → refresh_handler()  [DailyRefreshFunction]
               PORTFOLIO_MODE=synthetic — Schwab access only
               └─ cache_service.run_daily_refresh()
                    └─ context_loader._get_watchlist() → Schwab movers
                    └─ schwab_service.get_previous_day_movers(tickers, limit=50)
                         └─ dynamo_service.put_cache("scanner", movers)
                    └─ finnhub_service.score_batch_sentiment(top 15 movers)
                         └─ dynamo_service.put_cache("sentiment", scores)
                    └─ context_loader.load_context()
                    └─ claude_service.morning_briefing(ctx) — Anthropic API call
                         └─ dynamo_service.put_cache("briefing", {briefing, date})
               Note: intraday 5-min indicators (ORH/ORL/EMA/VWAP) are NOT cached here —
               they expire within minutes and are fetched live via the suggest_trades
               agentic tool call instead.

Lambda 2:    main.py → refresh_live_briefing_handler()  [DailyRefreshLiveBriefingFunction]
               PORTFOLIO_MODE=live — Schwab + Robinhood access
               └─ cache_service.run_live_briefing_refresh()
                    └─ context_loader.load_context() with real Robinhood portfolio
                    └─ claude_service.morning_briefing(ctx) — Anthropic API call
                         └─ dynamo_service.put_cache("briefing_live", {briefing, date})

Returns:     {refreshed_at, scanner_count, sentiment_count, briefing_cached, errors}
```

After 9:35am all caches are warm — both the public and private morning briefings are pre-generated and first page load is instant. Scanner and sentiment are shared between both URLs; each URL gets its own briefing cache key with portfolio context appropriate to its mode.

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

Everything lives in a single DynamoDB table named `trading-dashboard`. Three item types share the table, distinguished by their `status` field.

### Table keys

| Field | Type | Role |
|-------|------|------|
| `trade_id` | String | **Hash key** — UUID for trades, `"cache#<key>"` for cache items |
| `status` | String | **GSI hash key** — `open`, `closed`, `live`, `guardrail_event`, `cache` |
| `date` | String | **GSI range key** — `YYYY-MM-DD` for trades/events, ISO timestamp for cache |

The GSI (`status-date-index`) is what makes queries like "all open trades from today" efficient — without it every query would scan the full table.

### Trade items

Written by `paper_trading_service.open_trade()` and `dynamo_service.put_trade()`. Key fields: `ticker`, `direction` (`long`/`short`), `entry_price`, `target_price`, `stop_loss`, `shares`, `status` (`open`/`closed`), `mode` (`paper`/`live`), `realized_pnl` (null until closed), `close_reason` (`target_hit`/`stop_hit`/`manual`/`eod_close`/`kill_switch`).

### Cache items

`trade_id` = `"cache#scanner"`, `"cache#sentiment"`, `"cache#briefing"`, `"cache#briefing_live"`, or `"cache#paper_pnl"`. Most payloads stored as JSON string via `dynamo_service.put_cache()` / `get_cache()`. Exception: `cache#paper_pnl` stores a raw `Decimal` `total` attribute updated via DynamoDB `ADD` (atomic increment) on every paper trade close — it is the all-time cumulative realized P&L counter.

Freshness check in `cache_service._cache_is_fresh(cached_at)`: parses `cached_at` as ISO timestamp, converts to ET, returns `True` only if it matches today's ET date. Cache is never invalidated mid-day — it goes stale at midnight ET.

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
Cloudflare (ait.gsuarez.dev)
  ├─ Rate limit: 30 req/min per IP (block 1 hour on exceed)
  ├─ Bot Fight Mode: ON
  └─ DDoS protection: ON (automatic)
    │
    ├──▶ CloudFront ──▶ S3: trading-dashboard-public
    │         (static React files, VITE_PORTFOLIO_MODE=synthetic)
    │         (no x-api-key — public requests need no auth)
    │
    └──▶ Lambda Function URL ──▶ TradingDashboardFunction
                                   PORTFOLIO_MODE=synthetic
                                   IAM: Schwab only — no Robinhood access
                                      │
                           ┌──────────┼────────────┐
                           ▼          ▼            ▼
                       DynamoDB    SSM/Secrets  Schwab/Finnhub/Claude
                                   (Schwab token only)
```

### Production — Private Version

```
Owner visits private dashboard URL
    │
    ▼
Cloudflare Access
  └─ Shows login page
  └─ Emails 6-digit PIN → enter PIN → authenticated 24 hours
  └─ Anyone else: blocked entirely, never reaches S3 or Lambda
    │
    ▼
CloudFront ──▶ S3: trading-dashboard-private
                    (same React source, VITE_PORTFOLIO_MODE=live build)
                    (x-api-key baked into bundle at CI build time)
    │
    ▼
Lambda Function URL ──▶ TradingDashboardPrivateFunction
                           FastAPI middleware validates x-api-key header
                           PORTFOLIO_MODE=live
                           IAM: Schwab + Robinhood credentials
                              │
                   DynamoDB / SSM / Secrets / Schwab / Finnhub / Claude
                                              (Schwab token + Robinhood creds)
```

### Scheduled Jobs

```
EventBridge (Mon–Fri 9:35am ET) — two functions run concurrently:
    ├──▶ DailyRefreshFunction → cache_service.run_daily_refresh()
    │         PORTFOLIO_MODE=synthetic, Schwab access only
    │         Schwab movers     ──▶ DynamoDB cache["scanner"]
    │         Finnhub sentiment ──▶ DynamoDB cache["sentiment"]
    │         Claude briefing   ──▶ DynamoDB cache["briefing"]
    │
    └──▶ DailyRefreshLiveBriefingFunction → cache_service.run_live_briefing_refresh()
              PORTFOLIO_MODE=live, Schwab + Robinhood access
              Claude briefing (real portfolio context) ──▶ DynamoDB cache["briefing_live"]

EventBridge (every 1 min, Mon–Fri 9:00am–4:59pm ET)
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
          npm run build  [VITE_API_URL=PRIVATE_API_URL, VITE_PORTFOLIO_MODE=live,
                          VITE_API_KEY=PRIVATE_API_KEY]
          aws s3 sync frontend/dist → s3://trading-dashboard-private --delete
          CloudFront invalidation
```

Required GitHub repository secrets: `AWS_DEPLOY_ROLE_ARN`, `PUBLIC_API_URL`, `PRIVATE_API_URL`, `PUBLIC_CF_DIST_ID`, `PRIVATE_CF_DIST_ID`, `PRIVATE_API_KEY`.

---

## Guardrails Reference

All 8 guardrails run through `guardrail_service.check_all()` in `backend/services/guardrail_service.py`. Same checks for paper and live. Current config: daily goal $400, max 2 trades/day, max position size 27% of cash.

| Guardrail | What it checks | Triggered when |
|-----------|---------------|----------------|
| `daily_loss_limit` | Total realized P&L today | Losses reach `DAILY_LOSS_LIMIT` ($200 default) |
| `position_size_cap` | Trade value vs available cash | Position exceeds `MAX_POSITION_SIZE_PCT` (27% default) of cash |
| `cost_basis_protection` | Entry price vs avg cost on held positions | Entry is below your cost basis — would realize a loss on a winner. Override with `allow_loss=true` |
| `reward_risk_minimum` | Target gain ÷ max loss | Ratio is below 1.5 |
| `daily_trade_limit` | Trades placed today | `DAILY_TRADE_LIMIT` (2 default) already reached. Bypassed when `PDT_EXEMPT=true` in SSM (for accounts above the $25k PDT threshold) |
| `market_hours_lock` | Current time (ET) | Outside 9:30am–4:00pm ET, Monday–Friday |
| `intraday_60min_cutoff` | Current time for intraday trades | After 3:00pm ET — less than 60 minutes left in session |
| `buying_power_check` | Trade value vs cash balance | Insufficient cash to cover the full position |

**Kill switch:** Two-step confirm in GuardrailsPanel. Immediately closes all open paper trades (`close_reason="kill_switch"`) and sets `flagged_for_manual_close=true` on live trades. The app never auto-closes live positions.

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
| Robinhood session token | Secrets Manager `/trading-app/robinhood-session` | `robinhood_service.py` — restored on cold start, written back after each login | Yes — Lambda writes fresh token after each successful login |
| Private API key | SSM String `/trading-app/private-api-key` (also GitHub Secret `PRIVATE_API_KEY`) | SAM bakes it into private Lambda env var at deploy time; CI bakes it into private frontend bundle | No — rotate manually (generate new UUID, update SSM + GitHub Secret, redeploy) |

**`.env.local`** — Local dev only. Contains all credentials plus config. Gitignored. Copy from `.env.example` and fill in values. `start.sh` loads it automatically.

**`.env.example`** — Documents every required variable with empty values. Safe to commit. Reference for what needs to go into SSM/Secrets Manager before first AWS deploy.

Non-secret config (PORTFOLIO_MODE, TRADING_MODE, DAILY_GOAL, etc.) uses plain SSM parameters resolved at deploy time — baked into Lambda environment variables. API key secrets (Anthropic, Finnhub, Schwab client ID/secret) use SSM SecureString fetched at **runtime** by `ssm_service.get_secret()` on Lambda cold start, then cached for the container lifetime. Secrets Manager values (Schwab token, Robinhood credentials) are also fetched at runtime — always the current version, which is why Schwab token auto-rotation works transparently.

---

## Opening Range Strategy

Claude's trade suggestions are built around the 5-minute opening range — the price band established in the first candle of the session (9:30–9:35am ET). `schwab_service.get_technical_indicators()` fetches intraday 5-min bars for each candidate ticker and computes:

| Field | Meaning |
|-------|---------|
| `orh` | Opening Range High — high of the 9:30–9:35am candle |
| `orl` | Opening Range Low — low of the 9:30–9:35am candle |
| `ema_3` | EMA across all 5-min closes today (short-term momentum) |
| `ema_6` | EMA across all 5-min closes today (medium-term trend) |
| `vwap` | Cumulative volume-weighted average price since open |
| `bounce_setup` | `true` when EMA(3) > EMA(6) AND price > VWAP AND price ≥ ORH |
| `price_below_orl` | `true` when price has broken below the opening range low (bearish — skip) |

A valid long setup requires `bounce_setup=true`: the stock broke above its ORH and is holding there with bullish EMA momentum and net-positive buying pressure (above VWAP). Entry is at or just above the ORH; the ORH becomes support. Stop loss sits just below the ORL — if price retreats there, the opening structure has failed.

`TQQQ` and `IONZ` are always included in the indicator fetch regardless of where they rank on the day's scanner, because they won't appear in Schwab's index-component mover API but are always in scope as candidates.

---

## Phase Roadmap

### Phase 1 — Paper Trade (current)

Paper trade every day on real Schwab data. Use the morning briefing, scanner, and Claude suggestions to build a daily routine. Track results in DynamoDB. The goal isn't profit yet — it's proving the process is repeatable before real money is involved.

**Hard gate before Phase 2:** All 14 tests in `backend/tests/test_guardrails.py` must pass.

### Phase 2 — Validation Analytics

Add `validation_service.py` to benchmark paper results:
- Win rate > 55% and average reward-to-risk > 1.5
- Claude beats SPY on more than 60% of days
- Claude beats a random trade baseline on more than 60% of days
- Slippage-adjusted P&L still hits the daily goal
- Monte Carlo simulation: probability of a net-positive month > 70%

A SageMaker ML pipeline starts during this phase — trains on trade history and shows predictions alongside Claude suggestions. Observe only; no action taken on ML signals yet.

### Phase 3 — Live Trading (Small Size)

Switch `TRADING_MODE=live` (requires explicit confirmation). Trade at 25% of normal position sizes. Execute manually in Robinhood. SageMaker predictions visible but observe-only.

**Phase 2 → 3 gate:** All five validation criteria above must pass simultaneously.

### Phase 4 — Full Live Trading + ML Active

Full position sizes. ML predictions feed into Claude's context and suggestions. Optional: Alpaca API for automated order execution (not built — Phase 4 scope).

---

*FastAPI · Python 3.13 · React · Vite · AWS Lambda · API Gateway · DynamoDB · S3 · CloudFront · EventBridge · SAM · GitHub Actions · Schwab API · Finnhub · Anthropic Claude · Cloudflare*
