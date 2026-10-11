"""Economic calendar: scheduled releases as context for each session.

Sources (all opt-in; nothing is fetched automatically):
  * CSV import — headers like date,time,currency|country,impact,event|title,
    actual,forecast,previous (any order/case); naive times use the tz given
  * ForexFactory-style weekly JSON (title,country,date,impact,forecast,
    previous) — dates carry explicit offsets
  * the public weekly feed in that JSON format (one click, unofficial: it can
    change or disappear; files and manual entry always work)
  * manual entry

Events are context, never verdicts: the recap only *asks* about trades taken
close to high-impact releases.
"""
from __future__ import annotations

import json
import re
import sqlite3
import urllib.request
from datetime import datetime, timedelta, timezone

from .importers.parsing import parse_datetime, read_table, resolve_tz
from .sessions import SessionPolicy

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_IMPACT = {"high": "high", "red": "high", "3": "high", "medium": "medium", "med": "medium",
           "orange": "medium", "2": "medium", "low": "low", "yellow": "low", "1": "low",
           "holiday": "holiday", "non-economic": "low", "gray": "low", "grey": "low"}


def _impact(v) -> str | None:
    return _IMPACT.get(re.sub(r"\s+impact( expected)?$", "", str(v or "").strip().lower()))


def _store(conn, rows: list[dict], source: str) -> int:
    n = 0
    for r in rows:
        cur = conn.execute(
            "INSERT OR IGNORE INTO econ_events(ts_utc, all_day, currency, event, impact, actual, forecast, previous, source) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (r["ts_utc"], int(r.get("all_day", 0)), (r.get("currency") or "").upper() or None, r["event"],
             r.get("impact"), r.get("actual") or None, r.get("forecast") or None, r.get("previous") or None, source))
        n += cur.rowcount
    conn.commit()
    return n


def import_csv(conn: sqlite3.Connection, source, *, tz: str | None = "America/New_York") -> dict:
    headers, rows, _ = read_table(source)
    tzinfo = resolve_tz(tz)
    out, skipped = [], []
    for i, r in enumerate(rows, start=1):
        event = r.get("event") or r.get("title") or r.get("name")
        date = r.get("date") or r.get("datetime")
        if not event or not date:
            skipped.append(f"row {i}: needs a date and an event name")
            continue
        time_s = (r.get("time") or "").strip()
        all_day = not time_s or time_s.lower() in ("all day", "tentative", "day 1", "day 2")
        try:
            if all_day:
                ts = parse_datetime(f"{date} 12:00", tz=tzinfo)
            else:
                t = time_s.lower().replace(" ", "")
                m = re.fullmatch(r"(\d{1,2}):(\d{2})(am|pm)?", t)
                if m:
                    h, mi = int(m.group(1)), m.group(2)
                    if m.group(3) == "pm" and h < 12:
                        h += 12
                    if m.group(3) == "am" and h == 12:
                        h = 0
                    time_s = f"{h:02d}:{mi}"
                ts = parse_datetime(f"{date} {time_s}", tz=tzinfo)
        except ValueError as e:
            skipped.append(f"row {i}: {e}")
            continue
        out.append({"ts_utc": ts, "all_day": all_day, "event": event.strip(),
                    "currency": r.get("currency") or r.get("country") or r.get("ccy"),
                    "impact": _impact(r.get("impact")), "actual": r.get("actual"),
                    "forecast": r.get("forecast"), "previous": r.get("previous")})
    return {"added": _store(conn, out, "csv"), "rows": len(rows), "skipped": skipped}


def import_ff_json(conn: sqlite3.Connection, data: list[dict] | str | bytes, *, source: str = "ff-json") -> dict:
    if isinstance(data, (str, bytes)):
        data = json.loads(data)
    out, skipped = [], []
    for i, r in enumerate(data or [], start=1):
        try:
            ts = parse_datetime(r["date"])            # explicit offset in this format
            out.append({"ts_utc": ts, "event": r["title"].strip(), "currency": r.get("country"),
                        "impact": _impact(r.get("impact")), "forecast": r.get("forecast"),
                        "previous": r.get("previous"), "actual": r.get("actual")})
        except (KeyError, ValueError, AttributeError) as e:
            skipped.append(f"item {i}: {e}")
    return {"added": _store(conn, out, source), "rows": len(data or []), "skipped": skipped}


