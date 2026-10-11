"""Golden-scenario tests for the FIFO reconstruction engine.

These encode the cases the assessment flagged as the classic failure modes:
partial exits, scale-ins, reversals (zero-crossing splits), multi-account
separation, unknown instruments, open positions, and idempotent re-import.
"""
import sqlite3

import pytest

from completejournal import db as dbmod
from completejournal import reconstruction
from completejournal.importers.base import NormalizedExecution, ingest


@pytest.fixture()
def conn():
    c = dbmod.connect(":memory:")
    yield c
    c.close()


def _fill(symbol, side, qty, price, ts, fees=0.0, exec_id=None, contract=None):
    return NormalizedExecution(
        symbol=symbol, side=side, qty=qty, price=price,
        ts_utc=ts, fees=fees, exec_id=exec_id, contract=contract,
    )


def _setup(conn, fills, account="TestAcct"):
    acct = dbmod.get_or_create_account(conn, account)
    ingest(conn, acct, account, "test", "test", fills)
    report = reconstruction.rebuild(conn)
    return acct, report


def trades(conn):
    return conn.execute("SELECT * FROM trades ORDER BY entry_ts").fetchall()


T = "2026-10-09T13:3{}:00.000Z"  # minute slot template


def test_simple_long_round_trip(conn):
    # Buy 2 MES @ 5000, sell 2 @ 5010 -> +10 pts * 2 * $5 = $100, fees 2.5
    _setup(conn, [
        _fill("MES", "buy", 2, 5000.0, T.format(0), fees=1.25),
        _fill("MES", "sell", 2, 5010.0, T.format(5), fees=1.25),
    ])
    (t,) = trades(conn)
    assert t["direction"] == "long"
    assert t["realized_pnl"] == pytest.approx(100.0)
    assert t["fees"] == pytest.approx(2.5)
    assert t["net_pnl"] == pytest.approx(97.5)
    assert t["is_open"] == 0
    assert t["qty_max"] == 2


def test_short_trade(conn):
    # Sell 1 ES @ 6000, buy back @ 5990 -> +10 pts * $50 = $500
    _setup(conn, [
        _fill("ES", "sell", 1, 6000.0, T.format(0)),
        _fill("ES", "buy", 1, 5990.0, T.format(5)),
    ])
    (t,) = trades(conn)
    assert t["direction"] == "short"
    assert t["realized_pnl"] == pytest.approx(500.0)


def test_scale_in_partial_exits_fifo(conn):
    # Buy 2 @ 100, buy 2 @ 102, sell 1 @ 105, sell 3 @ 101 (symbol XX, pv=1)
    # FIFO: sell1@105 vs lot@100 -> +5; sell3: 1@100->+1, 2@102->-2 => total +4 pts
    _setup(conn, [
        _fill("XX", "buy", 2, 100.0, T.format(0)),
        _fill("XX", "buy", 2, 102.0, T.format(1)),
        _fill("XX", "sell", 1, 105.0, T.format(2)),
        _fill("XX", "sell", 3, 101.0, T.format(3)),
    ])
    (t,) = trades(conn)
    assert t["qty_max"] == 4
    assert t["n_executions"] == 4
    assert t["realized_pnl"] == pytest.approx(4.0)
    assert t["avg_entry"] == pytest.approx(101.0)
    assert t["avg_exit"] == pytest.approx(102.0)
    assert t["is_open"] == 0


def test_reversal_splits_into_two_trades(conn):
    # Long 2 @ 100; sell 5 @ 110 crosses zero: trade A long 2 closed +20 pts,
    # trade B short 3 opened @110, covered 3 @ 105 -> +15 pts (pv=1).
    _setup(conn, [
        _fill("XX", "buy", 2, 100.0, T.format(0)),
        _fill("XX", "sell", 5, 110.0, T.format(1)),
        _fill("XX", "buy", 3, 105.0, T.format(2)),
    ])
    a, b = trades(conn)
    assert a["direction"] == "long" and a["realized_pnl"] == pytest.approx(20.0)
    assert b["direction"] == "short" and b["realized_pnl"] == pytest.approx(15.0)
    assert a["is_open"] == 0 and b["is_open"] == 0
    # the reversal fill is attributed to both trades with split quantities
    qty_by_trade = {
        r["trade_id"]: r["qty"]
        for r in conn.execute(
            "SELECT te.trade_id, te.qty FROM trade_executions te "
            "JOIN executions e ON e.id = te.execution_id WHERE e.qty = 5"
        )
    }
    assert sorted(qty_by_trade.values()) == [2, 3]


