from fastapi import APIRouter, HTTPException, Query

from services import market_data_service, portfolio_factory

router = APIRouter(prefix="/scanner", tags=["scanner"])


def _resolve_tickers(tickers: str | None) -> list[str]:
    if tickers:
        return [t.strip().upper() for t in tickers.split(",") if t.strip()]
    provider = portfolio_factory.get_provider()
    portfolio = provider.get_portfolio()
    return [p["ticker"] for p in portfolio.get("positions", [])]


@router.get("/movers")
def get_movers(
    tickers: str | None = Query(default=None, description="Comma-separated ticker list; defaults to portfolio holdings"),
    limit: int = Query(default=20, ge=2, le=50),
):
    try:
        return market_data_service.get_previous_day_movers(_resolve_tickers(tickers), limit=limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Market data error: {e}")


@router.get("/results")
def get_results(
    tickers: str | None = Query(default=None, description="Comma-separated ticker list; defaults to portfolio holdings"),
    min_change_pct: float = Query(default=2.0, ge=0),
):
    try:
        return market_data_service.get_scanner_results(_resolve_tickers(tickers), min_change_pct=min_change_pct)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Market data error: {e}")
