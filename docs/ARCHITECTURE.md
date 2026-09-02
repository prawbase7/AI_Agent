# Architecture

## Overview

Deliberately thin layers:

```
external APIs ──► data_sources.py ─┬─► app.py ──► templates/index.html
   (I/O)          (normalize)      │   (caches,    (render + fetch analysis
                                   │    routes)     + stream chat)
                 reasoning.py ◄────┘
                 (Gemini: market read, chat)
```

The design rule: **`data_sources.py` knows nothing about the web or the LLM,
`reasoning.py` knows nothing about the web, and the web layer knows nothing
about HTTP clients or API quirks.** Later phases (backtest, trading) consume
`build_snapshot()` and `analyze_market()` the same way `app.py` does.

## `data_sources.py`

### `build_snapshot(tickers) -> dict`

```python
{
  "AAPL": {
    "price": {
      "ticker", "latest_close", "pct_change_1d",
      "52w_high", "52w_low", "market_cap", "sector",
      "history",           # pandas DataFrame, 1y daily OHLCV
    },
    "news": [
      {"title", "source", "published_at", "url", "description"},
      ...
    ],
  },
  ...
}
```

### Price data — `get_price_data()`

- Source: `yfinance` `Ticker.history(period="1y")`.
- 52-week high/low are computed from the last 365 days of the returned frame,
  **not** from `Ticker.info` — that endpoint is rate-limited from cloud IPs and
  returns blanks on Render.
- `.info` is still attempted for `sector` / `market_cap`, wrapped in
  try/except; those fields are best-effort.

### News — `get_news()`

Tries sources in order, first success wins:

1. **Alpaca** (`_get_news_alpaca`) — `GET data.alpaca.markets/v1beta1/news`,
   auth via `APCA-API-KEY-ID` / `APCA-API-SECRET-KEY` headers. News is tagged
   to symbols by the publisher, so relevance is high. History goes back to 2015,
   which is what makes phase-3 backtesting possible. Accepts `start` / `end`
   datetimes for point-in-time queries.
2. **NewsAPI** (`_get_news_newsapi`) — keyword search fallback. Query is
   `("Apple" OR AAPL) AND (stock OR earnings OR analyst OR ...)`, restricted to
   title+description, deduped by title, aggregators excluded. Free tier only
   covers ~30 days, so it is **not** usable for backtests.

If no credentials are set, returns `[]` and the page shows a "not configured"
note.

## `reasoning.py`

The LLM layer. Google Gemini via `google-genai`, free tier. Entirely optional —
every entry point degrades to "no analysis" if `GEMINI_API_KEY` is unset or a
call fails.

### `analyze_market(snapshot) -> dict | None`

- `build_context()` flattens the snapshot into one plain-text block: per ticker,
  the price stats then every headline + summary.
- One `generate_content` call with a JSON `response_schema`, an analyst-desk-note
  system prompt, and a small thinking budget. The model sees **all** tickers and
  news together so the read is cross-cutting, not name-by-name.
- Returns: `market_summary`, `top_stories[]` (headline, why_it_matters, tickers,
  impact), `themes[]`, and `tickers[]` — each with `stance`
  (bullish/bearish/neutral), `confidence` (clamped to 0–1), `rationale`,
  `key_factors`, `risks`, `catalysts`. Plus `by_ticker` (indexed for the
  template), `generated_at`, `model`.
- On a model error (free-tier 503s happen), retries once on
  `GEMINI_FALLBACK_MODEL` before giving up.

### `chat_stream(messages, snapshot, analysis) -> generator[str]`

Yields text chunks. The system prompt carries the same context block plus the
current desk note as JSON, so answers stay grounded. Thinking off for latency.

## `app.py`

- **Two caches**, both module-level dicts:
  - price snapshot — `SNAPSHOT_TTL` (5 min)
  - analysis — `ANALYSIS_TTL` (5 min), also invalidated whenever the snapshot it
    was built from is replaced
- **The page never blocks on the model.** `/` renders from the price snapshot
  only; the browser then calls `/api/analysis`, which generates the read on
  first request and serves it cached after.
- **View models** (`build_views`): pre-computed display data, never raw frames.
  - `_sparkline()` — last 30 closes → `"x,y ..."` for an SVG polyline.
  - `_range_position()` — latest close within the 52-week range, 0–100.
- **Routes:**
  - `/` — the page
  - `GET /api/analysis` — desk note as JSON (`status: ok | unavailable | disabled`)
  - `POST /api/chat` — SSE stream; body `{messages: [{role, content}]}`, history
    capped, grounded in the cached snapshot + analysis
  - `/healthz` — Render health check

## `templates/index.html`

Single file, no framework, no build. Inline `<style>`, vanilla JS for: the
refresh countdown, fetching `/api/analysis` and distributing per-ticker reads
into the cards, and the chat dock (streaming `fetch` + manual SSE parse).
Renders correctly with any field missing (no news, no sector, no sparkline,
no analysis).

## Deployment

`render.yaml` declares one free web service:

- `buildCommand: pip install -r requirements.txt`
- `startCommand: gunicorn app:app --timeout 120`
- `healthCheckPath: /healthz`
- `PYTHON_VERSION` pinned; `ALPACA_*` / `NEWSAPI_KEY` / `GEMINI_API_KEY` marked
  `sync: false` (set in dashboard, not in repo).

Push to `main` → Render rebuilds and redeploys.

### Free-tier behavior

- Instance sleeps after ~15 min idle; next request cold-starts in ~30–50s.
- Combined with the 5-min cache: a visitor to a warm instance gets an instant
  page; the first visitor after a sleep waits for boot + one `build_snapshot()`.

## Where later phases plug in

| Phase | Consumes | Produces | Likely new file |
|------:|----------|----------|-----------------|
| 2 ✅ | `build_snapshot()` output | combined market read + per-ticker confidence | `reasoning.py` |
| 3 | historical `get_price_data` + `get_news(start, end)` + `analyze_market()` | performance report | `backtest.py` |
| 4 | phase-2 signals | paper orders + portfolio state | `trader.py` |
