"""Confidence ranges, edge verdicts, slippage, and schema upgrades of old journals."""
import sqlite3

import pytest

from completejournal import analytics, db as dbmod, reconstruction, stats
from completejournal.importers import auto
from completejournal.importers.base import NormalizedExecution, ingest


@pytest.fixture()
def conn():
    c = dbmod.connect(":memory:")
    yield c
    c.close()


def test_wilson_interval_known_values():
    lo, hi = stats.wilson(7, 10)
    assert lo == pytest.approx(0.3968, abs=1e-3) and hi == pytest.approx(0.8922, abs=1e-3)
    assert stats.wilson(0, 0) is None
    assert stats.wilson(10, 10)[1] == 1.0


def test_bootstrap_is_deterministic_and_honest():
    noisy = [100, -90, 120, -110, 80, -70, 95, -105, 60, -40]
    ci = stats.bootstrap_mean(noisy)
    assert ci == stats.bootstrap_mean(noisy)          # seeded: same data, same range
    assert ci[0] < 0 < ci[1] and stats.verdict(ci) == "can't tell yet"
    assert stats.verdict(stats.bootstrap_mean([50, 60, 40, 55, 45, 70, 52, 48])) == "likely positive"
    assert stats.bootstrap_mean([1, 2]) is None
    assert stats.verdict(None) == "too few trades to estimate"


def test_overall_stats_carry_ranges(conn):
    a = dbmod.get_or_create_account(conn, "A")
    fills = []
    for i, pts in enumerate([10, -5, 8, -6, 12, -4]):
        t0, t1 = f"2026-10-0{1+i}T13:30:00.000Z", f"2026-10-0{1+i}T13:40:00.000Z"
        fills += [NormalizedExecution("MES", "buy", 1, 5000.0, t0),
                  NormalizedExecution("MES", "sell", 1, 5000.0 + pts, t1)]
    ingest(conn, a, "A", "t", "t", fills)
    reconstruction.rebuild(conn)
    s = analytics.overall(conn)
    assert s.n == 6 and s.win_rate_ci95[0] < 0.5 < s.win_rate_ci95[1]
    assert s.expectancy_ci95 is not None and s.edge in ("can't tell yet", "likely positive")


def test_slippage_from_real_style_projectx_export(conn, tmp_path):
    f = tmp_path / "orders.csv"
    f.write_text(
        "Id,AccountName,ContractName,Status,Type,Size,Side,CreatedAt,TradeDay,FilledAt,CancelledAt,"
        "TriggeredAt,StopPrice,LimitPrice,ExecutePrice,TriggeredPrice,PositionDisposition,"
        "CreationDisposition,RejectionReason,ExchangeOrderId,PlatformOrderId\n"
        "1,X,MESM6,Filled,Limit,1,Bid,06/11/2026 07:45:21 -06:00,,06/11/2026 07:45:21 -06:00,,,,7300.5,7300.5,,Opening,Trader,,E1,P1\n"
        "2,X,MESM6,Filled,Stop,1,Ask,06/11/2026 07:50:00 -06:00,,06/11/2026 07:50:00 -06:00,,,7298.00,,7297.25,,Closing,StopLoss,,E2,P2\n",
        encoding="utf-8")
    auto.import_file(conn, f, account_label="TSX")
    sl = stats.slippage(conn)
    assert sl["fills_measured"] == 2
    assert sl["by_order_type"]["stop"]["avg_ticks"] == 3.0          # sold 0.75 pts below a 7298 stop
    assert sl["by_order_type"]["stop"]["total_dollars"] == 3.75     # 0.75 x $5
    assert sl["by_order_type"]["limit"]["avg_ticks"] == 0.0


def test_old_journal_file_gains_new_column_without_data_loss(tmp_path):
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.executescript("""
        CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, firm TEXT,
            platform TEXT, account_type TEXT, currency TEXT NOT NULL DEFAULT 'USD', created_at TEXT);
        CREATE TABLE import_batches (id INTEGER PRIMARY KEY, source TEXT NOT NULL, filename TEXT,
            imported_at TEXT, rows_total INTEGER DEFAULT 0, rows_new INTEGER DEFAULT 0,
            rows_dup INTEGER DEFAULT 0, warnings TEXT);
        CREATE TABLE executions (id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL, source TEXT NOT NULL,
            import_batch INTEGER NOT NULL, exec_id TEXT, order_id TEXT, symbol TEXT NOT NULL, contract TEXT,
            side TEXT NOT NULL, qty INTEGER NOT NULL, price REAL NOT NULL, ts_utc TEXT NOT NULL,
            fees REAL NOT NULL DEFAULT 0, order_type TEXT, raw_payload TEXT, dedupe_key TEXT NOT NULL UNIQUE,
            created_at TEXT);
        INSERT INTO accounts(id, name) VALUES (1, 'Old');
        INSERT INTO import_batches(id, source) VALUES (1, 'csv');
        INSERT INTO executions(account_id, source, import_batch, symbol, side, qty, price, ts_utc, dedupe_key)
            VALUES (1, 'csv', 1, 'ES', 'buy', 1, 6000, '2026-01-02T15:00:00.000Z', 'k1');
    """)
    raw.commit(); raw.close()
    c = dbmod.connect(path)                                   # upgrade happens here
    cols = {r[1] for r in c.execute("PRAGMA table_info(executions)")}
    assert "intended_price" in cols
    assert c.execute("SELECT COUNT(*) FROM executions").fetchone()[0] == 1
    c.close()
