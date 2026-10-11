"""Generic column-mapping CSV importer — the universal tier.

Any platform that can export fills to CSV can feed the journal through this
importer by supplying a mapping from its column names to the normalized
fields. This is the guarantee behind "all firms, platforms, account types":
platform-specific importers are conveniences layered on top of this.

mapping keys (values are the CSV header names in the file):
  required: symbol|contract (at least one), side, qty, price, ts
  optional: exec_id, order_id, fees, order_type
options:
  side_values: {"buy": [...], "sell": [...]} — tokens meaning buy/sell
  tz_offset_minutes: offset of the file's naive timestamps from UTC
  ts_format: explicit strptime format, else autodetect
"""
from __future__ import annotations

from datetime import timedelta, timezone
from pathlib import Path

from .base import NormalizedExecution, contract_root, parse_money, read_csv, to_utc_iso

_DEFAULT_SIDE_VALUES = {
    "buy": ["buy", "b", "bot", "bought", "long", "buytoopen", "buytoclose"],
    "sell": ["sell", "s", "sld", "sold", "short", "selltoopen", "selltoclose", "sellshort"],
}


def _norm_side(value: str, side_values: dict) -> str:
    v = value.strip().lower().replace(" ", "").replace("_", "")
    for side, tokens in side_values.items():
        if v in tokens:
            return side
    raise ValueError(f"unrecognized side value {value!r}")


def parse(
    path: str | Path,
    mapping: dict,
    *,
    side_values: dict | None = None,
    tz_offset_minutes: int = 0,
    ts_format: str | None = None,
) -> tuple[list[NormalizedExecution], list[str]]:
    sides = {**_DEFAULT_SIDE_VALUES, **(side_values or {})}
    tz = timezone(timedelta(minutes=tz_offset_minutes))
    out: list[NormalizedExecution] = []
    warnings: list[str] = []
    for i, row in enumerate(read_csv(path), start=1):
        # tolerate header-case drift
        lower = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}

        def col(key: str) -> str | None:
            header = mapping.get(key)
            if not header:
                return None
            return lower.get(header.strip().lower()) or None

        try:
            contract = col("contract")
            symbol = col("symbol") or (contract_root(contract) if contract else None)
            if not symbol:
                raise ValueError("no symbol/contract")
            qty_raw = col("qty")
            qty = int(float(qty_raw)) if qty_raw else 0
            ex = NormalizedExecution(
                symbol=symbol.upper(),
                contract=contract.upper() if contract else None,
                side=_norm_side(col("side") or "", sides),
                qty=qty,
                price=parse_money(col("price")),
                ts_utc=to_utc_iso(col("ts") or "", fmt=ts_format, assume_tz=tz),
                exec_id=col("exec_id"),
                order_id=col("order_id"),
                fees=parse_money(col("fees")),
                order_type=col("order_type"),
                raw=dict(row),
            )
            ex.validate()
            out.append(ex)
        except (ValueError, KeyError) as e:
            warnings.append(f"row {i}: skipped ({e})")
    return out, warnings
