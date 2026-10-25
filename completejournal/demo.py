"""Demo data: a clearly labelled sample so the app is useful on first open.

Everything lands in an account named "Demo (sample data)" and every demo
journal entry is tagged `demo`, so it can never be mistaken for real records
and can be removed in one step (remove_demo). Deterministic (seeded RNG).
"""
from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timedelta, timezone

from . import bars, journal
from .db import get_or_create_account
from .importers.base import NormalizedExecution, ingest
from .reconstruction import rebuild

DEMO_ACCOUNT = "Demo (sample data)"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def seed(conn: sqlite3.Connection, *, days: int = 10, seed_value: int = 42) -> dict:
    if conn.execute("SELECT 1 FROM accounts WHERE name=?", (DEMO_ACCOUNT,)).fetchone():
        return {"seeded": False, "reason": "demo data already present"}
    rng = random.Random(seed_value)
    acct = get_or_create_account(conn, DEMO_ACCOUNT, firm="Sample", platform="demo",
                                 account_type="sim")
    # weekdays ending yesterday (UTC), 13:30-20:00 UTC ~ 08:30-15:00 CT
    day = datetime.now(timezone.utc).replace(hour=13, minute=30, second=0, microsecond=0)
    sessions = []
    while len(sessions) < days:
        day -= timedelta(days=1)
        if day.weekday() < 5:
            sessions.append(day)
    sessions.reverse()

    fills: list[NormalizedExecution] = []
    entries = 0
    for s in sessions:
        price = 5800 + rng.uniform(-60, 60)
        bar_rows = []
        t = s
        for _ in range(240):                       # 4h of 1-minute MES bars
            o = price
            c = o + rng.gauss(0, 1.4)
            h = max(o, c) + abs(rng.gauss(0, 0.8))
            l = min(o, c) - abs(rng.gauss(0, 0.8))
            bar_rows.append({"ts_utc": _iso(t), "open": round(o, 2), "high": round(h, 2),
                             "low": round(l, 2), "close": round(c, 2), "volume": rng.randint(200, 2500)})
            price = c
            t += timedelta(minutes=1)
        bars.store_bars(conn, "MES", "1m", bar_rows, source="demo")

        n_trades = rng.choice([1, 2, 2, 3, 4])
        minute = rng.randint(5, 30)
        for _ in range(n_trades):
            if minute > 220:
                break
            b_in = bar_rows[minute]
            hold = rng.randint(3, 18)
            b_out = bar_rows[min(minute + hold, 239)]
            qty = rng.choice([1, 1, 2, 3])
            side = rng.choice(["buy", "sell"])
            px_in = round(b_in["close"] * 4) / 4
            px_out = round(b_out["close"] * 4) / 4
            fills.append(NormalizedExecution("MES", side, qty, px_in, b_in["ts_utc"],
                                             contract="MESZ6", fees=0.62 * qty))
            fills.append(NormalizedExecution("MES", "sell" if side == "buy" else "buy", qty,
                                             px_out, b_out["ts_utc"], contract="MESZ6",
                                             fees=0.62 * qty))
            minute += hold + rng.randint(2, 40)

        date = s.strftime("%Y-%m-%d")
        eid = journal.create_entry(
            conn,
            f"Sample pre-market plan for @{date}: watching @MES around the overnight range. "
            f"Bias neutral until the open drive shows its hand; invalidation is a full "
            f"reversal through the range midpoint.\n\nInstruments: MES\nMax trades: 2\n"
            f"Max contracts: 2\nTrading window: 08:30-11:00\nStop after: 2 losses",
            kind="pre-market", title=f"Plan {date} (demo)", about_date=date)
        journal.tag(conn, eid, "demo")
        entries += 1

    ingest(conn, acct, DEMO_ACCOUNT, "demo", "demo", fills)
    report = rebuild(conn)

    last = sessions[-1].strftime("%Y-%m-%d")
    eid = journal.create_entry(
        conn,
        f"Sample end-of-day reflection for @{last}. This is demo text showing how a "
        f"free-form entry links itself to a session and an instrument (@MES) just by "
        f"mentioning them. Delete demo data from the Import screen when you are ready.",
        kind="end-of-day", title="Reflection (demo)", about_date=last)
    journal.tag(conn, eid, "demo")
    demo_trades = conn.execute("SELECT COUNT(*) FROM trades WHERE account_id=?", (acct,)).fetchone()[0]
    return {"seeded": True, "account": DEMO_ACCOUNT, "sessions": len(sessions),
            "executions": len(fills), "trades_total": demo_trades,
            "entries": entries + 1}


def remove_demo(conn: sqlite3.Connection) -> dict:
    """Remove all demo records. Real data is untouched (scoped by account/tag)."""
    acct = conn.execute("SELECT id FROM accounts WHERE name=?", (DEMO_ACCOUNT,)).fetchone()
    removed = {"trades": 0, "executions": 0, "entries": 0, "bars": 0}
    if acct:
        aid = acct["id"]
        removed["trades"] = conn.execute("DELETE FROM trades WHERE account_id=?", (aid,)).rowcount
        removed["executions"] = conn.execute("DELETE FROM executions WHERE account_id=?", (aid,)).rowcount
        conn.execute("DELETE FROM accounts WHERE id=?", (aid,))
    removed["bars"] = conn.execute("DELETE FROM bars WHERE source='demo'").rowcount
    ids = [r[0] for r in conn.execute("SELECT entry_id FROM tags WHERE tag='demo'")]
    for eid in ids:
        for tbl in ("links", "tags", "entry_versions", "entry_addenda"):
            conn.execute(f"DELETE FROM {tbl} WHERE entry_id=?", (eid,))
        row = conn.execute("SELECT title, body_md FROM entries WHERE id=?", (eid,)).fetchone()
        if row:  # external-content FTS needs the 'delete' command with old values
            conn.execute("INSERT INTO entries_fts(entries_fts, rowid, title, body_md) "
                         "VALUES('delete', ?, ?, ?)", (eid, row["title"], row["body_md"]))
        conn.execute("DELETE FROM entries WHERE id=?", (eid,))
    removed["entries"] = len(ids)
    conn.commit()
    return removed
