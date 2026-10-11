"""Weekly and monthly review reports.

A report puts the numbers next to the writing: performance for the period,
day by day, plan adherence, behavioural flags, decision grades — and the
trader's own entries from those days, so review starts from reasoning, not
only results. Exportable as Markdown. No AI involved.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from . import analytics, behavior, excursions, plan


def period_bounds(kind: str, anchor: str) -> tuple[str, str]:
    d = date.fromisoformat(anchor)
    if kind == "week":
        start = d - timedelta(days=d.weekday())
        end = start + timedelta(days=6)
    elif kind == "month":
        start = d.replace(day=1)
        nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = nxt - timedelta(days=1)
    else:
        raise ValueError("kind must be 'week' or 'month'")
    return start.isoformat(), end.isoformat()


def build(conn: sqlite3.Connection, kind: str, anchor: str) -> dict:
    start, end = period_bounds(kind, anchor)
    rows = conn.execute(
        "SELECT t.*, a.name AS account_name FROM trades t JOIN accounts a ON a.id=t.account_id "
        "WHERE t.is_open=0 AND t.session_date BETWEEN ? AND ? ORDER BY t.entry_ts",
        (start, end)).fetchall()
    stats = analytics._compute(rows).to_dict()

    days: dict[str, dict] = {}
    for t in rows:
        d = days.setdefault(t["session_date"], {"trades": 0, "net_pnl": 0.0})
        d["trades"] += 1
        d["net_pnl"] = round(d["net_pnl"] + t["net_pnl"], 2)

    adherence = []
    for d in sorted({t["session_date"] for t in rows} | {
            r[0] for r in conn.execute(
                "SELECT about_date FROM entries WHERE kind='pre-market' AND deleted_at IS NULL "
                "AND about_date BETWEEN ? AND ?", (start, end))}):
        pva = plan.plan_vs_actual(conn, d)
        if pva["results"]:
            adherence.append({"date": d, "kept": pva["kept"], "broken": pva["broken"],
                              "broken_rules": [r["rule"] for r in pva["results"] if not r["kept"]]})

    flags_all = behavior.all_flags(conn)
    flags = [f for key in ("revenge_reentries", "size_escalation", "overtrading_days")
             for f in flags_all[key] if start <= f["date"] <= end]

    graded = conn.execute(
        """SELECT g.grade, COUNT(*) n FROM trades t JOIN trade_grades g
             ON g.account_id=t.account_id AND g.symbol=t.symbol AND g.entry_ts=t.entry_ts
             AND g.direction=t.direction
           WHERE t.session_date BETWEEN ? AND ? GROUP BY g.grade""", (start, end)).fetchall()

    entries = conn.execute(
        "SELECT id, kind, title, about_date, written_at, substr(body_md,1,280) AS excerpt "
        "FROM entries WHERE deleted_at IS NULL AND "
        "COALESCE(about_date, substr(written_at,1,10)) BETWEEN ? AND ? ORDER BY written_at",
        (start, end)).fetchall()

    ex = [e for e in (excursions.trade_excursion(conn, t["id"]) for t in rows) if e]
    best = sorted(rows, key=lambda t: t["net_pnl"], reverse=True)[:3]
    worst = sorted(rows, key=lambda t: t["net_pnl"])[:3]

    return {
        "kind": kind, "start": start, "end": end,
        "stats": stats,
        "days": [{"date": k, **v} for k, v in sorted(days.items())],
        "best": [dict(t) for t in best if t["net_pnl"] > 0],
        "worst": [dict(t) for t in worst if t["net_pnl"] < 0],
        "plan_adherence": adherence,
        "flags": flags,
        "grades": {r["grade"]: r["n"] for r in graded},
        "entries": [dict(e) for e in entries],
        "excursions": {
            "trades_with_bars": len(ex),
            "avg_capture": (round(sum(e["capture_ratio"] for e in ex if e["capture_ratio"] is not None)
                                  / max(1, sum(1 for e in ex if e["capture_ratio"] is not None)), 3)
                            if ex else None),
        },
    }


def to_markdown(r: dict) -> str:
    s = r["stats"]
    money = lambda v: "—" if v is None else f"{'-' if v < 0 else ''}${abs(v):,.2f}"  # noqa: E731
    lines = [f"# {r['kind'].title()} review: {r['start']} → {r['end']}", ""]
    lines += [f"- Closed trades: **{s['n']}**" + (" (small sample — treat figures as noise-dominated)" if s["low_sample"] else ""),
              f"- Net P&L: **{money(s['net_pnl'])}** · fees {money(s['fees'])}",
              f"- Win rate: {('%.0f%%' % (100 * s['win_rate'])) if s['win_rate'] is not None else '—'}"
              f" · expectancy {money(s['expectancy'])} · profit factor "
              f"{('%.2f' % s['profit_factor']) if s['profit_factor'] else '—'}",
              f"- Max drawdown: {money(-s['max_drawdown'])}", ""]
    if r["days"]:
        lines += ["## Day by day", "", "| Date | Trades | Net |", "|---|---|---|"]
        lines += [f"| {d['date']} | {d['trades']} | {money(d['net_pnl'])} |" for d in r["days"]]
        lines.append("")
    if r["plan_adherence"]:
        lines += ["## Plan adherence", ""]
        for a in r["plan_adherence"]:
            lines.append(f"- {a['date']}: {a['kept']} kept, {a['broken']} broken"
                         + (f" — {', '.join(a['broken_rules'])}" if a["broken_rules"] else ""))
        lines.append("")
    if r["flags"]:
        lines += ["## Behaviour flags (review prompts, not verdicts)", ""]
        lines += [f"- {f['date']} · {f['kind']}: {f['detail']}" for f in r["flags"]]
        lines.append("")
    if r["grades"]:
        lines += ["## Decision grades", "", ", ".join(f"{g}: {n}" for g, n in sorted(r["grades"].items())), ""]
    lines += ["## What I wrote", ""]
    if r["entries"]:
        for e in r["entries"]:
            label = e["title"] or (e["kind"] or "entry")
            lines.append(f"- [entry:{e['id']}] {e['about_date'] or e['written_at'][:10]} — {label}")
    else:
        lines.append("- (no entries this period)")
    lines += ["", "## Reflection", "", "_Your review of this period:_", ""]
    return "\n".join(lines)