def fetch_feed(conn: sqlite3.Connection, *, fetch=None) -> dict:
    def _get():
        req = urllib.request.Request(FEED_URL, headers={"User-Agent": "CompleteJournal"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read()
    try:
        raw = (fetch or _get)()
    except Exception as e:
        return {"added": 0, "error": f"could not fetch the weekly feed ({e}); import a file instead"}
    return import_ff_json(conn, raw, source="ff-feed")


def add_manual(conn: sqlite3.Connection, *, when: str, event: str, impact: str = "high",
               currency: str = "USD", tz: str | None = "America/New_York") -> int:
    if not event.strip():
        raise ValueError("event name required")
    ts = parse_datetime(when, tz=resolve_tz(tz))
    _store(conn, [{"ts_utc": ts, "event": event.strip(), "impact": _impact(impact) or "high",
                   "currency": currency}], "manual")
    return conn.execute("SELECT id FROM econ_events WHERE ts_utc=? AND event=?", (ts, event.strip())).fetchone()[0]


def for_session(conn: sqlite3.Connection, date: str, *, min_impact: str = "medium") -> list[dict]:
    order = {"low": 0, "holiday": 0, "medium": 1, "high": 2}  # holidays: shown in the full list only
    pol = SessionPolicy.from_db(conn)
    d0 = datetime.fromisoformat(date) - timedelta(days=1)
    rows = conn.execute("SELECT * FROM econ_events WHERE ts_utc BETWEEN ? AND ? ORDER BY ts_utc",
                        (d0.strftime("%Y-%m-%d"), (d0 + timedelta(days=3)).strftime("%Y-%m-%d"))).fetchall()
    return [dict(r) for r in rows
            if pol.session_date(r["ts_utc"]) == date and order.get(r["impact"] or "low", 0) >= order[min_impact]]


def trades_near_events(conn: sqlite3.Connection, date: str | None = None, *, minutes: int = 5,
                       impact: str = "high") -> list[dict]:
    """Trades entered within ±minutes of a release of the given impact."""
    q = "SELECT * FROM trades WHERE is_open=0" + (" AND session_date=?" if date else "") + " ORDER BY entry_ts"
    trades = conn.execute(q, (date,) if date else ()).fetchall()
    events = conn.execute("SELECT * FROM econ_events WHERE impact=? AND all_day=0", (impact,)).fetchall()
    out = []
    for t in trades:
        te = datetime.fromisoformat(t["entry_ts"].replace("Z", "+00:00"))
        for ev in events:
            ee = datetime.fromisoformat(ev["ts_utc"].replace("Z", "+00:00"))
            delta = (te - ee).total_seconds() / 60
            if abs(delta) <= minutes:
                out.append({"trade_id": t["id"], "event": ev["event"], "currency": ev["currency"],
                            "minutes_from_release": round(delta, 1), "net_pnl": t["net_pnl"],
                            "session_date": t["session_date"]})
                break
    return out


def near_vs_away(conn: sqlite3.Connection, *, minutes: int = 5) -> dict:
    from .analytics import _compute
    near_ids = {x["trade_id"] for x in trades_near_events(conn, minutes=minutes)}
    rows = conn.execute("SELECT * FROM trades WHERE is_open=0 ORDER BY entry_ts").fetchall()
    return {"window_minutes": minutes,
            "near_high_impact": _compute([r for r in rows if r["id"] in near_ids]).to_dict(),
            "away": _compute([r for r in rows if r["id"] not in near_ids]).to_dict(),
            "note": "association, not cause — small samples are noise"}
