# Step 24 — README + Architecture Documentation Prompt

Use this prompt with Claude (with the full codebase loaded as context) to generate the final README.md and architecture documentation.

---

## Prompt

You are writing the README.md and architecture documentation for a personal AI-powered trading dashboard called **AI Trading Dashboard**. The audience is the developer who built this app — someone who understands the business logic and daily workflow but is not a strong software engineer and wants a clear, plain-language reference they can return to when they forget how something works.

The documentation should be thorough but readable. No unnecessary jargon. When a technical term is used, define it in one sentence. Write as if explaining to a smart person who works in finance, not to another engineer.

---

### Section 1 — Project Overview

Write a 3–4 paragraph overview that covers:
- What this app is and what problem it solves (daily trading workflow, morning briefing, paper trading before going live)
- Who uses it (single owner, personal use — not a SaaS product)
- The two deployment modes: public demo (synthetic portfolio, anyone can view) and private personal (real portfolio, owner only via Cloudflare Access)
- The philosophy behind the build: paper trade on real data, validate before going live, let Claude assist but not replace judgment

---

### Section 2 — Tech Stack

Write a clean table and brief prose explanation of every technology used and why it was chosen. Cover:

**Frontend:**
- React + Vite — what each one does, why Vite over older tools
- Deployed to S3, served via CloudFront — what that means for performance

**Backend:**
- FastAPI (Python) — what it is, why it's fast
- Mangum — the adapter that lets FastAPI run inside AWS Lambda (explain what an adapter does)
- AWS Lambda — serverless execution model, no server to manage
- API Gateway (HTTP API) — how it connects the internet to Lambda

**Data & Storage:**
- DynamoDB — what it stores (trades, cache, guardrail events), why NoSQL fits here
- SSM Parameter Store — non-secret config values
- Secrets Manager — sensitive credentials (Schwab token, Robinhood, API keys)

**External APIs:**
- Schwab API (schwab-py) — real-time quotes, movers, price history; requires OAuth token
- Finnhub — news headlines for VADER sentiment scoring
- Anthropic Claude API — morning briefing, chat, trade suggestions

**Infrastructure & Security:**
- AWS SAM — what IaC means, how template.yaml describes the whole stack
- GitHub Actions — CI/CD, what happens on every push to main
- Cloudflare — why it sits in front of CloudFront, what it protects
- Cloudflare Access — how the email OTP login wall works

---

### Section 3 — Repository Structure

Walk through every folder and key file in the repo. For each, write one sentence on what it is and one sentence on when you'd touch it. Use a tree diagram. Cover:

```
backend/
  main.py
  routers/          (one line per router file)
  services/         (one line per service file)
  models/schemas.py
  tests/
  requirements.txt
frontend/
  src/components/   (one line per component)
  src/App.jsx
cloudflare/
  setup.md
.github/workflows/
  deploy.yml
  lint.yml
  test-guardrails.yml
template.yaml
samconfig.toml
scripts/
  start.sh
  schwab_auth.py
```

---

### Section 4 — How the App Starts (Local Dev)

Trace exactly what happens when the developer runs `bash scripts/start.sh`:

1. What the script does step by step (venv activation, .env.local loading, uvicorn start, health check poll, Vite start)
2. What `main.py` does on startup (router registration, DynamoDB table check)
3. How environment variables flow from `.env.local` into the Python services
4. What `load_dotenv` does and why it's a no-op in Lambda
5. What URL the developer visits and what they see

---

### Section 5 — Feature Flows (the most important section)

For each feature below, trace the complete path from user action to final result. Use this format for each:

```
Feature Name
─────────────
Trigger:      What the user does (clicks, types, page loads)
Frontend:     Which component, what fetch call, what URL
Backend:      Which router function → which service(s) called → in what order
External:     Any API calls out (Schwab, Finnhub, Claude)
Cache:        Is DynamoDB cache checked? What happens on hit vs miss?
Response:     What comes back, how the component renders it
Error path:   What happens if something fails — what the user sees
```

