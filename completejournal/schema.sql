-- Complete Journal — core schema (SQLite, WAL mode, FTS5)
-- Provenance principles encoded here:
--   * executions is APPEND-ONLY raw source data (never updated, never deleted)
--   * trades are DERIVED and fully rebuildable (algorithm_version tracks the engine)
--   * entries are immutable-with-versions; AI output lives only in ai_artifacts

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ---------------------------------------------------------------- accounts
CREATE TABLE IF NOT EXISTS accounts (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,     -- user-facing label, e.g. "Apex #2 (50k eval)"
    firm        TEXT,                     -- prop firm / broker name
    platform    TEXT,                     -- execution platform (tradovate, rithmic, nt8, ...)
    account_type TEXT,                    -- eval | funded | live | sim | other
    currency    TEXT NOT NULL DEFAULT 'USD',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- -------------------------------------------------------------- instruments
-- Reference data for P&L math. point_value = currency per 1.0 of price.
CREATE TABLE IF NOT EXISTS instruments (
    symbol      TEXT PRIMARY KEY,         -- root symbol, e.g. ES, MES, NQ
    name        TEXT,
    exchange    TEXT,
    tick_size   REAL NOT NULL,
    point_value REAL NOT NULL,
    currency    TEXT NOT NULL DEFAULT 'USD'
);

-- --------------------------------------------------------------- executions
-- Raw fills exactly as imported. Append-only. Idempotency via dedupe_key.
CREATE TABLE IF NOT EXISTS executions (
    id           INTEGER PRIMARY KEY,
    account_id   INTEGER NOT NULL REFERENCES accounts(id),
    source       TEXT NOT NULL,           -- importer name, e.g. csv:tradovate, api:projectx
    import_batch INTEGER NOT NULL REFERENCES import_batches(id),
    exec_id      TEXT,                    -- platform execution id, when provided
    order_id     TEXT,                    -- platform order id, when provided
    symbol       TEXT NOT NULL,           -- instrument root (ES, MES, ...)
    contract     TEXT,                    -- specific contract, e.g. ESZ6
    side         TEXT NOT NULL CHECK (side IN ('buy','sell')),
    qty          INTEGER NOT NULL CHECK (qty > 0),
    price        REAL NOT NULL,
    ts_utc       TEXT NOT NULL,           -- ISO-8601 UTC
    fees         REAL NOT NULL DEFAULT 0, -- commissions + exchange fees for this fill
    order_type   TEXT,                    -- limit | market | stop | ...
    raw_payload  TEXT,                    -- original row/JSON, verbatim
    dedupe_key   TEXT NOT NULL UNIQUE,    -- stable hash; re-imports are no-ops
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_exec_acct_sym_ts ON executions(account_id, symbol, ts_utc);

CREATE TABLE IF NOT EXISTS import_batches (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,
    filename    TEXT,
    imported_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    rows_total  INTEGER NOT NULL DEFAULT 0,
    rows_new    INTEGER NOT NULL DEFAULT 0,
    rows_dup    INTEGER NOT NULL DEFAULT 0,
    warnings    TEXT                       -- JSON array of warning strings
);

-- ------------------------------------------------------------------- trades
-- Derived round trips (flat -> flat). Rebuildable; never the source of truth.
CREATE TABLE IF NOT EXISTS trades (
    id            INTEGER PRIMARY KEY,
    account_id    INTEGER NOT NULL REFERENCES accounts(id),
    symbol        TEXT NOT NULL,
    contract      TEXT,
    direction     TEXT NOT NULL CHECK (direction IN ('long','short')),
    qty_max       INTEGER NOT NULL,        -- peak position size during the trade
    entry_ts      TEXT NOT NULL,
    exit_ts       TEXT,                    -- NULL while open
    avg_entry     REAL NOT NULL,
    avg_exit      REAL,
    realized_pnl  REAL NOT NULL DEFAULT 0, -- points P&L * point_value, pre-fees
    fees          REAL NOT NULL DEFAULT 0,
    net_pnl       REAL NOT NULL DEFAULT 0,
    n_executions  INTEGER NOT NULL,
    is_open       INTEGER NOT NULL DEFAULT 0,
    algorithm_version TEXT NOT NULL,
    session_date  TEXT NOT NULL            -- trading day (UTC date of entry; policy v1)
);
CREATE INDEX IF NOT EXISTS ix_trades_acct_date ON trades(account_id, session_date);

-- Which executions belong to which trade (and how much qty was attributed).
CREATE TABLE IF NOT EXISTS trade_executions (
    trade_id     INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
    execution_id INTEGER NOT NULL REFERENCES executions(id),
    qty          INTEGER NOT NULL,         -- qty of this fill attributed to this trade
    PRIMARY KEY (trade_id, execution_id)
);

-- ------------------------------------------------------------------ entries
-- The journal. body is markdown. Rows are never UPDATEd in place by the app:
-- editing inserts into entry_versions and bumps current body atomically,
-- preserving every prior version. author is 'trader' | 'template' | 'ai'
-- (ai never allowed here by the app layer; constraint documents intent).
CREATE TABLE IF NOT EXISTS entries (
    id          INTEGER PRIMARY KEY,
    kind        TEXT,                      -- market-thought|pre-market|intraday|trade-review|post-trade|end-of-day|knowledge|psychology|NULL
    written_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    about_date  TEXT,                      -- the session/date the entry concerns (optional)
    title       TEXT,
    body_md     TEXT NOT NULL,
    author      TEXT NOT NULL DEFAULT 'trader' CHECK (author IN ('trader','template')),
    deleted_at  TEXT                       -- soft delete only; never hard-delete writing
);

CREATE TABLE IF NOT EXISTS entry_versions (
    id         INTEGER PRIMARY KEY,
    entry_id   INTEGER NOT NULL REFERENCES entries(id),
    body_md    TEXT NOT NULL,
    title      TEXT,
    saved_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Addenda: "what I learned later" — rendered below the original, never merged.
CREATE TABLE IF NOT EXISTS entry_addenda (
    id         INTEGER PRIMARY KEY,
    entry_id   INTEGER NOT NULL REFERENCES entries(id),
    body_md    TEXT NOT NULL,
    written_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- -------------------------------------------------------------------- links
-- Bidirectional, polymorphic: entry <-> trade | session(date) | instrument | entry
CREATE TABLE IF NOT EXISTS links (
    id          INTEGER PRIMARY KEY,
    entry_id    INTEGER NOT NULL REFERENCES entries(id),
    target_type TEXT NOT NULL CHECK (target_type IN ('trade','session','instrument','entry','account')),
    target_id   TEXT NOT NULL,             -- trade id / ISO date / symbol / entry id / account id
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (entry_id, target_type, target_id)
);
CREATE INDEX IF NOT EXISTS ix_links_target ON links(target_type, target_id);

-- --------------------------------------------------------------------- tags
CREATE TABLE IF NOT EXISTS tags (
    entry_id INTEGER NOT NULL REFERENCES entries(id),
    tag      TEXT NOT NULL,                -- flat or namespaced: setup/orb, mistake/chased
    PRIMARY KEY (entry_id, tag)
);

-- --------------------------------------------------------------- attachments
CREATE TABLE IF NOT EXISTS attachments (
    id         INTEGER PRIMARY KEY,
    entry_id   INTEGER REFERENCES entries(id),
    sha256     TEXT NOT NULL,
    filename   TEXT,
    media_type TEXT,
    size_bytes INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- -------------------------------------------------------------- ai_artifacts
-- The ONLY place AI-generated text may live. sources = JSON array of refs.
CREATE TABLE IF NOT EXISTS ai_artifacts (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,             -- daily-digest | theme-report | tag-suggestion | ...
    model       TEXT NOT NULL,
    content_md  TEXT NOT NULL,
    sources     TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- --------------------------------------------------------------------- bars
-- Price context (OHLCV) captured around trades: from CSV import or an API
-- fetcher (e.g. Databento). Charts rendered from here are RECONSTRUCTED price,
-- never "the chart as seen" — the UI must label them as such.
CREATE TABLE IF NOT EXISTS bars (
    symbol     TEXT NOT NULL,            -- instrument root (ES, MES, ...)
    resolution TEXT NOT NULL,            -- '1m', '5m', '1h', '1d'
    ts_utc     TEXT NOT NULL,            -- bar open time, ISO-8601 UTC
    open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
    volume     REAL,
    source     TEXT NOT NULL,            -- csv | databento | ...
    PRIMARY KEY (symbol, resolution, ts_utc)
);

-- --------------------------------------------------------------------- FTS
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    title, body_md, content='entries', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, title, body_md) VALUES (new.id, new.title, new.body_md);
END;
CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE OF title, body_md ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, title, body_md) VALUES ('delete', old.id, old.title, old.body_md);
    INSERT INTO entries_fts(rowid, title, body_md) VALUES (new.id, new.title, new.body_md);
END;
