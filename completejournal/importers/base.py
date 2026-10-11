"""Importer framework.

Every ingestion path — any platform's CSV, any API adapter — produces
NormalizedExecution records and hands them to `ingest()`. This is the
universality layer: supporting a new firm/platform/account type means
writing one adapter that maps its export to this schema, nothing more.

Idempotency: each execution gets a dedupe_key. When the platform provides a
real execution id we key on (source-family, account, exec_id); otherwise we
hash the full economic content of the fill. Re-importing a file is a no-op.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator


@dataclass
class NormalizedExecution:
    symbol: str                 # instrument root, e.g. "ES" (derived from contract if needed)
    side: str                   # "buy" | "sell"
    qty: int
    price: float
    ts_utc: str                 # ISO-8601 UTC
    contract: str | None = None # e.g. "ESZ6"
    exec_id: str | None = None
    order_id: str | None = None
    fees: float = 0.0
    order_type: str | None = None
    raw: dict = field(default_factory=dict)
    account: str | None = None  # account named inside the file, when present
    intended_price: float | None = None  # stop/limit price, when known (slippage)

    def validate(self) -> None:
        if self.side not in ("buy", "sell"):
            raise ValueError(f"invalid side {self.side!r}")
        if self.qty <= 0:
            raise ValueError(f"invalid qty {self.qty}")
        if self.price <= 0:
            raise ValueError(f"invalid price {self.price}")
        datetime.fromisoformat(self.ts_utc.replace("Z", "+00:00"))  # raises if bad


@dataclass
class ImportResult:
    batch_id: int
    rows_total: int
    rows_new: int
    rows_dup: int
    warnings: list[str] = field(default_factory=list)


# Contract root extraction: "ESZ6", "ESZ26", "MESZ2025" -> "MES"/"ES".
_CONTRACT_RE = re.compile(r"^([A-Z0-9]{1,4}?)([FGHJKMNQUVXZ])(\d{1,4})$")


def contract_root(contract: str) -> str:
    c = contract.strip().upper()
    m = _CONTRACT_RE.match(c)
    if m:
        return m.group(1)
    return c  # already a root, or unknown format — keep verbatim


def dedupe_key(source_family: str, account_name: str, ex: NormalizedExecution) -> str:
    """Stable identity for a fill. source_family groups importers that see the
    same underlying fills (e.g. 'tradovate' for both its CSV and API), so the
    same fill arriving via two routes dedupes."""
    if ex.exec_id:
        basis = f"id|{source_family}|{account_name}|{ex.exec_id}"
    else:
        basis = "|".join(
            [
                "content", source_family, account_name,
                ex.symbol, ex.contract or "", ex.side,
                str(ex.qty), f"{ex.price:.10g}", ex.ts_utc, ex.order_id or "",
            ]
        )
    return hashlib.sha256(basis.encode()).hexdigest()


def ingest(
    conn: sqlite3.Connection,
    account_id: int,
    account_name: str,
    source: str,              # e.g. "csv:tradovate"
    source_family: str,       # e.g. "tradovate"
    executions: Iterable[NormalizedExecution],
    filename: str | None = None,
    warnings: list[str] | None = None,
) -> ImportResult:
    warnings = list(warnings or [])
    executions = list(executions)
    # double-import guard: same account, overlapping time window, different
    # export source => likely the same fills arriving twice in two shapes
    if executions:
        lo = min(e.ts_utc for e in executions)
        hi = max(e.ts_utc for e in executions)
        other = conn.execute(
            "SELECT DISTINCT source FROM executions WHERE account_id=? AND source<>? "
            "AND ts_utc BETWEEN ? AND ?", (account_id, source, lo, hi)).fetchall()
        for o in other:
            warnings.append(
                f"account already has fills from '{o[0]}' in this time window — if both "
                f"files describe the same trades they will be double-counted")
    cur = conn.execute(
        "INSERT INTO import_batches(source, filename) VALUES (?,?)", (source, filename)
    )
    batch_id = cur.lastrowid
    total = new = dup = 0
    for ex in executions:
        total += 1
        try:
            ex.validate()
        except ValueError as e:
            warnings.append(f"row {total}: skipped ({e})")
            continue
        key = dedupe_key(source_family, account_name, ex)
        try:
            conn.execute(
                """INSERT INTO executions
                   (account_id, source, import_batch, exec_id, order_id, symbol, contract,
                    side, qty, price, ts_utc, fees, order_type, raw_payload, dedupe_key,
                    intended_price)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    account_id, source, batch_id, ex.exec_id, ex.order_id, ex.symbol,
                    ex.contract, ex.side, ex.qty, ex.price, ex.ts_utc, ex.fees,
                    ex.order_type, json.dumps(ex.raw, default=str), key, ex.intended_price,
                ),
            )
            new += 1
        except sqlite3.IntegrityError:
            dup += 1
    conn.execute(
        "UPDATE import_batches SET rows_total=?, rows_new=?, rows_dup=?, warnings=? WHERE id=?",
        (total, new, dup, json.dumps(warnings), batch_id),
    )
    conn.commit()
    return ImportResult(batch_id, total, new, dup, warnings)


# ------------------------------------------------------------------ helpers

def read_csv(path: str | Path) -> Iterator[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        yield from csv.DictReader(f)


def to_utc_iso(value: str, fmt: str | None = None, assume_tz: timezone = timezone.utc) -> str:
    """Parse a timestamp string into ISO-8601 UTC. If the value carries no
    offset, assume_tz is applied (default UTC — importers pass the platform's
    known export timezone)."""
    v = value.strip()
    dt: datetime | None = None
    if fmt:
        dt = datetime.strptime(v, fmt)
    else:
        for candidate in (
            "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
            "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
            "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p",
        ):
            try:
                dt = datetime.strptime(v, candidate)
                break
            except ValueError:
                continue
        if dt is None:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=assume_tz)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_money(value: str | float | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    v = value.strip().replace("$", "").replace(",", "")
    if not v:
        return 0.0
    neg = v.startswith("(") and v.endswith(")")
    if neg:
        v = v[1:-1]
    return -float(v) if neg else float(v)
