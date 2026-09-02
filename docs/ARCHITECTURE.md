# Architecture

## Overview

Three layers, deliberately thin:

```
external APIs  ──►  data_sources.py  ──►  app.py  ──►  templates/index.html
   (I/O)             (normalize)          (cache,       (render)
                                          view models)
```

The design rule: **`data_sources.py` knows nothing about the web, and the web
layer knows nothing about HTTP clients or API quirks.** Later phases (reasoning,
backtest, trading) consume `build_snapshot()` the same way `app.py` does.

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

## `app.py`

- **Cache:** module-level dict, 5-minute TTL. One `build_snapshot()` call
  serves every visitor in that window — keeps us well under API rate limits and
  makes cold pages fast.
- **View models** (`build_views`): the template gets pre-computed display data,
  never raw frames.
  - `_sparkline()` — last 30 closes → normalized `"x,y x,y ..."` string for an
    SVG polyline (viewBox `0 0 100 32`).
  - `_range_position()` — where latest close sits in the 52-week range, 0–100,
    for the meter dot.
- **Routes:** `/` (page), `/healthz` (JSON, used by Render's health check).

## `templates/index.html`

Single file, no framework, no build. Inline `<style>`, ~30 lines of vanilla JS
for the refresh countdown. Web fonts from Google Fonts. Renders correctly with
missing fields (no news, no sector, no sparkline).

## Deployment

`render.yaml` declares one free web service:

- `buildCommand: pip install -r requirements.txt`
- `startCommand: gunicorn app:app --timeout 120`
- `healthCheckPath: /healthz`
- `PYTHON_VERSION` pinned; `ALPACA_*` / `NEWSAPI_KEY` marked `sync: false`
  (set in dashboard, not in repo).

Push to `main` → Render rebuilds and redeploys.

### Free-tier behavior

- Instance sleeps after ~15 min idle; next request cold-starts in ~30–50s.
- Combined with the 5-min cache: a visitor to a warm instance gets an instant
  page; the first visitor after a sleep waits for boot + one `build_snapshot()`.

## Where later phases plug in

| Phase | Consumes | Produces | Likely new file |
|------:|----------|----------|-----------------|
| 2 | `build_snapshot()` output | scored thesis per ticker | `reasoning.py` |
| 3 | historical `get_price_data` + `get_news(start, end)` | performance report | `backtest.py` |
| 4 | phase-2 signals | paper orders + portfolio state | `trader.py` |
