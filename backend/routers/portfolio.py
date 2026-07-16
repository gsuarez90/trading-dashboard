import traceback
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from services import portfolio_factory, schwab_service

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("")
def get_portfolio(mode: Optional[str] = Query(default=None)):
    try:
        portfolio = portfolio_factory.get_provider(mode=mode).get_portfolio()
        portfolio["positions"] = schwab_service.enrich_positions_with_quotes(
            portfolio.get("positions", [])
        )
        return portfolio
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=502, detail=f"Portfolio fetch failed: {e}")


@router.get("/cash")
def get_cash(mode: Optional[str] = Query(default=None)):
    try:
        return {"cash": portfolio_factory.get_provider(mode=mode).get_cash()}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Portfolio fetch failed: {e}")
