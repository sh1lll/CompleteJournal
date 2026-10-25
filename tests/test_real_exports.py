"""Validation against REAL platform export layouts (tests/fixtures/real).

Every expected P&L here is either the platform's own reported figure or
hand-computed from contract specs — so passing means our parsing +
reconstruction agree with the platform, not just with ourselves.
"""
from pathlib import Path

import pytest

from completejournal import db as dbmod
from completejournal.importers import auto
from completejournal.importers.parsing import (
    parse_datetime, parse_instrument, parse_number, parse_side, read_table,
)
from completejournal.sessions import SessionPolicy

REAL = Path(__file__).parent / "fixtures" / "real"


@pytest.fixture()
def conn():
    c = dbmod.connect(":memory:")
    yield c
    c.close()


def _trades(conn):
    return conn.execute("SELECT * FROM trades ORDER BY entry_ts").fetchall()


# ------------------------------------------------------------ detection

@pytest.mark.parametrize("fname,fmt", [
    ("tradovate_position_history.csv", "paired"),
    ("projectx_orders.csv", "projectx_orders"),
    ("projectx_trades.csv", "projectx_trades"),
    ("ninjatrader_executions_eu.csv", "ninjatrader_executions"),
    ("ninjatrader_trades.csv", "ninjatrader_trades"),
    ("tradingview_performance.csv", "paired"),
])
def test_detects_every_real_format(fname, fmt):
    headers, _, _ = read_table(REAL / fname)
    assert auto.detect(headers)[0] == fmt


# ------------------------------------------------------- per-format P&L

def test_tradovate_position_history_matches_platform_pnl(conn):
    res = auto.import_file(conn, REAL / "tradovate_position_history.csv", tz="America/New_York")
    assert res["detected_format"] == "paired"
    assert res["accounts"] == ["APEX4977960000002"]   # account read from the file
    assert res["new"] == 10 and res["warnings"] == []
    total = sum(t["realized_pnl"] for t in _trades(conn))
    assert total == pytest.approx(-218.00)            # platform P/L column sum
    assert all(t["symbol"] == "MNQ" for t in _trades(conn))
    assert not any(t["is_open"] for t in _trades(conn))


def test_projectx_orders_bid_ask_offsets_and_rejections(conn):
    res = auto.import_file(conn, REAL / "projectx_orders.csv", account_label="Topstep 50K")
    assert res["accounts"] == ["Topstep 50K"]
    assert res["new"] == 5                            # rejected row skipped
    t1, t2 = _trades(conn)
    assert t1["direction"] == "long" and t1["realized_pnl"] == pytest.approx(16.25)
    assert t2["direction"] == "short" and t2["realized_pnl"] == pytest.approx(25.00)
    assert t1["entry_ts"].startswith("2026-06-11T13:45:21")  # -06:00 offset honoured
    assert t1["session_date"] == "2026-06-11"


def test_projectx_trades_round_trip(conn):
    auto.import_file(conn, REAL / "projectx_trades.csv", account_label="TSX")
    (t,) = _trades(conn)
    assert t["symbol"] == "ES" and t["direction"] == "long"
    assert t["realized_pnl"] == pytest.approx(500.00)   # platform PnL column
    assert t["fees"] == pytest.approx(3.00)             # Fees 1.00 + Commissions 2.00


def test_ninjatrader_european_locale(conn):
    res = auto.import_file(conn, REAL / "ninjatrader_executions_eu.csv", tz="Europe/Berlin")
    assert res["parse_info"]["decimal_comma"] is True
    assert res["parse_info"]["dayfirst"] is True
    assert res["parse_info"]["delimiter"] == ";"
    (t,) = _trades(conn)
    assert t["symbol"] == "MES" and t["contract"] == "MESM26"
    assert t["avg_entry"] == pytest.approx(7200.75)
    assert t["realized_pnl"] == pytest.approx(20.00)    # 4 pts x $5
    assert t["fees"] == pytest.approx(1.24)             # 2 x "0,62 $"
    assert t["entry_ts"].startswith("2026-04-27T04:05:02")  # 06:05 CEST -> UTC


def test_ninjatrader_trades_export(conn):
    auto.import_file(conn, REAL / "ninjatrader_trades.csv", tz="America/New_York")
    (t,) = _trades(conn)
    assert t["direction"] == "short" and t["contract"] == "MESU26"
    assert t["realized_pnl"] == pytest.approx(20.00)    # platform Profit column
    assert t["entry_ts"].startswith("2026-07-28T13:45:17")  # 9:45:17 AM EDT


def test_tradingview_performance(conn):
    res = auto.import_file(conn, REAL / "tradingview_performance.csv", tz="UTC")
    (t,) = _trades(conn)
    assert t["symbol"] == "AAPL" and t["realized_pnl"] == pytest.approx(1.0)
    assert "AAPL" in res["unknown_instruments"]         # stock: point value 1, flagged


def test_reimport_of_real_file_is_idempotent(conn):
    auto.import_file(conn, REAL / "tradovate_position_history.csv", tz="America/New_York")
    again = auto.import_file(conn, REAL / "tradovate_position_history.csv", tz="America/New_York")
    assert again["new"] == 0 and again["duplicates"] == 10


