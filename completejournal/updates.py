"""Update checks — opt-in, at most once a day, nothing about you is sent.

The app asks once whether to check. If yes, it asks GitHub for the latest
published release of Complete Journal (an anonymous GET of public release
metadata) and offers the download for this operating system. Installing
stays a deliberate click: replacing an unsigned app automatically is
fragile and blocked by macOS/Windows protections; automatic install comes
with code signing (see ROADMAP).
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

from . import __version__
from .phone import set_setting, setting

REPO = "sh1lll/CompleteJournal"
CHECK_INTERVAL = timedelta(hours=24)


def parse_version(v: str | None) -> tuple[int, ...] | None:
    m = re.match(r"^v?(\d+)\.(\d+)(?:\.(\d+))?", (v or "").strip())
    if not m:
        return None
    return tuple(int(x or 0) for x in m.groups())


def _os_key() -> str:
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def _asset(assets: list[dict], needle: str) -> dict | None:
    return next((a for a in assets or [] if needle in (a.get("name") or "").lower()), None)


def _asset_for_this_os(assets: list[dict]) -> str | None:
    a = _asset(assets, _os_key())
    return a.get("browser_download_url") if a else None


def _fetch_latest(repo: str) -> dict | None:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": f"CompleteJournal/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:          # no release published yet
            return None
        raise


def preference(conn: sqlite3.Connection) -> str:
    return setting(conn, "update_check", "ask")   # ask | on | off


def set_preference(conn: sqlite3.Connection, enabled: bool) -> None:
    set_setting(conn, "update_check", "on" if enabled else "off")


def check(conn: sqlite3.Connection, *, force: bool = False, fetch=None, repo: str = REPO) -> dict:
    pref = preference(conn)
    base = {"current": __version__, "preference": pref, "update_available": False}
    if pref != "on" and not force:
        return base
    now = datetime.now(timezone.utc)
    cached_at = setting(conn, "update_checked_at")
    cached = setting(conn, "update_latest")
    if not force and cached_at and cached is not None:
        if now - datetime.fromisoformat(cached_at) < CHECK_INTERVAL:
            return {**base, **json.loads(cached), "cached": True}
    try:
        rel = (fetch or _fetch_latest)(repo)
    except Exception as e:
        return {**base, "error": f"could not check for updates: {e}"}
    if not rel:
        info = {"latest": None, "note": "no release published yet"}
    else:
        latest = rel.get("tag_name")
        newer = (parse_version(latest) or (0,)) > (parse_version(__version__) or (0,))
        info = {"latest": latest, "update_available": bool(newer),
                "release_url": rel.get("html_url"),
                "download_url": _asset_for_this_os(rel.get("assets", [])) or rel.get("html_url"),
                "published_at": rel.get("published_at")}
    set_setting(conn, "update_latest", json.dumps(info))
    set_setting(conn, "update_checked_at", now.isoformat())
    return {**base, **info, "cached": False}


# ------------------------------------------------------- verified download

def _get_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"CompleteJournal/{__version__}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def parse_sums(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(\S.*)$", line.strip())
        if m:
            out[m.group(2).strip()] = m.group(1).lower()
    return out


def download_update(dest_dir, *, fetch=None, get_bytes=None, repo: str = REPO) -> dict:
    """Download this OS's build of the latest release and verify it against
    the release's SHA256SUMS.txt. Never installs anything by itself."""
    import hashlib
    from pathlib import Path

    rel = (fetch or _fetch_latest)(repo)
    if not rel:
        raise ValueError("no release published yet")
    assets = rel.get("assets", [])
    pkg = _asset(assets, _os_key())
    sums_asset = _asset(assets, "sha256sums")
    if not pkg:
        raise ValueError(f"the latest release has no build for this system ({_os_key()})")
    if not sums_asset:
        raise ValueError("the latest release has no checksum file; download it from the release page instead")
    get = get_bytes or _get_bytes
    expected = parse_sums(get(sums_asset["browser_download_url"]).decode("utf-8")).get(pkg["name"])
    if not expected:
        raise ValueError(f"no checksum listed for {pkg['name']}")
    data = get(pkg["browser_download_url"])
    actual = hashlib.sha256(data).hexdigest()
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    if actual != expected:
        raise ValueError("downloaded file failed verification (checksum mismatch) and was discarded")
    path = dest / pkg["name"]
    path.write_bytes(data)
    return {"path": str(path), "version": rel.get("tag_name"), "sha256": actual, "verified": True,
            "next_step": "Close Complete Journal, unpack this file and replace the old app. "
                         "Your journal is stored separately and is not touched."}


def reveal(path) -> None:
    """Show the downloaded file in the system file browser."""
    import subprocess
    from pathlib import Path
    p = Path(path)
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(p)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p.parent)])
