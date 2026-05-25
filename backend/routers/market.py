from fastapi import APIRouter, HTTPException, Query

from services import finnhub_service, schwab_service

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/quote/{ticker}")
def get_quote(ticker: str):
    try:
        return finnhub_service.get_quote(ticker)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Finnhub error: {e}")


@router.get("/quotes")
def get_batch_quotes(tickers: str = Query(description="Comma-separated ticker list")):
    try:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        return finnhub_service.get_batch_quotes(ticker_list)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Finnhub error: {e}")


@router.get("/news/{ticker}")
def get_news(ticker: str, days: int = Query(default=7, ge=1, le=30)):
    try:
        return finnhub_service.get_company_news(ticker, days=days)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Finnhub error: {e}")


@router.get("/status")
def get_market_status():
    try:
        return schwab_service.get_market_status()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Market status check failed: {e}")
