# Complete Journal

**Automated Trade Intelligence, Market Journaling, and Performance Optimization.**

Complete Journal is — first and foremost — a *journal*: a persistent, searchable record of a trader's thinking, decisions, and evolving understanding of the market. Automated trade capture, market context, quantitative analytics, and AI assistance exist to serve the journal, not replace it.

## Repository contents

- [`ROADMAP.md`](ROADMAP.md) — living project tracker (phases, status, assumptions, deferred items).
- [`docs/assessment/`](docs/assessment/) — the research-backed assessment (existing products, API feasibility, architecture, build-vs-buy recommendation, costs, prioritized implementation roadmap).

## Status

All planned features built ✅ · Windows, macOS and Linux builds pass on GitHub (tests, build, launch check) · Remaining items need accounts, certificates or a release decision — see `ROADMAP.md`. **Install:** [docs/INSTALL.md](docs/INSTALL.md) · **Signing:** [docs/SIGNING.md](docs/SIGNING.md).

## Quick start

Runs on Windows, macOS and Linux (Python 3.11+). Everything stays on your
computer: one `journal.db` file plus an attachments folder.

```bash
pip install -e ".[dev,desktop]"
completejournal-desktop                              # opens the app in its own window
# or: python -m completejournal serve --db journal.db  (browser tab at http://127.0.0.1:8321)
```

In the app: **Import** → choose any export file → done. The platform, number
format, date order and timezone are detected automatically. Click **Load demo
data** to explore with sample trades first.

CLI equivalents:

```bash
python -m completejournal import --db journal.db --file any_export.csv   # auto-detected
python -m completejournal demo   --db journal.db                         # sample data
python -m pytest                                                          # 172 tests
```

AI is optional. "Seen this before?", daily recaps, plan-vs-actual checks and
weekly/monthly reports all run on your computer without it. With an Anthropic
API key (Settings → AI) you also get written AI summaries and "Ask your
journal"; AI text is kept separate from your writing and cites its sources.

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
