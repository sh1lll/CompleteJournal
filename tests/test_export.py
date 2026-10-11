"""Export tests — the J9 data-ownership guarantee."""
import json

import pytest

from completejournal import db as dbmod, export, journal, reconstruction
from completejournal.importers.base import NormalizedExecution, ingest


@pytest.fixture()
def conn():
    c = dbmod.connect(":memory:")
    yield c
    c.close()


def _populate(conn):
    acct = dbmod.get_or_create_account(conn, "A")
    ingest(conn, acct, "A", "test", "test", [
        NormalizedExecution("MES", "buy", 1, 5000.0, "2026-10-09T13:30:00.000Z", fees=0.5),
        NormalizedExecution("MES", "sell", 1, 5010.0, "2026-10-09T14:00:00.000Z", fees=0.5),
    ])
    reconstruction.rebuild(conn)
    eid = journal.create_entry(conn, "Clean long off the open.", kind="trade-review",
                               title="MES open drive", about_date="2026-10-09")
    journal.link(conn, eid, "trade", "1")
    journal.tag(conn, eid, "setup/open-drive")
    journal.add_addendum(conn, eid, "Still my best setup a month later.")
    journal.edit_entry(conn, eid, "Clean long off the open. (clarified)")
    return eid


def test_markdown_mirror(conn, tmp_path):
    _populate(conn)
    n = export.export_markdown(conn, tmp_path)
    assert n == 1
    (f,) = list(tmp_path.glob("*.md"))
    text = f.read_text(encoding="utf-8")
    assert f.name.startswith("2026-10-09-0001-")
    assert '"trade:1"' in text and "setup/open-drive" in text
    assert "# MES open drive" in text
    assert "Addendum" in text and "best setup" in text
    assert "versions: 2" in text
    assert "(clarified)" in text  # current body exported; versions counted


def test_full_export_round_trippable(conn, tmp_path):
    _populate(conn)
    counts = export.export_full(conn, tmp_path)
    assert counts["executions"] == 2 and counts["trades"] == 1
    assert counts["entries"] == 1 and counts["entry_versions"] == 2
    assert counts["markdown_entries"] == 1
    # executions CSV carries raw payloads + account names
    head = (tmp_path / "executions.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "raw_payload" in head and "account_name" in head
    entries = json.loads((tmp_path / "entries.json").read_text(encoding="utf-8"))
    assert entries[0]["author"] == "trader"
    versions = json.loads((tmp_path / "entry_versions.json").read_text(encoding="utf-8"))
    assert versions[0]["body_md"] == "Clean long off the open."
