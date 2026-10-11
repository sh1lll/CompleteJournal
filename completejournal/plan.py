"""Plan vs actual: compare a session's pre-market plan with what happened.

The plan stays free writing. If — and only if — the trader includes simple
'Key: value' lines, those become checkable rules. Nothing is required:
a plan with no rule lines still appears side by side with the day's trades.

Recognised rule lines (case-insensitive, anywhere in the plan):
  Instruments: MES, NQ          (also 'Markets:' / 'Trade only:')
  Max trades: 3
  Max loss: 200                 (also 'Daily stop:' / 'Max daily loss:') — dollars
  Max contracts: 2              (also 'Max size:')
  Trading window: 08:30-11:00   (also 'Trade window:' / 'Hours:') — session timezone
  Stop after: 2 losses          (also 'Stop after 2 losses')
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime

from .sessions import SessionPolicy

PLAN_TEMPLATE = """Narrative:

Bias:

Scenarios:

Key levels:

Invalidation:

(Optional checkable rules — delete any you don't want)
Instruments: MES
Max trades: 3
Max loss: 200
Max contracts: 2
Trading window: 08:30-11:00
Stop after: 2 losses
"""

_NUM = r"\$?\s*([\d,]+(?:\.\d+)?)"


def parse_rules(text: str) -> dict:
    rules: dict = {}
    for line in (text or "").splitlines():
        s = line.strip().lstrip("-*• ").strip()
        low = s.lower()
        m = re.match(r"^(instruments|markets|trade only|symbols)\s*:\s*(.+)$", low)
        if m:
            syms = re.findall(r"@?([A-Za-z0-9]{1,6})", s.split(":", 1)[1])
            rules["instruments"] = sorted({x.upper() for x in syms})
            continue
        m = re.match(r"^max(?:imum)? trades\s*:\s*(\d+)", low)
        if m:
            rules["max_trades"] = int(m.group(1))
            continue
        m = re.match(r"^(?:max(?:imum)?(?: daily)? loss|daily stop|daily max loss)\s*:\s*" + _NUM, low)
        if m:
            rules["max_loss"] = float(m.group(1).replace(",", ""))
            continue
        m = re.match(r"^max(?:imum)? (?:contracts|size|position)\s*:\s*(\d+)", low)
        if m:
            rules["max_contracts"] = int(m.group(1))
            continue
        m = re.match(r"^(?:trading window|trade window|hours)\s*:\s*(\d{1,2}):(\d{2})\s*[-–to]+\s*(\d{1,2}):(\d{2})", low)
        if m:
            rules["window"] = (f"{int(m.group(1)):02d}:{m.group(2)}", f"{int(m.group(3)):02d}:{m.group(4)}")
            continue
        m = re.match(r"^stop after\s*:?\s*(\d+)\s*loss", low)
        if m:
            rules["stop_after_losses"] = int(m.group(1))
    return rules


def _local_hhmm(ts_utc: str, policy: SessionPolicy) -> str:
    return datetime.fromisoformat(ts_utc.replace("Z", "+00:00")).astimezone(policy.tz).strftime("%H:%M")


def evaluate(rules: dict, trades: list, policy: SessionPolicy) -> list[dict]:
    """Return one result per rule: kept / broken, with evidence trade ids."""
    out = []
    closed = [t for t in trades if not t["is_open"]]

    if "instruments" in rules:
        off = [t["id"] for t in trades if t["symbol"] not in rules["instruments"]]
        out.append({"rule": f"Instruments: {', '.join(rules['instruments'])}",
                    "kept": not off, "trade_ids": off,
                    "detail": f"{len(off)} trade(s) in other instruments" if off else "all trades in planned instruments"})
    if "max_trades" in rules:
        n = len(trades)
        extra = [t["id"] for t in trades[rules["max_trades"]:]]
        out.append({"rule": f"Max trades: {rules['max_trades']}", "kept": n <= rules["max_trades"],
                    "trade_ids": extra, "detail": f"{n} trade(s) taken"})
    if "max_contracts" in rules:
        big = [t["id"] for t in trades if t["qty_max"] > rules["max_contracts"]]
        out.append({"rule": f"Max contracts: {rules['max_contracts']}", "kept": not big,
                    "trade_ids": big,
                    "detail": f"largest position {max((t['qty_max'] for t in trades), default=0)}"})
    if "window" in rules:
        start, end = rules["window"]
        outside = [t["id"] for t in trades if not (start <= _local_hhmm(t["entry_ts"], policy) <= end)]
        out.append({"rule": f"Trading window: {start}-{end} ({policy.tz_name})", "kept": not outside,
                    "trade_ids": outside,
                    "detail": f"{len(outside)} entr{'y' if len(outside) == 1 else 'ies'} outside the window" if outside else "all entries inside the window"})
    if "max_loss" in rules:
        cum, breached_at, after = 0.0, None, []
        for t in closed:
            if breached_at is not None:
                after.append(t["id"])
            cum += t["net_pnl"]
            if breached_at is None and cum <= -rules["max_loss"]:
                breached_at = t["id"]
        day_net = round(sum(t["net_pnl"] for t in closed), 2)
        out.append({"rule": f"Max loss: ${rules['max_loss']:,.0f}",
                    "kept": breached_at is None or not after,
                    "trade_ids": after,
                    "detail": (f"limit hit at trade #{breached_at}; {len(after)} trade(s) taken after it"
                               if breached_at is not None else f"day net ${day_net:,.2f}")})
    if "stop_after_losses" in rules:
        k, losses, after = rules["stop_after_losses"], 0, []
        for t in closed:
            if losses >= k:
                after.append(t["id"])
            if t["net_pnl"] < 0:
                losses += 1
        out.append({"rule": f"Stop after {k} losses", "kept": not after, "trade_ids": after,
                    "detail": f"{len(after)} trade(s) after the {k}th loss" if after else f"{losses} loss(es) on the day"})
    return out


def plan_vs_actual(conn: sqlite3.Connection, date: str) -> dict:
    policy = SessionPolicy.from_db(conn)
    plan = conn.execute(
        "SELECT * FROM entries WHERE deleted_at IS NULL AND kind='pre-market' AND about_date=? "
        "ORDER BY written_at DESC LIMIT 1", (date,)).fetchone()
    trades = conn.execute(
        "SELECT t.*, a.name AS account_name FROM trades t JOIN accounts a ON a.id=t.account_id "
        "WHERE t.session_date=? ORDER BY t.entry_ts", (date,)).fetchall()
    reflections = conn.execute(
        "SELECT * FROM entries WHERE deleted_at IS NULL AND about_date=? "
        "AND kind IN ('end-of-day','post-trade','trade-review','intraday') ORDER BY written_at",
        (date,)).fetchall()
    rules = parse_rules(plan["body_md"]) if plan else {}
    results = evaluate(rules, trades, policy) if rules else []
    closed = [t for t in trades if not t["is_open"]]
    return {
        "date": date,
        "plan": dict(plan) if plan else None,
        "rules": {k: list(v) if isinstance(v, tuple) else v for k, v in rules.items()},
        "results": results,
        "kept": sum(1 for r in results if r["kept"]),
        "broken": sum(1 for r in results if not r["kept"]),
        "trades": [dict(t) for t in trades],
        "net_pnl": round(sum(t["net_pnl"] for t in closed), 2),
        "reflections": [dict(r) for r in reflections],
        "note": None if plan else "no pre-market plan written for this session",
    }
