"""Core performance analytics over derived trades.

Statistical-honesty rules (assessment §04): every aggregate carries n;
breakdowns with n < MIN_SAMPLE are flagged low_sample; nothing here claims
causality. All figures are computed from closed trades only unless stated.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

MIN_SAMPLE = 30


@dataclass
class Stats:
    n: int = 0
    wins: int = 0
    losses: int = 0
    scratches: int = 0
    win_rate: float | None = None
    avg_win: float | None = None
    avg_loss: float | None = None
    payoff_ratio: float | None = None
    expectancy: float | None = None
    profit_factor: float | None = None
    gross_pnl: float = 0.0
    fees: float = 0.0
    net_pnl: float = 0.0
    max_drawdown: float = 0.0
    low_sample: bool = True
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _compute(rows: list[sqlite3.Row]) -> Stats:
    s = Stats(n=len(rows))
    if not rows:
        return s
    win_sum = loss_sum = 0.0
    equity = peak = 0.0
    for r in rows:
        pnl = r["net_pnl"]
        s.gross_pnl += r["realized_pnl"]
        s.fees += r["fees"]
        s.net_pnl += pnl
        if pnl > 0:
            s.wins += 1
            win_sum += pnl
        elif pnl < 0:
            s.losses += 1
            loss_sum += -pnl
        else:
            s.scratches += 1
        equity += pnl
        peak = max(peak, equity)
        s.max_drawdown = max(s.max_drawdown, peak - equity)
    decided = s.wins + s.losses
    if decided:
        s.win_rate = s.wins / decided
    if s.wins:
        s.avg_win = win_sum / s.wins
    if s.losses:
        s.avg_loss = loss_sum / s.losses
    if s.avg_win and s.avg_loss:
        s.payoff_ratio = s.avg_win / s.avg_loss
    if s.n:
        s.expectancy = s.net_pnl / s.n
    if loss_sum > 0:
        s.profit_factor = win_sum / loss_sum
    elif win_sum > 0:
        s.notes.append("no losing trades yet — profit factor undefined")
    s.low_sample = s.n < MIN_SAMPLE
    if s.low_sample:
        s.notes.append(f"n={s.n} < {MIN_SAMPLE}: treat every figure as noise-dominated")
    return s


_CLOSED = "is_open = 0"


def overall(conn: sqlite3.Connection, account_id: int | None = None) -> Stats:
    where = f"WHERE {_CLOSED}" + (" AND account_id=?" if account_id else "")
    params = (account_id,) if account_id else ()
    rows = conn.execute(f"SELECT * FROM trades {where} ORDER BY entry_ts", params).fetchall()
    return _compute(rows)


def breakdown(conn: sqlite3.Connection, dimension: str, account_id: int | None = None) -> dict[str, dict]:
    """dimension: symbol | weekday | session_date | account | hour"""
    expr = {
        "symbol": "symbol",
        "session_date": "session_date",
        "weekday": "strftime('%w', entry_ts)",
        "hour": "substr(entry_ts, 12, 2)",
        "account": "(SELECT name FROM accounts WHERE id = trades.account_id)",
    }.get(dimension)
    if expr is None:
        raise ValueError(f"unknown dimension {dimension!r}")
    where = f"WHERE {_CLOSED}" + (" AND account_id=?" if account_id else "")
    params = (account_id,) if account_id else ()
    rows = conn.execute(
        f"SELECT {expr} AS bucket, * FROM trades {where} ORDER BY bucket, entry_ts", params
    ).fetchall()
    buckets: dict[str, list] = {}
    for r in rows:
        buckets.setdefault(str(r["bucket"]), []).append(r)
    return {k: _compute(v).to_dict() for k, v in buckets.items()}


def equity_curve(conn: sqlite3.Connection, account_id: int | None = None) -> list[dict]:
    where = f"WHERE {_CLOSED}" + (" AND account_id=?" if account_id else "")
    params = (account_id,) if account_id else ()
    rows = conn.execute(
        f"SELECT exit_ts, net_pnl FROM trades {where} ORDER BY exit_ts", params
    ).fetchall()
    out, cum = [], 0.0
    for r in rows:
        cum += r["net_pnl"]
        out.append({"ts": r["exit_ts"], "equity": round(cum, 2)})
    return out


def set_grade(conn: sqlite3.Connection, trade_id: int, grade: str, note: str | None = None) -> None:
    """Grade the DECISION (A–F), not the outcome. Keyed on the trade's stable
    fingerprint so it survives reconstruction rebuilds."""
    if grade not in ("A", "B", "C", "D", "F"):
        raise ValueError("grade must be A, B, C, D or F")
    t = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
    if not t:
        raise KeyError(f"trade {trade_id} not found")
    conn.execute(
        """INSERT INTO trade_grades(account_id, symbol, entry_ts, direction, grade, note)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(account_id, symbol, entry_ts, direction)
           DO UPDATE SET grade=excluded.grade, note=excluded.note,
                         graded_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
        (t["account_id"], t["symbol"], t["entry_ts"], t["direction"], grade, note),
    )
    conn.commit()


