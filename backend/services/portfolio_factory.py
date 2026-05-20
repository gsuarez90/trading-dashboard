import os
from typing import Protocol


class PortfolioProvider(Protocol):
    def get_portfolio(self) -> dict: ...
    def get_cash(self) -> float: ...


def get_provider():
    """Returns the portfolio provider module for the current PORTFOLIO_MODE.

    PORTFOLIO_MODE=synthetic  → static demo data, no credentials needed
    PORTFOLIO_MODE=live       → live Robinhood account via robin_stocks
    """
    mode = os.environ.get("PORTFOLIO_MODE", "synthetic").lower()
    if mode == "live":
        from services import robinhood_service

        return robinhood_service
    from services import synthetic_portfolio

    return synthetic_portfolio
