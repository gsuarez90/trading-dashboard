from fastapi import APIRouter, HTTPException, Query

from services import polygon_service

router = APIRouter(prefix="/scanner", tags=["scanner"])


@router.get("/movers")
def get_movers(limit: int = Query(default=20, ge=2, le=50)):
    try:
        return polygon_service.get_intraday_movers(limit=limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Polygon API error: {e}")


@router.get("/results")
def get_results(min_change_pct: float = Query(default=2.0, ge=0)):
    try:
        return polygon_service.get_scanner_results(min_change_pct=min_change_pct)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Polygon API error: {e}")
