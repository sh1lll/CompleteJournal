"""Trade reconstruction: executions -> logical trades.

Algorithm (v1):
  * per (account, symbol): sort fills by timestamp, then execution rowid
  * maintain signed net position and a FIFO queue of open lots
  * trade boundary = position returns to zero (flat -> flat = one trade;
    scale-ins/outs stay inside the trade)
  * a fill that crosses zero is SPLIT: the closing quantity ends trade A,
    the remainder opens trade B (the classic reversal case)
  * realized P&L = sum over matched lots of (exit - entry) * qty * point_value,
    sign-adjusted for direction; fees attributed pro-rata by attributed qty
  * trades are fully derived: rebuild() deletes and regenerates everything
    from the immutable executions table

P&L for unknown instruments uses point_value = 1.0 (points, not currency) and
is flagged in the rebuild report — honesty over silent wrong math.
"""
from __future__ import annotations

import sqlite3
from collections import deque
from dataclasses import dataclass, field

ALGORITHM_VERSION = "fifo-v1"


@dataclass
class _Lot:
    qty: int
    price: float


@dataclass
class _OpenTrade:
    direction: str              # long | short
    entry_ts: str
    contract: str | None
    lots: deque = field(default_factory=deque)       # open entry lots (FIFO)
    entry_qty: int = 0
    entry_value: float = 0.0    # sum(price*qty) over entries
    exit_qty: int = 0
    exit_value: float = 0.0
    realized_points: float = 0.0
    fees: float = 0.0
    qty_max: int = 0
    position: int = 0           # current absolute open qty
    executions: list = field(default_factory=list)   # (execution_id, attributed_qty)


@dataclass
class RebuildReport:
    trades_created: int = 0
    open_trades: int = 0
    unknown_instruments: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def rebuild(conn: sqlite3.Connection, account_id: int | None = None) -> RebuildReport:
    """Regenerate all derived trades (for one account or all) from executions."""
    report = RebuildReport()
    where, params = ("WHERE account_id = ?", (account_id,)) if account_id else ("", ())
    conn.execute(f"DELETE FROM trades {where}", params)

    pv_map = {
        r["symbol"]: r["point_value"]
        for r in conn.execute("SELECT symbol, point_value FROM instruments")
    }

    keys = conn.execute(
        f"SELECT DISTINCT account_id, symbol FROM executions {where}", params
    ).fetchall()
    for key in keys:
        acct, symbol = key["account_id"], key["symbol"]
        pv = pv_map.get(symbol)
        if pv is None:
            pv = 1.0
            if symbol not in report.unknown_instruments:
                report.unknown_instruments.append(symbol)
        fills = conn.execute(
            "SELECT id, side, qty, price, ts_utc, fees, contract FROM executions "
            "WHERE account_id=? AND symbol=? ORDER BY ts_utc, id",
            (acct, symbol),
        ).fetchall()
        _reconstruct_symbol(conn, acct, symbol, pv, fills, report)
    conn.commit()
    return report


def _reconstruct_symbol(conn, acct: int, symbol: str, pv: float, fills, report: RebuildReport):
    trade: _OpenTrade | None = None

    def close_out(tr: _OpenTrade, exit_ts: str | None):
        nonlocal report
        avg_entry = tr.entry_value / tr.entry_qty if tr.entry_qty else 0.0
        avg_exit = tr.exit_value / tr.exit_qty if tr.exit_qty else None
        realized = tr.realized_points * pv
        is_open = 1 if tr.position != 0 else 0
        net = realized - tr.fees
        session_date = tr.entry_ts[:10]
        cur = conn.execute(
            """INSERT INTO trades(account_id, symbol, contract, direction, qty_max,
               entry_ts, exit_ts, avg_entry, avg_exit, realized_pnl, fees, net_pnl,
               n_executions, is_open, algorithm_version, session_date)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (acct, symbol, tr.contract, tr.direction, tr.qty_max, tr.entry_ts,
             None if is_open else exit_ts, avg_entry, avg_exit, realized, tr.fees,
             net, len(tr.executions), is_open, ALGORITHM_VERSION, session_date),
        )
        tid = cur.lastrowid
        conn.executemany(
            "INSERT OR REPLACE INTO trade_executions(trade_id, execution_id, qty) VALUES (?,?,?)",
            [(tid, eid, q) for eid, q in tr.executions],
        )
        report.trades_created += 1
        if is_open:
            report.open_trades += 1

    for f in fills:
        qty_left = f["qty"]
        fee_per_contract = (f["fees"] or 0.0) / f["qty"]
        fill_sign = 1 if f["side"] == "buy" else -1

        while qty_left > 0:
            if trade is None:
                trade = _OpenTrade(
                    direction="long" if fill_sign > 0 else "short",
                    entry_ts=f["ts_utc"],
                    contract=f["contract"],
                )
            trade_sign = 1 if trade.direction == "long" else -1

            if fill_sign == trade_sign:
                # scale-in: add a lot
                q = qty_left
                trade.lots.append(_Lot(q, f["price"]))
                trade.entry_qty += q
                trade.entry_value += q * f["price"]
                trade.position += q
                trade.qty_max = max(trade.qty_max, trade.position)
                trade.fees += fee_per_contract * q
                trade.executions.append((f["id"], q))
                qty_left = 0
            else:
                # closing (possibly crossing zero)
                q = min(qty_left, trade.position)
                matched = q
                trade.exit_qty += q
                trade.exit_value += q * f["price"]
                trade.fees += fee_per_contract * q
                trade.executions.append((f["id"], q))
                while matched > 0:
                    lot = trade.lots[0]
                    take = min(matched, lot.qty)
                    trade.realized_points += (f["price"] - lot.price) * take * trade_sign
                    lot.qty -= take
                    matched -= take
                    if lot.qty == 0:
                        trade.lots.popleft()
                trade.position -= q
                qty_left -= q
                if trade.position == 0:
                    close_out(trade, f["ts_utc"])
                    trade = None
                    # remaining qty_left (reversal) opens a new trade next loop

    if trade is not None:
        # still open at end of data
        close_out(trade, None)
