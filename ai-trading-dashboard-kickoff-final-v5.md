# Claude Code Kickoff Prompt — AI Trading Dashboard (Final v5)

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

## Full Architecture

```
Public version (yourapp.com):
  Porkbun DNS (CNAME → CloudFront)
    → CloudFront + AWS Shield Standard (CDN + SSL + DDoS)
      → S3 (React frontend files)
        → API Gateway
          → Lambda (FastAPI backend)
            → DynamoDB (trade data)
            → S3 (Plotly analytics charts)

Personal version (private.yourapp.com):
  Porkbun DNS (CNAME → CloudFront)
    → CloudFront + Lambda@Edge (CDN + SSL + HTTP Basic Auth)
      → S3 (React frontend files — private bucket)
        → API Gateway
          → Lambda (FastAPI backend — live Robinhood)
            → DynamoDB
            → S3 (charts)
```

100% AWS infrastructure. One account, one bill, one ecosystem.

---

## Full Product Roadmap

```
Phase 1 — Build + Paper Trade (4-6 weeks)
  Core app built and running
  Paper trades against real Polygon.io market data
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
- `synthetic` — generated portfolio using real Polygon.io prices (cloud demo)

**Trading Mode:**
- `paper` — simulated trades tracked against real market prices
- `live` — manually placed trades logged and tracked

**Trade Scope:**
- `holdings_only`*(might want to separate into a cash holding and b stock holdings)* — Claude only suggests trades using stocks already owned
- `open` — Claude suggests from daily scanner
- `both` — Claude considers both

**Profit Mode:**
- `cash_intraday` — all positions opened and closed same day
- `swing` — positions can be held overnight
- `holdings` — trade around existing positions

**Recommended starting config:**
```
PORTFOLIO_MODE=live
TRADING_MODE=paper
TRADE_SCOPE=holdings_only
PROFIT_MODE=cash_intraday
DAILY_GOAL=100
```

---

## Tech Stack

### Phase 1 — Core
- **Backend**: Python 3.13, FastAPI, Mangum (Lambda adapter)
- **AI Layer**: Anthropic Claude API (claude-sonnet-4-20250514)
- **Market Data**: Polygon.io (free tier)
- **News/Sentiment**: Finnhub (free tier)
- **Portfolio read**: robin_stocks (read-only, no order placement)
- **Portfolio synthetic**: Internal generator using Polygon.io prices
- **Paper Trading**: Internal engine, DynamoDB persistence
- **Database**: DynamoDB (AWS free tier)
- **Frontend hosting**: AWS S3 + CloudFront
- **Backend hosting**: AWS Lambda + API Gateway
- **Scheduler**: AWS EventBridge
- **Security/Routing**: Cloudflare (rate limiting, DDoS, Access auth)
- **CI/CD**: GitHub Actions
- **IaC**: AWS SAM (template.yaml)

### Phase 2 additions
- **Validation**: validation_service.py
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
7:00am ET     Daily Refresh Lambda
              Scanner + sentiment → DynamoDB cache

9:30am ET     Price Monitor Lambda starts (market hours)
              Every 5 min — checks open paper/live trades
              Auto-closes trades hitting target or stop via Polygon.io

3:45pm ET     End of Day Lambda
              Auto-closes remaining open paper trades at market price
              Flags open live trades → dashboard alert for manual close

4:00pm ET     Price Monitor Lambda stops

Nightly       Analytics Lambda (Phase 2+)
              Validation, Monte Carlo, conditions analysis
              Plotly charts → S3
              Results → DynamoDB

Weekly        SageMaker Training Job (Phase 2+)
              Retrains ML model on accumulated trade data

Public Demo Lambda
              Always available at yourapp.com
              Synthetic portfolio, paper mode
              Cloudflare rate limited (30 req/min per IP)
```

---

## S3 + CloudFront Frontend Hosting

### Two S3 buckets — one per deployment:
```
trading-dashboard-public      → yourapp.com (public demo)
trading-dashboard-private     → private.yourapp.com (personal)
```

### CloudFront distributions — one per bucket:
- SSL certificate (AWS Certificate Manager — free)
- Global CDN distribution
- Cache invalidation on every deploy

