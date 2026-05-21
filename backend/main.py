from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env.local")  # No-op in Lambda

from fastapi import FastAPI
from mangum import Mangum

from routers import (
    ai,
    guardrails,
    live_tracking,
    market,
    paper_trading,
    portfolio,
    scanner,
    sentiment,
)
from services import cache_service, dynamo_service

app = FastAPI(title="AI Trading Dashboard")

try:
    dynamo_service.ensure_table_exists()
except Exception:
    pass  # non-fatal in Lambda cold start if table already exists

app.include_router(scanner.router)
app.include_router(portfolio.router)
app.include_router(market.router)
app.include_router(sentiment.router)
app.include_router(guardrails.router)
app.include_router(ai.router)
app.include_router(paper_trading.router)
app.include_router(live_tracking.router)


@app.get("/health")
def health():
    return {"status": "ok"}


handler = Mangum(app)


def price_monitor_handler(event, context):
    """Every 5 min during market hours — auto-closes paper trades at target/stop."""
    return cache_service.run_price_monitor()


def end_of_day_handler(event, context):
    """3:45pm ET — closes all open paper trades, flags live trades for manual close."""
    return cache_service.run_end_of_day()


def refresh_handler(event, context):
    """7am ET — scanner + sentiment → DynamoDB cache."""
    return cache_service.run_daily_refresh()


def analytics_handler(event, context):
    """Nightly — validation, Monte Carlo, Plotly charts. Phase 2."""
    pass
