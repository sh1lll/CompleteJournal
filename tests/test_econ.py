"""Economic calendar: imports, session placement, near-release questions."""
import json

import pytest

from completejournal import db as dbmod, econ, recap, reconstruction
from completejournal.importers.base import NormalizedExecution, ingest


@pytest.fixture()
def conn():
    c = dbmod.connect(":memory:")
    yield c
    c.close()


FF = json.dumps([
    {"title": "CPI m/m", "country": "USD", "date": "2026-10-09T08:30:00-04:00", "impact": "High",
     "forecast": "0.3%", "previous": "0.4%"},
    {"title": "Crude Oil Inventories", "country": "USD", "date": "2026-10-09T10:30:00-04:00", "impact": "Medium"},
    {"title": "Bank Holiday", "country": "JPY", "date": "2026-10-09T00:00:00-04:00", "impact": "Holiday"},
    {"title": "broken"},
])


def test_ff_json_import_idempotent(conn):
    r = econ.import_ff_json(conn, FF)
    assert r["added"] == 3 and len(r["skipped"]) == 1
    assert econ.import_ff_json(conn, FF)["added"] == 0
    ev = conn.execute("SELECT * FROM econ_events WHERE event='CPI m/m'").fetchone()
    assert ev["ts_utc"].startswith("2026-10-09T12:30:00") and ev["impact"] == "high"


def test_csv_import_with_am_pm_and_all_day(conn, tmp_path):
    f = tmp_path / "cal.csv"
    f.write_text("Date,Time,Currency,Impact,Event,Forecast,Previous\n"
                 "10/09/2026,8:30am,USD,High Impact Expected,Core CPI m/m,0.3%,0.3%\n"
                 "10/09/2026,All Day,USD,Low,Columbus Day prep,,\n"
                 ",,USD,High,missing date,,\n", encoding="utf-8")
    r = econ.import_csv(conn, f, tz="America/New_York")
    assert r["added"] == 2 and len(r["skipped"]) == 1
    cpi = conn.execute("SELECT * FROM econ_events WHERE event='Core CPI m/m'").fetchone()
    assert cpi["ts_utc"].startswith("2026-10-09T12:30:00") and cpi["impact"] == "high"
    assert conn.execute("SELECT all_day FROM econ_events WHERE event LIKE 'Columbus%'").fetchone()[0] == 1


def test_session_placement_and_trades_near_release(conn):
    econ.import_ff_json(conn, FF)
    a = dbmod.get_or_create_account(conn, "A")
    ingest(conn, a, "A", "test", "test", [
        NormalizedExecution("ES", "buy", 1, 6000.0, "2026-10-09T12:32:00.000Z"),   # 2 min after CPI
        NormalizedExecution("ES", "sell", 1, 6004.0, "2026-10-09T12:40:00.000Z"),
        NormalizedExecution("ES", "buy", 1, 6000.0, "2026-10-09T16:00:00.000Z"),   # quiet time
        NormalizedExecution("ES", "sell", 1, 5999.0, "2026-10-09T16:10:00.000Z"),
    ])
    reconstruction.rebuild(conn)
    evs = econ.for_session(conn, "2026-10-09", min_impact="medium")
    assert [e["event"] for e in evs] == ["CPI m/m", "Crude Oil Inventories"]
    near = econ.trades_near_events(conn, "2026-10-09")
    assert len(near) == 1 and near[0]["minutes_from_release"] == 2.0 and near[0]["event"] == "CPI m/m"
    split = econ.near_vs_away(conn)
    assert split["near_high_impact"]["n"] == 1 and split["away"]["n"] == 1
    r = recap.daily(conn, "2026-10-09")
    assert any("CPI m/m" in l for l in r["lines"])
    assert any("entered 2 min after CPI m/m" in l for l in r["lines"])
    assert any("around CPI m/m" in q for q in r["questions"])


def test_manual_and_feed_failure(conn):
    eid = econ.add_manual(conn, when="2026-10-29 14:00", event="FOMC Statement", tz="America/New_York")
    assert conn.execute("SELECT ts_utc FROM econ_events WHERE id=?", (eid,)).fetchone()[0].startswith("2026-10-29T18:00")
    with pytest.raises(ValueError):
        econ.add_manual(conn, when="2026-10-29 14:00", event="  ")

    def boom():
        raise OSError("offline")
    r = econ.fetch_feed(conn, fetch=boom)
    assert r["added"] == 0 and "import a file instead" in r["error"]
    assert econ.fetch_feed(conn, fetch=lambda: FF.encode())["added"] == 3
