# Roadmap

The project is built in four phases. Each phase is usable on its own and leaves
the previous one working.

Legend: ✅ done · 🔜 next up · ⬜ not started

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

## Phase 2 — LLM reasoning layer 🔜

Turn a per-ticker snapshot into a structured view with a confidence score.

- [ ] Define the output schema (`stance`, `confidence` 0–1, `rationale`,
      `key_factors`, `risks`, `time_horizon`)
- [ ] Prompt design: feed price stats + recent headlines, ask for the schema
- [ ] Model call wrapper (provider-agnostic; retries, timeout, cost logging)
- [ ] Confidence calibration — track predicted confidence vs realized outcome
- [ ] Add the reasoning block to the web page
- [ ] Cache reasoning alongside the data snapshot
- [ ] Guardrails: refuse/flag on thin or stale data

**Exit criteria:** each ticker on the page shows a scored, sourced thesis that
updates with the data.

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