def test_double_import_across_formats_warns(conn):
    auto.import_file(conn, REAL / "projectx_orders.csv", account_label="X")
    # same account, overlapping window, different export shape
    import tempfile, os
    csv = ("ContractName,EnteredAt,ExitedAt,EntryPrice,ExitPrice,Size,Type\n"
           "MESM6,06/11/2026 07:45:21 -06:00,06/11/2026 07:46:21 -06:00,7300.5,7303.75,1,Long\n")
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv)
    try:
        res = auto.import_file(conn, f.name, account_label="X")
        assert any("double-counted" in w for w in res["warnings"])
    finally:
        os.unlink(f.name)


def test_unknown_export_gives_actionable_error(tmp_path):
    f = tmp_path / "mystery.csv"
    f.write_text("foo,bar,baz\n1,2,3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Columns found: foo, bar, baz"):
        auto.parse_file(f)


def test_generic_fills_autodetected_without_mapping(conn, tmp_path):
    f = tmp_path / "anybroker.csv"
    f.write_text("Ticker,Direction,Contracts,Execution Price,Execution Time,Fee\n"
                 "MNQZ6,BOT,2,21000.25,2026-10-09 09:31:00,0.52\n"
                 "MNQZ6,SLD,2,21010.25,2026-10-09 09:40:00,0.52\n", encoding="utf-8")
    res = auto.import_file(conn, f, account_label="Any", tz="America/Chicago")
    assert res["detected_format"] == "generic_fills"
    (t,) = _trades(conn)
    assert t["realized_pnl"] == pytest.approx(10 * 2 * 2.0)  # 10 pts x 2 lots x $2
    assert t["fees"] == pytest.approx(1.04)


def test_generic_round_trips_autodetected(conn, tmp_path):
    f = tmp_path / "journal_export.csv"
    f.write_text("Symbol,Side,Qty,Open Time,Close Time,Open Price,Close Price\n"
                 "GCZ6,Short,1,2026-10-09T13:30:00Z,2026-10-09T13:50:00Z,2650.0,2645.0\n", encoding="utf-8")
    res = auto.import_file(conn, f, account_label="Gold")
    assert res["detected_format"] == "generic_trips"
    (t,) = _trades(conn)
    assert t["direction"] == "short" and t["realized_pnl"] == pytest.approx(500.0)


# ------------------------------------------------------------ primitives

@pytest.mark.parametrize("raw,dec,expected", [
    ("$1,234.50", None, 1234.5), ("7200,75", None, 7200.75), ("1.234,56", None, 1234.56),
    ("0,62 $", None, 0.62), ("(12.30)", None, -12.3), ("-$5.00", None, -5.0),
    ("90.00 $", None, 90.0), ("1,234", None, 1234.0), ("1,234", True, 1.234), ("", None, None),
])
def test_parse_number(raw, dec, expected):
    assert parse_number(raw, decimal_comma=dec) == (pytest.approx(expected) if expected is not None else None)


@pytest.mark.parametrize("raw,root,contract", [
    ("MES JUN26", "MES", "MESM26"), ("MES 09-26", "MES", "MESU26"), ("MNQM6", "MNQ", "MNQM6"),
    ("CME_MINI:MES1!", "MES", "MES"), ("NASDAQ:AAPL", "AAPL", "AAPL"),
    ("CON.F.US.MES.Z25", "MES", "MESZ25"), ("ESZ2026", "ES", "ESZ2026"), ("6EZ5", "6E", "6EZ5"),
])
def test_parse_instrument(raw, root, contract):
    assert parse_instrument(raw) == (root, contract)


@pytest.mark.parametrize("raw,side", [("Bid", "buy"), ("Ask", "sell"), ("BOT", "buy"), ("SLD", "sell"),
                                      ("Buy to cover", "buy"), ("Sell short", "sell"), ("B", "buy")])
def test_parse_side(raw, side):
    assert parse_side(raw) == side


def test_parse_datetime_variants():
    from completejournal.importers.parsing import resolve_tz
    utc = resolve_tz("UTC")
    assert parse_datetime("06/11/2026 07:45:21 -06:00").startswith("2026-06-11T13:45:21")
    assert parse_datetime("27/04/2026 6:05:02", dayfirst=True, tz=utc).startswith("2026-04-27T06:05:02")
    assert parse_datetime("7/28/2026 9:45:17 PM", tz=utc).startswith("2026-07-28T21:45:17")
    assert parse_datetime("1704067200").startswith("2024-01-01T00:00:00")
    assert parse_datetime("2026-10-09T13:30:00Z").startswith("2026-10-09T13:30:00")
    # value proves its own order even if the caller guessed wrong
    assert parse_datetime("04/27/2026 06:00:00", dayfirst=True, tz=utc).startswith("2026-04-27")


def test_session_policy_rolls_evening_globex():
    p = SessionPolicy()
    assert p.session_date("2026-10-09T13:30:00.000Z") == "2026-10-09"   # 08:30 CT
    assert p.session_date("2026-10-08T23:30:00.000Z") == "2026-10-09"   # 18:30 CT -> next day
    assert p.session_date("2026-10-09T21:59:00.000Z") == "2026-10-09"   # 16:59 CT
    assert SessionPolicy(roll_hour=24).session_date("2026-10-08T23:30:00.000Z") == "2026-10-08"
