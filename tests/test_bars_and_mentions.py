"""Tests for price bars (storage, CSV import, trade windows) and mentions."""
import pytest

from completejournal import bars, db as dbmod, journal, reconstruction
from completejournal.importers.base import NormalizedExecution, ingest


@pytest.fixture()
def conn():
    c = dbmod.connect(":memory:")
    yield c
    c.close()


def _mk_bars(start_min, count):
    return [{
        "ts_utc": f"2026-10-09T13:{m:02d}:00.000Z",
        "open": 5000 + m, "high": 5002 + m, "low": 4999 + m, "close": 5001 + m,
        "volume": 100,
    } for m in range(start_min, start_min + count)]


def test_store_and_window(conn):
    assert bars.store_bars(conn, "mes", "1m", _mk_bars(0, 50), "csv") == 50
    # idempotent
    assert bars.store_bars(conn, "MES", "1m", _mk_bars(0, 50), "csv") == 0
    w = bars.bars_around(conn, "MES", "2026-10-09T13:20:00.000Z", "2026-10-09T13:25:00.000Z",
                         pad_minutes=5)
    assert w["resolution"] == "1m" and w["reconstructed"] is True
    assert len(w["bars"]) == 16  # 13:15..13:30 inclusive
    empty = bars.bars_around(conn, "NQ", "2026-10-09T13:20:00.000Z", None)
    assert empty["bars"] == [] and empty["resolution"] is None


def test_ohlc_consistency_rejected(conn):
    with pytest.raises(ValueError, match="inconsistent"):
        bars.store_bars(conn, "ES", "1m", [{
            "ts_utc": "2026-10-09T13:00:00.000Z",
            "open": 10, "high": 5, "low": 1, "close": 3}], "csv")


def test_bars_csv_import(conn, tmp_path):
    f = tmp_path / "bars.csv"
    f.write_text("Time,Open,High,Low,Close,Volume\n"
                 "2026-10-09 08:30:00,5000,5002,4999,5001,120\n"
                 "2026-10-09 08:31:00,5001,5003,5000,5002,98\n", encoding="utf-8")
    n = bars.import_bars_csv(conn, f, "MES", "1m", tz_offset_minutes=-300)
    assert n == 2
    row = conn.execute("SELECT ts_utc FROM bars ORDER BY ts_utc LIMIT 1").fetchone()
    assert row["ts_utc"].startswith("2026-10-09T13:30:00")  # CT -> UTC


def _trade(conn):
    acct = dbmod.get_or_create_account(conn, "A")
    ingest(conn, acct, "A", "test", "test", [
        NormalizedExecution("MES", "buy", 1, 5000.0, "2026-10-09T13:30:00.000Z"),
        NormalizedExecution("MES", "sell", 1, 5010.0, "2026-10-09T13:40:00.000Z"),
    ])
    reconstruction.rebuild(conn)
    return conn.execute("SELECT id FROM trades").fetchone()["id"]


def test_mentions_parse_and_autolink(conn):
    tid = _trade(conn)
    body = (f"Long @MES off the open (see @trade:{tid}); same idea as @2026-10-01. "
            f"@FAKE should be ignored, email a@b.com too.")
    eid = journal.create_entry(conn, body, kind="trade-review")
    links = {(r["target_type"], r["target_id"]) for r in
             conn.execute("SELECT target_type, target_id FROM links WHERE entry_id=?", (eid,))}
    assert ("instrument", "MES") in links
    assert ("trade", str(tid)) in links
    assert ("session", "2026-10-01") in links
    assert not any(t == ("instrument", "FAKE") for t in links)
    assert not any(t[1] == "B" for t in links)  # email not a mention

    # entry appears in the trade's linked entries
    found = journal.entries_for_target(conn, "trade", str(tid))
    assert [r["id"] for r in found] == [eid]

    # editing adds new mentions, keeps old links
    journal.edit_entry(conn, eid, f"Rewritten: now about @NQ only.")
    links2 = {(r["target_type"], r["target_id"]) for r in
              conn.execute("SELECT target_type, target_id FROM links WHERE entry_id=?", (eid,))}
    assert ("instrument", "NQ") in links2 and ("instrument", "MES") in links2


def test_mention_of_nonexistent_trade_ignored(conn):
    eid = journal.create_entry(conn, "ref @trade:999 does not exist")
    assert conn.execute("SELECT COUNT(*) FROM links WHERE entry_id=?", (eid,)).fetchone()[0] == 0


def test_mention_candidates(conn):
    tid = _trade(conn)
    out = journal.mention_candidates(conn, "ME")
    assert any(c["token"] == "@MES" for c in out)
    out2 = journal.mention_candidates(conn, str(tid))
    assert any(c["token"] == f"@trade:{tid}" for c in out2)
    out3 = journal.mention_candidates(conn, "2026")
    assert any(c["type"] == "session" for c in out3)
