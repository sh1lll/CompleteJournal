"""No-AI features: similarity search and data-built daily recap."""
import pytest

from completejournal import db as dbmod, journal, reconstruction, recap, similar
from completejournal.importers.base import NormalizedExecution, ingest


@pytest.fixture()
def conn():
    c = dbmod.connect(":memory:")
    yield c
    c.close()


def test_similar_finds_related_entries_and_explains_why(conn):
    a = journal.create_entry(conn, "Chased a failed breakout on @MES after CPI. Classic FOMO entry.")
    journal.create_entry(conn, "Quiet range day, followed the plan, no trades taken.")
    c = journal.create_entry(conn, "Another failed breakout chase on @MES — same FOMO pattern.")
    journal.create_entry(conn, "Read a book on risk management and position sizing.")
    hits = similar.find_similar(conn, entry_id=c)
    assert hits[0]["id"] == a
    assert any("@mes" in w or "breakout" in w or "fomo" in w for w in hits[0]["why"])
    assert all(h["id"] != c for h in hits)            # never matches itself


def test_similar_from_draft_text(conn):
    target = journal.create_entry(conn, "Overtraded after the open drive failed; revenge trades.")
    journal.create_entry(conn, "Wrote out my weekly goals.")
    hits = similar.find_similar(conn, text="feels like revenge trading after a failed open drive")
    assert hits and hits[0]["id"] == target


def test_similar_empty_and_unknown(conn):
    assert similar.find_similar(conn, text="anything") == []
    journal.create_entry(conn, "x")
    with pytest.raises(KeyError):
        similar.find_similar(conn, entry_id=999)


def _day(conn):
    a = dbmod.get_or_create_account(conn, "A")
    ingest(conn, a, "A", "test", "test", [
        NormalizedExecution("MES", "buy", 1, 5000.0, "2026-10-09T13:30:00.000Z"),
        NormalizedExecution("MES", "sell", 1, 4990.0, "2026-10-09T13:40:00.000Z"),   # -50
        NormalizedExecution("MES", "buy", 2, 4991.0, "2026-10-09T13:41:00.000Z"),    # revenge + size up
        NormalizedExecution("MES", "sell", 2, 4995.0, "2026-10-09T13:50:00.000Z"),   # +40
    ])
    reconstruction.rebuild(conn)


def test_recap_cites_sources_and_asks_questions(conn):
    _day(conn)
    pid = journal.create_entry(conn, "Plan\nMax trades: 1", kind="pre-market", about_date="2026-10-09")
    r = recap.daily(conn, "2026-10-09")
    text = "\n".join(r["lines"])
    assert "2 closed trades in MES: net -$10.00" in text
    assert f"[entry:{pid}]" in text and "1 broken" in text
    assert "revenge-reentry" in text and "size-escalation" in text
    assert "trade:1" in r["citations"] and f"entry:{pid}" in r["citations"]
    assert any("end-of-day" in q for q in r["questions"])
    assert any("Max trades: 1" in q for q in r["questions"])
    assert r["source"].endswith("(no AI)")


def test_recap_empty_day(conn):
    r = recap.daily(conn, "2026-01-02")
    assert r["lines"][0] == "No trades recorded for this session."
    assert "No pre-market plan" in r["lines"][1]


def test_why_shows_written_words_not_stems(conn):
    journal.create_entry(conn, "Too many trades after the losing streak.")
    hits = similar.find_similar(conn, text="took trades during a losing streak")
    assert hits and any(w in ("trades", "losing", "streak", "losing streak") for w in hits[0]["why"])
    assert "trad" not in hits[0]["why"]


def test_ordinal_in_plan_detail():
    from completejournal.plan import _ordinal
    assert [_ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22)] == \
        ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd"]
