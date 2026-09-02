"""
AI Research Agent - Step 1: Data Sources
------------------------------------------
Pulls price data (yfinance) and recent news (NewsAPI) for a set of tickers.
This is the foundation layer everything else (LLM reasoning, signals,
backtesting) will build on top of.

Setup:
    pip3 install yfinance requests python-dotenv

    Get a free NewsAPI key at https://newsapi.org/register
    Then create a .env file in the project root:
        NEWSAPI_KEY=your_key_here
    (or export NEWSAPI_KEY="your_key_here" in your shell)
"""

import os
import pandas as pd
import yfinance as yf
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()  # reads .env in the project root, if present

# ---- Config ----
TICKERS = ["AAPL", "NVDA", "TSLA"]
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")  # set in .env or your environment
NEWS_LOOKBACK_DAYS = 3

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


def _build_news_query(ticker: str, company_name: str = None) -> str:
    """(Apple OR AAPL) AND (stock OR earnings OR analyst OR ...)"""
    name = company_name or COMPANY_NAMES.get(ticker, ticker)
    subject = f'("{name}" OR {ticker})' if name != ticker else ticker
    relevance = " OR ".join(f'"{t}"' if " " in t else t for t in MARKET_TERMS)
    return f"{subject} AND ({relevance})"


def get_news(ticker: str, company_name: str = None):
    """Fetch recent market-relevant news for a ticker/company via NewsAPI."""
    if not NEWSAPI_KEY:
        print("⚠️  No NEWSAPI_KEY set — skipping news fetch. See setup instructions.")
        return []

    from_date = (datetime.now() - timedelta(days=NEWS_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

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
                "title": title,
                "source": a["source"]["name"],
                "published_at": a["publishedAt"],
                "url": a["url"],
                "description": a.get("description"),
            }
        )
        if len(results) == 10:
            break
    return results


def build_snapshot(tickers=TICKERS):
    """Pull price + news data for each ticker into one combined snapshot."""
    snapshot = {}
    for ticker in tickers:
        print(f"Fetching data for {ticker}...")
        price_data = get_price_data(ticker)
        news_data = get_news(ticker, COMPANY_NAMES.get(ticker))
        snapshot[ticker] = {
            "price": price_data,
            "news": news_data,
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
