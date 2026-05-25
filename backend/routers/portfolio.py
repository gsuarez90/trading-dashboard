from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from services import portfolio_factory, schwab_service

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _enrich_positions(positions: list[dict]) -> list[dict]:
    """Add current_price and unrealized_pnl to each position via Schwab quotes."""
    if not positions:
        return positions

    tickers = [p["ticker"] for p in positions if p.get("ticker")]
    try:
        quotes = {q["ticker"]: q for q in schwab_service.get_batch_quotes(tickers)}
    except Exception:
        quotes = {}

    enriched = []
    for pos in positions:
        ticker = pos.get("ticker")
        quote = quotes.get(ticker, {})
        current_price = quote.get("price") or pos.get("current_price")
        avg_cost = pos.get("avg_cost") or 0
        shares = pos.get("shares") or 0

        unrealized_pnl = None
        unrealized_pnl_pct = None
        if current_price and avg_cost and shares:
            unrealized_pnl = round((current_price - avg_cost) * shares, 2)
            unrealized_pnl_pct = round((current_price - avg_cost) / avg_cost * 100, 2)

        enriched.append(
            {
                **pos,
                "current_price": current_price,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pnl_pct": unrealized_pnl_pct,
            }
        )
    return enriched


@router.get("")
@router.get("/")
def get_portfolio(mode: Optional[str] = Query(default=None)):
    try:
        portfolio = portfolio_factory.get_provider(mode=mode).get_portfolio()
        portfolio["positions"] = _enrich_positions(portfolio.get("positions", []))
        return portfolio
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Portfolio fetch failed: {e}")


@router.get("/cash")
def get_cash(mode: Optional[str] = Query(default=None)):
    try:
        return {"cash": portfolio_factory.get_provider(mode=mode).get_cash()}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Portfolio fetch failed: {e}")
