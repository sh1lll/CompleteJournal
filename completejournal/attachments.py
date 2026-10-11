"""Content-addressed attachment store.

Files live on disk at <root>/ab/cd/<sha256><ext>; metadata in the attachments
table. Content addressing makes storage idempotent (same screenshot pasted
twice = one file) and immune to entry edits. The attachments root defaults to
a directory next to the DB file.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

_EXT_BY_TYPE = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
    "image/webp": ".webp", "application/pdf": ".pdf", "text/csv": ".csv",
}
MAX_BYTES = 25 * 1024 * 1024  # one screenshot should never be this big


def store(
    conn: sqlite3.Connection,
    root: str | Path,
    data: bytes,
    *,
    filename: str | None = None,
    media_type: str | None = None,
    entry_id: int | None = None,
) -> dict:
    if not data:
        raise ValueError("empty attachment")
    if len(data) > MAX_BYTES:
        raise ValueError(f"attachment larger than {MAX_BYTES} bytes")
    sha = hashlib.sha256(data).hexdigest()
    ext = _EXT_BY_TYPE.get(media_type or "", Path(filename or "").suffix or ".bin")
    rel = Path(sha[:2]) / sha[2:4] / f"{sha}{ext}"
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(data)
    cur = conn.execute(
        "INSERT INTO attachments(entry_id, sha256, filename, media_type, size_bytes) "
        "VALUES (?,?,?,?,?)",
        (entry_id, sha, filename, media_type, len(data)),
    )
    conn.commit()
    return {"id": cur.lastrowid, "sha256": sha, "path": str(rel), "size": len(data)}


def load(conn: sqlite3.Connection, root: str | Path, attachment_id: int) -> tuple[bytes, dict]:
    row = conn.execute("SELECT * FROM attachments WHERE id=?", (attachment_id,)).fetchone()
    if not row:
        raise KeyError(f"attachment {attachment_id} not found")
    sha = row["sha256"]
    ext = _EXT_BY_TYPE.get(row["media_type"] or "", Path(row["filename"] or "").suffix or ".bin")
    path = Path(root) / sha[:2] / sha[2:4] / f"{sha}{ext}"
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != sha:
        raise ValueError(f"attachment {attachment_id} failed integrity check")
    return data, dict(row)
