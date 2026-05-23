import os
from typing import Protocol


class PortfolioProvider(Protocol):
    def get_portfolio(self) -> dict: ...
    def get_cash(self) -> float: ...


def get_provider(mode: str | None = None):
    """Returns the portfolio provider module.

    mode param (from request) takes precedence over PORTFOLIO_MODE env var.
    PORTFOLIO_MODE=synthetic  → static demo data, no credentials needed
    PORTFOLIO_MODE=live       → live Robinhood account via robin_stocks
    """
    resolved = (mode or os.environ.get("PORTFOLIO_MODE", "synthetic")).lower()
    if resolved == "live":
        from services import robinhood_service

        return robinhood_service
    from services import synthetic_portfolio

    return synthetic_portfolio
