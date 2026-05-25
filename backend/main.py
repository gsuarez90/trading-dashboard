from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env.local")  # No-op in Lambda

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from starlette.requests import Request

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

app = FastAPI(title="AI Trading Dashboard", redirect_slashes=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ait.gsuarez.dev", "https://degen.gsuarez.dev", "http://localhost:5173"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "x-api-key"],
)

@app.middleware("http")
async def strip_trailing_slash(request: Request, call_next):
    if request.url.path != "/" and request.url.path.endswith("/"):
        request.scope["path"] = request.url.path.rstrip("/")
    return await call_next(request)


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
    """9:35am ET weekdays — scanner + sentiment + synthetic briefing → DynamoDB cache."""
    return cache_service.run_daily_refresh()


def refresh_live_briefing_handler(event, context):
    """9:35am ET weekdays — live briefing with real Robinhood portfolio → DynamoDB cache."""
    return cache_service.run_live_briefing_refresh()


def analytics_handler(event, context):
    """Nightly — validation, Monte Carlo, Plotly charts. Phase 2."""
    pass
