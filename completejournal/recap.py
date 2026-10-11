"""Daily recap — built from your data, no AI.

Plain sentences assembled from the day's trades, plan, flags, grades and
writing. Every sentence carries citations ([trade:12], [entry:5]) to the
records it came from. It ends with reflection QUESTIONS derived from the
data — never verdicts, never a replacement for the trader's own
end-of-day writing.
"""
from __future__ import annotations

import sqlite3

from . import analytics, behavior, excursions, plan


def _m(v: float) -> str:
    return f"{'-' if v < 0 else ''}${abs(v):,.2f}"


def daily(conn: sqlite3.Connection, date: str) -> dict:
    pva = plan.plan_vs_actual(conn, date)
    trades = [t for t in pva["trades"] if not t["is_open"]]
    open_t = [t for t in pva["trades"] if t["is_open"]]
    lines: list[str] = []
    questions: list[str] = []
    cites: set[str] = set()

    if not pva["trades"]:
        lines.append("No trades recorded for this session.")
    else:
        syms = sorted({t["symbol"] for t in trades})
        accts = sorted({t["account_name"] for t in trades})
        wins = [t for t in trades if t["net_pnl"] > 0]
        losses = [t for t in trades if t["net_pnl"] < 0]
        fees = sum(t["fees"] for t in trades)
        ids = " ".join(f"[trade:{t['id']}]" for t in trades)
        cites.update(f"trade:{t['id']}" for t in trades)
        lines.append(
            f"{len(trades)} closed trade{'s' if len(trades) != 1 else ''} in {', '.join(syms)}"
            f"{' across ' + ', '.join(accts) if len(accts) > 1 else ''}: net {_m(pva['net_pnl'])} "
            f"({len(wins)} won, {len(losses)} lost), fees {_m(fees)}. {ids}")
        if open_t:
            lines.append(f"{len(open_t)} position(s) still open at end of data. "
                         + " ".join(f"[trade:{t['id']}]" for t in open_t))
        if len(trades) > 1:
            best = max(trades, key=lambda t: t["net_pnl"])
            worst = min(trades, key=lambda t: t["net_pnl"])
            if best["net_pnl"] > 0:
                lines.append(f"Best: {best['symbol']} {best['direction']} {_m(best['net_pnl'])} [trade:{best['id']}].")
            if worst["net_pnl"] < 0:
                lines.append(f"Worst: {worst['symbol']} {worst['direction']} {_m(worst['net_pnl'])} [trade:{worst['id']}].")
        for t in losses:
            e = excursions.trade_excursion(conn, t["id"])
            if e and e["mfe_points"] > 0 and e["mfe_points"] >= abs(e["realized_points"]):
                questions.append(f"Trade #{t['id']} was {e['mfe_points']:g} points in your favour before it "
                                 f"closed at a loss — what was the exit plan at that moment? [trade:{t['id']}]")

    if pva["plan"]:
        pid = pva["plan"]["id"]
        cites.add(f"entry:{pid}")
        if pva["results"]:
            lines.append(f"Pre-market plan [entry:{pid}]: {pva['kept']} rule(s) kept, {pva['broken']} broken.")
            for r in pva["results"]:
                if not r["kept"]:
                    ev = " ".join(f"[trade:{i}]" for i in r["trade_ids"])
                    lines.append(f"Broken — {r['rule']}: {r['detail']}. {ev}".rstrip())
                    questions.append(f"What led to '{r['rule']}' being broken? Was it a decision or a drift?")
        else:
            lines.append(f"Pre-market plan written [entry:{pid}] (no checkable rule lines).")
            questions.append("Reading your plan again now: which parts did the market confirm, and which did it reject?")
    else:
        lines.append("No pre-market plan was written for this session.")
        if trades:
            questions.append("Without a written plan, what was the reason behind the first trade?")

    flags = behavior.all_flags(conn)
    for key in ("revenge_reentries", "size_escalation", "overtrading_days"):
        for f in flags[key]:
            if f["date"] == date:
                ev = " ".join(f"[trade:{i}]" for i in f["trade_ids"])
                lines.append(f"Flag ({f['kind']}): {f['detail']} {ev}")
                if f["kind"] == "revenge-reentry":
                    questions.append("What were you feeling in the minutes before re-entering after that loss?")
                elif f["kind"] == "size-escalation":
                    questions.append("Why did size increase right after a loss — conviction, or getting it back?")

    graded = [t for t in trades if analytics.get_grade(conn, t["id"])]
    if trades and len(graded) < len(trades):
        questions.append(f"{len(trades) - len(graded)} trade(s) still ungraded — grade the decision, not the result.")

    writing = conn.execute(
        "SELECT id, kind, title FROM entries WHERE deleted_at IS NULL AND "
        "(about_date=? OR (about_date IS NULL AND substr(written_at,1,10)=?)) ORDER BY written_at",
        (date, date)).fetchall()
    if writing:
        cites.update(f"entry:{w['id']}" for w in writing)
        lines.append(f"You wrote {len(writing)} entr{'y' if len(writing) == 1 else 'ies'}: "
                     + ", ".join(f"{w['title'] or w['kind'] or 'entry'} [entry:{w['id']}]" for w in writing) + ".")
    if not any(w["kind"] == "end-of-day" for w in writing):
        questions.append("No end-of-day reflection yet — how would you describe today in your own words?")

    return {"date": date, "source": "computed from your records (no AI)",
            "lines": lines, "questions": questions, "citations": sorted(cites),
            "markdown": "\n".join(f"- {l}" for l in lines)
                        + ("\n\n**Questions to reflect on**\n" + "\n".join(f"- {q}" for q in questions)
                           if questions else "")}
