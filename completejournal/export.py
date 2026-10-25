"""Export: the J9 data-ownership guarantee.

Two shapes:
  * markdown mirror — every journal entry as a standalone .md file with YAML
    front matter (links, tags, addenda, versions count). Human-readable,
    git-able, Obsidian-compatible. The mirror is a projection; the DB stays
    the source of truth.
  * full export — executions.csv, trades.csv, entries.json, ai_artifacts.json:
    everything needed to leave this software behind entirely.
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
from pathlib import Path


def _slug(text: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "")).strip("-").lower()
    return s[:maxlen] or "entry"


def export_markdown(conn: sqlite3.Connection, out_dir: str | Path) -> int:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    entries = conn.execute(
        "SELECT * FROM entries WHERE deleted_at IS NULL ORDER BY written_at"
    ).fetchall()
    for e in entries:
        links = conn.execute(
            "SELECT target_type, target_id FROM links WHERE entry_id=?", (e["id"],)
        ).fetchall()
        tags = [r["tag"] for r in conn.execute(
            "SELECT tag FROM tags WHERE entry_id=?", (e["id"],))]
        addenda = conn.execute(
            "SELECT body_md, written_at FROM entry_addenda WHERE entry_id=? ORDER BY written_at",
            (e["id"],),
        ).fetchall()
        n_versions = conn.execute(
            "SELECT COUNT(*) FROM entry_versions WHERE entry_id=?", (e["id"],)
        ).fetchone()[0]

        front = {
            "id": e["id"],
            "kind": e["kind"],
            "written_at": e["written_at"],
            "about_date": e["about_date"],
            "author": e["author"],
            "versions": n_versions,
            "tags": tags,
            "links": [f"{l['target_type']}:{l['target_id']}" for l in links],
        }
        fm = "\n".join(
            f"{k}: {json.dumps(v)}" for k, v in front.items() if v not in (None, [], "")
        )
        body = e["body_md"]
        if e["title"]:
            body = f"# {e['title']}\n\n{body}"
        parts = ["---", fm, "---", "", body]
        for a in addenda:
            parts += ["", "---", f"**Addendum ({a['written_at'][:10]}):**", "", a["body_md"]]
        date = (e["about_date"] or e["written_at"][:10])
        name = f"{date}-{e['id']:04d}-{_slug(e['title'] or e['body_md'][:48])}.md"
        (out / name).write_text("\n".join(parts) + "\n", encoding="utf-8")
        n += 1
    return n


def export_full(conn: sqlite3.Connection, out_dir: str | Path) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}

    def dump_csv(name: str, query: str):
        rows = conn.execute(query).fetchall()
        path = out / f"{name}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            if rows:
                w = csv.DictWriter(f, fieldnames=rows[0].keys())
                w.writeheader()
                w.writerows({k: r[k] for k in r.keys()} for r in rows)
        counts[name] = len(rows)

    dump_csv("executions",
             "SELECT e.*, a.name AS account_name FROM executions e "
             "JOIN accounts a ON a.id=e.account_id ORDER BY e.ts_utc")
    dump_csv("trades",
             "SELECT t.*, a.name AS account_name FROM trades t "
             "JOIN accounts a ON a.id=t.account_id ORDER BY t.entry_ts")
    dump_csv("accounts", "SELECT * FROM accounts ORDER BY id")
    dump_csv("instruments", "SELECT * FROM instruments ORDER BY symbol")

    def dump_json(name: str, query: str):
        rows = [dict(r) for r in conn.execute(query).fetchall()]
        (out / f"{name}.json").write_text(
            json.dumps(rows, indent=2, default=str), encoding="utf-8")
        counts[name] = len(rows)

    dump_json("entries", "SELECT * FROM entries ORDER BY id")
    dump_json("entry_versions", "SELECT * FROM entry_versions ORDER BY id")
    dump_json("entry_addenda", "SELECT * FROM entry_addenda ORDER BY id")
    dump_json("links", "SELECT * FROM links ORDER BY id")
    dump_json("tags", "SELECT rowid AS id, entry_id, tag FROM tags ORDER BY entry_id")
    dump_json("ai_artifacts", "SELECT * FROM ai_artifacts ORDER BY id")

    counts["markdown_entries"] = export_markdown(conn, out / "markdown")
    return counts
