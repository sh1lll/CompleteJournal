# Complete Journal — Research Assessment: Executive Summary

> Research date: 2026-10-11. Full detail in sections 01–08. Confidence labels used throughout: **[V]** verified from official sources · **[S]/[I]** secondhand/inferred · **[U]** uncertain · **[EJ]** engineering judgment · 🚩 needs user input.

## The verdict

**Build it — incrementally, journal-first, with CSV capture as the permanent foundation and APIs layered on top.** No existing product delivers the defining features of the vision (bidirectional thought↔trade linking, immutable original writing with provenance, local-first data ownership, AI that cites rather than concludes), while the automated-capture half — the usual reason to buy — is tractable to build for the Tradovate/TopstepX/NinjaTrader ecosystems and is *equally limited for commercial products* on Rithmic. Estimated effort: **MVP in 4–6 person-weeks, full scope ~10–15 pw**; running costs **~$5–15/month** plus at most one platform API fee — less than any serious SaaS journal.

## Eight findings that drive the recommendation

1. **Market gap is real** (§01): TradeZella has the best writing surface but is a walled garden with no API; TradesViz has the best futures/prop capture and the only API+MCP data access but is analytics-first; Edgewonk is the most journal-first in spirit but has no auto-capture. **No product preserves "what I believed at the time" (immutability), and none links theses → trades → reviews.**
2. **Capture is feasible** (§02): Tradovate REST/WebSocket exposes fills/orders/positions/balance for ~$25/mo [V/I] — but **only the current session's history**, so the journal must sweep and persist data itself. TopstepX/ProjectX has a purpose-built API ($29/mo) with real-time SignalR events and trade search with P&L [V]. NinjaTrader 8 needs a free custom add-on. **Rithmic is closed to individuals** — manual daily R Trader CSV is the honest path there. IBKR/MT5/cTrader are free and well-documented.
3. **CSV importers come first** regardless (§02.4): they are the historical-import path, the test fixtures, and the insurance against API churn (Tradovate is in maintenance mode post-acquisition [I]; ProjectX narrowed partner support [U]).
4. **The journal is a spec, not a feature list** (§03): entries as first-class records, blank page always one action away, written-at vs about-time semantics, versioned immutability, AI text architecturally segregated (`ai_artifacts` table, never mixed into entries), quick intraday capture, thesis threads.
5. **Charts**: reconstruct price context from stored Databento OHLCV (pennies/month [V]) rendered with lightweight-charts + execution markers, *labeled reconstructed*; screenshots at capture time remain the only honest "chart as I saw it." Avoid Tradovate API market data entirely (CME licensing, $290–500/mo figures [U]).
6. **Analytics must be honest** (§04): sample-size warnings and confidence intervals on every breakdown; process-vs-outcome grading as the core review axis; AI retrieval-with-citations ranked top value, AI "coach verdicts" explicitly rejected.
7. **Architecture** (§05): local-first FastAPI + SQLite(FTS5) single file + TipTap editor + lightweight-charts; immutable `executions` → derived `trades` (re-runnable, versioned algorithm) reconciled against broker P&L; Litestream backups + git markdown mirror. Open-source projects (TradeTally, journalit, Trading-Journal-AI) are quarries for importer/reconstruction code, not forks.
8. **Interim posture** (§06.3): start the writing habit and the daily CSV ritual **now** (zero code); optionally run TradesViz for a month or two as a reconciliation oracle during the build.

## The one question that matters most 🚩

**Which firm(s), platform(s), and account types do you actually trade?** (Rithmic vs Tradovate vs TopstepX; NT8 vs TradingView vs web.) This single answer selects the Phase-2 integration and is the largest open variable. Full unknowns list: §02.7.

## Deliverable map (brief → documents)

| Brief section | Document |
|---|---|
| 1. Existing solutions | [01-existing-solutions.md](01-existing-solutions.md) |
| 2. Feasibility | [02-feasibility.md](02-feasibility.md) |
| 3. Journal experience | [03-journal-experience.md](03-journal-experience.md) |
| 4. Analytics & AI | [04-analytics-and-ai.md](04-analytics-and-ai.md) |
| 5. Technical architecture | [05-architecture.md](05-architecture.md) |
| 6. Implementation strategy | [06-implementation-strategy.md](06-implementation-strategy.md) |
| 7. Costs & limitations | [07-costs-and-limitations.md](07-costs-and-limitations.md) |
| 8. Prioritized roadmap | [08-prioritized-roadmap.md](08-prioritized-roadmap.md) |
