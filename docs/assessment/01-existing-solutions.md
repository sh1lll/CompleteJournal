# 1. Existing Solutions — Market Survey

> Part of the Complete Journal assessment. Research date: 2026-10-11. Pricing is volatile; re-verify before relying on figures.
> Confidence labels: **[V]** verified from official vendor pages/help docs · **[S]** secondhand (third-party reviews, often affiliate/competitor-authored) · **[A]** anecdotal (user reviews/forums).

## 1.1 Comparison table

| Product | Price (approx. 2025–26) | Free tier | Futures coverage (Tradovate / Rithmic / NinjaTrader / TradingView) | Sync | Journaling quality | AI | Export / API |
|---|---|---|---|---|---|---|---|
| **TradeZella** | $35 / $59 / $99 per mo (mid-2026 restructure) [S/V] | Trial only | Tradovate ✓ sync, NinjaTrader ✓ sync, MT4/5, cTrader, TradeStation, IBKR; **no Rithmic** [V] | Broad auto-sync + CSV | **Strong**: notebook, daily journal, playbooks, templates | Zella AI (auto-tag, session review) | Weak — no public API |
| **Tradervue** | ~$29 / ~$49 per mo; futures need Gold [S] | ~30 trades/mo (stocks) | Rithmic via R\|Trader file import; NinjaTrader via 3rd-party plugin; TradeStation, IBKR [V] | Mostly file import | Good long-form notes; mature, plain | Minimal | **Public REST API** (trades, journal, notes) [V] |
| **TraderSync** | $29.95 / $49.95 / $79.95 per mo [S] | Trial only | 700–900+ brokers claimed; futures sync **disputed** (possibly CSV for NT/Rithmic) [S, conflicting] | Mixed | Form-driven (setup/mistake tagging) | "Cypher" AI chat; Elite coach | CSV; no API |
| **Edgewonk** | ~$169–197/yr [S] | None | CSV import for most (NT7/8, DAS, IBKR, Quantower); claimed MT4/5 auto-sync [S, conflicting] | **Mostly manual/CSV** | **Deep**: diary, emotions, phase-by-phase trade comments, Tiltmeter | None | Excel heritage; fairly portable |
| **TradesViz** | Free (stocks); Pro ~$19.99, Platinum ~$29.99 per mo [V/S] | **Yes, generous** | **Tradovate direct sync**; Rithmic via R-Trader; NinjaTrader, Sierra; many prop firms (Topstep, MFFU, TradeDay…) [V] | Auto-sync + CSV | Rich-text, 3 note types, searchable | AI insights + **REST API & hosted MCP server** | **Best-in-class data access** [V] |
| **Journalytix (Jigsaw)** | $47/mo or $399/yr (free w/ Earn2Trade) [V/S] | No | Futures-native: NT8, Tradovate, daytradr, MT4/5 + **Rithmic**/CQG/TT feeds [V] | **Real-time (seconds)** [V, vendor] | Live in-session journaling | Limited | Unclear |
| **Chartlog** | $14.99–39.99/mo [S] | Trial only | **Equities-only (~10 brokers)**; no futures confirmed [S] | Auto (equities) | Light | None | Unclear |
| **Stonk Journal** | Free (donations) [A] | Fully free | **Manual entry only, no imports** [A] | Manual | Notes + screenshots, tags | None | Unclear |
| **UltraTrader** | Free tier; Pro ~$7–15/mo [S, conflicting] | Yes (sync paid) | Mobile-first; MT4/5 + crypto exchanges [S] | Auto on Pro | Lightweight, mobile | Some marketed | Unclear |
| **Trademetria** | Free (~30 orders/mo); $15–30/mo [S, conflicting] | Yes | 140+ brokers via file upload; API subset (IBKR, Schwab, Robinhood) [S] | Mixed | Basic | None | CSV |
| **Prop-native (Tradetanto, Lune, QC Journal)** | varies | varies | **ProjectX/TopstepX API-native** (Topstep + 15+ ProjectX firms), Rithmic/Tradovate | Real-time API | Light-to-moderate | Some | Unclear; all young |
| **Hoc-trade (TradeMedic)** | unpublished [S] | — | MT4/MT5 only (forex/crypto) | Account-linked | Not a journal | **AI-first behavioral pattern detection** | Unclear |

