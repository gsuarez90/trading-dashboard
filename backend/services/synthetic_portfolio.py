"""
Static portfolio snapshot used by the public demo (PORTFOLIO_MODE=synthetic).
Reflects a realistic but fictional holdings mix — no real account data.
"""

_PORTFOLIO = {
    "cash": 31485.40,
    "equity": 82000.00,
    "positions": [
        {"ticker": "NVDA", "shares": 10.0, "avg_cost": 115.00, "current_price": None},
        {"ticker": "MSFT", "shares": 25.0, "avg_cost": 380.00, "current_price": None},
        {"ticker": "AAPL", "shares": 30.0, "avg_cost": 175.00, "current_price": None},
        {"ticker": "AMZN", "shares": 15.0, "avg_cost": 185.00, "current_price": None},
        {"ticker": "GOOGL", "shares": 20.0, "avg_cost": 165.00, "current_price": None},
    ],
}


def get_portfolio() -> dict:
    return dict(_PORTFOLIO)


def get_cash() -> float:
    return _PORTFOLIO["cash"]
