import os

import robin_stocks.robinhood as rh


def _login():
    rh.login(
        username=os.environ["ROBINHOOD_USERNAME"],
        password=os.environ["ROBINHOOD_PASSWORD"],
        expiresIn=86400,
        store_session=True,
    )


def get_portfolio() -> dict:
    """Returns cash, equity, and open positions from Robinhood.

    Returned shape:
    {
        "cash": float,
        "equity": float,
        "positions": [
            {"ticker": str, "shares": float, "avg_cost": float, "current_price": float|None},
            ...
        ]
    }
    """
    _login()

    profile = rh.load_portfolio_profile()
    cash = float(profile.get("withdrawable_amount") or profile.get("cash") or 0)
    equity = float(profile.get("equity") or 0)

    raw_positions = rh.get_open_stock_positions()
    positions = []
    for pos in raw_positions:
        instrument_url = pos.get("instrument")
        ticker = None
        current_price = None

        if instrument_url:
            try:
                instrument = rh.get_instrument_by_url(instrument_url)
                ticker = instrument.get("symbol")
            except Exception:
                pass

        if ticker:
            try:
                quote = rh.get_latest_price(ticker)
                current_price = float(quote[0]) if quote else None
            except Exception:
                pass

        positions.append(
            {
                "ticker": ticker,
                "shares": float(pos.get("quantity") or 0),
                "avg_cost": float(pos.get("average_buy_price") or 0),
                "current_price": current_price,
            }
        )

    return {"cash": cash, "equity": equity, "positions": positions}


def get_cash() -> float:
    _login()
    profile = rh.load_portfolio_profile()
    return float(profile.get("withdrawable_amount") or profile.get("cash") or 0)
