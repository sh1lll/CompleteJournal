"""Databento historical OHLCV fetcher (optional market context).

Uses the plain HTTPS API (no SDK dependency):
  GET https://hist.databento.com/v0/timeseries.get_range
      dataset=GLBX.MDP3, schema=ohlcv-1m, encoding=json (one JSON object/line)
Auth: HTTP basic with the API key as username (key comes from the
DATABENTO_API_KEY environment variable at call time; never stored).

Symbol mapping: we query continuous front month ("ES.c.0", stype_in=continuous)
by default, which is adequate for journal context charts; exact-contract
queries can be added when needed.
⚠️ Built from Databento's public API docs; not yet run against the live API
from this environment (roadmap A5).
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

import httpx

from ..bars import store_bars

HIST = "https://hist.databento.com"

_SCHEMA_BY_RES = {"1m": "ohlcv-1m", "1h": "ohlcv-1h", "1d": "ohlcv-1d"}
_PX_SCALE = 1e-9  # Databento prices are fixed-point 1e-9


def fetch_ohlcv(
    conn: sqlite3.Connection,
    symbol: str,
    start_iso: str,
    end_iso: str,
    *,
    resolution: str = "1m",
    dataset: str = "GLBX.MDP3",
    api_key: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> int:
    """Fetch bars and store them. Returns number of new bars stored."""
    key = api_key or os.environ.get("DATABENTO_API_KEY")
    if not key:
        raise RuntimeError("DATABENTO_API_KEY not set (environment variable or api_key argument)")
    schema = _SCHEMA_BY_RES.get(resolution)
    if not schema:
        raise ValueError(f"resolution must be one of {sorted(_SCHEMA_BY_RES)}")
    params = {
        "dataset": dataset,
        "symbols": f"{symbol.upper()}.c.0",
        "stype_in": "continuous",
        "schema": schema,
        "start": start_iso,
        "end": end_iso,
        "encoding": "json",
        "pretty_px": "false",
        "map_symbols": "false",
    }
    with httpx.Client(base_url=HIST, timeout=60, auth=(key, ""), transport=transport) as http:
        r = http.get("/v0/timeseries.get_range", params=params)
        r.raise_for_status()
        rows = []
        for line in r.text.splitlines():
            if not line.strip():
                continue
            import json as _json
            rec = _json.loads(line)
            ts_ns = int(rec.get("hd", {}).get("ts_event") or rec.get("ts_event"))
            ts = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)
            rows.append({
                "ts_utc": ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                "open": int(rec["open"]) * _PX_SCALE,
                "high": int(rec["high"]) * _PX_SCALE,
                "low": int(rec["low"]) * _PX_SCALE,
                "close": int(rec["close"]) * _PX_SCALE,
                "volume": rec.get("volume"),
            })
    return store_bars(conn, symbol, resolution, rows, source="databento")
