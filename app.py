"""
AI Research Agent - Web layer
-----------------------------
Serves the price + news snapshot from data_sources.py as a page, plus:
  - GET  /api/analysis  -> the LLM market read (generated lazily, cached)
  - POST /api/chat      -> streaming chat grounded in the snapshot + analysis

The page never blocks on the model: it renders prices immediately and the
browser fetches the analysis afterward. Snapshot and analysis have separate
in-memory caches.

Run locally:   python3 app.py          # http://localhost:8000
Production:    gunicorn app:app
"""

import json
import os
import time
from datetime import datetime

from flask import Flask, Response, render_template, request, stream_with_context

from data_sources import build_snapshot, TICKERS
from reasoning import analyze_market, chat_stream

app = Flask(__name__)

SNAPSHOT_TTL = 300      # seconds — price + news
ANALYSIS_TTL = 300      # seconds — LLM market read

_snap = {"data": None, "at": 0.0}
_analysis = {"data": None, "at": 0.0, "snap_at": 0.0}


def get_snapshot():
    """Return (snapshot, fetched_at). Refreshes when stale."""
    now = time.time()
    if _snap["data"] is None or now - _snap["at"] > SNAPSHOT_TTL:
        _snap["data"] = build_snapshot(TICKERS)
        _snap["at"] = now
    return _snap["data"], datetime.fromtimestamp(_snap["at"])


def get_analysis():
    """Return the market read dict (or None). Regenerates when stale or when the
    snapshot it was built from has been replaced."""
    data, _ = get_snapshot()
    now = time.time()
    fresh = (
        _analysis["data"] is not None
        and now - _analysis["at"] <= ANALYSIS_TTL
        and _analysis["snap_at"] == _snap["at"]
    )
    if not fresh:
        _analysis["data"] = analyze_market(data)
        _analysis["at"] = now
        _analysis["snap_at"] = _snap["at"]
    return _analysis["data"]


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
    lo, hi, last = p.get("52w_low"), p.get("52w_high"), p.get("latest_close")
    if None in (lo, hi, last) or hi == lo:
        return None
    return max(0.0, min(100.0, (last - lo) / (hi - lo) * 100))


def build_views(data):
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
    next_refresh = int(max(0, SNAPSHOT_TTL - (time.time() - _snap["at"])))
    return render_template(
        "index.html",
        views=build_views(data),
        analysis_enabled=bool(os.environ.get("GEMINI_API_KEY")),
        fetched_at=fetched_at,
        news_enabled=news_enabled,
        cache_ttl_min=SNAPSHOT_TTL // 60,
        next_refresh=next_refresh,
    )


@app.route("/api/analysis")
def api_analysis():
    if not os.environ.get("GEMINI_API_KEY"):
        return {"status": "disabled"}, 200
    analysis = get_analysis()
    if not analysis:
        return {"status": "unavailable"}, 200
    payload = {k: v for k, v in analysis.items() if k != "by_ticker"}
    payload["status"] = "ok"
    return Response(json.dumps(payload, default=str), mimetype="application/json")


@app.route("/api/chat", methods=["POST"])
def api_chat():
    if not os.environ.get("GEMINI_API_KEY"):
        return {"error": "chat is not configured"}, 503

    body = request.get_json(silent=True) or {}
    raw = body.get("messages") or []
    messages = [
        {"role": "assistant" if m.get("role") == "assistant" else "user",
         "content": str(m.get("content", ""))[:4000]}
        for m in raw if m.get("content")
    ][-20:]
    if not messages or messages[-1]["role"] != "user":
        return {"error": "last message must be from the user"}, 400

    data, _ = get_snapshot()
    analysis = _analysis["data"]  # whatever's cached; fine if None

    @stream_with_context
    def generate():
        try:
            for chunk in chat_stream(messages, data, analysis):
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/healthz")
def healthz():
    return {"ok": True}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)
