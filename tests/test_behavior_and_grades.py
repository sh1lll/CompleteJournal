"""Tests for behavioral flags and process-vs-outcome grading."""
import pytest

from completejournal import analytics, behavior, db as dbmod, reconstruction
from completejournal.importers.base import NormalizedExecution, ingest


@pytest.fixture()
def conn():
    c = dbmod.connect(":memory:")
    yield c
    c.close()


def _round_trip(fills, symbol, qty, entry_px, exit_px, t_in, t_out):
    fills.append(NormalizedExecution(symbol, "buy", qty, entry_px, t_in))
    fills.append(NormalizedExecution(symbol, "sell", qty, exit_px, t_out))


def _ingest(conn, fills, account="A"):
    acct = dbmod.get_or_create_account(conn, account)
    ingest(conn, acct, account, "test", "test", fills)
    reconstruction.rebuild(conn)


def test_revenge_reentry_flagged_only_after_loss(conn):
    fills = []
    # losing trade exits 13:40, re-entry 13:42 (2 min) -> flag
    _round_trip(fills, "MES", 1, 5000, 4990, "2026-10-09T13:30:00.000Z", "2026-10-09T13:40:00.000Z")
    _round_trip(fills, "MES", 1, 4991, 4995, "2026-10-09T13:42:00.000Z", "2026-10-09T13:50:00.000Z")
    # winning trade exits 14:00, fast re-entry 14:01 -> NOT a flag
    _round_trip(fills, "MES", 1, 4996, 5002, "2026-10-09T13:55:00.000Z", "2026-10-09T14:00:00.000Z")
    _round_trip(fills, "MES", 1, 5003, 5004, "2026-10-09T14:01:00.000Z", "2026-10-09T14:10:00.000Z")
    _ingest(conn, fills)
    flags = behavior.revenge_reentries(conn)
    assert len(flags) == 1
    assert flags[0].kind == "revenge-reentry" and len(flags[0].trade_ids) == 2


def test_size_escalation_after_loss(conn):
    fills = []
    _round_trip(fills, "MES", 2, 5000, 4990, "2026-10-09T13:30:00.000Z", "2026-10-09T13:40:00.000Z")
    _round_trip(fills, "MES", 4, 4991, 4992, "2026-10-09T14:30:00.000Z", "2026-10-09T14:40:00.000Z")
    _ingest(conn, fills)
    flags = behavior.size_escalation_after_loss(conn)
    assert len(flags) == 1 and "2→4" in flags[0].detail


def test_overtrading_needs_baseline(conn):
    fills = []
    # 3 days of 1 trade each — below min_baseline_days(5): silent
    for d in (6, 7, 8):
        _round_trip(fills, "MES", 1, 5000, 5001,
                    f"2026-10-0{d}T13:30:00.000Z", f"2026-10-0{d}T13:40:00.000Z")
    _ingest(conn, fills)
    assert behavior.overtrading_days(conn) == []


def test_overtrading_flagged_with_baseline(conn):
    fills = []
    for d in range(1, 6):  # 5 baseline days, 1 trade each
        _round_trip(fills, "MES", 1, 5000, 5001,
                    f"2026-10-0{d}T13:30:00.000Z", f"2026-10-0{d}T13:40:00.000Z")
    for i in range(4):     # day 6: 4 trades (>= 2x median of 1)
        _round_trip(fills, "MES", 1, 5000, 5001,
                    f"2026-10-06T1{4+i}:00:00.000Z", f"2026-10-06T1{4+i}:30:00.000Z")
    _ingest(conn, fills)
    flags = behavior.overtrading_days(conn)
    assert len(flags) == 1 and flags[0].date == "2026-10-06" and len(flags[0].trade_ids) == 4


def test_streak_performance_counts(conn):
    fills = []
    seq = [(-5, "01"), (-5, "02"), (10, "03"), (10, "04"), (10, "05"), (-5, "06")]
    for pts, d in seq:
        _round_trip(fills, "XX", 1, 100, 100 + pts,
                    f"2026-10-{d}T13:30:00.000Z", f"2026-10-{d}T13:40:00.000Z")
    _ingest(conn, fills)
    st = behavior.streak_performance(conn, k=2)
    assert st["after_k_losses"]["n"] == 1   # trade 3 came after 2 losses
    assert st["after_k_wins"]["n"] == 2     # trades 5 and 6 after 2+ wins
    assert st["overall"]["n"] == 6


def test_grades_survive_rebuild_and_quadrant(conn):
    fills = []
    _round_trip(fills, "MES", 1, 5000, 5010, "2026-10-09T13:30:00.000Z", "2026-10-09T13:40:00.000Z")  # win
    _round_trip(fills, "MES", 1, 5000, 4990, "2026-10-09T14:30:00.000Z", "2026-10-09T14:40:00.000Z")  # loss
    _ingest(conn, fills)
    t1, t2 = [r["id"] for r in conn.execute("SELECT id FROM trades ORDER BY entry_ts")]
    analytics.set_grade(conn, t1, "F", "chased, no plan")   # bad decision that WON
    analytics.set_grade(conn, t2, "A", "perfect setup")      # good decision that LOST

    pvo = analytics.process_vs_outcome(conn)
    assert pvo["bad_process_won"]["n"] == 1
    assert pvo["good_process_lost"]["n"] == 1
    assert pvo["ungraded_or_c"] == 0

    # rebuild regenerates trade ids — grades must survive via the fingerprint
    reconstruction.rebuild(conn)
    pvo2 = analytics.process_vs_outcome(conn)
    assert pvo2["bad_process_won"]["n"] == 1 and pvo2["good_process_lost"]["n"] == 1
    new_t1 = conn.execute("SELECT id FROM trades ORDER BY entry_ts").fetchone()["id"]
    assert analytics.get_grade(conn, new_t1)["grade"] == "F"


def test_invalid_grade_rejected(conn):
    fills = []
    _round_trip(fills, "MES", 1, 5000, 5010, "2026-10-09T13:30:00.000Z", "2026-10-09T13:40:00.000Z")
    _ingest(conn, fills)
    tid = conn.execute("SELECT id FROM trades").fetchone()["id"]
    with pytest.raises(ValueError):
        analytics.set_grade(conn, tid, "E")
    with pytest.raises(KeyError):
        analytics.set_grade(conn, 999, "A")
