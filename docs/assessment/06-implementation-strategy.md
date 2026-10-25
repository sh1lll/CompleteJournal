# 6. Implementation Strategy — Buy, Integrate, or Build

> Part of the Complete Journal assessment. Synthesizes sections 01 (market), 02 (feasibility), 03 (journal spec), 04 (analytics/AI), 05 (architecture).

## 6.1 The decision in one paragraph

No existing product satisfies the journal-first vision (section 01.4: no bidirectional thought↔trade linking, no immutability/provenance of original writing, mostly poor data ownership), while the capture problem — the traditional reason to buy — turns out to be **tractable to build** for the Tradovate/ProjectX/NT8 ecosystems (section 02) and *equally hard for commercial products* on Rithmic. Custom development is therefore justified **by the journal, not by the tracker**: the differentiating 60% of the vision (writing surfaces, linking, provenance, AI-with-citations, local-first ownership) is exactly what cannot be bought. The recommendation is a **staged hybrid**: start journaling immediately with an interim setup, build Complete Journal incrementally (section 08), and optionally keep a cheap commercial journal as a reconciliation reference during the build.

## 6.2 Options evaluated

### Option A — Buy: adopt a commercial journal
Best candidates: **TradesViz** (best futures/prop capture + API/MCP data access, ~$20–30/mo) or **TradeZella** (best writing surface + sync, $35–99/mo, walled garden).
- ✅ Working capture in a day; proven reconstruction; charts with markers.
- ❌ Fails journal criteria J3, J5, J6 (plan-vs-actual, real linking, immutability); TradeZella has no export path for your writing; SaaS dependency contradicts section 8 of the brief ("the journal must remain usable even if a platform changes").
- **Verdict**: insufficient alone; viable as a *temporary* capture layer or permanent reconciliation reference.

### Option B — Integrate: Obsidian/Notion for writing + commercial journal for capture
Including the **journalit** Obsidian plugin (broker sync incl. Tradovate/Rithmic/NinjaTrader inside markdown).
- ✅ Immediately excellent writing + ownership; journalit is the closest existing thing to the vision.
- ❌ Two disconnected systems (the thought↔trade link — the core of the vision — remains manual); journalit is young (234★) and you inherit both Obsidian's editor constraints and the plugin's schema; analytics stay shallow; provenance (J6/J7) still unsolved.
- **Verdict**: the best *interim* state and a good source of import code, not the destination.

### Option C — Build on an open-source base (fork TradeNote / TradeTally / Trading-Journal-AI)
- ✅ Importer/reconstruction code exists to borrow.
- ❌ All are analytics-first; retrofitting a journal-first data model (entries as the primary entity, links, immutability, ai_artifacts) into a dashboard-first schema costs more than greenfield with borrowed parts; TradeNote's GPL + Mongo/Parse stack is a poor base; the journal-first candidates are months old.
- **Verdict**: **quarry, don't fork** — lift importer parsers, reconstruction tests, and API-client patterns.

### Option D — Build Complete Journal (recommended)
The architecture in section 05: FastAPI + SQLite(FTS5) + TipTap + lightweight-charts, local-first, immutable executions → derived trades, entries as first-class records, provenance-isolated AI. ~10–15 person-weeks to full scope; MVP in 4–6; ~$5–15/mo running costs vs $240–1,200/yr for SaaS.
- ✅ Only path that satisfies J1–J10, the linking model, and data ownership; costs less to *run* than any paid SaaS; CSV-first design survives API churn.
- ❌ Real build effort; you own maintenance (~1–3 days/quarter); reconstruction correctness is on you (mitigations in 05.9).

## 6.3 Recommended posture while building

1. **Week 0 (before any code)**: start the daily writing habit now in Obsidian or plain markdown using the section-03 entry kinds as filenames/templates — this content imports cleanly later, and the habit is the product's whole point.
2. **Interim capture**: export platform CSVs daily (2-minute ritual, section 02.4) into a `data/raw/` folder from day one — nothing is lost while the system is built, and these files become the MVP's test fixtures.
3. **Optional cross-check**: a TradesViz free/Pro account during the build provides independently computed P&L to reconcile the reconstruction engine against (worth one or two months' subscription purely as a test oracle).
4. **Build order**: per section 08 — capture/reconstruction + editor first; sync, charts, analytics next; AI last.

## 6.4 Decision gates 🚩

- If the user's accounts turn out to be **Rithmic-only with no Tradovate/TopstepX option**, auto-sync is off the table for a personal tool (section 02.2); the build still proceeds, but capture is CSV-ritual-based — and the marginal advantage of TradesViz's vendor sync grows. Re-evaluate at that point.
- If **build capacity is unavailable** (no 4–6 weeks for an MVP), fall back to Option B (journalit/Obsidian + TradesViz) and revisit.
