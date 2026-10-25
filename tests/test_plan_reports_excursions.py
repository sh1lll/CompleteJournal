"""Plan-vs-actual rules, weekly/monthly reports, MAE/MFE."""
import pytest

from completejournal import bars, db as dbmod, excursions, journal, plan, reconstruction, reports
from completejournal.importers.base import NormalizedExecution, ingest
from completejournal.sessions import SessionPolicy


@pytest.fixture()
def conn():
    c = dbmod.connect(":memory:")
    yield c
    c.close()


def _trip(fills, sym, qty, side, p_in, p_out, t_in, t_out):
    other = "sell" if side == "buy" else "buy"
    fills.append(NormalizedExecution(sym, side, qty, p_in, t_in))
    fills.append(NormalizedExecution(sym, other, qty, p_out, t_out))


def _load(conn, fills):
    a = dbmod.get_or_create_account(conn, "A")
    ingest(conn, a, "A", "test", "test", fills)
    reconstruction.rebuild(conn)


# 13:30Z = 08:30 CT on 2026-10-09 (CDT, UTC-5)
D = "2026-10-09"


def test_parse_rules_free_text_tolerant():
    r = plan.parse_rules("Bias long above ONH.\n- Instruments: @MES, NQ\nMax trades: 3\n"
                         "Daily stop: $200\nMax size: 2\nTrading window: 8:30 - 11:00\nStop after 2 losses")
    assert r == {"instruments": ["MES", "NQ"], "max_trades": 3, "max_loss": 200.0,
                 "max_contracts": 2, "window": ("08:30", "11:00"), "stop_after_losses": 2}
    assert plan.parse_rules("Just thoughts, no rules at all.") == {}


def test_plan_vs_actual_flags_each_broken_rule(conn):
    f = []
    _trip(f, "MES", 1, "buy", 5000, 4990, f"{D}T13:35:00.000Z", f"{D}T13:40:00.000Z")   # -50 loss
    _trip(f, "MES", 1, "buy", 5000, 4990, f"{D}T13:45:00.000Z", f"{D}T13:50:00.000Z")   # -50 loss
    _trip(f, "MES", 3, "buy", 5000, 5004, f"{D}T14:00:00.000Z", f"{D}T14:05:00.000Z")   # after 2 losses, size 3
    _trip(f, "CL", 1, "sell", 70.0, 70.5, f"{D}T17:30:00.000Z", f"{D}T17:40:00.000Z")   # 12:30 CT, wrong mkt, -500
    _load(conn, f)
    journal.create_entry(conn, "Plan.\nInstruments: MES\nMax trades: 3\nMax loss: 400\n"
                         "Max contracts: 2\nTrading window: 08:30-11:00\nStop after: 2 losses",
                         kind="pre-market", about_date=D)
    r = plan.plan_vs_actual(conn, D)
    by = {x["rule"].split(":")[0].split(" (")[0]: x for x in r["results"]}
    assert by["Instruments"]["kept"] is False
    assert by["Max trades"]["kept"] is False            # 4 trades
    assert by["Max contracts"]["kept"] is False         # size 3
    assert by["Trading window"]["kept"] is False        # 12:30 CT
    assert by["Stop after 2 losses"]["kept"] is False
    assert by["Max loss"]["kept"] is True               # limit hit only on the last trade
    assert r["broken"] == 5 and r["kept"] == 1


def test_plan_vs_actual_without_plan_or_rules(conn):
    assert plan.plan_vs_actual(conn, D)["note"] == "no pre-market plan written for this session"
    journal.create_entry(conn, "Feeling patient today.", kind="pre-market", about_date=D)
    r = plan.plan_vs_actual(conn, D)
    assert r["plan"] is not None and r["results"] == [] and r["note"] is None


def test_mae_mfe_from_bars(conn):
    f = []
    _trip(f, "MES", 1, "buy", 5000.0, 5004.0, f"{D}T13:30:20.000Z", f"{D}T13:33:00.000Z")
    _load(conn, f)
    bars.store_bars(conn, "MES", "1m", [
        {"ts_utc": f"{D}T13:30:00.000Z", "open": 5000, "high": 5001, "low": 4997, "close": 4999},
        {"ts_utc": f"{D}T13:31:00.000Z", "open": 4999, "high": 5008, "low": 4998, "close": 5006},
        {"ts_utc": f"{D}T13:32:00.000Z", "open": 5006, "high": 5007, "low": 5003, "close": 5004},
        {"ts_utc": f"{D}T13:40:00.000Z", "open": 5004, "high": 5050, "low": 4900, "close": 5004},  # after exit
    ], "csv")
    tid = conn.execute("SELECT id FROM trades").fetchone()[0]
    e = excursions.trade_excursion(conn, tid)
    assert e["mae_points"] == 3.0 and e["mfe_points"] == 8.0      # bar after exit ignored
    assert e["mae_per_contract"] == 15.0 and e["mfe_per_contract"] == 40.0
    assert e["capture_ratio"] == 0.5 and e["approximate"] is True


def test_mae_mfe_absent_without_bars(conn):
    f = []
    _trip(f, "ES", 1, "sell", 6000, 5990, f"{D}T13:30:00.000Z", f"{D}T13:40:00.000Z")
    _load(conn, f)
    tid = conn.execute("SELECT id FROM trades").fetchone()[0]
    assert excursions.trade_excursion(conn, tid) is None
    assert excursions.summary(conn)["trades_with_bars"] == 0


def test_weekly_and_monthly_reports(conn):
    f = []
    _trip(f, "MES", 1, "buy", 5000, 5010, "2026-10-06T13:30:00.000Z", "2026-10-06T13:40:00.000Z")  # Tue +50
    _trip(f, "MES", 1, "buy", 5000, 4995, "2026-10-08T13:30:00.000Z", "2026-10-08T13:40:00.000Z")  # Thu -25
    _trip(f, "MES", 1, "buy", 5000, 5002, "2026-10-14T13:30:00.000Z", "2026-10-14T13:40:00.000Z")  # next week
    _load(conn, f)
    journal.create_entry(conn, "Tuesday review: patient.", kind="end-of-day", about_date="2026-10-06")
    assert reports.period_bounds("week", "2026-10-08") == ("2026-10-05", "2026-10-11")
    assert reports.period_bounds("month", "2026-10-08") == ("2026-10-01", "2026-10-31")
    assert reports.period_bounds("month", "2026-12-15") == ("2026-12-01", "2026-12-31")
    wk = reports.build(conn, "week", "2026-10-08")
    assert wk["stats"]["n"] == 2 and wk["stats"]["net_pnl"] == pytest.approx(25.0)
    assert [d["date"] for d in wk["days"]] == ["2026-10-06", "2026-10-08"]
    assert len(wk["entries"]) == 1 and wk["best"][0]["net_pnl"] == pytest.approx(50.0)
    mo = reports.build(conn, "month", "2026-10-08")
    assert mo["stats"]["n"] == 3
    md = reports.to_markdown(wk)
    assert "# Week review: 2026-10-05 → 2026-10-11" in md and "[entry:" in md and "## Reflection" in md


def test_session_policy_window_uses_session_tz():
    p = SessionPolicy()
    assert plan._local_hhmm("2026-10-09T13:30:00.000Z", p) == "08:30"