### CI/CD — GitHub Actions builds and deploys both:
```yaml
- name: Build React app
  run: cd frontend && npm run build

- name: Deploy public frontend to S3
  run: aws s3 sync frontend/dist s3://trading-dashboard-public
  env:
    VITE_API_URL: ${{ secrets.PUBLIC_API_URL }}
    VITE_PORTFOLIO_MODE: synthetic

- name: Deploy private frontend to S3
  run: aws s3 sync frontend/dist s3://trading-dashboard-private
  env:
    VITE_API_URL: ${{ secrets.PRIVATE_API_URL }}
    VITE_PORTFOLIO_MODE: live

- name: Invalidate CloudFront caches
  run: |
    aws cloudfront create-invalidation \
      --distribution-id ${{ secrets.PUBLIC_CF_ID }} --paths "/*"
    aws cloudfront create-invalidation \
      --distribution-id ${{ secrets.PRIVATE_CF_ID }} --paths "/*"
```

Every push to main deploys both versions automatically.

---

## Cloudflare Configuration

### Public version (yourapp.com):
- DNS A record → CloudFront distribution URL
- Rate limiting: 30 requests/min per IP → block 1 hour
- Bot Fight Mode: on
- DDoS protection: on (automatic, free)

### Personal version (private.yourapp.com):
- DNS A record → CloudFront distribution URL
- Cloudflare Access application:
  - Authentication: One-time PIN to your email
  - Policy: allow your email address only
  - Everyone else: blocked, can't see anything
- No rate limiting needed (personal use only)

---

## Project Structure
```
trading-dashboard/
├── backend/
│   ├── main.py                          # FastAPI app + all Lambda handlers
│   ├── routers/
│   │   ├── scanner.py
│   │   ├── sentiment.py
│   │   ├── portfolio.py
│   │   ├── backtest.py
│   │   ├── ai.py                        # Briefing + chat + suggestions
│   │   ├── paper_trading.py
│   │   ├── live_tracking.py
│   │   ├── guardrails.py
│   │   ├── validation.py                # Phase 2
│   │   └── analytics.py                 # Phase 2
│   ├── services/
│   │   ├── polygon_service.py
│   │   ├── finnhub_service.py
│   │   ├── robinhood_service.py         # Read-only
│   │   ├── synthetic_portfolio.py
│   │   ├── portfolio_factory.py
│   │   ├── claude_service.py
│   │   ├── context_loader.py
│   │   ├── paper_trading_service.py
│   │   ├── live_tracking_service.py
│   │   ├── guardrail_service.py
│   │   ├── validation_service.py        # Phase 2
│   │   ├── analytics_service.py         # Phase 2
│   │   ├── sagemaker_service.py         # Phase 2
│   │   └── dynamo_service.py
│   ├── models/
│   │   └── schemas.py
│   ├── tests/
│   │   ├── test_guardrails.py
│   │   ├── test_paper_trading.py
│   │   ├── test_validation.py           # Phase 2
│   │   ├── test_analytics.py            # Phase 2
│   │   └── test_claude_service.py
│   ├── requirements.txt
│   └── template.yaml                    # AWS SAM
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ScannerPanel.jsx
│   │   │   ├── SentimentFeed.jsx
│   │   │   ├── PortfolioView.jsx
│   │   │   ├── BacktestPanel.jsx
│   │   │   ├── AIBriefing.jsx
│   │   │   ├── ChatPanel.jsx
│   │   │   ├── PaperTradingPanel.jsx
│   │   │   ├── LiveTrackingPanel.jsx
│   │   │   ├── DailySummaryPanel.jsx
│   │   │   ├── GuardrailsPanel.jsx
│   │   │   ├── ValidationPanel.jsx      # Phase 2
│   │   │   └── AnalyticsPanel.jsx       # Phase 2
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── package.json
│   └── vite.config.js
├── sagemaker/                           # Phase 2
│   ├── feature_engineering.py
│   ├── train.py
│   ├── inference.py
│   └── pipeline.py
├── .github/
│   └── workflows/
│       └── deploy.yml                   # Deploys Lambda + both S3 frontends
├── .env.example
├── .env.local                           # gitignored
└── README.md
```

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

### 14 Guardrail Tests — all must pass before TRADING_MODE=live
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

## AWS SAM Template (`template.yaml`)

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31

