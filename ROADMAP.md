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

## Phase 2 — LLM reasoning layer 🚧

Turn the whole snapshot into one combined market read with per-ticker
confidence scores, plus a chat box to interrogate it.

- [x] Output schema (`market_summary`, `top_stories`, `themes`, and per ticker:
      `stance`, `confidence` 0–1, `rationale`, `key_factors`, `risks`, `catalysts`)
- [x] Prompt design: feed all price stats + all headlines together, one call,
      analyst-desk-note framing
- [x] Model wrapper (`reasoning.py`, Google Gemini free tier, model fallback on 503)
- [x] Market read + per-ticker read rendered on the page (async, non-blocking)
- [x] `/api/chat` — streaming chat grounded in the snapshot + read
- [x] Analysis cached separately from the data snapshot
- [x] Best-effort: page renders fine when the key is missing or the call fails
- [ ] Confidence calibration — track predicted confidence vs realized outcome
- [ ] Cost/usage logging per call

**Exit criteria:** the page shows a combined market read and a scored, sourced
thesis per ticker, and the chat can answer questions about them. *(Calibration
tracking deferred — needs Phase 3's historical loop.)*

---

## Phase 3 — Backtesting ⬜

Check whether the signals would have worked.

- [ ] Historical data loader (point-in-time prices + news, no look-ahead)
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
