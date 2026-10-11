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

import re
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
    written_at: str | None = None,
) -> int:
    if kind is not None and kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    if author not in ("trader", "template"):
        raise ValueError("AI content must be stored in ai_artifacts, not entries")
    if written_at:
        cur = conn.execute(
            "INSERT INTO entries(kind, title, body_md, about_date, author, written_at) VALUES (?,?,?,?,?,?)",
            (kind, title, body_md, about_date, author, written_at),
        )
    else:
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
    sync_mention_links(conn, entry_id, body_md)
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
    sync_mention_links(conn, entry_id, body_md)


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


# ---------------------------------------------------------------- mentions
# Inline mention syntax (the writing-first way to link):
#   @ES / @MES …        -> instrument link (must exist in instruments table)
#   @2026-10-09         -> session link
#   @trade:12           -> trade link (must exist)
#   @entry:5            -> entry link (must exist)
_MENTION_RE = re.compile(
    r"(?<![\w.])@(?:(?P<kind>trade|entry):(?P<id>\d+)|(?P<date>\d{4}-\d{2}-\d{2})|(?P<sym>[A-Z0-9]{1,5}))"
)


def parse_mentions(conn: sqlite3.Connection, body_md: str) -> list[tuple[str, str]]:
    """Extract valid mention targets from text. Unknown symbols/ids are ignored
    (they stay plain text — writing is never blocked by a bad mention)."""
    out: list[tuple[str, str]] = []
    for m in _MENTION_RE.finditer(body_md):
        if m.group("kind") == "trade":
            if conn.execute("SELECT 1 FROM trades WHERE id=?", (m.group("id"),)).fetchone():
                out.append(("trade", m.group("id")))
        elif m.group("kind") == "entry":
            if conn.execute("SELECT 1 FROM entries WHERE id=?", (m.group("id"),)).fetchone():
                out.append(("entry", m.group("id")))
        elif m.group("date"):
            out.append(("session", m.group("date")))
        elif m.group("sym"):
            if conn.execute("SELECT 1 FROM instruments WHERE symbol=?", (m.group("sym"),)).fetchone():
                out.append(("instrument", m.group("sym")))
    seen: set = set()
    return [x for x in out if not (x in seen or seen.add(x))]


def sync_mention_links(conn: sqlite3.Connection, entry_id: int, body_md: str) -> int:
    """Create links for every mention in the text. Additive only: removing a
    mention from the text does not delete a link (the trader may have linked
    deliberately); explicit unlink is a separate action."""
    targets = parse_mentions(conn, body_md)
    for ttype, tid in targets:
        conn.execute(
            "INSERT OR IGNORE INTO links(entry_id, target_type, target_id) VALUES (?,?,?)",
            (entry_id, ttype, tid),
        )
    conn.commit()
    return len(targets)


def mention_candidates(conn: sqlite3.Connection, q: str, limit: int = 8) -> list[dict]:
    """Autocomplete for '@' in the editor: instruments, recent trades, dates, entries."""
    q = (q or "").strip()
    out: list[dict] = []
    like = f"{q.upper()}%"
    for r in conn.execute(
        "SELECT symbol, name FROM instruments WHERE symbol LIKE ? ORDER BY symbol LIMIT ?",
        (like, limit),
    ):
        out.append({"token": f"@{r['symbol']}", "label": f"{r['symbol']} — {r['name']}", "type": "instrument"})
    for r in conn.execute(
        """SELECT id, symbol, direction, session_date, net_pnl FROM trades
           WHERE CAST(id AS TEXT) LIKE ? OR symbol LIKE ? ORDER BY entry_ts DESC LIMIT ?""",
        (f"{q}%", like, limit),
    ):
        out.append({"token": f"@trade:{r['id']}",
                    "label": f"trade #{r['id']} {r['symbol']} {r['direction']} {r['session_date']} (${r['net_pnl']:.2f})",
                    "type": "trade"})
    if re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", q or ""):
        for r in conn.execute(
            "SELECT DISTINCT session_date FROM trades WHERE session_date LIKE ? ORDER BY session_date DESC LIMIT ?",
            (f"{q}%", limit),
        ):
            out.append({"token": f"@{r['session_date']}", "label": f"session {r['session_date']}", "type": "session"})
    if q:
        for r in conn.execute(
            """SELECT id, COALESCE(title, substr(body_md,1,40)) AS t FROM entries
               WHERE deleted_at IS NULL AND (title LIKE ? OR CAST(id AS TEXT)=?)
               ORDER BY written_at DESC LIMIT ?""",
            (f"%{q}%", q, limit),
        ):
            out.append({"token": f"@entry:{r['id']}", "label": f"entry #{r['id']}: {r['t']}", "type": "entry"})
    return out[: limit * 2]


