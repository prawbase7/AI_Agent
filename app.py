"""
AI Research Agent - Web layer
-----------------------------
Serves the price + news snapshot from data_sources.py as a page, plus:
  - GET  /api/analysis  -> the LLM market briefing (generated in the background)
  - POST /api/chat      -> streaming chat grounded in the snapshot + briefing

Nothing on the page blocks on the model. The price snapshot and the analysis
have independent caches; the analysis regenerates on a background thread so a
slow model call never holds up a request. Stale analysis is served while a
fresh one is being built.

Run locally:   python3 app.py          # http://localhost:8000
Production:    gunicorn app:app --threads 8
"""

import json
import os
import threading
import time
from datetime import datetime

from flask import Flask, Response, render_template, request, stream_with_context

from data_sources import build_snapshot, TICKERS
from reasoning import analyze_market, chat_stream, news_fingerprint

app = Flask(__name__)

# How often to re-scan the data sources (seconds). The LLM briefing is only
# rebuilt when the news/price fingerprint actually changes (see below), or once
# ANALYSIS_MAX_AGE has passed — this keeps us inside the model's free-tier quota
# while still reacting the moment there's real news.
SNAPSHOT_TTL = int(os.environ.get("SNAPSHOT_TTL", 120))
ANALYSIS_MAX_AGE = int(os.environ.get("ANALYSIS_MAX_AGE", 1800))

_snap = {"data": None, "at": 0.0}
_snap_lock = threading.Lock()

_analysis = {
    "data": None, "at": 0.0, "fingerprint": None, "generating": False,
}
_analysis_lock = threading.Lock()


def get_snapshot():
    """Return (snapshot, fetched_at). Refreshes when stale."""
    with _snap_lock:
        now = time.time()
        if _snap["data"] is None or now - _snap["at"] > SNAPSHOT_TTL:
            _snap["data"] = build_snapshot(TICKERS)
            _snap["at"] = now
        return _snap["data"], datetime.fromtimestamp(_snap["at"])


def _regenerate_analysis(snapshot, fingerprint):
    try:
        result = analyze_market(snapshot)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  analysis thread error: {e}")
        result = None
    with _analysis_lock:
        if result is not None:
            _analysis["data"] = result
            _analysis["at"] = time.time()
            _analysis["fingerprint"] = fingerprint
        _analysis["generating"] = False


def get_analysis_state():
    """('ok'|'pending'|'unavailable'|'disabled', data_or_None).

    Serves the cached briefing immediately. Kicks off a background rebuild only
    when the news/price fingerprint has changed or the briefing is older than
    ANALYSIS_MAX_AGE — so an unchanged watchlist costs zero model calls.
    """
    if not os.environ.get("GEMINI_API_KEY"):
        return "disabled", None

    data, _ = get_snapshot()
    fp = news_fingerprint(data)
    now = time.time()

    with _analysis_lock:
        cached = _analysis["data"]
        stale = (
            cached is None
            or _analysis["fingerprint"] != fp
            or now - _analysis["at"] > ANALYSIS_MAX_AGE
        )
        if stale and not _analysis["generating"]:
            _analysis["generating"] = True
            threading.Thread(
                target=_regenerate_analysis, args=(data, fp), daemon=True
            ).start()

        if cached is not None:
            return "ok", cached
        return ("pending" if _analysis["generating"] else "unavailable"), None


def _range_position(p):
    lo, hi, last = p.get("52w_low"), p.get("52w_high"), p.get("latest_close")
    if None in (lo, hi, last) or hi == lo:
        return None
    return max(0.0, min(100.0, (last - lo) / (hi - lo) * 100))


def _series(history, cap=260):
    """Full daily close series for the interactive chart: {"t": [...], "c": [...]}."""
    try:
        closes = [round(float(c), 2) for c in history["Close"].tolist()]
        dates = [d.strftime("%Y-%m-%d") for d in history.index]
    except Exception:
        return None
    if len(closes) < 2:
        return None
    if len(closes) > cap:                       # keep the payload small
        closes, dates = closes[-cap:], dates[-cap:]
    return {"t": dates, "c": closes}


def build_views(data):
    views = []
    for ticker, d in data.items():
        p = d["price"]
        views.append(
            {
                "ticker": ticker,
                "price": p,
                "news": d["news"],
                "spark_up": (p.get("pct_change_1d") or 0) >= 0,
                "range_pos": _range_position(p),
                "series": _series(p.get("history")),
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
        refresh_secs=SNAPSHOT_TTL,
        next_refresh=next_refresh,
    )


@app.route("/api/analysis")
def api_analysis():
    status, data = get_analysis_state()
    if status != "ok":
        return {"status": status}
    payload = {k: v for k, v in data.items() if k != "by_ticker"}
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
    analysis = _analysis["data"]  # whatever's cached; grounded on news either way

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
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)
