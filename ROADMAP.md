# Complete Journal — Research & Implementation Roadmap

> Living tracker for the Complete Journal project. Updated continuously as work progresses.
> Status legend: ✅ done · 🔄 in progress · ⏳ queued · 🚩 needs user input/review

## Phase 0 — Research & Assessment

| # | Task | Status | Notes |
|---|------|--------|-------|
| 0.1 | Repo inspection & plan | ✅ | Repo was empty (LICENSE + stub README). Greenfield. |
| 0.2 | Research existing journal products | ✅ | Report synthesized → `docs/assessment/01-existing-solutions.md` |
| 0.3 | Research broker/platform/prop-firm API feasibility | ✅ | → `docs/assessment/02-feasibility.md` |
| 0.4 | Research architecture building blocks | ✅ | → `docs/assessment/05-architecture.md` |
| 0.5a | Draft sections 03 (journal experience) & 04 (analytics/AI) | ✅ | Spec-driven |
| 0.5b | Synthesize research-dependent sections (01, 02, 05, 06, 07, 08) + executive summary (00) | ✅ | All eight assessment documents complete in `docs/assessment/` |
| 0.6 | Commit, push, publish report page | ✅ | Pushed to `claude/lucid-wright-6iz9l2`; report page: https://claude.ai/artifact/RweM6WpF5CGyPSK44To7nQ |

**Phase 0 outcome (recommendation):** Build Complete Journal incrementally — journal-first, local-first (FastAPI + SQLite/FTS5 + TipTap + lightweight-charts), CSV capture as the permanent foundation, APIs (Tradovate/ProjectX/NT8 add-on) layered on. MVP 4–6 pw; full ~10–15 pw; ~$5–15/mo running costs. See `docs/assessment/00-executive-summary.md`.

## Assumptions (marked for review)

- 🚩 **A1**: User trades futures via prop firms (inferred from brief language). Research weighted toward Tradovate / Rithmic / NinjaTrader / TradingView / ProjectX; general brokers covered secondarily. **Confirm actual firm(s), platform(s), account types — this selects the Phase-2 integration (see `docs/assessment/02-feasibility.md` §2.7 for the full unknowns list).**
- 🚩 **A2**: Deliverable for this phase is the research assessment + plan; implementation begins on user go-ahead (or continues autonomously if instructed).
- 🚩 **A3**: Pricing/policy figures labeled [U] in the assessment (Tradovate fees, ProjectX firm list, prop-firm automation policies, SaaS prices) must be re-verified before money is spent.

## Phase 0.5 — User inputs needed before Phase 2 (🚩 blocking only the integration choice, not Phase 1)

1. Which prop firm(s)/broker(s) and account types (Rithmic vs Tradovate vs TopstepX; eval vs funded)?
2. Which execution front-end (NT8 desktop, TradingView, TopstepX web, R Trader, Quantower)?
3. Existing API subscriptions (Tradovate ~$25/mo add-on, ProjectX $29/mo)?
4. Firm's current written automation/data-access policy.
5. Market-data budget tolerance ($0 prototype vs Databento usage-based).

## Phase 1 — MVP: capture + journal core (4–6 pw) ⏳

Schema (immutable `executions` → derived `trades`, `entries`, `links`, `attachments`, `ai_artifacts`) · CSV importers (Tradovate/NT8/R Trader) · FIFO reconstruction + reversal splitting + golden-file tests + broker-P&L reconciliation · TipTap editor (image paste, @-mentions, versioned immutability) · session view & calendar · FTS5 search · core stats with sample-size warnings · Litestream backup + git markdown mirror + full export.
**Interim habits to start immediately (zero code):** daily writing in markdown/Obsidian; daily CSV export ritual into `data/raw/<date>/`.

## Phase 2 — Auto-sync + market context (3–5 pw) ⏳ (blocked on 🚩 Phase 0.5)

Primary integration (Tradovate WS sweep / ProjectX SignalR / NT8 AddOn) · keychain credentials, no order endpoints ever · dedupe/reconciliation UI · Databento OHLCV + lightweight-charts with execution markers (labeled *reconstructed*) · screenshot watched-folder · economic calendar · plan pinning + plan-vs-actual.

## Phase 3 — Analytics depth + behavioral lens (2–3 pw) ⏳

Breakdowns with n + confidence intervals · MAE/MFE · slippage · behavioral flags (post-loss re-entry, size escalation, overtrading) · process-vs-outcome grading · weekly/monthly reports.

## Phase 4 — AI layer (3–4 pw) ⏳

Embeddings + hybrid retrieval ("when have I seen this before?") · daily digest with citations (stored in `ai_artifacts`, never in entries) · plan-vs-actual questioner · weekly theme reports · rule-vs-behavior prompts · tag suggestions. Explicitly excluded: AI trade grading/coach verdicts.

## Phase 5 — Polish & resilience (ongoing) ⏳

Optional Tauri wrap · mobile `/capture` PWA · optional VPS for live sync · import of interim markdown archive · quarterly restore drills · importer upkeep.

## Deferred / open items

- 🚩 Phase 0.5 user answers (above) — only these block Phase 2.
- Re-verify all [U]-labeled figures before purchase decisions (A3).
- Optional: 1–2 months of TradesViz as a reconciliation oracle during Phase 1–2.
- Deliberately deferred: always-on sync daemon, multi-user, order placement (never), native mobile apps, TradingView Advanced Charts license, Polygon/Massive futures data.
