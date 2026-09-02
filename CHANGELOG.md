# Changelog

All notable changes to this project are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
This project is pre-1.0; the API and schema may change between entries.

## [Unreleased]
- Phase 2: LLM reasoning layer with confidence scoring.

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
