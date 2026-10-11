"""Auto-detecting importer: drop in any export, get executions.

Detection is by header signature (normalized: lowercase, alphanumerics only).
Three export shapes exist in the wild and all are handled:

  * FILLS       one row = one execution            (Tradovate Orders, NinjaTrader
                                                     Executions, R|Trader Order
                                                     History, ProjectX Orders)
  * PAIRED      one row = a matched buy + sell     (Tradovate Position History,
                                                     TradingView Performance)
  * ROUND TRIP  one row = a whole trade            (NinjaTrader Trades, ProjectX
                                                     Trades, generic journals)

Paired and round-trip rows are expanded into their two executions, so every
shape flows through the same reconstruction engine and the same dedupe.

Format signatures were verified against real-world export samples published
in the open-source TradeTally project (Apache-2.0) — see
tests/fixtures/real/README.md — plus vendor documentation.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import parsing as P
from .base import NormalizedExecution, ingest

# ---------------------------------------------------------------- signatures

_SIGNATURES: list[tuple[str, str, list[set[str]]]] = [
    # (format, family, list of alternative required-header sets)
    ("paired", "tradovate_or_tradingview", [
        {"buyfillid", "sellfillid", "buyprice", "sellprice", "boughttimestamp", "soldtimestamp"},
    ]),
    ("projectx_orders", "projectx", [
        {"contractname", "status", "size", "side", "filledat", "executeprice"},
    ]),
    ("projectx_trades", "projectx", [
        {"contractname", "enteredat", "exitedat", "entryprice", "exitprice"},
    ]),
    ("ninjatrader_trades", "ninjatrader", [
        {"instrument", "marketpos", "qty", "entryprice", "exitprice", "entrytime", "exittime"},
    ]),
    ("ninjatrader_executions", "ninjatrader", [
        {"instrument", "action", "quantity", "price", "time", "ex"},
        {"instrument", "action", "quantity", "price", "time", "orderid"},
    ]),
    ("tradovate_orders", "tradovate", [
        {"bs", "contract", "filledqty", "avgprice"},
        {"bs", "contract", "filledqty", "avgfillprice"},
    ]),
    ("rithmic_orders", "rithmic", [
        {"qtyfilled", "avgfillprice", "symbol"},
    ]),
]

# generic synonyms (normalized) for unknown formats
_GEN_FILL = {
    "instrument": ["symbol", "instrument", "contract", "ticker", "contractname", "product", "market", "asset"],
    "side": ["side", "action", "bs", "buysell", "direction", "type", "transactiontype", "ordertype2"],
    "qty": ["quantity", "qty", "filledqty", "qtyfilled", "size", "filled", "shares", "contracts", "lots", "volume", "amount"],
    "price": ["price", "fillprice", "avgfillprice", "avgprice", "executeprice", "executionprice", "tradeprice", "averageprice"],
    "time": ["time", "timestamp", "datetime", "filltime", "executiontime", "exectime", "date", "tradetime", "filledat", "updatetime", "createdat"],
}
_GEN_TRIP = {
    "instrument": _GEN_FILL["instrument"],
    "side": ["side", "direction", "type", "marketpos", "position", "longshort"],
    "qty": _GEN_FILL["qty"],
    "entry_price": ["entryprice", "openprice", "priceopen", "entry", "avgentry", "buyprice"],
    "exit_price": ["exitprice", "closeprice", "priceclose", "exit", "avgexit", "sellprice"],
    "entry_time": ["entrytime", "opentime", "enteredat", "opendate", "opendatetime", "entrydate", "timeopen"],
    "exit_time": ["exittime", "closetime", "exitedat", "closedate", "closedatetime", "exitdate", "timeclose"],
}
_FEE_COLS = ["commission", "commissions", "fees", "fee", "totalfees", "clearingfee",
             "exchangefee", "ipfee", "nfafee", "regfee", "secfee"]
_ACCOUNT_COLS = ["account", "accountname", "accountid", "accountdisplayname", "clientaccountid"]
_SKIP_STATUS = {"rejected", "cancelled", "canceled", "expired", "working", "pending",
                "suspended", "accepted", "new", "inactive"}


@dataclass
class ParseResult:
    format: str
    family: str
    executions: list[NormalizedExecution]
    warnings: list[str] = field(default_factory=list)
    info: dict = field(default_factory=dict)


def detect(headers: list[str]) -> tuple[str, str]:
    hs = set(headers)
    for fmt, family, alternatives in _SIGNATURES:
        if any(req <= hs for req in alternatives):
            return fmt, family
    if all(any(c in hs for c in cands) for cands in _GEN_TRIP.values() if cands is not _GEN_TRIP["side"]):
        return "generic_trips", "generic"
    if all(any(c in hs for c in cands) for cands in _GEN_FILL.values()):
        return "generic_fills", "generic"
    return "unknown", "unknown"


def _dayfirst_from_iso_crosscheck(rows: list[dict], time_cols: list[str]) -> bool | None:
    """Prove date order from a row that also carries an unambiguous ISO date
    (e.g. Tradovate's 'Trade Date 2026-04-09' beside '04/09/2026 17:14:44')."""
    import re
    month_first = day_first = 0
    for r in rows[:200]:
        isos = {r[c][:10] for c in time_cols
                if re.match(r"^\d{4}-\d{2}-\d{2}", r.get(c, "") or "")}
        if not isos:
            continue
        for c in time_cols:
            m = P._DT_RE.match(r.get(c, "") or "")
            if not m or len(m.group("a")) == 4:
                continue
            a, b, y = int(m.group("a")), int(m.group("b")), m.group("c")
            y = int(y) + (2000 if len(y) == 2 else 0)
            if a == b:
                continue
            if f"{y:04d}-{a:02d}-{b:02d}" in isos:
                month_first += 1
            elif f"{y:04d}-{b:02d}-{a:02d}" in isos:
                day_first += 1
    if month_first and not day_first:
        return False
    if day_first and not month_first:
        return True
    return None


def _pick(hs: set[str], cands: list[str]) -> str | None:
    return next((c for c in cands if c in hs), None)


# ------------------------------------------------------------------ parse

def parse_file(source, *, tz: str | None = None, dayfirst: bool | None = None,
               force_format: str | None = None) -> ParseResult:
    headers, rows, info = P.read_table(source)
    fmt, family = (force_format, force_format.split("_")[0]) if force_format else detect(headers)
    if fmt == "unknown":
        raise ValueError(
            "could not recognize this export. Columns found: "
            + ", ".join(h for h in info["raw_headers"] if h.strip())
            + ". Use the generic importer with an explicit column mapping.")
    tzinfo = P.resolve_tz(tz)
    warnings: list[str] = []

    # file-level locale inference
    price_cols = [h for h in headers if "price" in h or h in ("avgbuy", "avgsell", "pnl", "pl", "profit")]
    dec_comma = P.file_uses_decimal_comma(rows, price_cols or headers, info["delimiter"])
    time_cols = [h for h in headers if any(k in h for k in ("time", "date", "at", "timestamp"))]
    if dayfirst is None:
        values = [r.get(c, "") for r in rows for c in time_cols]
        dayfirst, conflict = P.infer_dayfirst(values)
        if conflict:
            raise ValueError("dates in this file are inconsistent (both day-first and month-first)")
        if dayfirst is None:
            dayfirst = _dayfirst_from_iso_crosscheck(rows, time_cols)
        if dayfirst is None:
            dayfirst = dec_comma  # European locale => day-first convention
            if any(P._DT_RE.match(v or "") and len((P._DT_RE.match(v).group("a"))) < 4
                   for v in values[:50] if v):
                warnings.append(f"date order not provable from data; assumed "
                                f"{'day' if dayfirst else 'month'}-first")
    info.update({"format": fmt, "decimal_comma": dec_comma, "dayfirst": dayfirst,
                 "timezone": str(tz) if tz else "local system time"})

    num = lambda v: P.parse_number(v, decimal_comma=dec_comma)  # noqa: E731
    when = lambda v: P.parse_datetime(v, dayfirst=dayfirst, tz=tzinfo)  # noqa: E731
    hs = set(headers)
    acct_col = _pick(hs, _ACCOUNT_COLS)
    fee_cols = [c for c in _FEE_COLS if c in hs]

    def fees_of(r) -> float:
        return sum(abs(num(r.get(c)) or 0.0) for c in fee_cols)

    out: list[NormalizedExecution] = []

    def add(**kw):
        ex = NormalizedExecution(**kw)
        ex.validate()
        out.append(ex)

    for i, r in enumerate(rows, start=1):
        raw = r["__raw__"]
        account = r.get(acct_col) if acct_col else None
        try:
            status = (r.get("status") or "").strip().lower()
            if status and status in _SKIP_STATUS:
                continue

            if fmt == "paired":
                root, contract = P.parse_instrument(P.first(r, "contract", "symbol", "product"))
                qty = int(num(P.first(r, "pairedqty", "qty", "quantity")) or 0)
                if qty <= 0:
                    continue
                pair = P.first(r, "pairid") or f"{r.get('buyfillid')}-{r.get('sellfillid')}"
                for side, px, ts, fid in (("buy", "buyprice", "boughttimestamp", "buyfillid"),
                                          ("sell", "sellprice", "soldtimestamp", "sellfillid")):
                    add(symbol=root, contract=contract, side=side, qty=qty,
                        price=num(r[px]), ts_utc=when(r[ts]),
                        exec_id=f"pair:{pair}:{side}", order_id=r.get(fid),
                        raw=raw, account=account)

            elif fmt in ("projectx_trades", "ninjatrader_trades", "generic_trips"):
                if fmt == "projectx_trades":
                    inst, side_v, qty_v = r["contractname"], r.get("type"), P.first(r, "size", "qty")
                    ep, xp, et, xt = r["entryprice"], r["exitprice"], r["enteredat"], r["exitedat"]
                    tid = r.get("id")
                elif fmt == "ninjatrader_trades":
                    inst, side_v, qty_v = r["instrument"], r["marketpos"], r["qty"]
                    ep, xp, et, xt = r["entryprice"], r["exitprice"], r["entrytime"], r["exittime"]
                    tid = r.get("tradenumber")
                else:
                    g = {k: _pick(hs, c) for k, c in _GEN_TRIP.items()}
                    inst, side_v, qty_v = r[g["instrument"]], r.get(g["side"] or "", ""), r[g["qty"]]
                    ep, xp = r[g["entry_price"]], r[g["exit_price"]]
                    et, xt = r[g["entry_time"]], r[g["exit_time"]]
                    tid = None
                root, contract = P.parse_instrument(inst)
                direction = P.parse_side(side_v) if side_v else "buy"
                qty = int(abs(num(qty_v) or 0))
                if qty <= 0:
                    continue
                fee = fees_of(r)
                entry_side = direction
                exit_side = "sell" if direction == "buy" else "buy"
                key = tid or f"{inst}|{et}|{xt}|{ep}|{xp}|{qty}"
                add(symbol=root, contract=contract, side=entry_side, qty=qty, price=num(ep),
                    ts_utc=when(et), exec_id=f"trip:{key}:in", fees=fee / 2, raw=raw, account=account)
                add(symbol=root, contract=contract, side=exit_side, qty=qty, price=num(xp),
                    ts_utc=when(xt), exec_id=f"trip:{key}:out", fees=fee / 2, raw=raw, account=account)

            else:  # fills
                if fmt == "projectx_orders":
                    inst, side_v, qty_v = r["contractname"], r["side"], r["size"]
                    px, ts = r.get("executeprice"), r.get("filledat")
                    eid = P.first(r, "id", "platformorderid")
                    oid = P.first(r, "platformorderid", "exchangeorderid", "id")
                elif fmt == "ninjatrader_executions":
                    inst, side_v, qty_v = r["instrument"], r["action"], r["quantity"]
                    px, ts, eid, oid = r["price"], r["time"], r.get("id"), r.get("orderid")
                elif fmt == "tradovate_orders":
                    inst, side_v, qty_v = r["contract"], r["bs"], r["filledqty"]
                    px = P.first(r, "avgprice", "avgfillprice")
                    ts = P.first(r, "filltime", "timestamp", "date")
                    eid, oid = None, P.first(r, "orderid", "order")
                elif fmt == "rithmic_orders":
                    inst = r["symbol"]
                    side_v = P.first(r, "buysell", "side", "bs")
                    qty_v, px = r["qtyfilled"], r["avgfillprice"]
                    ts = P.first(r, "filltime", "updatetime", "time")
                    eid, oid = None, P.first(r, "ordernumber", "orderid")
                else:
                    g = {k: _pick(hs, c) for k, c in _GEN_FILL.items()}
                    inst, side_v, qty_v = r[g["instrument"]], r[g["side"]], r[g["qty"]]
                    px, ts = r[g["price"]], r[g["time"]]
                    eid = P.first(r, "executionid", "execid", "fillid", "tradeid", "id")
                    oid = P.first(r, "orderid", "ordernumber")
                if not px or not ts:
                    continue  # unfilled order row
                qty = int(abs(num(qty_v) or 0))
                if qty <= 0:
                    continue
                root, contract = P.parse_instrument(inst)
                add(symbol=root, contract=contract, side=P.parse_side(side_v), qty=qty,
                    price=num(px), ts_utc=when(ts), exec_id=eid, order_id=oid,
                    fees=fees_of(r), raw=raw, account=account)
        except (ValueError, KeyError, TypeError) as e:
            warnings.append(f"row {i}: skipped ({e})")

    return ParseResult(fmt, family, out, warnings, info)


# ------------------------------------------------------------------ import

def import_file(conn: sqlite3.Connection, source, *, account_label: str | None = None,
                tz: str | None = None, dayfirst: bool | None = None,
                force_format: str | None = None, filename: str | None = None) -> dict:
    """Parse + ingest + rebuild. Files containing several accounts are split
    into separate journal accounts (never mixed)."""
    from ..db import get_or_create_account
    from ..reconstruction import rebuild

    res = parse_file(source, tz=tz, dayfirst=dayfirst, force_format=force_format)
    groups: dict[str, list[NormalizedExecution]] = {}
    file_accounts = sorted({e.account for e in res.executions if e.account})
    for e in res.executions:
        if account_label and len(file_accounts) <= 1:
            name = account_label
        elif account_label:
            name = f"{account_label} · {e.account}" if e.account else account_label
        else:
            name = e.account or f"{res.family} import"
        groups.setdefault(name, []).append(e)

    totals = {"rows": 0, "new": 0, "duplicates": 0}
    accounts = []
    warnings = list(res.warnings)
    for name, execs in groups.items():
        acct_id = get_or_create_account(conn, name, platform=res.family)
        r = ingest(conn, acct_id, name, f"file:{res.format}", res.family, execs,
                   filename=filename or (str(source) if isinstance(source, (str, Path)) else None))
        totals["rows"] += r.rows_total
        totals["new"] += r.rows_new
        totals["duplicates"] += r.rows_dup
        warnings += r.warnings
        accounts.append(name)
    report = rebuild(conn)
    return {
        "detected_format": res.format,
        "accounts": accounts,
        **totals,
        "warnings": warnings,
        "trades_total": report.trades_created,
        "open_trades": report.open_trades,
        "unknown_instruments": report.unknown_instruments,
        "parse_info": {k: v for k, v in res.info.items() if k != "raw_headers"},
    }
