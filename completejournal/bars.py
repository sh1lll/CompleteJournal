"""Price-bar storage: OHLCV context around trades.

Sources: generic CSV import (universal tier) and the optional Databento
fetcher in sync/databento.py. Charts built from these bars are reconstructed
price — the UI labels them as such; screenshots remain the record of what the
trader actually saw.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .importers.base import read_csv, to_utc_iso

RESOLUTIONS = ("1m", "5m", "15m", "1h", "1d")


def store_bars(conn: sqlite3.Connection, symbol: str, resolution: str, rows: list[dict], source: str) -> int:
    """rows: dicts with ts_utc, open, high, low, close, volume(optional)."""
    if resolution not in RESOLUTIONS:
        raise ValueError(f"resolution must be one of {RESOLUTIONS}")
    n = 0
    for r in rows:
        o, h, l, c = (float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
        if not (l <= o <= h and l <= c <= h and l <= h):
            raise ValueError(f"inconsistent OHLC at {r['ts_utc']}: {o}/{h}/{l}/{c}")
        cur = conn.execute(
            "INSERT OR IGNORE INTO bars(symbol, resolution, ts_utc, open, high, low, close, volume, source) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (symbol.upper(), resolution, r["ts_utc"], o, h, l, c,
             float(r["volume"]) if r.get("volume") not in (None, "") else None, source),
        )
        n += cur.rowcount
    conn.commit()
    return n


def import_bars_csv(
    conn: sqlite3.Connection,
    path: str | Path,
    symbol: str,
    resolution: str,
    *,
    tz_offset_minutes: int = 0,
) -> int:
    """Universal bar import. Accepts headers (case-insensitive):
    time/timestamp/date/datetime/ts, open, high, low, close, volume(optional)."""
    tz = timezone(timedelta(minutes=tz_offset_minutes))
    rows = []
    for row in read_csv(path):
        lower = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        ts_raw = next((lower[h] for h in ("time", "timestamp", "date", "datetime", "ts") if lower.get(h)), None)
        if not ts_raw:
            raise ValueError("no time column found")
        rows.append({
            "ts_utc": to_utc_iso(ts_raw, assume_tz=tz),
            "open": lower["open"], "high": lower["high"],
            "low": lower["low"], "close": lower["close"],
            "volume": lower.get("volume") or lower.get("vol"),
        })
    return store_bars(conn, symbol, resolution, rows, source="csv")


def bars_around(
    conn: sqlite3.Connection,
    symbol: str,
    start_ts: str,
    end_ts: str | None,
    *,
    pad_minutes: int = 45,
    resolution: str | None = None,
) -> dict:
    """Bars covering [start - pad, (end or start) + pad]. Picks the finest
    resolution that has data in the window unless one is forced."""
    def _shift(ts: str, minutes: int) -> str:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00")) + timedelta(minutes=minutes)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    lo = _shift(start_ts, -pad_minutes)
    hi = _shift(end_ts or start_ts, pad_minutes)
    resolutions = [resolution] if resolution else list(RESOLUTIONS)
    for res in resolutions:
        rows = conn.execute(
            "SELECT ts_utc, open, high, low, close, volume FROM bars "
            "WHERE symbol=? AND resolution=? AND ts_utc BETWEEN ? AND ? ORDER BY ts_utc",
            (symbol.upper(), res, lo, hi),
        ).fetchall()
        if rows:
            return {"symbol": symbol.upper(), "resolution": res,
                    "bars": [dict(r) for r in rows], "reconstructed": True}
    return {"symbol": symbol.upper(), "resolution": None, "bars": [], "reconstructed": True}
