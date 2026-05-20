"""
Run this script to verify all API connections before building.

  cd scripts
  ..\backend\.venv\Scripts\activate
  python verify_apis.py

NOTE — Schwab first-run: a browser window will open for OAuth login.
After you approve, tokens are saved to schwab_token.json in the scripts folder.
Subsequent runs reuse the saved token (no browser needed until the 7-day refresh expires).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=ROOT / ".env.local")

PASS = "  OK"
FAIL = "  FAIL"
SKIP = "  SKIP (key not set)"


def check(label: str, fn):
    try:
        result = fn()
        print(f"{PASS}  {label}")
        print(f"        {result}\n")
    except Exception as e:
        print(f"{FAIL}  {label}")
        print(f"        {e}\n")


def skip(label: str):
    print(f"{SKIP}  {label}\n")


# ── yfinance ────────────────────────────────────────────────────────────────

def verify_yfinance():
    import yfinance as yf

    def test_current_quote():
        info = yf.Ticker("AAPL").fast_info
        return (
            f"AAPL  last={info.last_price:.2f}  "
            f"prev_close={info.previous_close:.2f}  "
            f"change={((info.last_price - info.previous_close) / info.previous_close * 100):+.2f}%"
        )

    def test_batch_movers():
        tickers = ["AAPL", "MSFT", "NVDA", "TSLA", "GOOGL", "META", "AMZN"]
        data = yf.download(tickers, period="2d", interval="1d", progress=False, auto_adjust=True)
        closes = data["Close"]
        changes = ((closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2] * 100).round(2)
        top = changes.abs().nlargest(3)
        return "  ".join([f"{t}:{changes[t]:+.1f}%" for t in top.index])

    def test_intraday_bars():
        data = yf.download("AAPL", period="1d", interval="5m", progress=False, auto_adjust=True)
        if data.empty:
            return "No intraday data (market may be closed)"
        bar = data.iloc[-1]
        return (
            f"AAPL 5m  o={bar['Open']:.2f}  h={bar['High']:.2f}  "
            f"l={bar['Low']:.2f}  c={bar['Close']:.2f}  v={int(bar['Volume'])}"
        )

    def test_daily_history():
        data = yf.download("AAPL", period="5d", interval="1d", progress=False, auto_adjust=True)
        if data.empty:
            return "No history returned"
        return f"{len(data)} days  latest close={data['Close'].iloc[-1]:.2f}"

    check("yfinance — current quote (fast_info)", test_current_quote)
    check("yfinance — batch movers 7 tickers", test_batch_movers)
    check("yfinance — intraday 5-min bars", test_intraday_bars)
    check("yfinance — daily history 5 days", test_daily_history)


# ── Schwab ───────────────────────────────────────────────────────────────────

def verify_schwab():
    app_key = os.environ.get("SCHWAB_APP_KEY", "")
    app_secret = os.environ.get("SCHWAB_APP_SECRET", "")
    if not app_key or not app_secret:
        skip("Schwab — real-time quote (AAPL)")
        skip("Schwab — price history AAPL 5 days")
        return

    import schwab

    token_path = Path(__file__).parent / "schwab_token.json"
    callback_url = "https://127.0.0.1"

    # easy_client opens a browser on first run to complete OAuth2.
    # After approval it saves tokens to token_path and reuses them.
    client = schwab.auth.easy_client(
        api_key=app_key,
        app_secret=app_secret,
        callback_url=callback_url,
        token_path=str(token_path),
    )

    def test_quote():
        from schwab.orders.common import PriceType
        resp = client.get_quotes(["AAPL"])
        resp.raise_for_status()
        data = resp.json()["AAPL"]
        quote = data.get("quote", data)
        last = quote.get("lastPrice") or quote.get("mark") or quote.get("closePrice")
        bid = quote.get("bidPrice")
        ask = quote.get("askPrice")
        return f"AAPL  last={last}  bid={bid}  ask={ask}"

    def test_price_history():
        from schwab.client import Client
        resp = client.get_price_history_every_day("AAPL", need_extended_hours_data=False)
        resp.raise_for_status()
        candles = resp.json().get("candles", [])
        if not candles:
            return "No candles returned"
        last = candles[-1]
        return (
            f"{len(candles)} candles  "
            f"latest o={last['open']}  h={last['high']}  l={last['low']}  c={last['close']}"
        )

    check("Schwab — real-time quote (AAPL)", test_quote)
    check("Schwab — price history AAPL daily bars", test_price_history)


# ── Finnhub ─────────────────────────────────────────────────────────────────

def verify_finnhub():
    import finnhub

    key = os.environ.get("FINNHUB_API_KEY", "")
    if not key:
        skip("Finnhub — company_news('AAPL')")
        skip("Finnhub — quote('AAPL')")
        return

    client = finnhub.Client(api_key=key)

    def test_news():
        from datetime import date, timedelta
        today = date.today().isoformat()
        week_ago = (date.today() - timedelta(days=7)).isoformat()
        news = client.company_news("AAPL", _from=week_ago, to=today)
        return f"{len(news)} articles  first headline: {news[0]['headline'][:60] if news else 'none'}..."

    def test_quote():
        quote = client.quote("AAPL")
        return f"AAPL  c={quote['c']}  o={quote['o']}  h={quote['h']}  l={quote['l']}  pc={quote['pc']}"

    check("Finnhub — company_news('AAPL')", test_news)
    check("Finnhub — quote('AAPL')", test_quote)


# ── Robinhood (robin_stocks) ─────────────────────────────────────────────────

def verify_robinhood():
    username = os.environ.get("ROBINHOOD_USERNAME", "")
    password = os.environ.get("ROBINHOOD_PASSWORD", "")
    if not username or not password:
        skip("Robinhood — login + get_open_stock_positions()")
        skip("Robinhood — load_portfolio_profile()")
        return

    import robin_stocks.robinhood as rh

    def test_login_and_positions():
        rh.login(username, password)
        positions = rh.get_open_stock_positions()
        return f"{len(positions)} open positions"

    def test_portfolio():
        profile = rh.load_portfolio_profile()
        cash = profile.get("withdrawable_amount") or profile.get("cash")
        equity = profile.get("equity")
        return f"cash={cash}  equity={equity}"

    check("Robinhood — login + get_open_stock_positions()", test_login_and_positions)
    check("Robinhood — load_portfolio_profile()", test_portfolio)


# ── Anthropic ────────────────────────────────────────────────────────────────

def verify_anthropic():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        skip("Anthropic — basic message (claude-sonnet-4-6)")
        return

    import anthropic

    def test_message():
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=32,
            messages=[{"role": "user", "content": "Reply with only: API OK"}],
        )
        return msg.content[0].text.strip()

    check("Anthropic — basic message (claude-sonnet-4-6)", test_message)


# ── Run all ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n=== API Verification ===\n")
    verify_yfinance()
    verify_schwab()
    verify_finnhub()
    verify_robinhood()
    verify_anthropic()
    print("=== Done ===\n")
