"""MAE / MFE — how far each trade went against you and in your favour.

Computed from stored price bars between entry and exit, so it is a
BAR-RESOLUTION APPROXIMATION: with 1-minute bars the extremes inside the
entry and exit minutes may include prices from just before entry or just
after exit. Results say which resolution was used and are labelled
'approximate'. Trades without bar coverage return None rather than a guess.

Definitions (per contract, in points, from the average entry price):
  MAE  maximum adverse excursion  — worst price against the position
  MFE  maximum favourable excursion — best price in the position's favour
  capture = realized points / MFE points (how much of the move you kept)
"""
from __future__ import annotations

import sqlite3

from .bars import RESOLUTIONS


def trade_excursion(conn: sqlite3.Connection, trade_id: int) -> dict | None:
    t = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
    if not t or t["is_open"] or not t["exit_ts"]:
        return None
    lo_ts = t["entry_ts"][:16] + ":00.000Z"  # floor to the entry minute
    for res in RESOLUTIONS:
        row = conn.execute(
            "SELECT MIN(low) lo, MAX(high) hi, COUNT(*) n FROM bars "
            "WHERE symbol=? AND resolution=? AND ts_utc BETWEEN ? AND ?",
            (t["symbol"], res, lo_ts, t["exit_ts"]),
        ).fetchone()
        if row["n"]:
            break
    else:
        return None
    pv_row = conn.execute("SELECT point_value FROM instruments WHERE symbol=?",
                          (t["symbol"],)).fetchone()
    pv = pv_row["point_value"] if pv_row else 1.0
    entry = t["avg_entry"]
    if t["direction"] == "long":
        mae_pts = max(0.0, entry - row["lo"])
        mfe_pts = max(0.0, row["hi"] - entry)
        realized_pts = (t["avg_exit"] - entry)
    else:
        mae_pts = max(0.0, row["hi"] - entry)
        mfe_pts = max(0.0, entry - row["lo"])
        realized_pts = (entry - t["avg_exit"])
    return {
        "trade_id": t["id"],
        "resolution": res,
        "bars": row["n"],
        "mae_points": round(mae_pts, 6),
        "mfe_points": round(mfe_pts, 6),
        "mae_per_contract": round(mae_pts * pv, 2),
        "mfe_per_contract": round(mfe_pts * pv, 2),
        "realized_points": round(realized_pts, 6),
        "capture_ratio": round(realized_pts / mfe_pts, 3) if mfe_pts > 0 else None,
        "approximate": True,
    }


def summary(conn: sqlite3.Connection, account_id: int | None = None) -> dict:
    """Aggregate excursion profile: are losers allowed to run, are winners cut?"""
    q = "SELECT id, net_pnl FROM trades WHERE is_open=0" + (" AND account_id=?" if account_id else "")
    rows = conn.execute(q, (account_id,) if account_id else ()).fetchall()
    winners, losers, covered = [], [], 0
    for r in rows:
        e = trade_excursion(conn, r["id"])
        if not e:
            continue
        covered += 1
        (winners if r["net_pnl"] > 0 else losers).append(e)

    def avg(xs, k):
        vals = [x[k] for x in xs if x[k] is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    return {
        "trades_with_bars": covered,
        "trades_total": len(rows),
        "winners": {"n": len(winners), "avg_mae_points": avg(winners, "mae_points"),
                    "avg_mfe_points": avg(winners, "mfe_points"),
                    "avg_capture": avg(winners, "capture_ratio")},
        "losers": {"n": len(losers), "avg_mae_points": avg(losers, "mae_points"),
                   "avg_mfe_points": avg(losers, "mfe_points")},
        "reading": ("losers with large MFE were in profit before turning; winners "
                    "with low capture left most of the move on the table"),
        "approximate": True,
    }
