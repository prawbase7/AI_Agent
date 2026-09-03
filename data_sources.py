"""
AI Research Agent - Step 1: Data Sources
------------------------------------------
Pulls price data (yfinance) and recent news for a set of tickers.
This is the foundation layer everything else (LLM reasoning, signals,
backtesting) will build on top of.

News source: Alpaca's news API (publisher-tagged by symbol, history back to
2015 — so it works for backtesting). NewsAPI is kept as an automatic fallback
for when Alpaca keys aren't set.

Setup:
    pip3 install yfinance requests python-dotenv

    Alpaca (preferred): create a free account at https://alpaca.markets, then
    Paper Trading -> API Keys -> Generate. Put both in .env:
        ALPACA_API_KEY_ID=your_key_id
        ALPACA_API_SECRET_KEY=your_secret_key

    NewsAPI (fallback): free key at https://newsapi.org/register
        NEWSAPI_KEY=your_key_here
"""

import html
import os
import pandas as pd
import yfinance as yf
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()  # reads .env in the project root, if present

# ---- Config ----
TICKERS = ["AAPL", "NVDA", "TSLA"]
NEWS_LOOKBACK_DAYS = 3

# Alpaca news (preferred source)
ALPACA_API_KEY_ID = os.environ.get("ALPACA_API_KEY_ID", "")
ALPACA_API_SECRET_KEY = os.environ.get("ALPACA_API_SECRET_KEY", "")
ALPACA_NEWS_URL = "https://data.alpaca.markets/v1beta1/news"

# NewsAPI (fallback source)
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")

# Full company names give NewsAPI far better recall than raw tickers.
COMPANY_NAMES = {
    "AAPL": "Apple",
    "NVDA": "Nvidia",
    "TSLA": "Tesla",
}

# Terms that keep results market-relevant (drops product reviews, lawsuits, etc.)
MARKET_TERMS = [
    "stock", "shares", "earnings", "revenue", "guidance",
    "analyst", "price target", "upgrade", "downgrade", "market cap",
]

# Low-signal aggregators worth filtering out.
EXCLUDE_DOMAINS = ["biztoc.com"]


def get_price_data(ticker: str, period: str = "1y"):
    """Fetch recent price history + basic stats for a ticker.

    Everything shown comes from the price-history endpoint, which stays reliable
    from cloud servers. `stock.info` (sector, market cap) is attempted too but
    Yahoo rate-limits it from hosted IPs, so treat those fields as best-effort.
    """
    stock = yf.Ticker(ticker)
    history = stock.history(period=period)

    if history.empty:
        return {
            "ticker": ticker,
            "latest_close": None,
            "pct_change_1d": None,
            "52w_high": None,
            "52w_low": None,
            "market_cap": None,
            "sector": None,
            "history": history,
        }

    closes = history["Close"]
    latest_close = closes.iloc[-1]
    prev_close = closes.iloc[-2] if len(closes) > 1 else None
    pct_change = (
        ((latest_close - prev_close) / prev_close * 100) if prev_close else None
    )

    # 52-week range straight from the last year of prices
    cutoff = history.index.max() - pd.Timedelta(days=365)
    last_year = history[history.index >= cutoff]
    week52_high = last_year["High"].max()
    week52_low = last_year["Low"].min()

    try:
        info = stock.info
    except Exception as e:
        print(f"⚠️  Could not fetch info for {ticker}: {e}")
        info = {}

    return {
        "ticker": ticker,
        "latest_close": round(float(latest_close), 2),
        "pct_change_1d": round(float(pct_change), 2) if pct_change is not None else None,
        "52w_high": round(float(week52_high), 2),
        "52w_low": round(float(week52_low), 2),
        "market_cap": info.get("marketCap"),
        "sector": info.get("sector"),
        "history": history,  # full dataframe if you need it downstream
    }


def get_intraday(ticker: str):
    """Most recent trading session as intraday 5-minute bars.

    Returns {"t": ["09:30", ...], "c": [...], "day": "YYYY-MM-DD"} or None.
    Uses a 5-day / 5-minute pull and keeps the last day present, so it still
    works before the open, on weekends, and on holidays.
    """
    try:
        df = yf.Ticker(ticker).history(period="5d", interval="5m")
        if df.empty:
            return None
        last_day = df.index[-1].date()
        day = df[df.index.map(lambda ts: ts.date() == last_day)]
        if len(day) < 2:
            return None
        return {
            # 12-hour labels in the exchange's timezone (US Eastern for these names)
            "t": [ts.strftime("%I:%M %p").lstrip("0") + " ET" for ts in day.index],
            "c": [round(float(c), 2) for c in day["Close"].tolist()],
            "day": last_day.strftime("%Y-%m-%d"),
        }
    except Exception as e:  # noqa: BLE001 — intraday is a nice-to-have
        print(f"⚠️  intraday fetch failed for {ticker}: {e}")
        return None


