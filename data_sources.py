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
import yfinance as yf
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()  # reads .env in the project root, if present

# ---- Config ----
TICKERS = ["AAPL", "NVDA", "TSLA"]
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")  # set in .env or your environment
NEWS_LOOKBACK_DAYS = 3


def get_price_data(ticker: str, period: str = "1mo"):
    """Fetch recent price history + basic info for a ticker."""
    stock = yf.Ticker(ticker)
    history = stock.history(period=period)
    try:
        info = stock.info  # company fundamentals/summary (can be slow / rate-limited)
    except Exception as e:
        print(f"⚠️  Could not fetch info for {ticker}: {e}")
        info = {}

    latest_close = history["Close"].iloc[-1] if not history.empty else None
    prev_close = history["Close"].iloc[-2] if len(history) > 1 else None
    pct_change = (
        ((latest_close - prev_close) / prev_close * 100)
        if latest_close is not None and prev_close
        else None
    )

    return {
        "ticker": ticker,
        "latest_close": round(latest_close, 2) if latest_close else None,
        "pct_change_1d": round(pct_change, 2) if pct_change is not None else None,
        "52w_high": info.get("fiftyTwoWeekHigh"),
        "52w_low": info.get("fiftyTwoWeekLow"),
        "market_cap": info.get("marketCap"),
        "sector": info.get("sector"),
        "history": history,  # full dataframe if you need it downstream
    }


def get_news(ticker: str, company_name: str = None):
    """Fetch recent news headlines related to a ticker/company via NewsAPI."""
    if not NEWSAPI_KEY:
        print("⚠️  No NEWSAPI_KEY set — skipping news fetch. See setup instructions.")
        return []

    query = company_name or ticker
    from_date = (datetime.now() - timedelta(days=NEWS_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "from": from_date,
        "sortBy": "publishedAt",
        "language": "en",
        "apiKey": NEWSAPI_KEY,
        "pageSize": 10,
    }

    response = requests.get(url, params=params)
    if response.status_code != 200:
        print(f"⚠️  News fetch failed for {ticker}: {response.status_code} {response.text}")
        return []

    articles = response.json().get("articles", [])
    return [
        {
            "title": a["title"],
            "source": a["source"]["name"],
            "published_at": a["publishedAt"],
            "url": a["url"],
            "description": a.get("description"),
        }
        for a in articles
    ]


def build_snapshot(tickers=TICKERS):
    """Pull price + news data for each ticker into one combined snapshot."""
    snapshot = {}
    for ticker in tickers:
        print(f"Fetching data for {ticker}...")
        price_data = get_price_data(ticker)
        news_data = get_news(ticker)
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
