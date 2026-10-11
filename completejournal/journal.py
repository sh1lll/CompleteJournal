"""Journal store: entries, versions, addenda, links, tags, search.

Invariants enforced here (the J6/J7 provenance guarantees):
  * creating an entry stores version 1; every edit stores a new version —
    no prior text is ever lost
  * addenda ("what I learned later") are separate records, never merged
  * author may only be 'trader' or 'template' — AI text is structurally
    impossible here and must go to ai_artifacts
  * delete is soft (deleted_at); hard deletion of writing is not offered
"""
from __future__ import annotations

import sqlite3

KINDS = (
    "market-thought", "pre-market", "intraday", "trade-review",
    "post-trade", "end-of-day", "knowledge", "psychology",
)


def create_entry(
    conn: sqlite3.Connection,
    body_md: str,
    *,
    kind: str | None = None,
    title: str | None = None,
    about_date: str | None = None,
    author: str = "trader",
) -> int:
    if kind is not None and kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    if author not in ("trader", "template"):
        raise ValueError("AI content must be stored in ai_artifacts, not entries")
    cur = conn.execute(
        "INSERT INTO entries(kind, title, body_md, about_date, author) VALUES (?,?,?,?,?)",
        (kind, title, body_md, about_date, author),
    )
    entry_id = cur.lastrowid
    conn.execute(
        "INSERT INTO entry_versions(entry_id, body_md, title) VALUES (?,?,?)",
        (entry_id, body_md, title),
    )
    conn.commit()
    return entry_id


def edit_entry(conn: sqlite3.Connection, entry_id: int, body_md: str, title: str | None = None) -> None:
    row = conn.execute("SELECT id FROM entries WHERE id=? AND deleted_at IS NULL", (entry_id,)).fetchone()
    if not row:
        raise KeyError(f"entry {entry_id} not found")
    conn.execute(
        "UPDATE entries SET body_md=?, title=COALESCE(?, title) WHERE id=?",
        (body_md, title, entry_id),
    )
    conn.execute(
        "INSERT INTO entry_versions(entry_id, body_md, title) VALUES (?,?,?)",
        (entry_id, body_md, title),
    )
    conn.commit()


def add_addendum(conn: sqlite3.Connection, entry_id: int, body_md: str) -> int:
    cur = conn.execute(
        "INSERT INTO entry_addenda(entry_id, body_md) VALUES (?,?)", (entry_id, body_md)
    )
    conn.commit()
    return cur.lastrowid


def soft_delete(conn: sqlite3.Connection, entry_id: int) -> None:
    conn.execute(
        "UPDATE entries SET deleted_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (entry_id,),
    )
    conn.commit()


def link(conn: sqlite3.Connection, entry_id: int, target_type: str, target_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO links(entry_id, target_type, target_id) VALUES (?,?,?)",
        (entry_id, target_type, str(target_id)),
    )
    conn.commit()


def tag(conn: sqlite3.Connection, entry_id: int, *tags: str) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO tags(entry_id, tag) VALUES (?,?)",
        [(entry_id, t) for t in tags],
    )
    conn.commit()


def entries_for_target(conn: sqlite3.Connection, target_type: str, target_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT e.* FROM entries e JOIN links l ON l.entry_id = e.id
           WHERE l.target_type=? AND l.target_id=? AND e.deleted_at IS NULL
           ORDER BY e.written_at""",
        (target_type, str(target_id)),
    ).fetchall()


def search(conn: sqlite3.Connection, query: str, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        """SELECT e.id, e.kind, e.title, e.written_at, e.about_date,
                  snippet(entries_fts, 1, '<mark>', '</mark>', ' … ', 18) AS snippet
           FROM entries_fts f JOIN entries e ON e.id = f.rowid
           WHERE entries_fts MATCH ? AND e.deleted_at IS NULL
           ORDER BY rank LIMIT ?""",
        (query, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def versions(conn: sqlite3.Connection, entry_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM entry_versions WHERE entry_id=? ORDER BY id", (entry_id,)
    ).fetchall()


def session_timeline(conn: sqlite3.Connection, date: str) -> dict:
    """Everything that belongs to one trading day: entries about it, trades on it."""
    entries = conn.execute(
        """SELECT * FROM entries
           WHERE deleted_at IS NULL AND (about_date=? OR substr(written_at,1,10)=?)
           ORDER BY written_at""",
        (date, date),
    ).fetchall()
    trades = conn.execute(
        """SELECT t.*, a.name AS account_name FROM trades t
           JOIN accounts a ON a.id = t.account_id
           WHERE t.session_date=? ORDER BY t.entry_ts""",
        (date,),
    ).fetchall()
    return {"date": date, "entries": [dict(r) for r in entries], "trades": [dict(r) for r in trades]}
