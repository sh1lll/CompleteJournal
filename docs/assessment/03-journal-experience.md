# 3. The Journal Experience — Essential Capabilities Specification

> Part of the Complete Journal assessment. This section is a requirements/design specification derived from the project brief plus product-design judgment. It is **not** dependent on external research; the product-comparison section (01) evaluates existing tools against these requirements.

## 3.1 Design principle

The journal is the primary surface; trades are context attached to writing, not the other way around. Every design decision below follows one rule: **a blank page must always be one action away, and nothing written on it may ever be silently altered.**

## 3.2 Entry model

A single first-class record type — the **entry** — with these properties:

- **Body**: unrestricted long-form rich text / markdown. No required fields, no minimum structure, no forced tags. An entry may be three words or three thousand.
- **Kind** (optional, one label): `market-thought`, `pre-market`, `intraday`, `trade-review`, `post-trade`, `end-of-day`, `knowledge`, `psychology` — or none. Kind drives default placement in timeline views and which optional template is offered; it never constrains content.
- **Timestamp semantics**: `written_at` (immutable) is distinct from `about` (a date, session, time range, or trade the entry concerns). An end-of-day reflection written the next morning stays honest about both.
- **Immutability with visible revision history**: edits create versions; the original is always recoverable. Post-hoc annotations ("what I learned later") are **addenda** rendered distinctly below the original, never inline mutations. This is the mechanism that preserves "what I believed at the time" vs. "what I learned afterward."
- **Authorship provenance**: every block of content carries an author type — `trader`, `template`, `ai`. AI-generated text can never be saved as trader-authored. Visually distinct, filterable, excludable from search.

## 3.3 The writing surfaces

1. **The blank page** — global quick action (hotkey / single click) opens an empty entry, pre-linked to the current session date only. Nothing else.
2. **Quick capture (intraday)** — a minimal one-line capture bar that timestamps instantly and files the note into the session timeline; expandable into a full entry after the close. During a session, speed beats structure.
3. **Trade-attached writing** — from any trade, "write about this" opens an entry pre-linked to the trade. Optional prompts (thesis? invalidation? execution vs. plan? alternatives rejected? lesson?) render as dismissible ghost text, not form fields.
4. **Pre-market plan** — an optional template (narrative, bias, scenarios, levels, invalidation, scheduled events) that produces a normal entry. The plan is *pinned to the session* so the day's trades and EOD reflection can reference it, enabling plan-vs-actual review.
5. **End-of-day page** — a session view assembling that day's plan, quick captures, trades, and P&L as *sidebar context* around a blank writing area — the trader narrates the day with the evidence in view, rather than filling out a scorecard.
6. **Knowledge notes** — entries with no date-of-market relevance (strategy theory, psychology, rules, unresolved questions). First-class, same editor, same search, organized by links/tags rather than timeline.

## 3.4 Linking model (contextual connections)

- **Inline mentions**: typing `@` links a trade, instrument, session date, strategy/setup, or another entry; links are bidirectional (the trade shows every entry mentioning it; the entry shows its targets).
- **Theses as threads**: an entry can be marked as a *hypothesis/thesis*; later entries and trades can attach to it, producing a thread view: original thesis → intraday updates → associated trades → outcome reflection. This is the "coherent timeline connecting original thinking, market behavior, decisions, conclusions."
- **Attachments**: paste/drop images (chart screenshots, annotated charts) into any entry; attachments are stored content-addressed and survive entry edits.
- **Tags** are optional, flat or namespaced (`setup/orb`, `mistake/chased`), applied by the trader; AI may *suggest* tags but suggestions are pending until accepted and always marked as AI-originated.

## 3.5 Timeline & retrieval

- **Session view** (one trading day): plan → captures → trades (with markers) → EOD reflection, in time order.
- **Calendar views**: daily/weekly/monthly/yearly with both P&L and *writing density* (a journal that shows only money reinforces outcome-fixation; showing where thinking happened reinforces process).
- **Full-text search** across all entries and trade notes, with filters (kind, instrument, tag, date range, linked-trade outcome, author type).
- **Resurfacing**: "entries that mention this instrument/setup/mistake," "similar past sessions," "this day last month/year." These are retrieval features, valuable even with zero AI; AI only improves ranking.

## 3.6 What the journal must never do

- Require a field, tag, rating, or template to save an entry.
- Auto-summarize or auto-tag into the trader's own text.
- Silently rewrite history (edits are versioned; AI output is segregated; imported-data corrections are logged, not silent).
- Block writing when sync/API/network is down — writing is local-first and must work offline; trade links reconcile later.
- Reduce a day to a scorecard: metrics are context in the margin, not the page itself.

## 3.7 Acceptance criteria for any candidate product (used in section 01 comparison)

| # | Criterion | Why |
|---|-----------|-----|
| J1 | Blank, unstructured entries exist independent of trades | Journal-first |
| J2 | Long-form rich text with image paste, no length/structure limits | Real writing |
| J3 | Pre-market plan preserved + comparable to actuals | Plan-vs-actual |
| J4 | Quick intraday capture with timestamps | In-session use |
| J5 | Entries linkable to trades, sessions, instruments, other entries | Context web |
| J6 | Original text immutable; later notes distinguishable | Honest record |
| J7 | AI text visibly segregated from trader text | Provenance |
| J8 | Full-text search over all writing | Retrieval |
| J9 | Full export of writing (not just trades) in open format | Data ownership |
| J10 | Writing works when integrations are down | Durability |
