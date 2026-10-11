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

## Decisions

- ✅ **D1 (user, 2026-10-11)**: Complete Journal supports **ALL firms, platforms, and account types** — it is a universal journal, not a single-integration tool. Resolves former assumption A1. Architectural consequence: a platform-agnostic ingestion layer — one normalized execution schema + pluggable importer adapters. CSV/file importers are the universal tier (every platform exports something); API adapters (Tradovate, ProjectX, IBKR Flex, MT5, cTrader, NT8 add-on) are an optional tier layered on the same normalized schema. The generic column-mapping CSV importer guarantees that even unlisted platforms can feed the journal.

## Assumptions (marked for review)

- 🚩 **A2**: Phase 1 implementation now underway (user go-ahead given via D1 + "start Phase 1" standing offer accepted in context).
- 🚩 **A3**: Pricing/policy figures labeled [U] in the assessment must be re-verified before money is spent.
- 🚩 **A4**: Platform-specific CSV importers are built against *documented* export layouts (synthetic fixtures); they must be validated against real export files from each platform before being trusted. The generic mapping importer is the safe path meanwhile.

## Phase 1 — MVP: capture + journal core 🔄 (core built 2026-10-11, 50 tests passing)

| Item | Status | Notes |
|---|---|---|
| Schema: immutable `executions` → derived `trades`, `entries` + versions + addenda, `links`, `tags`, `attachments`, `ai_artifacts`, FTS5 | ✅ | `completejournal/schema.sql` |
| CSV importers: Tradovate, NinjaTrader 8, Rithmic R Trader + **generic column-mapping importer** (the universal tier per D1) | ✅ | 🚩 A4: validated on synthetic fixtures only — run real platform exports through them |
| FIFO reconstruction: flat→flat trades, scale-ins/outs, **reversal splitting**, pro-rata fees, rebuildable (`algorithm_version`) | ✅ | 10 golden-scenario tests incl. reversal fee attribution |
| Reconciliation report (computed vs platform statement, per account+day) | ✅ | `analytics.reconciliation` |
| Journal store: versioned immutability, addenda, soft-delete only, AI structurally barred from `entries` | ✅ | provenance invariants tested |
| FTS5 search with snippets; bidirectional entry↔trade/session/instrument links | ✅ | |
| Core stats with sample-size honesty (n<30 flagged) + breakdowns + equity curve | ✅ | |
| Web UI: write / journal+search / session timeline / calendar / trades+detail / analytics / import | ✅ | @-mention autocomplete, markdown preview, image paste; TipTap rich editor still optional/deferred |
| CLI: init/import/rebuild/stats/reconcile/write/search/serve | ✅ | `python -m completejournal …` |
| Live verification | ✅ | CLI + HTTP smoke test: 3 platforms imported, P&L hand-checked (MES $52.50, ES $83.32, NQ $190.00) |
| Markdown/git export mirror + full data export | ✅ | `export.py`; CLI `export`; YAML front matter, CSV/JSON dumps |
| Attachments upload + clipboard image paste | ✅ | content-addressed, integrity-verified (`attachments.py`) |
| Month-grid calendar UI (P&L + writing density) | ✅ | day click opens session timeline |
| Backup & durability guide | ✅ | `docs/BACKUP.md` (Litestream + markdown mirror + restore drills) |

**Interim habits (zero code):** daily writing in markdown/Obsidian; daily CSV export ritual into `data/raw/<date>/` (gitignored).

## Phase 2 — Auto-sync + market context 🔄 (unblocked by D1: all-platform adapter architecture)

| Item | Status | Notes |
|---|---|---|
| @-mention auto-linking (@MES, @2026-10-09, @trade:12, @entry:5) + autocomplete API | ✅ | links created on save; additive, never destructive |
| Price-bar storage (`bars` table) + universal bars CSV importer + per-trade window API | ✅ | OHLC consistency validated; labeled *reconstructed* |
| Canvas candle chart with execution markers (zero-dependency, offline-first) | ✅ | CDN egress blocked in build env → hand-rolled; lightweight-charts remains an optional swap |
| **Tradovate REST adapter** (auth, token refresh, fills + fees + contract resolution, idempotent sync) | ✅ code | 🚩 **A5: not yet run against live API** (no credentials in build env); mocked-transport tests pass |
| **ProjectX adapter** (loginKey auth, Account/Trade search, contractId parsing, platform-P&L reconciliation) | ✅ code | 🚩 A5; side encoding (0=buy) to confirm on first live sync |
| Read-only guarantee | ✅ | no order endpoints exist in any adapter; enforced by tests |
| Databento OHLCV fetcher (plain HTTPS, key via env var) | ✅ code | 🚩 A5: mocked-transport tested; first live fetch needs DATABENTO_API_KEY |
| Tradovate WebSocket live sweep / ProjectX SignalR | ⏳ | REST backfill pattern first (assessment §5.3) |
| Screenshot folder import (content-addressed, per-day index entries, auto session links) | ✅ | CLI `import-screenshots --dir` |
| Sync CLI (`sync --platform tradovate\|projectx`, env-var credentials) | ✅ | credentials never stored |
| Economic calendar, plan pinning UI, Tauri wrap | ⏳ | |

- 🚩 **A5**: Sync adapters are built from official docs + community SDKs with mocked-transport tests. First live run (user credentials required) must confirm: Tradovate fillFee fields, ProjectX side encoding, timestamp formats.

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
