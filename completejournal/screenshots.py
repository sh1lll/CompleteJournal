"""Screenshot watched-folder import.

The honest 'chart as I saw it' record: the trader saves/export screenshots
into a folder during or after the session; this scans the folder once,
stores each image content-addressed, and files it to a session date taken
from the file's modification time (or an explicit date). Already-imported
files (same content hash) are skipped. One optional journal entry per day
indexes the imported shots so they are searchable and linkable.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import attachments, journal

IMAGE_EXTS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".gif": "image/gif", ".webp": "image/webp"}


def import_folder(
    conn: sqlite3.Connection,
    root: str | Path,
    folder: str | Path,
    *,
    date: str | None = None,
    make_entries: bool = True,
) -> dict:
    folder = Path(folder)
    if not folder.is_dir():
        raise NotADirectoryError(str(folder))
    imported: dict[str, list[dict]] = {}
    skipped = 0
    for f in sorted(folder.iterdir()):
        ext = f.suffix.lower()
        if not f.is_file() or ext not in IMAGE_EXTS:
            continue
        data = f.read_bytes()
        import hashlib
        sha = hashlib.sha256(data).hexdigest()
        if conn.execute("SELECT 1 FROM attachments WHERE sha256=?", (sha,)).fetchone():
            skipped += 1
            continue
        day = date or datetime.fromtimestamp(
            f.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d")
        meta = attachments.store(conn, root, data, filename=f.name,
                                 media_type=IMAGE_EXTS[ext])
        imported.setdefault(day, []).append({"id": meta["id"], "filename": f.name})

    entry_ids = []
    if make_entries:
        for day, shots in imported.items():
            lines = [f"Screenshots imported for @{day}:", ""]
            lines += [f"![{s['filename']}](/api/attachments/{s['id']})" for s in shots]
            eid = journal.create_entry(conn, "\n".join(lines), kind="intraday",
                                       title=f"Screenshots {day}", about_date=day)
            for s in shots:
                conn.execute("UPDATE attachments SET entry_id=? WHERE id=?", (eid, s["id"]))
            conn.commit()
            entry_ids.append(eid)
    return {
        "imported": sum(len(v) for v in imported.values()),
        "skipped_duplicates": skipped,
        "days": sorted(imported),
        "entry_ids": entry_ids,
    }
