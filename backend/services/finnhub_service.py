import os
from datetime import date, timedelta

import finnhub
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_analyzer = SentimentIntensityAnalyzer()


def _client() -> finnhub.Client:
    return finnhub.Client(api_key=os.environ["FINNHUB_API_KEY"])


def get_quote(ticker: str) -> dict:
    """Current price snapshot for a single ticker.

    Returns OHLC + previous close. Used by the price monitor Lambda to check
    open paper trades every 5 minutes during market hours.
    """
    q = _client().quote(ticker.upper())
    return {
        "ticker": ticker.upper(),
        "price": q["c"],
        "open": q["o"],
        "high": q["h"],
        "low": q["l"],
        "prev_close": q["pc"],
        "change_pct": round((q["c"] - q["pc"]) / q["pc"] * 100, 2) if q["pc"] else None,
    }


def get_batch_quotes(tickers: list[str]) -> list[dict]:
    """Quote for each ticker in the list. One API call per ticker (Finnhub has no batch endpoint).

    Free tier: 60 calls/min. Callers should keep lists short (<= 20 tickers).
    """
    client = _client()
    results = []
    for ticker in tickers:
        try:
            q = client.quote(ticker.upper())
            prev_close = q.get("pc") or 0
            current = q.get("c") or 0
            results.append(
                {
                    "ticker": ticker.upper(),
                    "price": current,
                    "open": q.get("o"),
                    "high": q.get("h"),
                    "low": q.get("l"),
                    "prev_close": prev_close,
                    "change_pct": (
                        round((current - prev_close) / prev_close * 100, 2) if prev_close else None
                    ),
                }
            )
        except Exception:
            continue
    return results


def get_company_news(ticker: str, days: int = 7) -> list[dict]:
    """Recent news articles for a ticker. Used by Claude for sentiment context.

    Returns articles sorted newest-first, trimmed to the fields Claude needs.
    """
    today = date.today()
    from_date = (today - timedelta(days=days)).isoformat()
    to_date = today.isoformat()

    raw = _client().company_news(ticker.upper(), _from=from_date, to=to_date)
    articles = []
    for item in raw:
        articles.append(
            {
                "headline": item.get("headline", ""),
                "summary": item.get("summary", ""),
                "source": item.get("source", ""),
                "url": item.get("url", ""),
                "published_at": item.get("datetime"),
            }
        )
    articles.sort(key=lambda x: x["published_at"] or 0, reverse=True)
    return articles


def score_sentiment(ticker: str, days: int = 3) -> dict:
    """Aggregate news sentiment for a ticker over the past N days.

    Scores each headline with VADER, averages the compound scores, and returns
    a structured result for the context_loader briefing payload.

    Returned shape:
    {
        "ticker": str,
        "score": float,          # -1.0 (very bearish) to +1.0 (very bullish)
        "label": str,            # "bullish" | "neutral" | "bearish"
        "article_count": int,
        "top_headlines": list[str]   # 3 most recent headlines
    }
    """
    articles = get_company_news(ticker, days=days)
    if not articles:
        return {
            "ticker": ticker.upper(),
            "score": 0.0,
            "label": "neutral",
            "article_count": 0,
            "top_headlines": [],
        }

    scores = []
    for article in articles:
        text = article.get("headline", "") + " " + article.get("summary", "")
        vs = _analyzer.polarity_scores(text.strip())
        scores.append(vs["compound"])

    avg_score = round(sum(scores) / len(scores), 4)

    if avg_score >= 0.05:
        label = "bullish"
    elif avg_score <= -0.05:
        label = "bearish"
    else:
        label = "neutral"

    return {
        "ticker": ticker.upper(),
        "score": avg_score,
        "label": label,
        "article_count": len(articles),
        "top_headlines": [a["headline"] for a in articles[:3]],
    }


def score_batch_sentiment(tickers: list[str], days: int = 3) -> list[dict]:
    """Sentiment scores for a list of tickers. Used by the morning refresh Lambda."""
    results = []
    for ticker in tickers:
        try:
            results.append(score_sentiment(ticker, days=days))
        except Exception:
            results.append(
                {
                    "ticker": ticker.upper(),
                    "score": 0.0,
                    "label": "neutral",
                    "article_count": 0,
                    "top_headlines": [],
                }
            )
    return results
