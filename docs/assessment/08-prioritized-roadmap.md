# 8. Prioritized Implementation Roadmap

> Part of the Complete Journal assessment. Ordered by practical value ÷ (feasibility risk × dependency depth). Effort in person-weeks (pw) from section 05.8. Items marked 🚩 depend on user confirmation (section 02.7).

## Phase 0 — Start now, zero code (this week)

| Step | Deliverable |
|---|---|
| 0.1 | **Begin the writing habit**: markdown folder (or Obsidian vault) with the section-03 entry kinds as optional templates (pre-market, intraday capture, trade review, EOD, knowledge). Content imports cleanly later. |
| 0.2 | **Daily CSV ritual**: export platform order/fill CSVs into `data/raw/<date>/` after each session. These become MVP test fixtures and guarantee zero data loss during the build. |
| 0.3 | 🚩 **Answer the unknowns** (section 02.7): firm(s), platform(s), account types, existing API subscriptions, firm automation policy, data budget. This selects the Phase-2 integration. |

## Phase 1 — MVP: capture + journal core (4–6 pw)

*Goal: every trade recorded, every thought writable, linked, and searchable — from CSVs alone.*

1. **Schema & core services**: SQLite (WAL, FTS5); tables `executions` (immutable, raw payload), `trades`, `sessions`, `entries`, `links`, `attachments`, `ai_artifacts` (empty for now); instrument reference table (tick size/value incl. micros).
2. **CSV importers** (priority by 🚩 answer): Tradovate orders+cash report, NT8 Trade Performance, R Trader Completed Orders; idempotent re-import via execution-ID + hash dedupe.
3. **Reconstruction engine**: FIFO lot matching, flat→flat trade boundaries, reversal splitting, fees; **golden-file tests** for partials/scales/reversals/same-ms fills; daily reconciliation report vs broker-reported P&L (discrepancies surfaced, never hidden).
4. **Journal editor**: TipTap with markdown serialization, image paste (content-addressed attachments), `@`-mentions linking trades/sessions/instruments/entries (bidirectional), optional templates, entry versioning (originals immutable; addenda distinct).
5. **Session view & calendar**: day timeline (plan → captures → trades → EOD), monthly calendar with P&L + writing density.
6. **Search**: FTS5 across entries + trade notes with filters.
7. **Core stats**: expectancy, profit factor, win rate, drawdown, equity curve per account; sample-size warnings from day one.
8. **Safety**: Litestream backup + markdown/git export mirror + full CSV/JSON export.

**Exit criteria**: a full week journaled end-to-end from real CSVs; reconstruction matches broker P&L to the cent (or diffs explained); restore-from-backup drill passes.

## Phase 2 — Auto-sync + market context (3–5 pw)

*Depends on Phase 1 + 🚩 platform answer.*

1. **Primary integration** (pick per 🚩): Tradovate REST backfill + WebSocket `user/syncrequest` sweep (history persisted locally — session-only API!), **or** ProjectX REST trade search + SignalR user hub, **or** NT8 NinjaScript AddOn posting `ExecutionUpdate` events to the journal.
2. Credential handling: OS keychain; no order endpoints implemented, ever.
3. **Dedupe/reconciliation UI**: sync vs CSV vs broker statement; missing-execution and quantity-mismatch alerts.
4. **Charts**: Databento post-session OHLCV fetch (±2h of 1-min bars around fills, cached) + lightweight-charts rendering with execution markers and entry/exit lines, labeled *reconstructed*; screenshot paste/watched-folder stays the primary "as-seen" record.
5. **Economic calendar** ingestion (FMP or similar) attached to sessions.
6. Pre-market **plan pinning** + plan-vs-actual side-by-side in the session view.

**Exit criteria**: a session captured with zero manual steps (if API available); every trade opens with a reconstructed chart + any screenshots; calendar events visible on the session.

## Phase 3 — Analytics depth + behavioral lens (2–3 pw, overlaps Phase 2)

1. Breakdowns (instrument, time-of-day, weekday, duration, tag/setup) with n and confidence intervals (bootstrap).
2. MAE/MFE from stored bars; slippage where limit prices exist.
3. Behavioral flags: post-loss re-entry timing, size escalation, overtrade-vs-baseline, plan-adherence checks.
4. Process-vs-outcome grading axis (trader-graded A–F, split analytics).
5. Weekly/monthly report pages (exportable).

## Phase 4 — AI layer (3–4 pw)

*Strictly after the archive has content; provenance architecture from Phase 1 already in place.*

1. Embeddings (local sentence-transformers or API) + hybrid FTS/vector retrieval: "when have I seen this before?"
2. Daily digest with citations → `ai_artifacts`, rendered distinctly, offered **after** EOD writing.
3. Plan-vs-actual questioner; weekly theme reports with citation lists.
4. Rule-vs-behavior discrepancy prompts (knowledge entries × measured stats).
5. Tag suggestions (pending-until-accepted).
   — Explicitly out of scope: AI trade grading/coach verdicts (section 04.2).

## Phase 5 — Polish & resilience (ongoing)

Tauri desktop wrap (optional) · mobile `/capture` PWA page · VPS/home-server deployment for live sync (optional) · import of the Phase-0 interim markdown archive · quarterly restore drills · importer upkeep.

## Dependency graph (summary)

```
0.3 🚩 answers ──► 2.1 integration choice
1.1 schema ──► 1.2 importers ──► 1.3 reconstruction ──► 1.7 stats ──► 3.* analytics
1.1 schema ──► 1.4 editor ──► 1.5 session view ──► 2.6 plan-vs-actual
1.3 + 2.4 bars ──► 3.2 MAE/MFE
1.4 entries + 1.6 search ──► 4.1 RAG ──► 4.2–4.5
```

## What is deliberately deferred

- Live always-on sync daemon (VPS) — post-hoc capture covers ~95% of journal value.
- Multi-user/sharing, order placement (never), mobile-native apps, TradingView Advanced Charts license, Polygon/Massive futures data (immature [U]).
