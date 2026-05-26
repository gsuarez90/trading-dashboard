import base64
import json
import os
from pathlib import Path

import boto3
import robin_stocks.robinhood as rh

_authenticated = False

# Lambda writes HOME to /tmp — token file lands at /tmp/.tokens/robinhood.pickle
_TOKEN_PATH = Path("/tmp/.tokens/robinhood.pickle")
_SESSION_SECRET_ID = "/trading-app/robinhood-session"


def _get_credentials() -> dict:
    username = os.environ.get("ROBINHOOD_USERNAME")
    password = os.environ.get("ROBINHOOD_PASSWORD")
    if username and password:
        return {
            "username": username,
            "password": password,
            "mfa_code": os.environ.get("ROBINHOOD_MFA_CODE", ""),
        }
    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("secretsmanager", region_name=region)
    raw = client.get_secret_value(SecretId="/trading-app/robinhood-credentials")["SecretString"]
    return json.loads(raw)


def _restore_session():
    """Fetch the persisted token from Secrets Manager and write it to /tmp/.tokens/.

    Silently skips if no session is stored yet (first cold start after deploy).
    """
    try:
        region = os.environ.get("AWS_REGION", "us-east-1")
        sm = boto3.client("secretsmanager", region_name=region)
        raw = sm.get_secret_value(SecretId=_SESSION_SECRET_ID)["SecretString"]
        token_b64 = json.loads(raw).get("token")
        if not token_b64:
            return
        _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_TOKEN_PATH, "wb") as f:
            f.write(base64.b64decode(token_b64))
    except Exception:
        pass


def _save_session():
    """Write the current /tmp/.tokens/ pickle back to Secrets Manager.

    Called after every successful login so the next cold start reuses the token
    and skips the device-approval flow. Silently no-ops on local dev where the
    SM secret doesn't exist.
    """
    try:
        if not _TOKEN_PATH.exists():
            return
        with open(_TOKEN_PATH, "rb") as f:
            token_b64 = base64.b64encode(f.read()).decode()
        region = os.environ.get("AWS_REGION", "us-east-1")
        sm = boto3.client("secretsmanager", region_name=region)
        sm.put_secret_value(
            SecretId=_SESSION_SECRET_ID,
            SecretString=json.dumps({"token": token_b64}),
        )
    except Exception:
        pass


def _login():
    global _authenticated
    if _authenticated:
        return
    os.environ["HOME"] = "/tmp"
    _restore_session()
    creds = _get_credentials()

    login_kwargs = dict(
        username=creds["username"],
        password=creds["password"],
        expiresIn=86400,
        store_session=True,
    )
    mfa_code = creds.get("mfa_code")
    if mfa_code:
        login_kwargs["mfa_code"] = mfa_code

    rh.login(**login_kwargs)
    _save_session()
    _authenticated = True


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