def test_reversal_fee_attribution(conn):
    # 5-lot reversal fill with $5 fees: $2 to trade A (2 contracts), $3 to B.
    _setup(conn, [
        _fill("XX", "buy", 2, 100.0, T.format(0), fees=2.0),
        _fill("XX", "sell", 5, 110.0, T.format(1), fees=5.0),
        _fill("XX", "buy", 3, 105.0, T.format(2), fees=3.0),
    ])
    a, b = trades(conn)
    assert a["fees"] == pytest.approx(2.0 + 2.0)
    assert b["fees"] == pytest.approx(3.0 + 3.0)


def test_open_position_flagged_not_fabricated(conn):
    _setup(conn, [_fill("MES", "buy", 1, 5000.0, T.format(0))])
    (t,) = trades(conn)
    assert t["is_open"] == 1
    assert t["exit_ts"] is None
    assert t["avg_exit"] is None
    assert t["realized_pnl"] == 0.0


def test_accounts_and_symbols_never_mix(conn):
    a1 = dbmod.get_or_create_account(conn, "Acct1")
    a2 = dbmod.get_or_create_account(conn, "Acct2")
    ingest(conn, a1, "Acct1", "test", "test", [
        _fill("MES", "buy", 1, 5000.0, T.format(0)),
        _fill("MES", "sell", 1, 5010.0, T.format(1)),
    ])
    ingest(conn, a2, "Acct2", "test", "test", [
        _fill("MES", "buy", 1, 5000.0, T.format(0)),
        _fill("MES", "sell", 1, 5010.0, T.format(1)),
    ])
    reconstruction.rebuild(conn)
    rows = trades(conn)
    assert len(rows) == 2
    assert {r["account_id"] for r in rows} == {a1, a2}


def test_reimport_is_idempotent(conn):
    fills = [
        _fill("MES", "buy", 1, 5000.0, T.format(0), exec_id="e1"),
        _fill("MES", "sell", 1, 5010.0, T.format(1), exec_id="e2"),
    ]
    acct = dbmod.get_or_create_account(conn, "A")
    r1 = ingest(conn, acct, "A", "test", "test", fills)
    r2 = ingest(conn, acct, "A", "test", "test", fills)
    assert r1.rows_new == 2 and r2.rows_new == 0 and r2.rows_dup == 2
    reconstruction.rebuild(conn)
    assert len(trades(conn)) == 1


def test_content_dedupe_without_exec_ids(conn):
    fills = [_fill("MES", "buy", 1, 5000.0, T.format(0))]
    acct = dbmod.get_or_create_account(conn, "A")
    ingest(conn, acct, "A", "test", "test", fills)
    r2 = ingest(conn, acct, "A", "test", "test", fills)
    assert r2.rows_dup == 1


def test_unknown_instrument_reported_pnl_in_points(conn):
    _, report = _setup(conn, [
        _fill("ZZZT", "buy", 1, 10.0, T.format(0)),
        _fill("ZZZT", "sell", 1, 12.0, T.format(1)),
    ])
    assert "ZZZT" in report.unknown_instruments
    (t,) = trades(conn)
    assert t["realized_pnl"] == pytest.approx(2.0)  # points, pv=1 fallback


def test_rebuild_is_deterministic(conn):
    _setup(conn, [
        _fill("ES", "buy", 3, 6000.0, T.format(0)),
        _fill("ES", "sell", 1, 6005.0, T.format(1)),
        _fill("ES", "sell", 2, 6002.0, T.format(2)),
    ])
    first = [dict(r) for r in trades(conn)]
    reconstruction.rebuild(conn)
    second = [dict(r) for r in trades(conn)]
    for a, b in zip(first, second):
        a.pop("id"); b.pop("id")
    assert first == second
