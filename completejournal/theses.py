"""Thesis threads: one idea followed from first statement to outcome.

A thesis is any entry tagged `thesis`. Its thread is assembled from links the
trader already makes while writing — no extra forms:
  * entries that mention it (@entry:N) or that it mentions
  * trades linked from the thesis or from any entry in the thread
  * addenda on the thesis ("what I learned later")
Status is the trader's call, set with a tag: outcome/confirmed,
outcome/invalidated, outcome/mixed (otherwise 'open').
"""
from __future__ import annotations

import sqlite3

OUTCOMES = ("confirmed", "invalidated", "mixed")


def _status(conn, eid: int) -> str:
    for o in OUTCOMES:
        if conn.execute("SELECT 1 FROM tags WHERE entry_id=? AND tag=?", (eid, f"outcome/{o}")).fetchone():
            return o
    return "open"


def list_theses(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT e.* FROM entries e JOIN tags t ON t.entry_id=e.id AND t.tag='thesis' "
        "WHERE e.deleted_at IS NULL ORDER BY e.written_at DESC").fetchall()
    out = []
    for r in rows:
        th = thread(conn, r["id"])
        out.append({"id": r["id"], "title": r["title"], "written_at": r["written_at"],
                    "about_date": r["about_date"], "excerpt": (r["body_md"] or "")[:200],
                    "status": th["status"], "entries": len(th["entries"]),
                    "trades": len(th["trades"]), "net_pnl": th["net_pnl"]})
    return out


def thread(conn: sqlite3.Connection, thesis_id: int) -> dict:
    root = conn.execute("SELECT * FROM entries WHERE id=? AND deleted_at IS NULL", (thesis_id,)).fetchone()
    if not root:
        raise KeyError(f"entry {thesis_id} not found")
    # entries connected to the thesis in either direction (one hop is the
    # meaningful thread; deeper chains are reachable by opening those entries)
    ids = {thesis_id}
    for r in conn.execute("SELECT entry_id FROM links WHERE target_type='entry' AND target_id=?",
                          (str(thesis_id),)):
        ids.add(r[0])
    for r in conn.execute("SELECT target_id FROM links WHERE entry_id=? AND target_type='entry'",
                          (thesis_id,)):
        if str(r[0]).isdigit():
            ids.add(int(r[0]))
    q = ",".join("?" * len(ids))
    entries = [dict(r) for r in conn.execute(
        f"SELECT * FROM entries WHERE id IN ({q}) AND deleted_at IS NULL ORDER BY written_at", tuple(ids))]
    trade_ids = {int(r[0]) for r in conn.execute(
        f"SELECT DISTINCT target_id FROM links WHERE target_type='trade' AND entry_id IN ({q})", tuple(ids))
        if str(r[0]).isdigit()}
    trades = []
    if trade_ids:
        tq = ",".join("?" * len(trade_ids))
        trades = [dict(r) for r in conn.execute(
            f"SELECT t.*, a.name AS account_name FROM trades t JOIN accounts a ON a.id=t.account_id "
            f"WHERE t.id IN ({tq}) ORDER BY t.entry_ts", tuple(trade_ids))]
    addenda = [dict(r) for r in conn.execute(
        "SELECT * FROM entry_addenda WHERE entry_id=? ORDER BY written_at", (thesis_id,))]

    timeline = [{"at": e["written_at"], "type": "thesis" if e["id"] == thesis_id else "entry", "entry": e}
                for e in entries]
    timeline += [{"at": t["entry_ts"], "type": "trade", "trade": t} for t in trades]
    timeline += [{"at": a["written_at"], "type": "addendum", "addendum": a} for a in addenda]
    timeline.sort(key=lambda x: x["at"])
    closed = [t for t in trades if not t["is_open"]]
    return {"thesis": dict(root), "status": _status(conn, thesis_id), "entries": entries,
            "trades": trades, "addenda": addenda, "timeline": timeline,
            "net_pnl": round(sum(t["net_pnl"] for t in closed), 2)}


def set_status(conn: sqlite3.Connection, thesis_id: int, status: str) -> None:
    if status not in OUTCOMES + ("open",):
        raise ValueError(f"status must be one of {OUTCOMES + ('open',)}")
    conn.execute("DELETE FROM tags WHERE entry_id=? AND tag LIKE 'outcome/%'", (thesis_id,))
    if status != "open":
        conn.execute("INSERT OR IGNORE INTO tags(entry_id, tag) VALUES (?,?)", (thesis_id, f"outcome/{status}"))
    conn.execute("INSERT OR IGNORE INTO tags(entry_id, tag) VALUES (?, 'thesis')", (thesis_id,))
    conn.commit()
