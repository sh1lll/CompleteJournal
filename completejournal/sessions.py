"""Trading-session date policy.

A fill belongs to the trading day it trades in, not the UTC calendar date.
Default convention (CME Globex, also correct for US equities hours): the
session date is the America/Chicago calendar date, rolled forward one day for
fills at or after 17:00 CT (Globex reopens 17:00 CT for the next trading day).

Configurable per journal via the meta table:
  session_tz        IANA timezone (default America/Chicago)
  session_roll_hour hour at which the next session starts (default 17;
                    set 24 to disable rolling, e.g. for non-futures traders)
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from .importers.parsing import resolve_tz

DEFAULT_TZ = "America/Chicago"
DEFAULT_ROLL_HOUR = 17


class SessionPolicy:
    def __init__(self, tz: str = DEFAULT_TZ, roll_hour: int = DEFAULT_ROLL_HOUR):
        self.tz_name = tz
        self.tz = resolve_tz(tz) or timezone.utc
        self.roll_hour = roll_hour

    @classmethod
    def from_db(cls, conn: sqlite3.Connection) -> "SessionPolicy":
        meta = dict(conn.execute(
            "SELECT key, value FROM meta WHERE key IN ('session_tz','session_roll_hour')"
        ).fetchall())
        return cls(meta.get("session_tz", DEFAULT_TZ),
                   int(meta.get("session_roll_hour", DEFAULT_ROLL_HOUR)))

    def session_date(self, ts_utc: str) -> str:
        dt = datetime.fromisoformat(ts_utc.replace("Z", "+00:00")).astimezone(self.tz)
        if dt.hour >= self.roll_hour:
            dt += timedelta(days=1)
        return dt.strftime("%Y-%m-%d")


def set_policy(conn: sqlite3.Connection, tz: str | None = None, roll_hour: int | None = None) -> None:
    if tz is not None:
        resolve_tz(tz)  # validate
        conn.execute("INSERT INTO meta(key,value) VALUES('session_tz',?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (tz,))
    if roll_hour is not None:
        if not 0 <= roll_hour <= 24:
            raise ValueError("roll_hour must be 0..24")
        conn.execute("INSERT INTO meta(key,value) VALUES('session_roll_hour',?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(roll_hour),))
    conn.commit()
