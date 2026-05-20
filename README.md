# AI Trading Dashboard

A personal AI-assisted stock trading dashboard. Scans for movers each morning, suggests intraday cash trades targeting a daily P&L goal, tracks paper trades, and eventually executes via Robinhood with manual confirmation.

Built with FastAPI + AWS Lambda, Claude as the trading brain, and a React frontend with a public demo mode and a private live mode.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend API | Python 3.13, FastAPI, Mangum |
| AI | Anthropic Claude (claude-sonnet-4-6) |
| Market Data | yfinance (scanner/history), Finnhub (news/quotes), Schwab API (real-time, pending) |
| Brokerage | Robinhood via robin_stocks (read positions + cash) |
| Infrastructure | AWS Lambda, API Gateway, DynamoDB, S3, CloudFront, EventBridge |
| IaC | AWS SAM |
| CI/CD | GitHub Actions (OIDC, no static credentials) |
| Frontend | React + Vite (planned) |

---

## Deployment

Two independent deployments share the same backend code:

| Version | URL | Portfolio Mode |
|---------|-----|----------------|
| Public demo | `trading-dashboard.com` | Synthetic (no real data) |
| Private / live | `private.trading-dashboard.com` | Live Robinhood account |

The private version is protected by Lambda@Edge HTTP Basic Auth.

---

## Local Setup

### Prerequisites
- Python 3.13
- Node.js 24+
- AWS SAM CLI
- A `.env.local` file at the repo root (see `.env.example`)

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate       # Windows
pip install -r requirements-dev.txt
uvicorn main:app --reload
```

API available at `http://localhost:8000`. Interactive docs at `/docs`.

### Verify APIs

```bash
cd scripts
..\backend\.venv\Scripts\activate
python verify_apis.py
```

---

## Environment Variables

Copy `.env.example` to `.env.local` and fill in your keys. See `.env.example` for all required variables.

Key settings:

| Variable | Values | Description |
|----------|--------|-------------|
| `PORTFOLIO_MODE` | `synthetic` / `live` | Use demo data or real Robinhood account |
| `TRADING_MODE` | `paper` / `live` | Paper track or real execution |
| `TRADE_SCOPE` | `open` / `holdings_only` | Buy new positions or manage existing only |
| `DAILY_GOAL` | number | Target daily cash P&L in dollars |
| `DAILY_LOSS_LIMIT` | number | Hard stop — no new trades after this loss |

**Never commit `.env.local`.** It is gitignored. All secrets in production go through AWS SSM Parameter Store.

---

## Project Structure

```
├── backend/
│   ├── main.py                      # FastAPI app + Lambda handlers
│   ├── routers/
│   │   ├── market.py                # GET /market/quote, /market/quotes, /market/news
│   │   ├── portfolio.py             # GET /portfolio/ (enriched), /portfolio/cash
│   │   ├── scanner.py               # GET /scanner/movers, /scanner/results
│   │   ├── sentiment.py             # GET /sentiment/{ticker}, /sentiment/batch/scores
│   │   └── guardrails.py            # GET /guardrails/status, POST /guardrails/kill-switch
│   ├── models/
│   │   └── schemas.py               # Pydantic models: TradeSetup, PaperTrade, DailyCashSummary
│   ├── services/
│   │   ├── dynamo_service.py        # DynamoDB CRUD for trade records
│   │   ├── finnhub_service.py       # Quotes, news, and VADER sentiment scoring via Finnhub
│   │   ├── polygon_service.py       # Daily bars + movers via yfinance
│   │   ├── portfolio_factory.py     # Returns live or synthetic provider
│   │   ├── robinhood_service.py     # Live positions + cash via robin_stocks
│   │   ├── guardrail_service.py     # 8 guardrails, kill switch, GuardrailContext/Result
│   │   └── synthetic_portfolio.py  # Static demo data for public version
│   └── tests/
│   │   └── test_dynamo_service.py   # DynamoDB service tests (moto mock)
├── frontend/                        # React + Vite (planned)
├── scripts/
│   └── verify_apis.py               # Pre-build API connectivity check
├── .github/workflows/               # CI/CD (deploy, lint, test-guardrails)
├── .env.example                     # Key reference — no real values
└── template.yaml                    # AWS SAM IaC (planned)
```

---

## Trading Guardrails

Eight hard guardrails enforced before any trade executes (paper or live):

1. Daily loss limit — no new trades after hitting `DAILY_LOSS_LIMIT`
2. Daily trade count — max `DAILY_TRADE_LIMIT` trades per day
3. Max position size — no single trade exceeds `MAX_POSITION_SIZE_PCT` of cash
4. Market hours only — no trades outside 9:30am–4:00pm ET
5. Min liquidity — position must meet minimum volume threshold
6. No duplicate positions — can't open a position already held
7. Paper mode guard — live execution blocked unless `TRADING_MODE=live`
8. Manual confirmation — all live trades require explicit user approval

These are tested in `backend/tests/test_guardrails.py` and block merge via GitHub Actions if they fail.

---

## Development Status

- [x] Phase 0 — Scaffolding, CI/CD, API verification
- [ ] Phase 1 — Core trading loop (scanner → Claude → paper trades → DynamoDB)
  - [x] Step 1 — Project structure, pyproject.toml, requirements
  - [x] Step 2 — Scanner router + yfinance market data service
  - [x] Step 3 — Portfolio layer (Robinhood + synthetic + factory)
  - [x] Step 4 — Portfolio router with HoldingContext enrichment (current price + unrealized P&L)
  - [x] Step 5 — Finnhub sentiment scoring (VADER) + sentiment router + market router
  - [x] Step 5b — Pydantic schemas + DynamoDB service + moto tests (built early as foundation)
  - [x] Step 6 — `guardrail_service.py` — all 8 guardrails + kill switch + guardrails router
  - [ ] Step 7 — Claude trade suggestion service
  - [ ] Step 8 — Morning briefing Lambda
  - [ ] Step 9 — Price monitor Lambda
- [ ] Phase 2 — Frontend dashboard
- [ ] Phase 3 — Live trading + Robinhood execution
- [ ] Phase 4 — SageMaker ML on trade history
