# Changelog

All notable changes to this project are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
This project is pre-1.0; the API and schema may change between entries.

## [Unreleased]
- Phase 2 finish: confidence calibration tracking, per-call usage logging.

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
