# Complete Journal

**Automated Trade Intelligence, Market Journaling, and Performance Optimization.**

Complete Journal is — first and foremost — a *journal*: a persistent, searchable record of a trader's thinking, decisions, and evolving understanding of the market. Automated trade capture, market context, quantitative analytics, and AI assistance exist to serve the journal, not replace it.

## Repository contents

- [`ROADMAP.md`](ROADMAP.md) — living project tracker (phases, status, assumptions, deferred items).
- [`docs/assessment/`](docs/assessment/) — the research-backed assessment (existing products, API feasibility, architecture, build-vs-buy recommendation, costs, prioritized implementation roadmap).

## Status

Phase 0 research ✅ · Phase 1 journal + capture ✅ · Phase 2 sync + context ~80% · Phase 3 analytics ~70% · Phase 4 AI ⏳ · Phase 5 desktop installer ⏳ — see `ROADMAP.md`.

## Quick start

Runs on Windows, macOS and Linux (Python 3.11+). Everything stays on your
computer: one `journal.db` file plus an attachments folder.

```bash
pip install -e ".[dev]"
python -m completejournal serve --db journal.db      # open http://127.0.0.1:8321
```

In the app: **Import** → choose any export file → done. The platform, number
format, date order and timezone are detected automatically. Click **Load demo
data** to explore with sample trades first.

CLI equivalents:

```bash
python -m completejournal import --db journal.db --file any_export.csv   # auto-detected
python -m completejournal demo   --db journal.db                         # sample data
python -m pytest                                                          # 110 tests
```

Recognized exports: Tradovate (Orders, Position History), TopstepX/ProjectX
(Orders, Trades), NinjaTrader 8 (Executions, Trades — any locale), Rithmic
R|Trader (Order History), TradingView (Performance) — plus any other file with
recognizable fill or round-trip columns.

Any platform not covered by a preset importer can be ingested with the generic
column-mapping importer (`completejournal.importers.generic`) — that is the
universality guarantee: **all firms, platforms, and account types**.

Design principles: executions are immutable source data; trades are derived and
rebuildable; journal entries are versioned and never silently rewritten; AI
output is structurally confined to `ai_artifacts`; this codebase contains no
order-placement code anywhere, by design.