Globals:
  Function:
    Timeout: 30
    MemorySize: 512
    Environment:
      Variables:
        PORTFOLIO_MODE: !Sub '{{resolve:ssm:/trading-app/portfolio-mode}}'
        TRADING_MODE: !Sub '{{resolve:ssm:/trading-app/trading-mode}}'
        PROFIT_MODE: !Sub '{{resolve:ssm:/trading-app/profit-mode}}'
        ANTHROPIC_API_KEY: !Sub '{{resolve:ssm-secure:/trading-app/anthropic-key}}'
        POLYGON_API_KEY: !Sub '{{resolve:ssm-secure:/trading-app/polygon-key}}'
        FINNHUB_API_KEY: !Sub '{{resolve:ssm-secure:/trading-app/finnhub-key}}'
        DYNAMO_TABLE_NAME: trading-dashboard
        S3_CHARTS_BUCKET: trading-dashboard-charts

Resources:
  # Public demo API
  TradingDashboardFunction:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: backend/
      Handler: main.handler
      Runtime: python3.13
      ReservedConcurrentExecutions: 5
      Policies:
        - AWSSecretsManagerGetSecretValuePolicy:
            SecretArn: !Ref RobinhoodCredentials
      Events:
        Api:
          Type: HttpApi
          Properties:
            Path: /{proxy+}
            Method: ANY

  # Price monitor — every 5 min, market hours
  PriceMonitorFunction:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: backend/
      Handler: main.price_monitor_handler
      Runtime: python3.13
      ReservedConcurrentExecutions: 2
      Events:
        MarketHours:
          Type: Schedule
          Properties:
            Schedule: cron(*/5 13-21 ? * MON-FRI *)

  # End of day — 3:45pm ET
  EndOfDayFunction:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: backend/
      Handler: main.end_of_day_handler
      Runtime: python3.13
      ReservedConcurrentExecutions: 1
      Events:
        EOD:
          Type: Schedule
          Properties:
            Schedule: cron(45 20 ? * MON-FRI *)

  # Daily 7am context refresh
  DailyRefreshFunction:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: backend/
      Handler: main.refresh_handler
      Runtime: python3.13
      Events:
        DailyTrigger:
          Type: Schedule
          Properties:
            Schedule: cron(0 12 * * ? *)

  # Nightly analytics + validation — Phase 2
  AnalyticsFunction:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: backend/
      Handler: main.analytics_handler
      Runtime: python3.13
      Timeout: 300
      MemorySize: 1024
      Events:
        NightlyAnalytics:
          Type: Schedule
          Properties:
            Schedule: cron(0 22 * * ? *)    # 6pm ET

  # Secrets Manager — Robinhood credentials (private Lambda only)
  RobinhoodCredentials:
    Type: AWS::SecretsManager::Secret
    Properties:
      Name: /trading-app/robinhood-credentials
      Description: Robinhood username and password for private Lambda
      SecretString: '{"username": "placeholder", "password": "placeholder"}'
  # After sam deploy, populate real values via CLI (never stored in code or git):
  # aws secretsmanager put-secret-value \
  #   --secret-id /trading-app/robinhood-credentials \
  #   --secret-string '{"username": "real_user", "password": "real_pass"}'

  # S3 — public frontend
  PublicFrontendBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: trading-dashboard-public
      WebsiteConfiguration:
        IndexDocument: index.html

  # S3 — private frontend
  PrivateFrontendBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: trading-dashboard-private
      WebsiteConfiguration:
        IndexDocument: index.html

  # S3 — Plotly analytics charts
  ChartsBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: trading-dashboard-charts

  # CloudFront — public
  PublicDistribution:
    Type: AWS::CloudFront::Distribution
    Properties:
      DistributionConfig:
        Origins:
          - DomainName: !GetAtt PublicFrontendBucket.RegionalDomainName
            Id: PublicS3Origin
        DefaultCacheBehavior:
          ViewerProtocolPolicy: redirect-to-https
          TargetOriginId: PublicS3Origin
        Enabled: true
        DefaultRootObject: index.html

  # CloudFront — private
  PrivateDistribution:
    Type: AWS::CloudFront::Distribution
    Properties:
      DistributionConfig:
        Origins:
          - DomainName: !GetAtt PrivateFrontendBucket.RegionalDomainName
            Id: PrivateS3Origin
        DefaultCacheBehavior:
          ViewerProtocolPolicy: redirect-to-https
          TargetOriginId: PrivateS3Origin
        Enabled: true
        DefaultRootObject: index.html
