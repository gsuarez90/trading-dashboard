import json
import os

import boto3
import robin_stocks.robinhood as rh


def _get_credentials() -> dict:
    username = os.environ.get("ROBINHOOD_USERNAME")
    password = os.environ.get("ROBINHOOD_PASSWORD")
    if username and password:
        return {"username": username, "password": password}
    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("secretsmanager", region_name=region)
    raw = client.get_secret_value(SecretId="/trading-app/robinhood-credentials")["SecretString"]
    return json.loads(raw)


def _login():
    # robin_stocks unconditionally creates ~/.tokens/ in login() — redirect HOME
    # to /tmp so it uses /tmp/.tokens/ which is writable in Lambda.
    os.environ.setdefault("HOME", "/tmp")
    creds = _get_credentials()
    rh.login(
        username=creds["username"],
        password=creds["password"],
        expiresIn=86400,
        store_session=False,
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
