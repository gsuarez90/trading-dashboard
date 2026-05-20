from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env.local")  # No-op in Lambda

from fastapi import FastAPI
from mangum import Mangum

from routers import scanner

app = FastAPI(title="AI Trading Dashboard")
app.include_router(scanner.router)


@app.get("/health")
def health():
    return {"status": "ok"}


handler = Mangum(app)


def price_monitor_handler(event, context):
    """Every 5 min during market hours — checks open trades against Polygon prices."""
    pass


def end_of_day_handler(event, context):
    """3:45pm ET — auto-closes paper trades, flags live trades for manual close."""
    pass


def refresh_handler(event, context):
    """7am ET — scanner + sentiment → DynamoDB cache."""
    pass


def analytics_handler(event, context):
    """Nightly — validation, Monte Carlo, Plotly charts. Phase 2."""
    pass
