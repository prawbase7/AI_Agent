# Roadmap

The project is built in four phases. Each phase is usable on its own and leaves
the previous one working.

Legend: ✅ done · 🚧 in progress · 🔜 next up · ⬜ not started

---

## Phase 1 — Data layer ✅

Reliable, backtest-ready market data plus a deployed way to look at it.

- [x] Price history via `yfinance` (1y daily OHLCV)
- [x] Derived stats: latest close, 1-day % change, 52-week range
- [x] News via NewsAPI (keyword search)
- [x] Flask web page with an in-memory cache
- [x] Deployed to Render (blueprint, auto-deploy on `main`)
- [x] Swap primary news source to Alpaca (symbol-tagged, history to 2015)
- [x] `get_news(start, end)` for point-in-time queries
- [x] UI pass — sparklines, 52-week range meter, live refresh countdown

**Exit criteria met:** both data sources return clean, dated data suitable for
a backtest, and the snapshot renders on a public URL.

---

## Phase 2 — LLM reasoning layer ✅

One combined market read with a per-ticker call + confidence score, plus a chat
that takes a position.

- [x] Output schema — `market_summary`, `top_stories`, `themes`, and per ticker
      a plain-English walk-through (`what_happened` → `why_it_happened` →
      `what_could_change` → `todays_move` → `expected_outcome`) + `stance` +
      `confidence` 0–1
- [x] Prompt design: all prices + all headlines in one call; opinionated —
      commits to a direction, magnitude, timeframe, confirm/break levels
- [x] Model wrapper (`reasoning.py`, Gemini free tier `flash-lite`, retry +
      fallback model on 5xx)
- [x] Rebuilt only when `news_fingerprint()` changes → stays inside free quota
- [x] Runs on a background thread; page + `/api/analysis` never block on it
- [x] `/api/chat` — streaming, grounded, Markdown, "Toohigh" persona
- [x] `/api/state` — page refreshes prices + chart + read in place, no reload
- [x] Best-effort: page renders fine when the key is missing or a call fails
- [ ] Confidence calibration — track predicted confidence vs realized outcome
      *(moved to Phase 3 — needs the historical loop)*
- [ ] Cost/usage logging per call

**Exit criteria met:** the live page shows a combined market read and a scored,
sourced call per ticker, and the chat answers questions about them.

---

## Phase 3 — Backtesting 🔜

Check whether the signals would have worked.

- [ ] Historical data loader (point-in-time prices + news, no look-ahead)
- [ ] Confidence calibration — predicted confidence vs realized outcome (carried
      over from Phase 2)
- [ ] Replay engine: walk dates, regenerate signal, simulate a simple rule
      (e.g. long above confidence threshold)
- [ ] Metrics: total return, Sharpe, max drawdown, hit rate, turnover
- [ ] Benchmark vs buy-and-hold
- [ ] Parameter sweep over confidence thresholds / horizons
- [ ] Report output (tables + equity curve)

**Exit criteria:** a repeatable command that produces a performance report for a
chosen date range and watchlist.

---

## Phase 4 — Paper trading ⬜

Run the strategy forward against Alpaca's paper account.

- [ ] Alpaca trading client (paper endpoint only)
- [ ] Position sizing + risk limits (max position, max exposure, stop rules)
- [ ] Scheduler: daily signal → target portfolio → orders
- [ ] Reconciliation + fill logging
- [ ] Dashboard: open positions, P&L, signal history
- [ ] Kill switch

**Exit criteria:** the agent maintains a paper portfolio unattended and its
decisions are auditable after the fact.

---

## Explicitly out of scope (for now)

- Live money / real brokerage execution
- Intraday / high-frequency strategies
- Options, futures, crypto
- Multi-user accounts or auth

## Known gaps to revisit

- No fundamentals (P/E, margins, revenue growth) or analyst estimates yet —
  candidate source: Financial Modeling Prep or Alpha Vantage free tier.
- No earnings calendar.
- `yfinance` `.info` (sector, market cap) is unreliable from cloud IPs.
- Alpaca sometimes tags macro stories to multiple tickers — noise for phase 2 to weight down.
