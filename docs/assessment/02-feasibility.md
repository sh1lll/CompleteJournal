# 2. Automated Trade Capture — Feasibility by Platform

> Part of the Complete Journal assessment. Research date: 2026-10-11.
> Confidence labels: **[V]** verified against official docs/help centers · **[I]** inferred from multiple consistent secondary sources · **[U]** uncertain/conflicting — verify before relying on it.

## 2.1 Summary table

| Platform | Data available | Access method | Real-time | History | Cost | Confidence |
|---|---|---|---|---|---|---|
| **Tradovate API** | fills, orders, positions, cashBalance, account | REST + WebSocket (`user/syncrequest`), token auth | WS push | **Current session only** (separate, poorly documented Reporting API for more) | ~$25/mo API add-on; **no market-data fee needed for fills** | V core / U fees |
| **ProjectX (TopstepX, The Futures Desk)** | accounts, orders, positions, **trades with P&L**, bars | REST + SignalR, API key | SignalR user hub | trade search is historical | $29/mo | V structure / U firm list |
| **Rithmic R\|API+** | everything | C++/.NET/protobuf; vendor agreement + conformance | yes | yes | impractical for individuals | I |
| **R Trader export** | completed orders/fills | manual CSV, **one day at a time** | no | per-day | free | V |
| **NinjaTrader 8** | executions, paired trades | NinjaScript AddOn (`Account.ExecutionUpdate`) or manual Trade Performance export | event-driven | local platform history | free | V |
| **TradingView** | none directly (alert webhooks; paper-trading export) | webhook; manual export | alerts only | n/a | paid plan for webhooks | V |
| **Interactive Brokers** | executions, P&L, positions, cash | **Flex Web Service** (token; ideal read-only) + TWS/CP API | TWS `execDetails` | 365 d/query; years via statements | free | V |
| **MT5** | deals, orders, positions, account | official Python package (Windows, terminal running) / EA | `OnTradeTransaction` | full server history | free | V |
| **cTrader** | deals (closed trades), positions | Open API (OAuth, protobuf) | event stream | deals yes, **orders no** | free | V/I |

## 2.2 Key platform findings

