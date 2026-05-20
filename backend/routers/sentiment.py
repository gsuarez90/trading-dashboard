from fastapi import APIRouter, HTTPException, Query

from services import finnhub_service

router = APIRouter(prefix="/sentiment", tags=["sentiment"])


@router.get("/{ticker}")
def get_sentiment(ticker: str, days: int = Query(default=3, ge=1, le=14)):
    try:
        return finnhub_service.score_sentiment(ticker, days=days)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Sentiment fetch failed: {e}")


@router.get("/batch/scores")
def get_batch_sentiment(
    tickers: str = Query(description="Comma-separated ticker list"),
    days: int = Query(default=3, ge=1, le=14),
):
    try:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        return finnhub_service.score_batch_sentiment(ticker_list, days=days)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Sentiment fetch failed: {e}")