Cover every feature:

1. **Morning Briefing** — DailySummaryPanel loads on mount, calls GET /ai/briefing, cache-first from DynamoDB, falls back to Claude API call, writes to cache on miss, returns briefing text + minutes remaining in trading day

2. **Scanner — Top Movers** — ScannerPanel loads + auto-polls every 60s (visibility-gated), calls GET /scanner/movers, cache-first from DynamoDB, falls back to Schwab get_quotes on dynamic watchlist (Schwab movers across SPX/Nasdaq/Dow), filters by min price + volume, returns sorted by abs % change

3. **Portfolio** — PortfolioView loads + auto-polls every 90s, calls GET /portfolio/, portfolio_factory selects provider based on PORTFOLIO_MODE (live = Schwab, synthetic = fake data), enriches positions with live Schwab quotes for current price and unrealized P&L

4. **Sentiment Feed** — SentimentFeed loads, calls GET /ai/sentiment, cache-first, falls back to context_loader which runs VADER scoring on Finnhub news for the dynamic watchlist tickers + portfolio holdings, returns compound scores with bullish/bearish/neutral labels

5. **Chat** — ChatPanel user types message, POST /ai/chat, loads full DailyContext (portfolio, movers, sentiment, guardrail events), sends to Claude with system prompt, returns conversational reply

6. **Trade Suggestions** — user clicks Suggest Trades in ChatPanel, POST /ai/suggest-trades, same context load, Claude returns structured list of trade setups (ticker, direction, entry, target, stop, rationale), each rendered as a suggestion card

7. **Paper Trade Submission** — user clicks Paper Trade on a suggestion card, POST /paper-trades/, guardrail_service runs all 8 checks (market hours, daily loss limit, trade count, position size, kill switch, price range, liquidity, pattern day trader), if all pass trade is written to DynamoDB, if any fail a guardrail event is logged and error is returned

8. **Guardrails Panel** — GuardrailsPanel loads + auto-polls every 60s, GET /guardrails/ returns live status of all 8 guardrails (computed from current time + DynamoDB data), GET /guardrails/events returns today's triggered events from DynamoDB, kill switch is a two-step confirm that writes kill_switch=true to DynamoDB

9. **Paper Trading Panel** — three tabs: Open (active paper trades from DynamoDB), History (closed trades), Summary (win rate, avg R/R, total P&L vs daily goal)

10. **Live Tracking Panel** — same three-tab structure as paper trading but for live trades, shows mode notice banner if TRADING_MODE is not "live", close form calls POST /live-trades/{id}/exit

11. **Price Monitor (scheduled)** — EventBridge triggers every 5 min during market hours (9:30am–4pm ET), Lambda calls Schwab get_quotes on all open paper trade tickers, auto-closes trades that hit target or stop, flags live trades for manual review

12. **Daily Refresh (scheduled)** — EventBridge triggers at 7am ET, Lambda calls Schwab movers → Finnhub sentiment → Claude briefing in sequence, writes all three to DynamoDB cache, so the first page load of the day is instant with no API calls

13. **End of Day (scheduled)** — EventBridge triggers at 3:45pm ET, closes all open paper trades at last price, flags open live trades

---

### Section 6 — Data Model

Explain what lives in DynamoDB and how the single table is structured. Cover:

- **Trades** — `trade_id` (UUID hash key), `status` (GSI hash: open/closed/live/guardrail_event/cache), `date` (GSI range), all trade fields
- **Cache items** — `trade_id = "cache#scanner"`, `"cache#sentiment"`, `"cache#briefing"` — how freshness is checked (cached_at date == today ET)
- **Guardrail events** — `status = "guardrail_event"`, queried by date via GSI, used in Claude context and GuardrailsPanel

Explain the GSI (Global Secondary Index) pattern — what it is, why it lets us query by status + date without scanning the whole table.

---

