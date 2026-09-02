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


def _sparkline(history, n=30, w=100, h=28, pad=2):
    """Turn the last n closes into an SVG polyline 'x,y x,y ...' string."""
    try:
        closes = [float(c) for c in history["Close"].tail(n).tolist()]
    except Exception:
        return None
    if len(closes) < 2:
        return None
    lo, hi = min(closes), max(closes)
    span = (hi - lo) or 1.0
    step = w / (len(closes) - 1)
    pts = []
    for i, c in enumerate(closes):
        x = i * step
        y = pad + (h - 2 * pad) * (1 - (c - lo) / span)
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def _range_position(p):
    """Where the latest close sits in the 52-week range, as 0-100 (or None)."""
    lo, hi, last = p.get("52w_low"), p.get("52w_high"), p.get("latest_close")
    if None in (lo, hi, last) or hi == lo:
        return None
    return max(0.0, min(100.0, (last - lo) / (hi - lo) * 100))


def build_views(data):
    """Shape the raw snapshot into per-ticker view models for the template."""
    views = []
    for ticker, d in data.items():
        p = d["price"]
        views.append(
            {
                "ticker": ticker,
                "price": p,
                "news": d["news"],
                "spark": _sparkline(p.get("history")),
                "spark_up": (p.get("pct_change_1d") or 0) >= 0,
                "range_pos": _range_position(p),
            }
        )
    return views


@app.route("/")
def index():
    data, fetched_at = get_snapshot()
    news_enabled = bool(
        (os.environ.get("ALPACA_API_KEY_ID") and os.environ.get("ALPACA_API_SECRET_KEY"))
        or os.environ.get("NEWSAPI_KEY")
    )
    next_refresh = int(
        max(0, CACHE_TTL_SECONDS - (time.time() - _cache["fetched_at"]))
    )
    return render_template(
        "index.html",
        views=build_views(data),
        fetched_at=fetched_at,
        news_enabled=news_enabled,
        cache_ttl_min=CACHE_TTL_SECONDS // 60,
        next_refresh=next_refresh,
    )


@app.route("/healthz")
def healthz():
    return {"ok": True}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)