**Tradovate / NinjaTrader brokerage** — the best API option for prop futures traders, with two caveats. The REST API (`live.tradovateapi.com/v1`) exposes `fill/list`, `order/list`, `position/list`, `cashBalance/list`, `account/list` [V: [docs](https://docs.ninjatrader.com/api/rest-api-endpoints/orders/fill-list.md)]. **Caveat 1 — history**: `fill/list` returns only the *current trading session*; after ~5pm ET it archives and returns `[]`. A journal must sweep fills during/after each session and persist them itself (or use the undocumented Reporting API, `rpt-live.tradovateapi.com`) [V: [community thread](https://community.tradovate.com/t/how-to-retrieve-historical-fills-trades-via-oauth/12607)]. **Caveat 2 — maintenance mode**: post NinjaTrader acquisition, community moderators report API development has largely stopped [I]. Auth: API key → token (~80–90 min validity) → WebSocket `authorize`; `user/syncrequest` pushes fills/orders/positions/balance in real time (official guidance: use WS, not REST polling; rate limits are two-tier with 429 penalty tickets [V structure: [rate limits](https://partner.tradovate.com/overview/core-concepts/rate-limits)]). Cost ≈ $25/mo API add-on [I]. Crucially, **order/fill/account data does not require the CME market-data license** (only chart/market data does).

**ProjectX Gateway API** (TopstepX and other ProjectX firms) — purpose-built for this use case: REST trade search (fills **with realized P&L**), order/position/account search, historical bars, plus **SignalR real-time user hub** streaming orders, positions, balances. API key after subscribing ($29/mo). [V structure: [realtime docs](https://gateway.docs.projectx.com/docs/realtime/); community SDKs: [project-x-py](https://github.com/TexasCoding/project-x-py), [rundef/projectx-api](https://github.com/rundef/projectx-api)]. ⚠️ **[U]**: ProjectX reportedly wound down third-party support for most partner firms during 2025–26; as of Sept 2026 the docs may list only TopstepX and The Futures Desk — verify at gateway.docs.projectx.com. Note: the API key is **full trading access** (no read-only scope), so credential handling matters (§5.7).

**Rithmic** — direct R|API+ access requires a signed vendor agreement + conformance process; designed for vendors/institutions, **not practical for an individual** [I]. Prop traders' Rithmic credentials are firm-issued, and only one active connection per credential — a personal app login can conflict with the trader's own platform session (vendors like TradesViz get separate plugin logins). Realistic routes: (a) a third-party journal's existing Rithmic vendor sync, or (b) **R Trader manual CSV export** — Completed Orders grid, one day per export, add "Qty Filled"/"Order Number" columns, mind the timezone [V via journal help docs: [TradeZella guide](https://help.tradezella.com/en/articles/6839918-rithmic-r-trader-how-to-import-trades-from-rithmic-r-trader-into-tradezella-using-the-file-upload-method)].

**NinjaTrader 8 desktop** — no automated export built in (manual: Trade Performance → right-click → Export) [V: [NT forum staff answer](https://forum.ninjatrader.com/forum/ninjatrader-8/platform-technical-support-aa/1070410-add-on-for-export-trades)], but a **NinjaScript AddOn is fully feasible and free**: subscribe to `Account.ExecutionUpdate`/`OrderUpdate`/`PositionUpdate`, POST to a local journal endpoint; this is NT staff's recommended pattern [V]. Programmatic chart screenshots are possible from an add-on (full C#/.NET) — custom code, moderate effort [I].

**TradingView** — **no retail API for your own executed fills**; the "Broker REST API" is for brokers integrating into TV, not users pulling data out [V: [broker-api-docs](https://www.tradingview.com/broker-api-docs/)]. Fills belong to the underlying broker (a Tradovate/TopstepX account traded *through* TradingView is still captured via that broker's API). Alert webhooks capture strategy signals, not fills.

**Interactive Brokers** — the gold-standard fallback pattern: **Flex Web Service** (token + query ID, no gateway/2FA, explicitly read-only) delivers execution reports with 90+ fields incl. P&L and commissions; Activity Flex refreshes daily, Trade Confirmation Flex intraday (~5–10 min lag); schedulable email/FTP delivery [V: [IBKR docs](https://www.interactivebrokers.com/campus/ibkr-api-page/flex-web-service)]. TWS API `execDetails` for real-time. Free.

**MT5 / cTrader** — both well-covered: MT5's official Python package returns full deal history (Windows, terminal running) [V]; cTrader Open API returns historical deals via OAuth (but not historical orders) [V/I].

## 2.3 Prop-firm reality

| Firm | Platform(s) | Trader API access | Export |
|---|---|---|---|
| **Topstep** | TopstepX (ProjectX) | **Yes — ProjectX API, $29/mo**; one key covers all accounts [V: [help](https://help.topstep.com/en/articles/11187768)] | TopstepX order history |
| **Apex** | Rithmic or Tradovate | Tradovate API on Tradovate accounts; **no R\|API on Rithmic accounts** | R Trader CSV (1 day); Tradovate CSVs |
| **MyFundedFutures** | Tradovate/NT/Rithmic | Tradovate API where applicable | Platform CSVs |
| **TakeProfitTrader** | Rithmic-based | No direct API | R Trader CSV; journal credential sync |
| **Tradeify** | Tradovate-based (+ ProjectX?) | Help article suggests API access **[U — confirm with support]** | Platform CSVs |

General rule [I]: **read-only journal syncing is universally tolerated** (major journals publicly support each firm); firm rules bite on *execution automation*, not data capture. Apex's automation policy reports conflict — 🚩 verify the firm's current written policy.

## 2.4 Fallback reliability ranking

1. **IBKR Flex Query (scheduled)** — machine-readable, scheduled delivery, canonical.
2. **Tradovate account report CSVs** (Orders + Cash history).
3. **NinjaTrader Trade Performance export.**
4. **R Trader Completed Orders CSV** (1 day at a time; column setup; timezone pitfalls).
5. **MT4/5 statement HTML / EA-written file.**
6. **Email-statement parsing** — good as a reconciliation layer; brittle as primary.
7. **Screen-scraping web dashboards** — last resort; ToS-gray, fragile.

## 2.5 Market data, charts, and event context

- **Databento** is the best fit for CME futures context: usage-based history from $0.50/GB back to 2010, $125 free credits; pulling ±2h of 1-min bars around each fill costs pennies [V: [pricing](https://databento.com/pricing)]. Polygon/"Massive" launched futures coverage (history from ~2017) — maturity unclear [U]. yfinance: continuous front-month only, prototype-grade [I].
- **Chart reconstruction is feasible and is what journals actually do**: store OHLCV around each trade, render with lightweight-charts + execution markers (Tradervue precedent [V: [blog](https://www.tradervue.com/blog/tradingview-charts)]). TradingView *embedded widgets* cannot overlay your own fills; the gated Advanced Charts library can, with a license. **Platform screenshots cannot be reconstructed after the fact** — the trader's indicators/drawings exist only at capture time, so screenshot capture (manual paste, watched folder, or NT8 add-on) is the only honest source of "the chart as I saw it." Reconstructed charts must be labeled reconstructed.
- **Economic calendar**: FMP or similar API; ForexFactory has no official API and scraping is fragile/ToS-gray [I].

## 2.6 What this means for Complete Journal

1. Automated capture is **feasible today** for Tradovate-based and TopstepX/ProjectX-based accounts via official, trader-accessible APIs (~$25–29/mo); NT8 desktop via a free custom add-on; IBKR/MT5/cTrader free via official mechanisms.
2. **Rithmic-based prop accounts are the hard case**: no individual API; choice is manual daily R Trader CSV or relying on a commercial journal's vendor sync.
3. Whatever the integration, **CSV importers must exist first** — they are the universal fallback, the historical-import path, and the insurance against API churn.
4. Tradovate's session-only history means live/daily sweeping with local persistence is a *requirement*, not an optimization — which strengthens the case for an owned local datastore (section 05).

## 2.7 Unknowns requiring user confirmation 🚩

1. Which prop firm(s) and account type (eval vs funded; Rithmic vs Tradovate vs TopstepX) — this single answer selects the integration.
2. Which front-end platform is actually used for execution (NT8 desktop, TradingView, TopstepX web, R Trader, Quantower).
3. Whether Tradovate API add-on / ProjectX API subscription is already paid; whether a firm-issued Tradovate account can enable the API add-on [U].
4. Current ProjectX supported-firm list and fee.
5. Tradovate Reporting API access terms (ask NinjaTrader support).
6. The firm's current written automation/data-access policy.
7. TradingView plan tier (webhooks/paper-export gating), if relevant.
8. Budget tolerance for market data ($0 prototype vs Databento usage-based vs IQFeed ~$100+/mo).
