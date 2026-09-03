# Changelog

All notable changes to this project are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
This project is pre-1.0; the API and schema may change between entries.

## [Unreleased]
- Phase 2 finish: confidence calibration tracking, per-call usage logging.

## [0.2.4] — 2026-09-03

### Changed
- **The page no longer reloads to refresh.** New `GET /api/state` returns prices,
  chart series, and the analysis in one payload; the browser polls it every 15s
  and updates the cards, charts, and market read in place. The chat panel and
  its history are never touched by a data refresh.
- Chat history also persists across a manual reload (sessionStorage).
- Intraday chart labels are 12-hour (`9:30 AM` … `3:55 PM`).
- Chart scrubbing is bounded to the plot area — drag below the chart baseline
  and it stops, instead of continuing to track.

## [0.2.3] — 2026-09-03

### Added
- **1D intraday** on the price chart — today's session as 5-minute bars
  (`get_intraday()`, a 5-day/5-min pull kept to the last session so it works
  pre-open and on weekends). New default view; scrub shows the time + price.

### Changed
- Chat is now **"Toohigh"** — renamed throughout; greets with
  "Hello, my name is Toohigh and I am an AI agent for research."
- Chat answers are short and direct — reworked system prompt (1-3 sentences,
  no preamble, no bullet essays), `max_output_tokens` 2000 → 600.
- Chat context trimmed to a compact block (prices + headline titles + a one-line
  read per ticker) instead of the full news bodies and full briefing JSON —
  fewer input tokens, faster replies. (Free-tier latency still varies 1-15s.)
- Removed the example-prompt hint line under the chat.
- News titles/summaries are HTML-unescaped (`Storage &amp;` → `Storage &`).

## [0.2.2] — 2026-09-03

### Fixed
- **Chat was completely broken**: the message array was named `history`, which
  is a read-only global in browsers, so `history.push(...)` threw and the send
  never fired. Renamed to `convo`.

### Added
- Interactive price chart per ticker — scrub left/right with mouse or touch to
  read the close and % change at any point in the window, with 1M / 3M / 6M / 1Y
  range buttons. Replaces the static sparkline; the 52-week range bar stays.
  Full daily series (up to ~260 points) is sent inline; no extra request.
- SVG emoji favicon (was 404ing).

## [0.2.1] — 2026-09-02

### Changed
- Per-company analysis is now a plain-English walk-through: *what happened → why
  → what it could change → what the stock did today → what to expect next*, with
  a one-line headline read (replaces the old factors/risks/catalysts lists).
- Chat rewritten: conversational system prompt, Markdown rendering, model
  fallback, robust SSE parsing (fixes the "types but never answers" case).
- Analysis now runs on a **background thread** — the page and `/api/analysis`
  never block on the model; stale briefing is served while a new one builds.
- Analysis rebuilds only when the **news/price fingerprint changes** (or every
  30 min), instead of on a fixed timer — keeps within the model's free-tier
  daily quota while still reacting immediately to real news.
- Default model → `gemini-3.1-flash-lite` (the full `flash` models are capped at
  ~20 requests/day on the free tier; flash-lite's quota is far higher).
- Data re-scan interval 5 min → 2 min. Gunicorn runs with `--threads 8` so
  requests aren't serialised behind a slow model call.

## [0.2.0] — 2026-09-02

Phase 2 — reasoning layer and chat.

### Added
- `reasoning.py` — `analyze_market()` sends the whole snapshot (all tickers,
  all news) to Google Gemini in one call and returns a structured "desk note":
  `market_summary`, ranked `top_stories`, cross-cutting `themes`, and per ticker
  a `stance` + calibrated `confidence` (0–1) + `rationale` / `key_factors` /
  `risks` / `catalysts`. JSON schema-constrained; falls back to a second model
  on a 503.
- `chat_stream()` + `POST /api/chat` — streaming (SSE) chat grounded in the
  current snapshot and desk note.
- `GET /api/analysis` — the desk note as JSON, generated lazily and cached
  separately from the price snapshot.
- Web UI: a "Market Read" card, per-ticker stance/confidence/rationale blocks,
  and an "Ask the desk" chat dock. The page renders prices immediately and
  loads the analysis asynchronously — it never blocks on the model.
- `google-genai` dependency; `GEMINI_API_KEY` (+ optional `GEMINI_MODEL`,
  `GEMINI_FALLBACK_MODEL`) config.

### Notes
- Uses the Gemini free tier (no card, 1,500 req/day). The whole reasoning layer
  is optional — no key means the page just shows prices + news as before.

## [0.1.0] — 2026-09-02

First working data layer, deployed.

### Added
- `data_sources.py` — price data (`yfinance`) and news, combined by
  `build_snapshot()`.
- Alpaca news API as the primary news source (symbol-tagged, history to 2015,
  `start`/`end` params for point-in-time backtest queries); NewsAPI keyword
  search retained as an automatic fallback.
- `app.py` — Flask web layer with a 5-minute in-memory cache, `/` and
  `/healthz` routes, per-ticker view models (sparkline points, 52-week range
  position).
- `templates/index.html` — single-page UI: sparklines, 52-week range meter,
  animated live-refresh countdown, glass cards.
- `render.yaml` — Render blueprint; auto-deploy on `main`.
- Project docs: README, ROADMAP, CONTRIBUTING, ARCHITECTURE, `.env.example`,
  issue/PR templates, MIT license.

### Changed
- 52-week range is now computed from price history instead of `yfinance`
  `.info`, which Yahoo rate-limits from cloud IPs.
- NewsAPI query tightened: full company names OR ticker, AND-ed with
  market-relevance terms; results deduped; low-signal aggregators excluded.

### Known issues
- `.info` fields (sector, market cap) can be blank when running on a cloud host.
- No fundamentals or earnings-calendar data yet.
