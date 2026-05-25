# Frontend — AI Trading Dashboard

React + Vite single-page app. Builds into a static bundle deployed to S3/CloudFront.

## Development

```bash
npm ci           # install dependencies
npm run dev      # dev server at http://localhost:5173 (proxies /api → localhost:8000)
npm run build    # production build → dist/
npm run lint     # ESLint
```

The dev server proxies `/api/*` to the backend at `:8000`. Start the backend first:
```bash
bash ../scripts/start.sh
```

## Environment variables

Set in `.env.local` for local dev (gitignored). Baked into the bundle at build time by CI.

| Variable | Description |
|---|---|
| `VITE_API_URL` | Backend API base URL. Omit locally (proxy handles it). |
| `VITE_PORTFOLIO_MODE` | `synthetic` (public demo) or `live` (real Robinhood account). |
| `VITE_API_KEY` | Private build only — `x-api-key` header sent on every API request. |

## Two builds from one source

CI produces two separate bundles from this codebase:

- **Public build** (`VITE_PORTFOLIO_MODE=synthetic`) → `s3://trading-dashboard-public` → `ait.gsuarez.dev`
- **Private build** (`VITE_PORTFOLIO_MODE=live`) → `s3://trading-dashboard-private` → `degen.gsuarez.dev` (Cloudflare Access protected)

Both call the same backend. `VITE_PORTFOLIO_MODE` controls which portfolio provider the backend uses.

## Key components

| Component | Description |
|---|---|
| `PortfolioView` | Holdings with live prices, unrealized P&L |
| `DailySummaryPanel` | Morning briefing from Claude, market-closed state |
| `ScannerPanel` | Top movers from Schwab, cached at 9:35 AM ET |
| `SentimentFeed` | Finnhub sentiment scores |
| `ChatPanel` | Free-form Claude chat + trade suggestions |
| `PaperTradingPanel` | Enter/track/close paper trades |
| `LiveTrackingPanel` | Live trade log (manual Robinhood execution) |
| `GuardrailsPanel` | Guardrail status, kill switch, blocked trade log |
