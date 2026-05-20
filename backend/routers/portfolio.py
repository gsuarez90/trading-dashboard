from fastapi import APIRouter, HTTPException

from services import portfolio_factory

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/")
def get_portfolio():
    try:
        return portfolio_factory.get_provider().get_portfolio()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Portfolio fetch failed: {e}")


@router.get("/cash")
def get_cash():
    try:
        return {"cash": portfolio_factory.get_provider().get_cash()}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Portfolio fetch failed: {e}")