```

---

## GitHub Actions (`deploy.yml`)

```yaml
name: Deploy Trading Dashboard

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - uses: aws-actions/setup-sam@v2

      - uses: aws-actions/configure-aws-credentials@v2
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1

      # Deploy Lambda functions
      - run: sam build
      - run: sam deploy --no-confirm-changeset --no-fail-on-empty-changeset

      # Build and deploy public frontend
      - name: Build public frontend
        run: cd frontend && npm install && npm run build
        env:
          VITE_API_URL: ${{ secrets.PUBLIC_API_URL }}
          VITE_PORTFOLIO_MODE: synthetic

      - name: Deploy public frontend to S3
        run: aws s3 sync frontend/dist s3://trading-dashboard-public --delete

      - name: Invalidate public CloudFront cache
        run: |
          aws cloudfront create-invalidation \
            --distribution-id ${{ secrets.PUBLIC_CF_DIST_ID }} \
            --paths "/*"

      # Build and deploy private frontend
      - name: Build private frontend
        run: cd frontend && npm run build
        env:
          VITE_API_URL: ${{ secrets.PRIVATE_API_URL }}
          VITE_PORTFOLIO_MODE: live

      - name: Deploy private frontend to S3
        run: aws s3 sync frontend/dist s3://trading-dashboard-private --delete

      - name: Invalidate private CloudFront cache
        run: |
          aws cloudfront create-invalidation \
            --distribution-id ${{ secrets.PRIVATE_CF_DIST_ID }} \
            --paths "/*"
```

One push to main deploys everything — Lambda functions, public frontend, private frontend. Fully automated.

---

## Environment Variables

### `.env.example`
```
PORTFOLIO_MODE=synthetic
TRADING_MODE=paper
TRADE_SCOPE=holdings_only
PROFIT_MODE=cash_intraday
DAILY_GOAL=100
DAILY_LOSS_LIMIT=200
MAX_POSITION_SIZE_PCT=20
DAILY_TRADE_LIMIT=3
ANTHROPIC_API_KEY=
POLYGON_API_KEY=
FINNHUB_API_KEY=
ROBINHOOD_USERNAME=
ROBINHOOD_PASSWORD=
DYNAMO_TABLE_NAME=trading-dashboard
S3_CHARTS_BUCKET=trading-dashboard-charts
SAGEMAKER_ENDPOINT=trading-dashboard-endpoint
AWS_REGION=us-east-1
```

### `.env.local` (gitignored — your personal file)
```
PORTFOLIO_MODE=live
TRADING_MODE=paper
TRADE_SCOPE=holdings_only
PROFIT_MODE=cash_intraday
DAILY_GOAL=100
DAILY_LOSS_LIMIT=200
MAX_POSITION_SIZE_PCT=20
DAILY_TRADE_LIMIT=3
ANTHROPIC_API_KEY=your_key
POLYGON_API_KEY=your_key
FINNHUB_API_KEY=your_key
ROBINHOOD_USERNAME=your_username
ROBINHOOD_PASSWORD=your_password
DYNAMO_TABLE_NAME=trading-dashboard
S3_CHARTS_BUCKET=trading-dashboard-charts
SAGEMAKER_ENDPOINT=trading-dashboard-endpoint
AWS_REGION=us-east-1
```

### AWS SSM Parameters (cloud secrets — SecureString, KMS-encrypted)
```
/trading-app/portfolio-mode  → synthetic
/trading-app/trading-mode    → paper
/trading-app/profit-mode     → cash_intraday
/trading-app/anthropic-key   → key
/trading-app/polygon-key     → key
/trading-app/finnhub-key     → key
```

### AWS Secrets Manager (private Lambda only)
```
/trading-app/robinhood-credentials  → {"username": "...", "password": "..."}
```
Populated manually via CLI after deploy. Never stored in code or git.

---

## Local Development
```bash
# Backend — live portfolio, paper trading
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --env-file .env.local

# Frontend
cd frontend
npm install
npm run dev
```

Local: `http://localhost:8000` (API), `http://localhost:5173` (UI)

---

## Build Order

