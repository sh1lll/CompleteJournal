"""Phone quick-capture: one-line notes and photos from your phone, on your Wi-Fi.

Security model (least privilege):
  * OFF by default. When on, a second listener binds the local network on a
    fixed port; the main app stays bound to 127.0.0.1.
  * A phone must be paired by opening the pairing link (shown as a QR code
    on the computer). Pairing sets a long-lived cookie holding a random token.
  * A paired phone can reach ONLY the capture page and the capture/photo
    endpoints — never the journal, trades, settings or exports.
  * "Unpair all phones" rotates the token, invalidating every paired phone.
  * Plain HTTP on the local network: fine at home; on untrusted Wi-Fi use a
    private network such as Tailscale instead.
"""
from __future__ import annotations

import ipaddress
import secrets
import socket
import sqlite3
from datetime import datetime, timedelta, timezone

PHONE_PORT_DEFAULT = 8765
COOKIE = "cj_pair"

# the only paths a paired phone may use
PHONE_ALLOWED_EXACT = {"/capture", "/api/capture", "/api/capture/recent", "/manifest.webmanifest",
                       "/sw.js", "/icon.svg", "/api/health"}
PHONE_ALLOWED_POST = {"/api/attachments"}


def is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host in ("localhost", "testclient"):  # testclient: the in-process test harness
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def get_token(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM meta WHERE key='phone_token'").fetchone()
    if row:
        return row[0]
    return rotate_token(conn)


def rotate_token(conn: sqlite3.Connection) -> str:
    tok = secrets.token_urlsafe(24)
    conn.execute("INSERT INTO meta(key,value) VALUES('phone_token',?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (tok,))
    conn.commit()
    return tok


def token_ok(conn: sqlite3.Connection, presented: str | None) -> bool:
    if not presented:
        return False
    return secrets.compare_digest(presented, get_token(conn))


def phone_may_access(method: str, path: str) -> bool:
    return path in PHONE_ALLOWED_EXACT or (method == "POST" and path in PHONE_ALLOWED_POST)


def lan_ip() -> str:
    """Best-effort local network address (no packets are sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def qr_svg(text: str) -> str | None:
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError:
        return None
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    return img.to_string(encoding="unicode")


def setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO meta(key,value) VALUES(?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()


# ----------------------------------------------------------------- capture

def save_capture(conn: sqlite3.Connection, body: str, *, client_id: str,
                 captured_at: str | None = None, attachment_ids: list[int] | None = None) -> dict:
    """Create an intraday entry from a phone capture. Idempotent per client_id
    (the phone retries until it gets an answer, possibly after being offline)."""
    from . import journal
    from .sessions import SessionPolicy

    body = (body or "").strip()
    attachment_ids = [int(a) for a in (attachment_ids or [])]
    if not body and not attachment_ids:
        raise ValueError("empty capture")
    if not client_id or len(client_id) > 80:
        raise ValueError("missing client_id")
    seen = conn.execute("SELECT entry_id FROM capture_log WHERE client_id=?", (client_id,)).fetchone()
    if seen:
        return {"entry_id": seen[0], "duplicate": True}

    now = datetime.now(timezone.utc)
    when = now
    if captured_at:
        try:
            t = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            # trust the phone's clock for queued notes, within sane bounds
            if now - timedelta(days=7) <= t <= now + timedelta(minutes=5):
                when = t.astimezone(timezone.utc)
        except ValueError:
            pass
    written = when.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    day = SessionPolicy.from_db(conn).session_date(written)
    text = body
    for aid in attachment_ids:
        text += f"\n\n![photo](/api/attachments/{aid})"
    eid = journal.create_entry(conn, text.strip(), kind="intraday", about_date=day, written_at=written)
    journal.tag(conn, eid, "phone")
    for aid in attachment_ids:
        conn.execute("UPDATE attachments SET entry_id=? WHERE id=? AND entry_id IS NULL", (eid, aid))
    conn.execute("INSERT INTO capture_log(client_id, entry_id) VALUES (?,?)", (client_id, eid))
    conn.commit()
    return {"entry_id": eid, "duplicate": False, "written_at": written, "session_date": day}


def recent(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        "SELECT e.id, e.written_at, substr(e.body_md,1,140) AS excerpt FROM entries e "
        "JOIN tags t ON t.entry_id=e.id AND t.tag='phone' WHERE e.deleted_at IS NULL "
        "ORDER BY e.written_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