def get_news(ticker, company_name=None, lookback_days=NEWS_LOOKBACK_DAYS,
             limit=10, start=None, end=None):
    """Recent news for a ticker. Tries Alpaca first, falls back to NewsAPI.

    Pass explicit `start`/`end` (datetimes) instead of `lookback_days` when
    pulling point-in-time news for backtesting.
    """
    if ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY:
        try:
            # an empty list is a legitimate result for a quiet ticker
            return _get_news_alpaca(ticker, lookback_days, limit, start, end)
        except Exception as e:
            print(f"⚠️  Alpaca news failed for {ticker}: {e} — trying NewsAPI")

    return _get_news_newsapi(ticker, company_name, lookback_days, limit)


def _get_news_alpaca(ticker, lookback_days, limit, start=None, end=None):
    """Fetch symbol-tagged news from Alpaca's news API."""
    if start is None:
        start = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    headers = {
        "APCA-API-KEY-ID": ALPACA_API_KEY_ID,
        "APCA-API-SECRET-KEY": ALPACA_API_SECRET_KEY,
    }
    params = {
        "symbols": ticker,
        "start": start.isoformat(),
        "limit": min(max(limit, 1), 50),
        "sort": "desc",
        "exclude_contentless": "true",
    }
    if end is not None:
        params["end"] = end.isoformat()

    resp = requests.get(ALPACA_NEWS_URL, headers=headers, params=params, timeout=15)
    resp.raise_for_status()

    articles = resp.json().get("news", [])
    return [
        {
            "title": html.unescape(a["headline"] or ""),
            "source": (a.get("source") or "Alpaca").title(),
            "published_at": a.get("updated_at") or a.get("created_at"),
            "url": a.get("url"),
            "description": html.unescape(a.get("summary") or "") or None,
        }
        for a in articles
    ]


def _build_news_query(ticker: str, company_name: str = None) -> str:
    """(Apple OR AAPL) AND (stock OR earnings OR analyst OR ...)"""
    name = company_name or COMPANY_NAMES.get(ticker, ticker)
    subject = f'("{name}" OR {ticker})' if name != ticker else ticker
    relevance = " OR ".join(f'"{t}"' if " " in t else t for t in MARKET_TERMS)
    return f"{subject} AND ({relevance})"


def _get_news_newsapi(ticker, company_name=None, lookback_days=NEWS_LOOKBACK_DAYS,
                      limit=10):
    """Fetch recent market-relevant news for a ticker/company via NewsAPI."""
    if not NEWSAPI_KEY:
        print("⚠️  No Alpaca or NewsAPI credentials set — skipping news. See setup.")
        return []

    from_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": _build_news_query(ticker, company_name),
        "searchIn": "title,description",  # ignore matches buried in article body
        "from": from_date,
        "sortBy": "publishedAt",
        "language": "en",
        "apiKey": NEWSAPI_KEY,
        "pageSize": 20,  # over-fetch, we dedupe and trim below
    }
    if EXCLUDE_DOMAINS:
        params["excludeDomains"] = ",".join(EXCLUDE_DOMAINS)

    response = requests.get(url, params=params)
    if response.status_code != 200:
        print(f"⚠️  News fetch failed for {ticker}: {response.status_code} {response.text}")
        return []

    articles = response.json().get("articles", [])

    seen_titles = set()
    results = []
    for a in articles:
        title = (a.get("title") or "").strip()
        if not title or title.lower() in seen_titles:
            continue
        seen_titles.add(title.lower())
        results.append(
            {
                "title": html.unescape(title),
                "source": a["source"]["name"],
                "published_at": a["publishedAt"],
                "url": a["url"],
                "description": html.unescape(a.get("description") or "") or None,
            }
        )
        if len(results) == limit:
            break
    return results


def build_snapshot(tickers=TICKERS):
    """Pull price + intraday + news data for each ticker into one snapshot."""
    snapshot = {}
    for ticker in tickers:
        print(f"Fetching data for {ticker}...")
        snapshot[ticker] = {
            "price": get_price_data(ticker),
            "intraday": get_intraday(ticker),
            "news": get_news(ticker, COMPANY_NAMES.get(ticker)),
        }
    return snapshot


if __name__ == "__main__":
    data = build_snapshot()

    for ticker, d in data.items():
        print(f"\n=== {ticker} ===")
        p = d["price"]
        print(f"Close: ${p['latest_close']}  |  1d change: {p['pct_change_1d']}%  |  Sector: {p['sector']}")
        print(f"News articles found: {len(d['news'])}")
        for article in d["news"][:3]:
            print(f"  - {article['title']} ({article['source']})")
