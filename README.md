# Complete Journal

**Automated Trade Intelligence, Market Journaling, and Performance Optimization.**

Complete Journal is — first and foremost — a *journal*: a persistent, searchable record of a trader's thinking, decisions, and evolving understanding of the market. Automated trade capture, market context, quantitative analytics, and AI assistance exist to serve the journal, not replace it.

## Repository contents

- [`ROADMAP.md`](ROADMAP.md) — living project tracker (phases, status, assumptions, deferred items).
- [`docs/assessment/`](docs/assessment/) — the research-backed assessment (existing products, API feasibility, architecture, build-vs-buy recommendation, costs, prioritized implementation roadmap).

## Status

Phase 0 (research & assessment) ✅ · Phase 1 (MVP core) 🔄 — see `ROADMAP.md`.

## Quick start

```bash
pip install -e ".[dev]"
python -m pytest                      # 32 tests

# import a platform CSV (tradovate | ninjatrader | rithmic)
python -m completejournal import --db journal.db \
    --file fills.csv --format tradovate --account "Apex #1" --tz-offset-minutes -300

# write, search, stats, reconcile
echo "Pre-market: ..." | python -m completejournal write --db journal.db --kind pre-market
python -m completejournal search --db journal.db --query "breakout"
python -m completejournal stats --db journal.db
python -m completejournal reconcile --db journal.db

# web UI (local only)
python -m completejournal serve --db journal.db --port 8321
```

Any platform not covered by a preset importer can be ingested with the generic
column-mapping importer (`completejournal.importers.generic`) — that is the
universality guarantee: **all firms, platforms, and account types**.

Design principles: executions are immutable source data; trades are derived and
rebuildable; journal entries are versioned and never silently rewritten; AI
output is structurally confined to `ai_artifacts`; this codebase contains no
order-placement code anywhere, by design.
