import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

import finnhub
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

logger = logging.getLogger(__name__)
_analyzer = SentimentIntensityAnalyzer()


def _get_api_key() -> str:
    key = os.environ.get("FINNHUB_API_KEY")
    if key:
        return key
    from services.ssm_service import get_secret
    return get_secret("/trading-app/finnhub-key")


def _client() -> finnhub.Client:
    return finnhub.Client(api_key=_get_api_key())


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
    today = datetime.now(tz=ET).date()
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
            logger.exception("finnhub score_sentiment failed for %s", ticker)
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


_MAX_EARNINGS_AGE_DAYS = 730  # ~2 years — Finnhub's history for some tickers has gaps
# (e.g. T is missing 2025-09-30 entirely) and fills the requested count with whatever
# else it has on file, including decades-old outliers. Filtering by recency means a
# gappy ticker shows fewer, real quarters instead of a misleading ancient one.


def get_quarterly_earnings(ticker: str, limit: int = 4) -> list[dict]:
    """Quarterly EPS estimate vs actual for a ticker, most recent quarter first.

    Returns [] when Finnhub has no (recent) earnings history for the symbol —
    expected for leveraged/index ETFs (TQQQ, SQQQ) and thinly-covered tickers,
    not an error.
    """
    # Pull more than `limit` raw records so there's still enough left to fill
    # `limit` after the recency filter removes any stale entries.
    data = _client().company_earnings(ticker.upper(), limit=max(limit * 3, 12))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_MAX_EARNINGS_AGE_DAYS)).date().isoformat()
    recent = [d for d in (data or []) if d.get("period", "") >= cutoff]
    recent.sort(key=lambda d: d["period"], reverse=True)
    return [
        {
            "period": d["period"],
            "quarter": d["quarter"],
            "year": d["year"],
            "estimate": d["estimate"],
            "actual": d["actual"],
            "surprise": d["surprise"],
            "surprise_percent": d["surprisePercent"],
        }
        for d in recent[:limit]
    ]


def get_batch_quarterly_earnings(tickers: list[str], limit: int = 4) -> dict[str, list[dict]]:
    """Quarterly earnings for each ticker, keyed by ticker. Empty list per-ticker on
    failure or no coverage — same resilience pattern as score_batch_sentiment."""
    results = {}
    for ticker in tickers:
        try:
            results[ticker.upper()] = get_quarterly_earnings(ticker, limit=limit)
        except Exception:
            logger.exception("finnhub company_earnings failed for %s", ticker)
            results[ticker.upper()] = []
    return results