def get_grade(conn: sqlite3.Connection, trade_id: int) -> dict | None:
    row = conn.execute(
        """SELECT g.grade, g.note, g.graded_at FROM trades t
           JOIN trade_grades g ON g.account_id=t.account_id AND g.symbol=t.symbol
                AND g.entry_ts=t.entry_ts AND g.direction=t.direction
           WHERE t.id=?""", (trade_id,)).fetchone()
    return dict(row) if row else None


def process_vs_outcome(conn: sqlite3.Connection, account_id: int | None = None) -> dict:
    """The quadrant that matters: good decisions/bad outcomes vs the reverse.
    Grades A/B count as good process, D/F as bad; C and ungraded are excluded."""
    where = f"WHERE {_CLOSED}" + (" AND t.account_id=?" if account_id else "")
    params = (account_id,) if account_id else ()
    rows = conn.execute(
        f"""SELECT t.*, g.grade FROM trades t
            LEFT JOIN trade_grades g ON g.account_id=t.account_id AND g.symbol=t.symbol
                 AND g.entry_ts=t.entry_ts AND g.direction=t.direction
            {where} ORDER BY t.entry_ts""", params).fetchall()
    quad = {"good_process_won": [], "good_process_lost": [],
            "bad_process_won": [], "bad_process_lost": []}
    ungraded = 0
    for r in rows:
        if r["grade"] in ("A", "B"):
            quad["good_process_won" if r["net_pnl"] > 0 else "good_process_lost"].append(r)
        elif r["grade"] in ("D", "F"):
            quad["bad_process_won" if r["net_pnl"] > 0 else "bad_process_lost"].append(r)
        else:
            ungraded += 1
    out = {k: _compute(v).to_dict() for k, v in quad.items()}
    out["ungraded_or_c"] = ungraded
    out["reading"] = ("bad_process_won is the most dangerous quadrant — "
                      "profit that trains a bad habit")
    return out


def reconciliation(conn: sqlite3.Connection) -> list[dict]:
    """Per account+day: computed net P&L and execution counts, so the trader can
    compare against the platform's own daily statement. Discrepancies are for
    humans to judge — we surface, we do not auto-correct."""
    rows = conn.execute(
        """SELECT a.name AS account, t.session_date AS date,
                  COUNT(*) AS trades, SUM(t.n_executions) AS executions,
                  ROUND(SUM(t.realized_pnl), 2) AS gross_pnl,
                  ROUND(SUM(t.fees), 2) AS fees,
                  ROUND(SUM(t.net_pnl), 2) AS net_pnl,
                  SUM(t.is_open) AS still_open
           FROM trades t JOIN accounts a ON a.id = t.account_id
           GROUP BY a.name, t.session_date ORDER BY t.session_date DESC, a.name"""
    ).fetchall()
    return [dict(r) for r in rows]
