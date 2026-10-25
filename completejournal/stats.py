"""Statistical honesty helpers: confidence ranges and slippage.

* Win rate uses the Wilson score interval (well-behaved for small n).
* Expectancy uses a percentile bootstrap (no normality assumption — trade
  P&L is fat-tailed). Seeded, so the same data always shows the same range.
* A range that spans zero is reported as "can't tell yet" — the honest
  answer for most samples under a few hundred trades.
* Slippage is measured only where the export recorded the intended price
  (stop or limit). Positive = worse than intended.
"""
from __future__ import annotations

import math
import random
import sqlite3


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


def bootstrap_mean(values: list[float], *, resamples: int = 1000, seed: int = 7,
                   level: float = 0.95) -> tuple[float, float] | None:
    n = len(values)
    if n < 5:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(values, k=n)) / n for _ in range(resamples))
    lo = means[int((1 - level) / 2 * resamples)]
    hi = means[min(resamples - 1, int((1 + level) / 2 * resamples))]
    return round(lo, 2), round(hi, 2)


def verdict(ci: tuple[float, float] | None) -> str:
    if ci is None:
        return "too few trades to estimate"
    lo, hi = ci
    if lo > 0:
        return "likely positive"
    if hi < 0:
        return "likely negative"
    return "can't tell yet"


def slippage(conn: sqlite3.Connection, account_id: int | None = None) -> dict:
    q = ("SELECT e.*, i.tick_size, i.point_value FROM executions e "
         "LEFT JOIN instruments i ON i.symbol = e.symbol WHERE e.intended_price IS NOT NULL"
         + (" AND e.account_id=?" if account_id else "") + " ORDER BY e.ts_utc")
    rows = conn.execute(q, (account_id,) if account_id else ()).fetchall()
    by_type: dict[str, list] = {}
    detail = []
    for r in rows:
        pts = (r["price"] - r["intended_price"]) if r["side"] == "buy" else (r["intended_price"] - r["price"])
        tick = r["tick_size"] or None
        dollars = pts * (r["point_value"] or 1.0) * r["qty"]
        kind = "stop" if "stop" in (r["order_type"] or "") else "limit" if "limit" in (r["order_type"] or "") else "other"
        rec = {"execution_id": r["id"], "symbol": r["symbol"], "order_type": kind, "side": r["side"],
               "intended": r["intended_price"], "filled": r["price"], "points": round(pts, 6),
               "ticks": round(pts / tick, 2) if tick else None, "dollars": round(dollars, 2)}
        detail.append(rec)
        by_type.setdefault(kind, []).append(rec)
    summary = {}
    for kind, recs in by_type.items():
        ticks = [x["ticks"] for x in recs if x["ticks"] is not None]
        summary[kind] = {"fills": len(recs),
                         "avg_ticks": round(sum(ticks) / len(ticks), 2) if ticks else None,
                         "total_dollars": round(sum(x["dollars"] for x in recs), 2)}
    return {"fills_measured": len(detail), "by_order_type": summary, "detail": detail[-200:],
            "note": ("measured only where the export recorded the stop/limit price; "
                     "positive = filled worse than intended")}
