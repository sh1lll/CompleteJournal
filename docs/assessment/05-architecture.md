# 5. Technical Architecture — Recommended Stack, Prior Art, Effort & Risks

> Part of the Complete Journal assessment. Research date: 2026-10-11.
> Confidence labels: **[V]** verified against live sources · **[EJ]** engineering judgment · **[U]** uncertain/needs confirmation.

## 5.1 Recommended reference architecture ("boring local-first")

| Layer | Choice | Rationale |
|---|---|---|
| Core | **Python + FastAPI** backend, single process | Best ecosystem overlap: broker clients (async_rithmic, Tradovate wrappers), pandas for analytics/CSV, easy LLM integration. [EJ] |
| Database | **SQLite (WAL) + FTS5 + sqlite-vec** — one file | Single user, embedded, zero ops; full-text and vector search in the same transaction scope. [EJ] |
| Journal content | **Markdown in DB rows** (source of truth) + automated git-committed markdown export mirror | Referential integrity + FTS without Obsidian-style file/index drift; the mirror gives data ownership, diffable history, and Obsidian interop. [EJ] |
| Frontend | **Browser SPA served by FastAPI** (Vue/React + Vite) | Local web app; wrap in Tauri later if a desktop binary is wanted. [EJ] |
| Editor | **TipTap (ProseMirror)** with markdown serialization, `@`-mention node for trades/sessions/instruments, image-paste | Mature mention/suggestion plugins; optional templates as content snippets. [EJ] |
| Charts | **TradingView lightweight-charts v5** (Apache-2.0, attribution required, ~35 kB, multi-pane) | Candles + volume + execution markers + entry/exit price lines. [V: [v5 blog](https://www.tradingview.com/blog/en/tradingview-lightweight-charts-version-5-50837)] |
| OHLCV | **Databento pay-as-you-go historical** (CME OHLCV-1s/1m), pulled after each session; screenshots remain first-class regardless | Avoids Tradovate/CME API market-data licensing entirely (§5.4). |
| Ingestion | Background asyncio tasks; **CSV import as the always-works fallback**; optional VPS/home-server for always-on sync | §5.3. |
| Backup | **Litestream** continuous SQLite replication + git for the markdown mirror + restic/rsync for attachments | Near-zero RPO, trivial restore. [EJ] |
| AI | Claude API (Haiku/Sonnet tier) + local or API embeddings into sqlite-vec; AI output **only** in a dedicated `ai_artifacts` table with source refs | §5.6. |

**Core data model [EJ]:** append-only `executions` (raw broker fills, immutable, `source`, `raw_payload` JSON, import batch id) → derived `trades` (round trips, rebuildable at any time — event-sourced in practice) → `sessions` (trading days) → `entries` (journal markdown, typed) → `links` (polymorphic bidirectional entry↔trade/session/instrument) → `attachments` (content-addressed files on disk, metadata in DB) → `ai_artifacts` (kind, model, prompt hash, `sources[]` of entry/trade ids). Keep broker-reported P&L alongside computed P&L and surface reconciliation diffs — never trust either silently.

## 5.2 Storage alternatives considered

- **Postgres / cloud DBs**: buy nothing for one user except ops burden; cloud contradicts data ownership. Revisit only for multi-device concurrent writes. [EJ]
- **Markdown files + index (Obsidian-style)** vs rows: files win on ownership, lose on integrity (stale trade links, FTS drift, sync conflicts). Rows + exported mirror gives both. Counter-example that proves the plugin route viable: **journalit** (§5.5) — but then you live in Obsidian's editor and lose control of the trade UI. [EJ]
- **Attachments**: content-addressed on disk (`attachments/ab/cd/<sha256>.png`); don't BLOB images into SQLite (bloat, backup churn). [EJ]
- **Provenance**: executions insert-only; re-imports idempotent via broker execution IDs + hash dedupe; trades carry `algorithm_version` so reconstruction is auditable and re-runnable. [EJ]
- **sqlite-vec** is still alpha-stage (v0.1.7-alpha as of early 2025 [V at search time / U today]); brute-force cosine in Python is a fine fallback at journal scale (thousands of chunks). [EJ]

## 5.3 App shape & sync

- **Start as a local web app** (one `uvicorn` process, browser UI, Tailscale for remote/mobile). Tauri/Electron packaging is a later nicety — broker sync and the data model are the hard parts, not windowing. [EJ]
- **Always-on sync**: Tradovate/Rithmic WebSockets need a continuously running process; a sleeping laptop misses events. Two sane patterns: **(a)** journal-first means post-hoc — a nightly/on-demand REST backfill of orders/fills covers ~95% of value with zero daemon (recommended for MVP); **(b)** live capture later via a ~$5/mo VPS or home mini-PC behind Tailscale. Fill/order data is account data (free with the account); only *market data* is license-gated. [EJ; gating V per community threads]
- **Mobile/quick-capture**: responsive PWA + a minimal `/capture` page (text + photo, auto-attached to today's session). [EJ]

## 5.4 Charting & market data — the key cost decision

- **Tradovate's own `md/getChart`** sits behind CME market-data licensing for API access; community threads report **$290/mo (2022 sub-vendor figure)** up to **$500/mo CME ILS (Jan 2025 thread)**, plus ~$25 API sub. Figures conflict and aren't official — **[U]** — but the conclusion stands: **don't build around Tradovate chart data.** ([thread 1](https://community.tradovate.com/t/whats-the-deal-with-market-subscriptions-and-api-access-to-charts-do-we-need-another-payment/11039), [thread 2](https://community.tradovate.com/t/is-cme-sub-vendor-requirement-for-api-access-is-290-per-month/6215))
- **Databento** [V: [pricing](https://databento.com/pricing)]: usage-based historical from $0.50/GB, $125 free credits, CME/CBOT/NYMEX/COMEX OHLCV available. Fetching a day of 1-min bars for 2–5 symbols post-session ≈ **pennies to low single-digit $/month** [EJ]. Live feeds (~$199/mo [U]) are unnecessary for post-hoc journaling.
- **Screenshots stay first-class** (paste/drag, or a watched folder for TradingView exports): zero cost, captures *your* annotations, and de-risks the vendor dependency. A reconstructed OHLCV chart is labeled *reconstructed* — it is never presented as "the chart as you saw it."

## 5.5 Trade reconstruction & open-source prior art

**Algorithm [EJ, informed by prior art]:**
1. Sort executions per (account, contract) by timestamp then execution id.
2. Maintain signed net position + FIFO queue of open lots; matched quantity realizes `(exit−entry)×qty×pointValue` minus fees.
3. **Trade boundary = position returns to zero** (scale-ins/outs stay inside one trade; flat→flat = one logical trade with avg entry/exit, MAE/MFE, duration).
4. **Reversals**: a fill crossing zero is split — closing quantity ends trade A, remainder opens trade B. The most common bug in naive implementations; test explicitly (also same-timestamp fills, fills spanning days, session-boundary policy).
5. **Reconciliation**: futures P&L is deterministic given contract specs (keep an instrument reference table incl. micros); compare computed vs broker-reported per day and surface mismatches.
6. `algorithm_version` on trades → re-run regenerates all trades from immutable executions.

**Prior art (stars verified via GitHub API, 2026-10-11) [V]:**

| Project | Stars | Stack | License | Fit |
|---|---|---|---|---|
| [TradeNote](https://github.com/Eleven-Trading/TradeNote) | 970 | Vue + MongoDB + Parse, Docker | GPL-3.0 [U] | Most mature; analytics-first, weak long-form journaling; heavy stack; GPL constrains derivatives. Reference, don't fork. |
| [LuxAlgo/trade-journal](https://github.com/LuxAlgo/trade-journal) | 445 | TypeScript, SQLite, Docker | MIT | New (Aug 2026), early; broker sync + AI reflection; schema may churn. Watch/borrow. |
| [TradeTally](https://github.com/GeneBO98/tradetally) | 340 | Vue + Node + PostgreSQL | check repo | Active TraderVue alternative, Schwab/IBKR auto-sync; stock-centric, journal secondary. **Best source for importer code.** |
| [journalit](https://github.com/Cursivez/journalit) | 234 | TypeScript **Obsidian plugin** | — | **Closest to journal-first**: broker sync incl. Tradovate/Rithmic/NinjaTrader, prop-firm tracking, inside a real markdown editor. Strongest fork/extend candidate *if* living in Obsidian is acceptable; otherwise mine its import code. |
| [deltalytix](https://github.com/hugodemenez/deltalytix) | 159 | Next.js, AI agents | — | SaaS-shaped, dashboard-first. |
| [Trading-Journal-AI](https://github.com/simonro/Trading-Journal-AI) | 77 | **FastAPI + React + SQLite**, Claude-powered | MIT | Local-first, no telemetry, CSV→round-trip reconstruction — architecturally the same shape as this proposal; young (Sep 2026). Strong reference. |
| [OpenTraderWorld](https://github.com/G-OTW/OpenTraderWorld) | 65 | Rust, MCP server | fair-source | Broad workspace incl. journal; license limits reuse. |

**Broker clients [V]:** [tradovate/example-api-js](https://github.com/tradovate/example-api-js) (official patterns, de-facto docs) · [TradovatePy](https://github.com/antonio-hickey/TradovatePy) (45★, semi-abandoned after API pricing changes — [thread](https://community.tradovate.com/t/python-tradovate-api-wrapper/7044)) · [Tradovate-Python-Client](https://github.com/cullen-b/Tradovate-Python-Client) (31★) · [async_rithmic](https://github.com/rundef/async_rithmic) (122★, active, reconnect logic — **recommended Rithmic path**, [docs](https://async-rithmic.readthedocs.io)). Plan to write a thin in-repo Tradovate client over the official examples. **NinjaTrader**: no official REST API for account history — CSV export (or an NT8 add-on writing executions to disk) is the practical route. [EJ/U]

## 5.6 AI layer

- **Provenance is architectural**: AI never writes into `entries`. Generations land in `ai_artifacts(id, kind, model, created_at, content_md, sources)`; UI renders them distinctly with clickable citations. Original writing stays byte-identical forever.
- **RAG**: chunk entries (~500 tokens), hybrid retrieval = FTS5 BM25 + vector with reciprocal-rank fusion; local sentence-transformers (free, private) or Voyage/OpenAI embeddings (trivial cost). The Claude API has no embeddings endpoint. [V]
- **Costs** [V, 2026-10 pricing]: Sonnet 5.5 $2/$10 per MTok in/out; Haiku 5.5 $0.10/$0.50. Daily summary (~15k in / 1k out) ≈ $0.04/day on Sonnet; weekly theme pass ≈ $0.20. **Realistic single-user spend: $1–5/month** (under $0.50 on Haiku); Batch API halves it.

## 5.7 Search & security

- **FTS5 wins outright** for one user: zero extra process, BM25, snippets, triggers keep it in sync. Meilisearch = a second service for typo-tolerance you don't need. [EJ]
- **Read-only posture**: Tradovate API keys can be scoped to exclude trading permissions [U — verify in key UI]; Rithmic credentials are account creds, so the control is structural — never implement order endpoints in the client wrapper. Credentials in the OS keychain (`keyring`), never DB or git; VPS deployments bind to localhost + Tailscale. [EJ]

## 5.8 Effort & running costs [EJ]

One competent dev with AI assistance, person-weeks (pw):

| Phase | Scope | Effort |
|---|---|---|
| **1 — MVP** | Schema; CSV import (Tradovate/NT exports); FIFO reconstruction + reversal splitting + golden-file tests; sessions; TipTap editor w/ image paste; entry↔trade links; FTS5 search; basic stats; Litestream | **4–6 pw** |
| **2 — Sync + charts** | Tradovate OAuth/REST backfill (+ optional WS); async_rithmic ingest; dedupe/reconciliation UI; Databento OHLCV + lightweight-charts markers; markdown/git export; CSV/Excel export | **3–5 pw** |
| **3 — AI + polish** | Embeddings + hybrid RAG; daily summaries w/ citations; ai_artifacts UI; templates; mobile capture; analytics breakdowns; optional Tauri wrap | **3–4 pw** |
| **Total** | | **~10–15 pw** (4–7 months part-time) |

**Maintenance**: ~1–3 days/quarter, dominated by broker API churn and CSV format drift; permanent CSV fallback is the insurance. **Running costs**: $0–5 hosting; Databento ~$0–5; LLM $1–5; backup <$1 → **~$5–15/month total**.

## 5.9 Key risks

1. **Tradovate market-data licensing** (conflicting $290–500/mo figures) — mitigated: Databento bars + screenshots; fill/account data stays free.
2. **Broker API churn, thin community clients** — thin in-repo client over official examples + CSV fallback.
3. **Reconstruction correctness** (reversals, same-ms fills, fee attribution) — immutable executions, broker-P&L reconciliation, golden-file tests.
4. **sqlite-vec maturity** — brute-force cosine fallback is fine at this scale.
5. **Scope creep toward a trading platform** — journal-first framing (entries first-class, trades as linked context) is the differentiator; protect it.
6. **Young prior art** (LuxAlgo, Trading-Journal-AI are months old) — borrow code, don't depend on them.