### Phase 1
1. `main.py` + Mangum handler + health check
2. `polygon_service.py` + scanner router + `get_intraday_movers()`
3. `synthetic_portfolio.py` + `robinhood_service.py` + `portfolio_factory.py`
4. `portfolio.py` router + `HoldingContext` enrichment with cost basis
5. `finnhub_service.py` + sentiment router
6. `guardrail_service.py` — all 8 guardrails
7. `tests/test_guardrails.py` — all 14 tests passing
8. `context_loader.py` — full daily context assembly
9. `schemas.py` — all Phase 1 models
10. `claude_service.py` + `/ai/briefing` endpoint
11. `/ai/chat` + `/ai/suggest-trades` endpoints
12. `paper_trading_service.py` + paper trading endpoints
13. `live_tracking_service.py` + live trade logging endpoints
14. React frontend — scanner, sentiment, portfolio panels
15. `DailySummaryPanel.jsx`
16. `ChatPanel.jsx` — suggestion cards + RH instructions
17. `PaperTradingPanel.jsx` — 3 tabs
18. `LiveTrackingPanel.jsx`
19. `GuardrailsPanel.jsx`
20. DynamoDB caching layer
21. AWS SAM deploy — Lambda functions + S3 buckets + CloudFront distributions
22. GitHub Actions CI/CD — deploys Lambda + both S3 frontends
23. Cloudflare DNS + rate limiting (public) + Access auth (private)
24. README + architecture diagram

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
□ 4-6 weeks paper trading data
□ Basic win rate and P&L metrics stable
□ All 14 guardrail tests passing
□ Daily workflow established
□ 3:45pm alarm habit consistent
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
Compute:      Lambda, API Gateway
Storage:      S3 (3 buckets), DynamoDB
CDN:          CloudFront
Scheduler:    EventBridge
ML:           SageMaker (Phase 2)
Security:     IAM, SSM Parameter Store (SecureString), Secrets Manager, KMS
IaC:          SAM (CloudFormation)
CI/CD:        GitHub Actions
External:     Cloudflare (DNS, CDN security, Access auth)
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

## README (Portfolio-Ready)
```
# AI Trading Dashboard

A personal AI-assisted stock trading tool built on a fully serverless
AWS infrastructure stack.

## Tech Stack
FastAPI · Python 3.13 · Anthropic Claude API · AWS Lambda · API Gateway ·
DynamoDB · S3 · CloudFront · EventBridge · SageMaker · SAM · GitHub Actions ·
Cloudflare · Polygon.io · Finnhub

## Problem
Retail traders lack affordable access to the scanning, sentiment analysis,
AI synthesis, and quantitative validation that institutional desks use daily.
Commercial tools solving this cost $200-400/month.

## Solution
A personal dashboard that scans stocks, scores news sentiment, and provides
a conversational interface where the user asks Claude to generate trade
suggestions targeting a daily cash P&L goal. Validated against market
benchmarks, modeled with Monte Carlo simulation, and enhanced with a
SageMaker ML probability layer. Deployed fully serverlessly for ~$1-12/month.

## Architecture
[diagram — fully serverless AWS, two CloudFront/S3 deployments,
 5 Lambda functions, Cloudflare security layer]

## Key Features
- Morning AI briefing + conversational trade queries
- Holdings-only mode with cost basis protection
- Structured suggestion cards with Robinhood placement instructions
- Paper trading engine on real Polygon.io market data
- SPY benchmark + random baseline + slippage validation
- Monte Carlo simulation, Kelly Criterion, conditions analysis
- SageMaker ML trade probability scoring
- 8 production guardrails tested before real money
- Public demo + private personal version from one codebase
- Fully serverless — runs whether laptop is on or not

## Phased Roadmap
Phase 1: Core app + paper trading (~$1/mo)
Phase 2: Validation + analytics + SageMaker init (~$4-7/mo)
Phase 3: Live trading small size + ML calibration
Phase 4: Full live trading + ML active + Alpaca option (~$6-12/mo)

## Live Demo
[yourapp.com]

## Local Setup
...

## Going Live Checklist
[transition checklists above]
```

---

## Future Considerations

- **Native CloudFormation IaC practice:** SAM generates and deploys CloudFormation under the hood. At some point, consider writing infrastructure directly in native CloudFormation (without SAM abstractions) as a hands-on IaC exercise — useful for AWS SAA-C03 depth and portfolio.
- **Lambda vs. Batch (confirmed: Lambda):** All functions are correctly Lambda. The heaviest is the nightly Analytics Lambda (Phase 2, 5-min timeout, 1024MB) running Monte Carlo + benchmarks + Plotly charts. At personal-trader scale (~400 trades over 6 months), NumPy/Pandas/SciPy operations complete in well under 1 minute — far below the timeout. Batch would add Docker/ECR/ECS overhead, minute-scale cold starts, and complexity with no benefit. Only revisit if the Analytics Lambda actually times out in production. SageMaker handles heavy ML training (Phase 2+) — Lambda and Batch are both wrong for that.