def link(conn: sqlite3.Connection, entry_id: int, target_type: str, target_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO links(entry_id, target_type, target_id) VALUES (?,?,?)",
        (entry_id, target_type, str(target_id)),
    )
    conn.commit()


def normalize_tag(t: str) -> str:
    """'Mistake/ Chased Entry' -> 'mistake/chased-entry'. Namespaces via '/'."""
    t = re.sub(r"\s*/\s*", "/", (t or "").strip().lower().lstrip("#"))
    t = re.sub(r"[^a-z0-9/\-]+", "-", t).strip("-/")
    t = re.sub(r"-{2,}", "-", t)
    if not t or len(t) > 60:
        raise ValueError("tag must be 1-60 characters of letters, numbers, '-' or '/'")
    return t


def tag(conn: sqlite3.Connection, entry_id: int, *tags: str) -> list[str]:
    clean = [normalize_tag(t) for t in tags]
    conn.executemany(
        "INSERT OR IGNORE INTO tags(entry_id, tag) VALUES (?,?)",
        [(entry_id, t) for t in clean],
    )
    conn.commit()
    return clean


def untag(conn: sqlite3.Connection, entry_id: int, tag_: str) -> None:
    conn.execute("DELETE FROM tags WHERE entry_id=? AND tag=?", (entry_id, tag_))
    conn.commit()


def tags_of(conn: sqlite3.Connection, entry_id: int) -> list[str]:
    return [r[0] for r in conn.execute("SELECT tag FROM tags WHERE entry_id=? ORDER BY tag", (entry_id,))]


def all_tags(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT t.tag, COUNT(*) AS n FROM tags t JOIN entries e ON e.id=t.entry_id "
        "WHERE e.deleted_at IS NULL GROUP BY t.tag ORDER BY n DESC, t.tag")]


def unlink(conn: sqlite3.Connection, entry_id: int, target_type: str, target_id: str) -> None:
    """Explicit removal only — editing text never deletes links."""
    conn.execute("DELETE FROM links WHERE entry_id=? AND target_type=? AND target_id=?",
                 (entry_id, target_type, str(target_id)))
    conn.commit()


def backlinks(conn: sqlite3.Connection, entry_id: int) -> list[dict]:
    """Entries that link TO this entry (via @entry:N or an explicit link)."""
    return [dict(r) for r in conn.execute(
        """SELECT e.id, e.kind, e.title, e.written_at, e.about_date, substr(e.body_md,1,160) AS excerpt
           FROM links l JOIN entries e ON e.id=l.entry_id
           WHERE l.target_type='entry' AND l.target_id=? AND e.deleted_at IS NULL
           ORDER BY e.written_at""", (str(entry_id),))]


def describe_links(conn: sqlite3.Connection, entry_id: int) -> list[dict]:
    """This entry's outgoing links with human labels."""
    out = []
    for l in conn.execute("SELECT target_type, target_id FROM links WHERE entry_id=? ORDER BY id", (entry_id,)):
        label = f"{l['target_type']} {l['target_id']}"
        if l["target_type"] == "trade":
            t = conn.execute("SELECT symbol, direction, session_date, net_pnl FROM trades WHERE id=?",
                             (l["target_id"],)).fetchone()
            label = (f"trade #{l['target_id']} {t['symbol']} {t['direction']} {t['session_date']} "
                     f"({'+' if t['net_pnl'] >= 0 else '-'}${abs(t['net_pnl']):,.2f})") if t else f"trade #{l['target_id']} (no longer present)"
        elif l["target_type"] == "entry":
            e = conn.execute("SELECT title, kind, substr(body_md,1,50) b FROM entries WHERE id=?",
                             (l["target_id"],)).fetchone()
            label = f"entry #{l['target_id']}: {(e['title'] or e['b']) if e else '(missing)'}"
        elif l["target_type"] == "session":
            label = f"session {l['target_id']}"
        elif l["target_type"] == "instrument":
            label = f"@{l['target_id']}"
        out.append({"target_type": l["target_type"], "target_id": l["target_id"], "label": label})
    return out


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
