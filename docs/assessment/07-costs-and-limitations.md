# 7. Costs, Constraints, and Limitations

> Part of the Complete Journal assessment. All figures are 2026-10 estimates; pricing labeled [U] conflicts across sources — re-verify before budgeting.

## 7.1 Build cost (custom path, section 05/06)

| Item | Estimate | Basis |
|---|---|---|
| MVP (CSV import, reconstruction, editor, links, search, basic stats) | **4–6 person-weeks** | Engineering judgment (section 05.8) |
| Broker sync + charts + exports | 3–5 pw | " |
| AI layer + polish | 3–4 pw | " |
| **Total to full scope** | **~10–15 pw** (4–7 months part-time) | " |
| Ongoing maintenance | **1–3 days/quarter** (API churn, CSV drift) | " |

## 7.2 Running costs (monthly)

| Item | Custom build | Notes |
|---|---|---|
| Hosting | $0 (local) – $5 (VPS for always-on sync) | VPS optional; MVP needs none |
| Tradovate API add-on | ~$25 [I/U] | Only if on Tradovate and wanting auto-sync |
| ProjectX API | $29 [V, Topstep help] | Only if on TopstepX/ProjectX |
| Market data (Databento historical OHLCV) | ~$0–5 | Pennies per session of 1-min bars; $125 free credits to start |
| LLM API (daily digest, weekly themes, RAG) | $1–5 (Sonnet-tier); <$0.50 (Haiku) | [V pricing, 2026-10] |
| Backups (object storage) | <$1 | Litestream to B2/S3 |
| **Total** | **~$5–15/mo** + at most one platform API fee | |

**Comparison — SaaS journals**: TradesViz Pro ~$20–30/mo; TradeZella $35–99/mo; TraderSync $30–80/mo; Edgewonk ~$170–200/yr; Journalytix $47/mo. [S — volatile]

## 7.3 Hard constraints to design around

1. **Tradovate history**: API returns only the current session's fills; the journal must sweep and persist during/after each session (or obtain Reporting API access, undocumented). [V]
2. **Rithmic**: no individual API; one-connection-per-credential; manual R Trader CSV is one-day-at-a-time. [V/I]
3. **No read-only API scopes** on ProjectX (key = full trading access) and effectively none on Rithmic — read-only is enforced structurally (never implement order endpoints) + keychain credential storage. [I/U]
4. **Charts as seen cannot be reconstructed**: stored OHLCV re-renders price, never the trader's indicators/drawings/DOM; screenshots at capture time are the only honest record. Reconstructed charts must be labeled as such. [V/EJ]
5. **TradingView exposes no fill data** to end users; capture happens at the broker behind it. [V]
6. **Market-data licensing**: Tradovate API *chart* data sits behind CME fees ($290–500/mo figures, conflicting [U]) — avoided entirely via Databento + screenshots.
7. **Prop-firm rules**: read-only journal sync is universally tolerated; *automation* policies vary and conflict across sources — the user must verify their firm's current written policy. 🚩
8. **API churn**: Tradovate API in maintenance mode post-acquisition [I]; ProjectX narrowed partner support during 2025–26 [U]; community client libraries are thin or semi-abandoned. CSV importers are permanent insurance.
9. **Statistical honesty**: a few hundred trades cannot validate most edge claims; the analytics layer must display sample sizes and confidence intervals rather than manufacture insight (section 04).
10. **AI limits**: no embeddings endpoint on the Claude API (use local/third-party embeddings); LLM interpretations of intent are inference and must be provenance-labeled, never merged into original writing.

## 7.4 Risk register (top 6, with mitigations)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Reconstruction bugs (reversals, same-ms fills, fees) | Medium | High (trust) | Immutable executions + `algorithm_version` re-runs; reconcile vs broker P&L daily; golden-file tests; optional TradesViz cross-check during build |
| Broker API change/retirement | Medium | Medium | CSV-first design; thin in-repo clients; raw payload storage |
| Build stalls mid-way | Medium | Medium | MVP ordering puts the journal + CSV import first — value lands in weeks 1–6; interim Obsidian habit from day 0 |
| Data loss | Low | Severe | Litestream continuous replication + git mirror + attachment backups; restore drills |
| Scope creep into a trading platform | Medium | Medium | Journal-first acceptance criteria (J1–J10) as the standing test; no order endpoints ever |
| Vendor figures wrong (pricing/policies marked [U]) | Medium | Low–Med | 🚩 verification checklist in section 02.7 before spending |
