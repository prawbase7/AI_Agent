"""
AI Research Agent - Web layer
-----------------------------
Serves the price + news snapshot from data_sources.py as a single read-only
web page. Results are cached in memory for a few minutes so page reloads are
fast and we don't hammer yfinance / NewsAPI.

Run locally:
    python3 app.py          # http://localhost:8000

Production (Render):
    gunicorn app:app
"""

import os
import time
from datetime import datetime

from flask import Flask, render_template

from data_sources import build_snapshot, TICKERS

app = Flask(__name__)

CACHE_TTL_SECONDS = 300
_cache = {"data": None, "fetched_at": 0.0}


def get_snapshot():
    """Return (snapshot, fetched_at_datetime), refreshing if the cache is stale."""
    now = time.time()
    if _cache["data"] is None or now - _cache["fetched_at"] > CACHE_TTL_SECONDS:
        _cache["data"] = build_snapshot(TICKERS)
        _cache["fetched_at"] = now
    return _cache["data"], datetime.fromtimestamp(_cache["fetched_at"])


@app.route("/")
def index():
    data, fetched_at = get_snapshot()
    news_enabled = bool(
        (os.environ.get("ALPACA_API_KEY_ID") and os.environ.get("ALPACA_API_SECRET_KEY"))
        or os.environ.get("NEWSAPI_KEY")
    )
    return render_template(
        "index.html",
        data=data,
        fetched_at=fetched_at,
        news_enabled=news_enabled,
        cache_ttl_min=CACHE_TTL_SECONDS // 60,
    )


@app.route("/healthz")
def healthz():
    return {"ok": True}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)
