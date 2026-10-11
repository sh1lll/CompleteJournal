"""Tags, links/backlinks, and thesis threads."""
import pytest
from fastapi.testclient import TestClient

from completejournal import db as dbmod, journal, reconstruction, theses
from completejournal.api import create_app
from completejournal.importers.base import NormalizedExecution, ingest


@pytest.fixture()
def conn():
    c = dbmod.connect(":memory:")
    yield c
    c.close()


def test_tag_normalization_and_removal(conn):
    eid = journal.create_entry(conn, "x")
    assert journal.tag(conn, eid, "Mistake/ Chased Entry", "#FOMO") == ["mistake/chased-entry", "fomo"]
    with pytest.raises(ValueError):
        journal.tag(conn, eid, "   ")
    journal.untag(conn, eid, "fomo")
    assert journal.tags_of(conn, eid) == ["mistake/chased-entry"]
    assert journal.all_tags(conn) == [{"tag": "mistake/chased-entry", "n": 1}]


def test_backlinks_and_described_links(conn):
    a = journal.create_entry(conn, "Thesis: NQ fails at ONH", title="ONH fade")
    b = journal.create_entry(conn, f"Update on @entry:{a}: rejected twice on @NQ")
    assert [x["id"] for x in journal.backlinks(conn, a)] == [b]
    labels = [l["label"] for l in journal.describe_links(conn, b)]
    assert f"entry #{a}: ONH fade" in labels and "@NQ" in labels
    journal.unlink(conn, b, "instrument", "NQ")
    assert "@NQ" not in [l["label"] for l in journal.describe_links(conn, b)]


def _trade(conn, start, px_in, px_out):
    acct = dbmod.get_or_create_account(conn, "A")
    ingest(conn, acct, "A", "test", "test", [
        NormalizedExecution("NQ", "sell", 1, px_in, f"{start}:00.000Z"),
        NormalizedExecution("NQ", "buy", 1, px_out, f"{start}:59.000Z"),
    ])
    reconstruction.rebuild(conn)
    return conn.execute("SELECT id FROM trades ORDER BY entry_ts DESC").fetchone()[0]


def test_thesis_thread_assembles_from_ordinary_links(conn):
    th = journal.create_entry(conn, "NQ should fail at the overnight high today.", kind="pre-market",
                              title="ONH fade", about_date="2026-10-09",
                              written_at="2026-10-09T13:00:00.000Z")   # written before the open
    journal.tag(conn, th, "thesis")
    t1 = _trade(conn, "2026-10-09T13:45", 21500.0, 21490.0)     # +10 pts short
    upd = journal.create_entry(conn, f"Rejected at ONH as planned (@entry:{th}), shorted @trade:{t1}.",
                               kind="intraday", about_date="2026-10-09",
                               written_at="2026-10-09T14:05:00.000Z")
    journal.create_entry(conn, "Unrelated knowledge note on sizing.")
    journal.add_addendum(conn, th, "A week later: this pattern held on 3 of 4 days.")

    thr = theses.thread(conn, th)
    assert [e["id"] for e in thr["entries"]] == [th, upd]          # unrelated note excluded
    assert [t["id"] for t in thr["trades"]] == [t1]
    assert thr["net_pnl"] == pytest.approx(200.0)                  # 10 pts x $20
    assert thr["status"] == "open"
    types = [x["type"] for x in thr["timeline"]]
    assert types.count("trade") == 1 and "addendum" in types and types[0] == "thesis"

    theses.set_status(conn, th, "confirmed")
    assert theses.thread(conn, th)["status"] == "confirmed"
    theses.set_status(conn, th, "invalidated")
    assert journal.tags_of(conn, th).count("outcome/invalidated") == 1
    assert "outcome/confirmed" not in journal.tags_of(conn, th)
    with pytest.raises(ValueError):
        theses.set_status(conn, th, "maybe")
    lst = theses.list_theses(conn)
    assert lst[0]["id"] == th and lst[0]["trades"] == 1 and lst[0]["status"] == "invalidated"


def test_journal_tools_api(tmp_path):
    c = TestClient(create_app(tmp_path / "t.db"))
    eid = c.post("/api/entries", json={"body_md": "First version"}).json()["id"]
    assert c.post(f"/api/entries/{eid}/tags", json={"tag": "Psychology/Patience"}).json()["tags"] == ["psychology/patience"]
    assert c.post(f"/api/entries/{eid}/tags", json={"tag": "!!!"}).status_code == 400
    assert c.delete(f"/api/entries/{eid}/tags/psychology/patience").json()["tags"] == []
    c.put(f"/api/entries/{eid}", json={"body_md": "Second version"})
    c.post(f"/api/entries/{eid}/addenda", json={"body_md": "Later insight"})
    full = c.get(f"/api/entries/{eid}").json()
    assert full["n_versions"] == 2 and full["addenda"][0]["body_md"] == "Later insight"
    vers = c.get(f"/api/entries/{eid}/versions").json()
    assert [v["body_md"] for v in vers] == ["First version", "Second version"]
    c.post(f"/api/entries/{eid}/tags", json={"tag": "thesis"})
    assert c.get("/api/theses").json()[0]["id"] == eid
    assert c.post(f"/api/theses/{eid}/status", json={"status": "mixed"}).json()["status"] == "mixed"
    assert c.get("/api/theses/9999").status_code == 404
