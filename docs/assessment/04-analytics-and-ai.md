# 4. Analytics & AI — Valuable Features and Their Limits

> Part of the Complete Journal assessment. Mostly design/domain judgment; product-specific AI claims are evaluated in section 01, technical costs in sections 05/07.

## 4.1 Quantitative analytics worth building (in priority order)

**Tier 1 — table stakes, computable from executions alone**
- Per-trade: direction, size path (scale-ins/outs), gross/net P&L, R multiple (when risk is known), MAE/MFE (requires price data), duration, commissions/fees, slippage vs. intended entry (when the order record carries limit prices).
- Aggregates: win rate, average win/loss, payoff ratio, expectancy (per trade and per R), profit factor, max drawdown, equity curve (per account — never mixed across prop accounts), fee burden as % of gross.
- Breakdowns: instrument, session/time-of-day, weekday, hold time, day of evaluation cycle (prop-relevant), strategy/setup (only where tagged — labeled as trader-classified, not measured).

**Tier 2 — behavioral, computable from executions + timestamps**
- Overtrading detection: trade count vs. personal baseline, revenge-trade proxy (re-entry within N minutes of a loss, larger size after a loss).
- Consistency: performance after K consecutive losses/wins; size variance; stop-moving detection where order modification history exists.
- Plan adherence: trades taken outside planned instruments/hours/scenarios from the pinned pre-market plan (requires the plan to state them — this is a journaling payoff, not a data feed).

**Tier 3 — statistical honesty layer (differentiator, rarely done by existing products)**
- Sample-size warnings on every breakdown (n < ~30 flagged; confidence intervals on win rate/expectancy via bootstrap).
- Explicit "correlation ≠ cause" framing on condition splits; no "insight" shown without its n.
- Process-vs-outcome tagging: trader grades decision quality (A–F) independent of P&L; analytics then split *good decisions/bad outcomes* from *bad decisions/good outcomes* — the single most valuable review axis, and impossible without the journal.

## 4.2 AI features ranked by value ÷ risk

| Rank | Feature | Mechanism | Value | Risk/limit |
|---|---|---|---|---|
| 1 | **Retrieval over past entries** ("when have I seen this before?", "show entries about failed breakouts on CPI days") | Embeddings + full-text hybrid search; returns *the trader's own entries* with links | Very high — the journal compounds | Low: it quotes, doesn't conclude |
| 2 | **Daily digest with citations** | LLM summarizes the day's trades + entries; every claim cites source entry/trade IDs | High | Medium: must be stored as AI-authored record; never replaces EOD writing, offered *after* it |
| 3 | **Plan-vs-actual comparison** | LLM compares pinned pre-market plan to session trades/notes, flags deviations as *questions* ("You planned to skip the first 15 min; trade #2 was at 9:33 — intentional?") | High | Medium: phrased as questions, not verdicts |
| 4 | **Recurring-theme reports** (weekly/monthly) | Periodic LLM pass over the window's entries; themes with citation lists | High over time | Needs months of data to be meaningful |
| 5 | **Rule-vs-behavior discrepancy detection** | Compare `knowledge`-kind rules entries to measured behavior stats | Medium-high | Only as good as stated rules; false positives |
| 6 | **Auto-tag suggestions** | Classify entries/trades to existing tag taxonomy, pending acceptance | Medium | Must stay suggestions |
| 7 | **Contextual resurfacing** ("similar setup to your 2026-06-12 entry") | Embedding similarity on pre-market plans/conditions | Medium | Similarity ≠ relevance; show, don't push |
| ✗ | **AI trade grading / "AI coach" verdicts** | — | Low | Rejected: outcome-biased LLM judgments presented as authority corrupt the reflective process. The journal asks questions; the trader concludes. |

## 4.3 Hard limits to state plainly

1. **AI cannot know why a trade was taken.** Only the trader's contemporaneous writing can. Every AI interpretation of intent is inference and must be labeled as such.
2. **Journal entries are not facts.** They contain tentative, emotional, and wrong beliefs by design; the AI layer must treat them as *records of belief at a time*, not ground truth (prompting and schema must carry this framing).
3. **Small samples dominate retail/prop trading stats.** Most "edges" visible in <100 trades are noise; the system must say so rather than sell insight.
4. **Market context reconstruction is partial.** Stored OHLCV + an economic calendar ≠ the chart as the trader saw it (indicators, drawings, DOM state). Anything reconstructed is labeled reconstructed (details in sections 02/05).
5. **Provenance is architectural, not cosmetic**: AI output lives in separate records with `author=ai`, model/version, prompt context hash, and source citations — so any conclusion is traceable and the original record is untouched.

## 4.4 Cost reality (refined in section 07)

For a single trader: daily digest + weekly theme pass + embedding of all entries is small (thousands, not millions, of tokens/day). Expect roughly **$3–15/month** in LLM API usage at current Claude pricing tiers depending on model choice and usage; embeddings are negligible. This is engineering-judgment estimation, not a quote.
