"""Demo data must be clearly separated and removable without touching real data."""
import pytest

from completejournal import db as dbmod, demo, journal
from completejournal.importers.base import NormalizedExecution, ingest
from completejournal.reconstruction import rebuild


@pytest.fixture()
def conn():
    c = dbmod.connect(":memory:")
    yield c
    c.close()


def test_seed_and_remove_leaves_real_data_intact(conn):
    real = dbmod.get_or_create_account(conn, "Real")
    ingest(conn, real, "Real", "test", "test", [
        NormalizedExecution("ES", "buy", 1, 6000.0, "2026-10-09T13:30:00.000Z"),
        NormalizedExecution("ES", "sell", 1, 6004.0, "2026-10-09T13:40:00.000Z"),
    ])
    rebuild(conn)
    real_entry = journal.create_entry(conn, "My real thought about @ES")

    r = demo.seed(conn)
    assert r["seeded"] and r["trades_total"] > 5 and r["entries"] == 11
    demo_id = conn.execute("SELECT id FROM accounts WHERE name=?", (demo.DEMO_ACCOUNT,)).fetchone()[0]
    assert r["trades_total"] == conn.execute("SELECT COUNT(*) FROM trades WHERE account_id=?", (demo_id,)).fetchone()[0]
    assert demo.seed(conn)["seeded"] is False          # idempotent
    assert journal.search(conn, "demo")                # demo entries searchable

    removed = demo.remove_demo(conn)
    assert removed["entries"] == 11 and removed["trades"] > 0
    assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 0
    assert [e["id"] for e in conn.execute("SELECT id FROM entries")] == [real_entry]
    assert journal.search(conn, "demo") == []          # FTS index cleaned too
    assert journal.search(conn, "real")[0]["id"] == real_entry
