"""Database bootstrap and helpers. One SQLite file, WAL mode, FTS5."""
from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

SCHEMA_VERSION = "1"


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")  # live sync and the UI write concurrently
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    schema = resources.files("completejournal").joinpath("schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    # columns added after a journal was first created (CREATE TABLE IF NOT
    # EXISTS does not add them to existing files)
    _ensure_column(conn, "executions", "intended_price", "REAL")
    conn.execute(
        "INSERT INTO meta(key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (SCHEMA_VERSION,),
    )
    _seed_instruments(conn)
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


# CME/CBOT/NYMEX/COMEX contract specs most relevant to futures journaling.
# point_value = currency per 1.0 price point; tick_size = minimum increment.
# Source: exchange contract specs (stable, well-known values). Extend freely.
_INSTRUMENTS = [
    # symbol, name, exchange, tick_size, point_value
    ("ES",  "E-mini S&P 500",        "CME",   0.25,   50.0),
    ("MES", "Micro E-mini S&P 500",  "CME",   0.25,    5.0),
    ("NQ",  "E-mini Nasdaq-100",     "CME",   0.25,   20.0),
    ("MNQ", "Micro E-mini Nasdaq",   "CME",   0.25,    2.0),
    ("YM",  "E-mini Dow",            "CBOT",  1.0,     5.0),
    ("MYM", "Micro E-mini Dow",      "CBOT",  1.0,     0.5),
    ("RTY", "E-mini Russell 2000",   "CME",   0.10,   50.0),
    ("M2K", "Micro E-mini Russell",  "CME",   0.10,    5.0),
    ("CL",  "Crude Oil",             "NYMEX", 0.01, 1000.0),
    ("MCL", "Micro Crude Oil",       "NYMEX", 0.01,  100.0),
    ("GC",  "Gold",                  "COMEX", 0.10,  100.0),
    ("MGC", "Micro Gold",            "COMEX", 0.10,   10.0),
    ("SI",  "Silver",                "COMEX", 0.005, 5000.0),
    ("NG",  "Natural Gas",           "NYMEX", 0.001, 10000.0),
    ("ZB",  "30-Yr US Treasury Bond","CBOT",  0.03125, 1000.0),
    ("ZN",  "10-Yr US Treasury Note","CBOT",  0.015625, 1000.0),
    ("6E",  "Euro FX",               "CME",   0.00005, 125000.0),
]


def _seed_instruments(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO instruments(symbol, name, exchange, tick_size, point_value) "
        "VALUES (?,?,?,?,?)",
        _INSTRUMENTS,
    )


def get_or_create_account(
    conn: sqlite3.Connection,
    name: str,
    firm: str | None = None,
    platform: str | None = None,
    account_type: str | None = None,
) -> int:
    row = conn.execute("SELECT id FROM accounts WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO accounts(name, firm, platform, account_type) VALUES (?,?,?,?)",
        (name, firm, platform, account_type),
    )
    conn.commit()
    return cur.lastrowid


def point_value(conn: sqlite3.Connection, symbol: str) -> float | None:
    row = conn.execute(
        "SELECT point_value FROM instruments WHERE symbol = ?", (symbol,)
    ).fetchone()
    return row["point_value"] if row else None
