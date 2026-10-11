"""Tests for the journal store (provenance invariants) and analytics honesty."""
import pytest

from completejournal import analytics, db as dbmod, journal, reconstruction
from completejournal.importers.base import NormalizedExecution, ingest


@pytest.fixture()
def conn():
    c = dbmod.connect(":memory:")
    yield c
    c.close()


def test_entry_versioning_preserves_originals(conn):
    eid = journal.create_entry(conn, "Original thought: NQ looks heavy.", kind="market-thought")
    journal.edit_entry(conn, eid, "Original thought: NQ looks heavy. EDIT: it bounced.")
    vs = journal.versions(conn, eid)
    assert len(vs) == 2
    assert vs[0]["body_md"] == "Original thought: NQ looks heavy."
    # current body is the edit; version 1 untouched
    row = conn.execute("SELECT body_md FROM entries WHERE id=?", (eid,)).fetchone()
    assert "EDIT" in row["body_md"]


def test_addenda_are_separate_records(conn):
    eid = journal.create_entry(conn, "Pre-market: expecting range day.", kind="pre-market")
    journal.add_addendum(conn, eid, "Looking back a week later: it trended all day.")
    adds = conn.execute("SELECT * FROM entry_addenda WHERE entry_id=?", (eid,)).fetchall()
    assert len(adds) == 1
    # original untouched
    assert conn.execute("SELECT body_md FROM entries WHERE id=?", (eid,)).fetchone()[0] \
        == "Pre-market: expecting range day."


def test_ai_cannot_author_entries(conn):
    with pytest.raises(ValueError):
        journal.create_entry(conn, "AI summary", author="ai")
    # ai content goes to ai_artifacts
    conn.execute(
        "INSERT INTO ai_artifacts(kind, model, content_md, sources) VALUES (?,?,?,?)",
        ("daily-digest", "claude-test", "Summary …", '["entry:1"]'),
    )


def test_soft_delete_never_destroys(conn):
    eid = journal.create_entry(conn, "oops")
    journal.soft_delete(conn, eid)
    row = conn.execute("SELECT * FROM entries WHERE id=?", (eid,)).fetchone()
    assert row is not None and row["deleted_at"] is not None


def test_bidirectional_links_and_blank_kind(conn):
    eid = journal.create_entry(conn, "Thesis: breakout over ONH if CPI is tame.")
    journal.link(conn, eid, "session", "2026-10-09")
    journal.link(conn, eid, "instrument", "NQ")
    found = journal.entries_for_target(conn, "instrument", "NQ")
    assert [r["id"] for r in found] == [eid]
    # kind is optional — a blank entry is valid
    assert conn.execute("SELECT kind FROM entries WHERE id=?", (eid,)).fetchone()[0] is None


def test_fts_search_with_snippets(conn):
    journal.create_entry(conn, "Chased the failed breakout again. Classic mistake.")
    journal.create_entry(conn, "Patient day, followed the plan.")
    hits = journal.search(conn, "breakout")
    assert len(hits) == 1
    assert "<mark>" in hits[0]["snippet"]
    journal.edit_entry(conn, hits[0]["id"], "Edited: no breakout talk anymore.")
    assert journal.search(conn, "chased") == []


def test_session_timeline_combines_entries_and_trades(conn):
    acct = dbmod.get_or_create_account(conn, "A")
    ingest(conn, acct, "A", "test", "test", [
        NormalizedExecution("MES", "buy", 1, 5000.0, "2026-10-09T13:30:00.000Z"),
        NormalizedExecution("MES", "sell", 1, 5010.0, "2026-10-09T14:00:00.000Z"),
    ])
    reconstruction.rebuild(conn)
    journal.create_entry(conn, "EOD: clean execution.", kind="end-of-day", about_date="2026-10-09")
    tl = journal.session_timeline(conn, "2026-10-09")
    assert len(tl["trades"]) == 1 and len(tl["entries"]) == 1


def test_analytics_sample_size_honesty(conn):
    acct = dbmod.get_or_create_account(conn, "A")
    fills = []
    base = "2026-10-09T13:{:02d}:00.000Z"
    for i in range(3):
        fills.append(NormalizedExecution("MES", "buy", 1, 5000.0, base.format(2 * i), fees=0.5))
        px = 5010.0 if i < 2 else 4995.0
        fills.append(NormalizedExecution("MES", "sell", 1, px, base.format(2 * i + 1), fees=0.5))
    ingest(conn, acct, "A", "test", "test", fills)
    reconstruction.rebuild(conn)
    s = analytics.overall(conn)
    assert s.n == 3 and s.wins == 2 and s.losses == 1
    assert s.low_sample is True
    assert any("noise" in n for n in s.notes)
    assert s.net_pnl == pytest.approx(2 * 49 + (-25 - 1))  # 2 wins of +50-1, 1 loss of -25-1
    by_sym = analytics.breakdown(conn, "symbol")
    assert "MES" in by_sym and by_sym["MES"]["n"] == 3
    curve = analytics.equity_curve(conn)
    assert len(curve) == 3 and curve[-1]["equity"] == pytest.approx(s.net_pnl)


def test_reconciliation_report(conn):
    acct = dbmod.get_or_create_account(conn, "A")
    ingest(conn, acct, "A", "test", "test", [
        NormalizedExecution("MES", "buy", 1, 5000.0, "2026-10-09T13:30:00.000Z", fees=0.5),
        NormalizedExecution("MES", "sell", 1, 5010.0, "2026-10-09T14:00:00.000Z", fees=0.5),
    ])
    reconstruction.rebuild(conn)
    rep = analytics.reconciliation(conn)
    assert rep[0]["net_pnl"] == pytest.approx(49.0)
    assert rep[0]["executions"] == 2
