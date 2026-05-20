"""
Run this script to verify all API connections before building.

  cd backend
  .venv\Scripts\activate
  python ..\scripts\verify_apis.py
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv(dotenv_path=".env.local")

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


# ── Polygon.io ──────────────────────────────────────────────────────────────

def verify_polygon():
    from polygon import RESTClient

    key = os.environ.get("POLYGON_API_KEY", "")
    if not key:
        skip("Polygon — get_intraday_movers()")
        skip("Polygon — get_stock_price('AAPL')")
        return

    client = RESTClient(api_key=key)

    def test_movers():
        gainers = client.get_snapshot_direction("stocks", "gainers", include_otc=False) or []
        if not gainers:
            return "No gainers returned (market may be closed)"
        snap = gainers[0]
        price = (
            getattr(snap.min, "c", None)
            or getattr(snap.day, "c", None)
            or getattr(snap.prev_day, "c", None)
        )
        vol = getattr(snap.day, "v", None)
        change = snap.todays_change_perc
        return f"Top gainer: {snap.ticker}  price={price}  vol={vol}  change={change}%"

    def test_price():
        snap = client.get_snapshot_ticker("stocks", "AAPL")
        price = (
            getattr(snap.min, "c", None)
            or getattr(snap.day, "c", None)
            or getattr(snap.prev_day, "c", None)
        )
        return f"AAPL price={price}"

    check("Polygon — get_snapshot_direction (gainers)", test_movers)
    check("Polygon — get_snapshot_ticker (AAPL)", test_price)


# ── Finnhub ─────────────────────────────────────────────────────────────────

def verify_finnhub():
    import finnhub

    key = os.environ.get("FINNHUB_API_KEY", "")
    if not key:
        skip("Finnhub — company_news('AAPL')")
        skip("Finnhub — news_sentiment('AAPL')")
        return

    client = finnhub.Client(api_key=key)

    def test_news():
        from datetime import date, timedelta
        today = date.today().isoformat()
        week_ago = (date.today() - timedelta(days=7)).isoformat()
        news = client.company_news("AAPL", _from=week_ago, to=today)
        return f"{len(news)} articles  first headline: {news[0]['headline'][:60] if news else 'none'}..."

    def test_sentiment():
        sentiment = client.news_sentiment("AAPL")
        buzz = getattr(sentiment, "buzz", None) or sentiment.get("buzz", {})
        score = getattr(sentiment, "companyNewsScore", None) or sentiment.get("companyNewsScore")
        return f"companyNewsScore={score}  buzz={buzz}"

    check("Finnhub — company_news('AAPL')", test_news)
    check("Finnhub — news_sentiment('AAPL')", test_sentiment)


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
        skip("Anthropic — basic message (claude-sonnet-4-20250514)")
        return

    import anthropic

    def test_message():
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=32,
            messages=[{"role": "user", "content": "Reply with only: API OK"}],
        )
        return msg.content[0].text.strip()

    check("Anthropic — basic message (claude-sonnet-4-20250514)", test_message)


# ── Run all ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n=== API Verification ===\n")
    verify_polygon()
    verify_finnhub()
    verify_robinhood()
    verify_anthropic()
    print("=== Done ===\n")
