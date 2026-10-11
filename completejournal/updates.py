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


def _asset_for_this_os(assets: list[dict]) -> str | None:
    key = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    for a in assets or []:
        if key in (a.get("name") or "").lower():
            return a.get("browser_download_url")
    return None


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
