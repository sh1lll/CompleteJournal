"""Platform-specific CSV importers: thin presets over the generic importer.

⚠️ Built against *documented* export layouts (vendor help pages, forum posts)
with header synonyms for drift — they have NOT yet been validated against real
export files (roadmap item A4). Each parser falls back gracefully: unknown
headers produce row-level warnings, never silent data corruption, and the
generic importer with an explicit mapping always works.

Timezone policy: platform exports with naive timestamps are interpreted in the
timezone the caller passes (default: exchange-standard US/Central is NOT
assumed — callers must say). to_utc_iso stores everything as UTC.
"""
from __future__ import annotations

from datetime import timedelta, timezone
from pathlib import Path

from .base import NormalizedExecution, contract_root, parse_money, read_csv, to_utc_iso

_SYN = {
    # normalized field -> candidate headers (lowercase), in priority order
    "contract": ["contract", "symbol", "instrument", "product"],
    "side": ["b/s", "side", "buy/sell", "action", "buysell", "market side"],
    "qty": ["filledqty", "qty filled", "filled qty", "quantity", "qty", "fill qty", "filled"],
    "price": ["avgprice", "avg fill price", "avg price", "price", "fill price", "avgfillprice"],
    "ts": ["fill time", "update time", "time", "timestamp", "date/time", "datetime", "fill time (utc)"],
    "exec_id": ["execution id", "exec id", "fill id", "id"],
    "order_id": ["order id", "orderid", "order number", "order #"],
    "fees": ["commission", "commissions", "fees", "total fees", "commission filled"],
    "order_type": ["type", "order type", "ordertype"],
    "status": ["status", "order status"],
}


def _lookup(lower_row: dict, field: str) -> str | None:
    for h in _SYN[field]:
        v = lower_row.get(h)
        if v:
            return v
    return None


def _parse_rows(
    path: str | Path,
    *,
    tz_offset_minutes: int,
    filled_only: bool,
    instrument_style: str,  # "contract" (ESZ5) | "nt" (ES 12-25)
) -> tuple[list[NormalizedExecution], list[str]]:
    tz = timezone(timedelta(minutes=tz_offset_minutes))
    out: list[NormalizedExecution] = []
    warnings: list[str] = []
    for i, row in enumerate(read_csv(path), start=1):
        lower = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        try:
            status = (_lookup(lower, "status") or "").lower()
            if filled_only and status and "fill" not in status and status != "complete":
                continue  # skip working/canceled/rejected orders
            inst = _lookup(lower, "contract")
            if not inst:
                raise ValueError("no instrument column found")
            if instrument_style == "nt":
                # NinjaTrader style: "ES 12-25" -> root ES, contract ES 12-25
                symbol = inst.split()[0].upper()
                contract = inst.upper()
            else:
                contract = inst.upper()
                symbol = contract_root(contract)
            side_raw = (_lookup(lower, "side") or "").lower()
            side = "buy" if side_raw.startswith("b") else "sell" if side_raw.startswith("s") else ""
            if not side:
                raise ValueError(f"unrecognized side {side_raw!r}")
            qty_raw = _lookup(lower, "qty")
            price_raw = _lookup(lower, "price")
            ts_raw = _lookup(lower, "ts")
            if not (qty_raw and price_raw and ts_raw):
                raise ValueError("missing qty/price/time")
            qty = int(float(qty_raw))
            if qty == 0:
                continue  # zero-fill order rows are not executions
            ex = NormalizedExecution(
                symbol=symbol,
                contract=contract,
                side=side,
                qty=qty,
                price=parse_money(price_raw),
                ts_utc=to_utc_iso(ts_raw, assume_tz=tz),
                exec_id=_lookup(lower, "exec_id"),
                order_id=_lookup(lower, "order_id"),
                fees=abs(parse_money(_lookup(lower, "fees"))),
                order_type=_lookup(lower, "order_type"),
                raw=dict(row),
            )
            ex.validate()
            out.append(ex)
        except (ValueError, KeyError) as e:
            warnings.append(f"row {i}: skipped ({e})")
    return out, warnings


def parse_tradovate_orders(path: str | Path, *, tz_offset_minutes: int = 0):
    """Tradovate account report → Orders CSV. Fill-bearing order rows only.
    Note: order-level export → one row per order (avgPrice/filledQty), so
    partial fills inside one order are already aggregated by the platform."""
    return _parse_rows(path, tz_offset_minutes=tz_offset_minutes,
                       filled_only=True, instrument_style="contract")


def parse_ninjatrader_executions(path: str | Path, *, tz_offset_minutes: int = 0):
    """NinjaTrader 8 Trade Performance → Executions grid export."""
    return _parse_rows(path, tz_offset_minutes=tz_offset_minutes,
                       filled_only=False, instrument_style="nt")


def parse_rithmic_orders(path: str | Path, *, tz_offset_minutes: int = 0):
    """Rithmic R Trader → Completed Orders grid CSV (one day per export;
    requires 'Qty Filled' and 'Order Number' columns added to the grid)."""
    return _parse_rows(path, tz_offset_minutes=tz_offset_minutes,
                       filled_only=True, instrument_style="contract")


REGISTRY = {
    "tradovate": (parse_tradovate_orders, "csv:tradovate"),
    "ninjatrader": (parse_ninjatrader_executions, "csv:ninjatrader"),
    "rithmic": (parse_rithmic_orders, "csv:rithmic"),
}
