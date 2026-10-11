"""Behavioral analytics: patterns in *how* trading happened, not just results.

Assessment §4.1 Tier 2. Every detector returns observations with the evidence
(trade ids, timestamps) attached — these are flags for the trader to judge
during review, never verdicts. Thresholds are explicit parameters, not hidden
magic.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Flag:
    kind: str
    date: str
    detail: str
    trade_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


def _closed_trades(conn, account_id=None):
    q = ("SELECT * FROM trades WHERE is_open=0" +
         (" AND account_id=?" if account_id else "") + " ORDER BY entry_ts")
    return conn.execute(q, (account_id,) if account_id else ()).fetchall()


def _minutes_between(a: str, b: str) -> float:
    da = datetime.fromisoformat(a.replace("Z", "+00:00"))
    db = datetime.fromisoformat(b.replace("Z", "+00:00"))
    return (db - da).total_seconds() / 60.0


def revenge_reentries(conn, account_id=None, *, within_minutes: float = 5.0) -> list[Flag]:
    """Re-entry in the same symbol within N minutes of a losing exit — the
    classic tilt signature. Fast re-entry after a WIN is not flagged."""
    out: list[Flag] = []
    trades = _closed_trades(conn, account_id)
    by_key: dict[tuple, list] = {}
    for t in trades:
        by_key.setdefault((t["account_id"], t["symbol"]), []).append(t)
    for seq in by_key.values():
        for prev, nxt in zip(seq, seq[1:]):
            if prev["net_pnl"] < 0 and prev["exit_ts"] and nxt["entry_ts"]:
                gap = _minutes_between(prev["exit_ts"], nxt["entry_ts"])
                if 0 <= gap <= within_minutes:
                    out.append(Flag(
                        "revenge-reentry", nxt["session_date"],
                        f"{nxt['symbol']}: re-entered {gap:.1f} min after a "
                        f"${-prev['net_pnl']:.2f} loss (trade #{prev['id']} → #{nxt['id']})",
                        [prev["id"], nxt["id"]],
                    ))
    return out


def size_escalation_after_loss(conn, account_id=None, *, factor: float = 1.5) -> list[Flag]:
    """Position size grew by >= factor on the trade immediately after a loss."""
    out: list[Flag] = []
    trades = _closed_trades(conn, account_id)
    by_acct: dict[int, list] = {}
    for t in trades:
        by_acct.setdefault(t["account_id"], []).append(t)
    for seq in by_acct.values():
        for prev, nxt in zip(seq, seq[1:]):
            if prev["net_pnl"] < 0 and nxt["qty_max"] >= prev["qty_max"] * factor and prev["qty_max"] > 0:
                out.append(Flag(
                    "size-escalation", nxt["session_date"],
                    f"size {prev['qty_max']}→{nxt['qty_max']} immediately after a "
                    f"${-prev['net_pnl']:.2f} loss (trade #{prev['id']} → #{nxt['id']})",
                    [prev["id"], nxt["id"]],
                ))
    return out


def overtrading_days(conn, account_id=None, *, factor: float = 2.0, min_baseline_days: int = 5) -> list[Flag]:
    """Days with trade count >= factor × personal median. Needs a baseline of
    min_baseline_days sessions first; silent before that (no fake insight)."""
    rows = conn.execute(
        "SELECT session_date, COUNT(*) n, GROUP_CONCAT(id) ids FROM trades WHERE is_open=0" +
        (" AND account_id=?" if account_id else "") +
        " GROUP BY session_date ORDER BY session_date",
        (account_id,) if account_id else (),
    ).fetchall()
    if len(rows) < min_baseline_days:
        return []
    counts = sorted(r["n"] for r in rows)
    median = counts[len(counts) // 2]
    out = []
    for r in rows:
        if median > 0 and r["n"] >= median * factor:
            out.append(Flag(
                "overtrading", r["session_date"],
                f"{r['n']} trades vs personal median {median}",
                [int(i) for i in r["ids"].split(",")],
            ))
    return out


def streak_performance(conn, account_id=None, *, k: int = 2) -> dict:
    """Expectancy after k consecutive losses vs after k consecutive wins vs
    overall — does performance degrade when behind? Includes n for honesty."""
    trades = _closed_trades(conn, account_id)
    after_losses, after_wins, every = [], [], []
    streak = 0  # positive = wins, negative = losses
    for t in trades:
        if streak <= -k:
            after_losses.append(t["net_pnl"])
        elif streak >= k:
            after_wins.append(t["net_pnl"])
        every.append(t["net_pnl"])
        if t["net_pnl"] > 0:
            streak = streak + 1 if streak > 0 else 1
        elif t["net_pnl"] < 0:
            streak = streak - 1 if streak < 0 else -1

    def avg(xs):
        return round(sum(xs) / len(xs), 2) if xs else None

    return {
        "k": k,
        "after_k_losses": {"n": len(after_losses), "expectancy": avg(after_losses)},
        "after_k_wins": {"n": len(after_wins), "expectancy": avg(after_wins)},
        "overall": {"n": len(every), "expectancy": avg(every)},
        "note": "differences on small n are noise, not signal",
    }


def all_flags(conn, account_id=None) -> dict:
    return {
        "revenge_reentries": [f.to_dict() for f in revenge_reentries(conn, account_id)],
        "size_escalation": [f.to_dict() for f in size_escalation_after_loss(conn, account_id)],
        "overtrading_days": [f.to_dict() for f in overtrading_days(conn, account_id)],
        "streaks": streak_performance(conn, account_id),
        "disclaimer": "flags are review prompts backed by trade ids — not verdicts",
    }
