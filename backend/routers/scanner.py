from fastapi import APIRouter, HTTPException, Query

from services import polygon_service

router = APIRouter(prefix="/scanner", tags=["scanner"])


@router.get("/movers")
def get_movers(
    tickers: str = Query(description="Comma-separated ticker list"),
    limit: int = Query(default=20, ge=2, le=50),
):
    try:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        return polygon_service.get_previous_day_movers(ticker_list, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Polygon API error: {e}")


@router.get("/results")
def get_results(
    tickers: str = Query(description="Comma-separated ticker list"),
    min_change_pct: float = Query(default=2.0, ge=0),
):
    try:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        return polygon_service.get_scanner_results(ticker_list, min_change_pct=min_change_pct)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Polygon API error: {e}")