### Section 7 — Architecture Diagram

Draw a complete ASCII diagram showing the full system. It must show:

**Local dev path:**
```
Developer → browser → Vite (5173) → /api proxy → uvicorn FastAPI (8000)
                                                        ↓
                                              Schwab API / Finnhub / Claude API
                                                        ↓
                                                    DynamoDB (AWS)
```

**Production path:**
```
Public user → Cloudflare (rate limit + DDoS) → CloudFront → S3 (public frontend)
                                                     ↓
                                              API Gateway → Lambda (FastAPI/Mangum)
                                                                ↓
                                                    SSM / Secrets Manager / DynamoDB
                                                                ↓
                                              Schwab API / Finnhub / Claude API

Owner → Cloudflare Access (email OTP) → CloudFront → S3 (private frontend)
                                               ↓
                                        (same API Gateway + Lambda as above)
```

**Scheduled jobs:**
```
EventBridge (7am ET)    → DailyRefreshFunction  → Schwab + Finnhub + Claude → DynamoDB cache
EventBridge (*/5 market hours) → PriceMonitorFunction → Schwab quotes → auto-close paper trades
EventBridge (3:45pm ET) → EndOfDayFunction      → close all open paper trades
```

**CI/CD:**
```
git push main → GitHub Actions:
  job 1: sam build + sam deploy → Lambda (backend)
  job 2: npm build (VITE_PORTFOLIO_MODE=synthetic) + s3 sync → public S3 + CloudFront invalidation
  job 3: npm build (VITE_PORTFOLIO_MODE=live)      + s3 sync → private S3 + CloudFront invalidation
```

---

### Section 8 — Guardrails Reference

List all 8 guardrails in a table with: name, what it checks, what happens when triggered. Then explain the kill switch — what it does, how it's reset, why it exists.

---

### Section 9 — Secrets & Credentials Reference

A table of every secret/credential the app uses:

| Name | Where stored | How loaded | Rotated? |
|------|-------------|------------|---------|
| ANTHROPIC_API_KEY | SSM SecureString | SAM resolve at deploy | Manual |
| FINNHUB_API_KEY | SSM SecureString | SAM resolve at deploy | Manual |
| SCHWAB_CLIENT_ID | SSM SecureString | SAM resolve at deploy | Manual |
| SCHWAB_CLIENT_SECRET | SSM SecureString | SAM resolve at deploy | Manual |
| Schwab OAuth token | Secrets Manager | Runtime via boto3 | Auto (schwab-py writes refreshed token) |
| Robinhood credentials | Secrets Manager | Runtime via boto3 | Manual |

Include a note on what `.env.local` is for (local dev only, gitignored, never deployed) and what `.env.example` is for (documents required variables, safe to commit).

---

### Section 10 — Phase Roadmap

Briefly describe the 4 phases and where the app currently is:

- **Phase 1 (current):** Paper trade on real Schwab data. Build daily habit. All 14 guardrail tests must pass before advancing.
- **Phase 2:** Validation analytics — SPY benchmark, random baseline, Monte Carlo, Kelly Criterion. SageMaker pipeline starts (observe only).
- **Phase 3:** Live trading at 25% position size. Manual execution. SageMaker predictions visible but not acted on.
- **Phase 4:** Full live trading. ML predictions active. Optional Alpaca auto-execution.

Include the Phase 2→3 gate criteria (win rate, R/R, benchmark comparisons, Monte Carlo probability).

---

### Tone and Format Instructions

- Write in plain English. Define every acronym the first time it appears.
- Use headers, tables, and code blocks generously — this is a reference document, not prose.
- For the feature flows, be specific about file names and function names (e.g. "calls `cache_service.get_cached_briefing()` in `backend/services/cache_service.py`") so the developer can find the code when something breaks.
- The architecture diagram must be ASCII — no external image dependencies.
- Total length: as long as it needs to be. This is a reference document meant to last through all 4 phases of development.