## 1.2 Highlights per product

- **TradeZella** — the polished all-rounder. Official broker list [V: [help article](https://help.tradezella.com/en/articles/10055421-list-of-supported-brokers-and-platforms)] confirms direct sync for Tradovate, NinjaTrader, TradeStation, IBKR, MT4/5, cTrader; file-upload-only for CQG, DAS, ATAS; **Rithmic, TopstepX, Apex absent**. Strongest writing surface of the big journals (notebook, daily journal, playbook rule-checklists checked against actual trades), TradingView-white-label charts with markers, tick replay + backtesting (tier-gated). Mid-2026 pricing restructure to $35/$59/$99 [V: [vendor blog](https://www.tradezella.com/blog/tradezella-pricing)]. Weakness: walled garden — no public API, limited export. Trustpilot ~4.8/~900 reviews; complaints cluster on sync/P&L bugs and unsupported brokers [A].
- **Tradervue** — the veteran. 70+ brokers [V: [broker list](https://www.tradervue.com/help/brokers)]; file-import culture; futures via IBKR/TOS/TradeStation/NinjaTrader; Rithmic only through R|Trader exports. Mature deep analytics (MFE/MAE on Gold). The standout is a **documented public REST API** covering trades, executions, journal entries, notes, and import [V: [github.com/tradervue/api-docs](https://github.com/tradervue/api-docs)]. Caveat: CSV export is trade-level and loses partial-fill detail [S].
- **TraderSync** — biggest marketing claims (700–900+ brokers), **futures auto-sync disputed** between sources; form-driven journaling; "Cypher" AI chat grounded in your trades is among the more real AI implementations [S]. No public API.
- **Edgewonk** — the most psychology/journal-first philosophy: integrated diary with emotions and screenshots, structured per-phase trade comments feeding Tiltmeter/efficiency analytics, 20 custom stat categories, free human journal review [V: [features](https://edgewonk.com/features)]. Fails the auto-capture half: CSV-driven daily import, dated UI, no AI. Cheapest serious option (~$169–197/yr).
- **TradesViz** — power-user analytics (600+ stats, rollover-adjusted futures P&L) with the **best futures/prop capture**: Tradovate direct sync, Rithmic via R-Trader, dedicated import paths for Topstep, My Funded Futures, Earn2Trade, TradeDay, FTMO etc. [V]. Rich-text notes in three types (trade/day/general) with export [V: [notes guide](https://www.tradesviz.com/blog/notes-complete-guide/)]. Unique in the market: **public REST API + hosted MCP server** so external AI assistants can read trades and write notes [V: [api-mcp](https://www.tradesviz.com/api-mcp/)]. Criticism: dense, overwhelming UI; analytics-first in spirit.
- **Journalytix (Jigsaw)** — genuinely **real-time** futures journaling (trades hit their server within seconds) across NT8/Tradovate/daytradr with Rithmic/CQG/TT feeds [V, vendor]. Narrow elsewhere; $47/mo is steep; no ProjectX/TopstepX support.
- **Prop-native newcomers** — TopstepX has a basic built-in per-trade journal [V: [Topstep help](https://intercom.help/topstep-llc/en/articles/9638876-topstepx-journal)]; Tradetanto/Lune/QC Journal sync via the ProjectX API across 15+ prop firms. All young, thin independent coverage, and much of the comparison content online is authored by these competitors — treat with caution [S/A].
- **Notion / Obsidian** — the inverse of the commercial journals: perfect freeform writing, total data ownership, real linking between thoughts — and **zero auto-capture**, hand-built formulas that break, no charts with trade markers. Obsidian's trading ecosystem is essentially DIY (but see `journalit`, section 05, which adds broker sync inside Obsidian).

## 1.3 Scoring against the journal acceptance criteria (section 03, J1–J10)

| Criterion | TradeZella | Tradervue | TraderSync | Edgewonk | TradesViz | Journalytix | Notion/Obsidian |
|---|---|---|---|---|---|---|---|
| J1 Blank entries independent of trades | ✓ (notebook) | ✓ (journal) | partial | ✓ (diary) | ✓ (general notes) | ✓ | ✓✓ |
| J2 Long-form rich text, image paste | ✓ | partial | partial | ✓ | ✓ | partial | ✓✓ |
| J3 Pre-market plan vs actual | partial (playbooks) | ✗ | ✗ | partial | partial | partial | manual |
| J4 Quick intraday capture | partial | ✗ | ✗ | ✗ | partial | ✓✓ (real-time) | partial |
| J5 Entry↔trade↔session↔entry links | partial (tags/dates) | partial | partial | partial | partial | partial | ✓ (manual links) |
| J6 Immutable originals / visible revisions | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | partial (git/sync history) |
| J7 AI output segregated | partial | n/a | partial | n/a | partial | n/a | n/a |
| J8 Full-text search over writing | ✓ | ✓ | ✓ | partial | ✓ | ? | ✓✓ |
| J9 Full export of writing | ✗ | ✓ (API) | ✗ | partial | ✓ (API/HTML) | ? | ✓✓ |
| J10 Writing works when integrations down | ✓ (SaaS up) | ✓ | ✓ | ✓ (local-ish) | ✓ | ? | ✓✓ (local) |

(✓✓ = exemplary; all SaaS products share the dependency that **the company staying in business is a J10 prerequisite**.)

## 1.4 Conclusions

**(a) Closest to the journal-first + auto-capture vision:** none fully deliver both. TradeZella (best writing-surface + sync combo, but walled garden, no Rithmic), TradesViz (best futures/prop capture + only API/MCP data access, but analytics-first UX), Edgewonk (most journal-first philosophy, no auto-capture), Journalytix (unique real-time capture, narrow elsewhere).

**(b) Common market gaps** — these define Complete Journal's opportunity:
1. Freeform writing is a bolted-on text box nearly everywhere; nobody approaches Notion/Obsidian-grade editing and backlinking.
2. **No product offers bidirectional linking** of arbitrary notes ↔ plans ↔ trades (thesis → trades → review threads).
3. Data ownership is mostly poor: Tradervue and TradesViz are the only real exceptions; no one offers local/markdown-native storage.
4. Rithmic auto-sync is a hole in mainstream products; ProjectX/prop coverage lives with fragile newcomers.
5. Complex-position accuracy (partial fills, scaling, reversals) is where user complaints concentrate [A].
6. No product preserves immutability/provenance of original writing (J6) — the "what I believed at the time" guarantee simply doesn't exist in the market.
7. AI is mostly summarization/auto-tagging; retrieval-over-your-own-thinking is absent.

**(c) Confidence:** broker lists for TradeZella/Tradervue/TradesViz/Journalytix and the Tradervue/TradesViz APIs are [V]; all pricing is [S] and volatile; all sentiment is [A] and heavily polluted by competitor-authored content marketing.

**Key sources:** [TradeZella broker list](https://help.tradezella.com/en/articles/10055421-list-of-supported-brokers-and-platforms) · [TradeZella pricing](https://www.tradezella.com/blog/tradezella-pricing) · [Tradervue brokers](https://www.tradervue.com/help/brokers) · [Tradervue API](https://github.com/tradervue/api-docs) · [TradesViz pricing](https://tradesviz.com/pricing/) · [TradesViz API/MCP](https://www.tradesviz.com/api-mcp/) · [Edgewonk features](https://edgewonk.com/features) · [Topstep journal](https://intercom.help/topstep-llc/en/articles/9638876-topstepx-journal) · [Trustpilot TradeZella](https://www.trustpilot.com/review/tradezella.com)
