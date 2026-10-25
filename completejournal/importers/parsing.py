"""Locale-robust parsing primitives for real-world broker exports.

Real exports differ from documentation in ways that silently corrupt data if
ignored: semicolon delimiters, European decimals ("7200,75"), currency
suffixes ("0,62 $"), day-first dates ("27/04/2026"), explicit UTC offsets
("06/11/2026 07:45:21 -06:00"), title rows above the header, BOMs, and
instrument spellings ("MES JUN26", "MES 09-26", "MESM6", "CME_MINI:MES1!",
"CON.F.US.MES.Z25"). Everything here is deterministic and testable.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore


# ----------------------------------------------------------------- headers

def norm_header(h: str) -> str:
    """'B/S' -> 'bs', 'Market pos.' -> 'marketpos', 'Avg. Buy' -> 'avgbuy'."""
    return re.sub(r"[^a-z0-9]", "", (h or "").lower())


# --------------------------------------------------------------------- csv

def read_table(source: str | Path | bytes) -> tuple[list[str], list[dict], dict]:
    """Read a delimited export. Returns (normalized headers, rows keyed by
    normalized header, info). Sniffs delimiter, strips BOM, skips title rows
    above the real header, ignores fully empty rows."""
    if isinstance(source, (str, Path)) and Path(source).exists():
        raw = Path(source).read_bytes()
    elif isinstance(source, bytes):
        raw = source
    else:
        raw = str(source).encode()
    text = raw.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    if not lines:
        raise ValueError("file is empty")

    # delimiter: pick the candidate that yields the most consistent wide rows
    sample = lines[:20]
    best = (",", 0)
    for d in (",", ";", "\t", "|"):
        counts = [ln.count(d) for ln in sample if ln.strip()]
        if counts:
            common = max(set(counts), key=counts.count)
            score = common * counts.count(common)
            if common > 0 and score > best[1]:
                best = (d, score)
    delim = best[0]

    # header line: first line whose field count matches the dominant width
    widths = [len(next(csv.reader([ln], delimiter=delim))) for ln in sample if ln.strip()]
    dominant = max(set(widths), key=widths.count) if widths else 1
    header_idx = 0
    for i, ln in enumerate(lines[:20]):
        if ln.strip() and len(next(csv.reader([ln], delimiter=delim))) >= max(2, dominant - 1):
            header_idx = i
            break

    reader = csv.reader(io.StringIO("\n".join(lines[header_idx:])), delimiter=delim)
    raw_headers = next(reader)
    headers = [norm_header(h) for h in raw_headers]
    rows = []
    for cells in reader:
        if not any(c.strip() for c in cells):
            continue
        row = {}
        for h, raw_h, v in zip(headers, raw_headers, cells):
            if h and h not in row:
                row[h] = v.strip()
        row["__raw__"] = dict(zip(raw_headers, cells))
        rows.append(row)
    info = {"delimiter": delim, "header_line": header_idx, "raw_headers": raw_headers}
    return headers, rows, info


# ----------------------------------------------------------------- numbers

_THOUSANDS_COMMA = re.compile(r"^\d{1,3}(,\d{3})+$")


def parse_number(value: str | float | int | None, *, decimal_comma: bool | None = None) -> float | None:
    """'$1,234.50' 1234.5 · '7200,75' 7200.75 · '1.234,56' 1234.56 ·
    '0,62 $' 0.62 · '(12.30)' -12.3 · '-$5' -5 · '' None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    v = value.strip()
    if not v:
        return None
    neg = False
    if v.startswith("(") and v.endswith(")"):
        neg, v = True, v[1:-1]
    v = re.sub(r"[^\d,.\-+]", "", v)  # drop currency symbols, spaces, letters
    if v.startswith("-"):
        neg, v = (not neg), v[1:]
    v = v.lstrip("+")
    if not v:
        return None
    if "," in v and "." in v:
        # the LAST separator is the decimal separator
        if v.rfind(",") > v.rfind("."):
            v = v.replace(".", "").replace(",", ".")
        else:
            v = v.replace(",", "")
    elif "," in v:
        if decimal_comma is True:
            v = v.replace(",", ".")
        elif decimal_comma is False or _THOUSANDS_COMMA.match(v):
            v = v.replace(",", "")
        else:
            v = v.replace(",", ".")
    out = float(v)
    return -out if neg else out


def file_uses_decimal_comma(rows: list[dict], fields: list[str], delimiter: str) -> bool:
    """Infer European decimals from the price-like columns of the whole file."""
    if delimiter == ";":
        votes_comma = 1
    else:
        votes_comma = 0
    votes_dot = 0
    for r in rows[:200]:
        for f in fields:
            v = (r.get(f) or "").strip()
            if re.search(r"\d,\d{1,2}(\D|$)", v) and not _THOUSANDS_COMMA.match(re.sub(r"[^\d,]", "", v)):
                votes_comma += 1
            elif re.search(r"\d\.\d", v):
                votes_dot += 1
    return votes_comma > votes_dot


# ------------------------------------------------------------------- dates

_DT_RE = re.compile(
    r"^\s*(?P<a>\d{1,4})[/\-.](?P<b>\d{1,2})[/\-.](?P<c>\d{2,4})"
    r"(?:[ T]+(?P<H>\d{1,2}):(?P<M>\d{2})(?::(?P<S>\d{2})(?:\.(?P<f>\d+))?)?)?"
    r"\s*(?P<ampm>[AaPp][Mm])?"
    r"\s*(?P<tz>Z|[+\-]\d{2}:?\d{2})?\s*$"
)


def infer_dayfirst(values: list[str]) -> tuple[bool | None, bool]:
    """Scan date strings: returns (dayfirst or None if undecidable, conflict)."""
    dayfirst = monthfirst = False
    for v in values:
        m = _DT_RE.match(v or "")
        if not m or len(m.group("a")) == 4:
            continue
        a, b = int(m.group("a")), int(m.group("b"))
        if a > 12:
            dayfirst = True
        if b > 12:
            monthfirst = True
    if dayfirst and monthfirst:
        return None, True
    if dayfirst:
        return True, False
    if monthfirst:
        return False, False
    return None, False


def resolve_tz(tz: str | tzinfo | None) -> tzinfo | None:
    """IANA name -> tzinfo. None means 'this computer's local time'."""
    if tz is None or isinstance(tz, tzinfo):
        return tz
    if tz.upper() == "UTC":
        return timezone.utc
    if ZoneInfo is None:
        raise ValueError("zoneinfo unavailable; pass a fixed offset instead")
    return ZoneInfo(tz)


def parse_datetime(value: str | float | int, *, dayfirst: bool = False,
                   tz: tzinfo | None = None) -> str:
    """Any common export timestamp -> ISO-8601 UTC 'YYYY-MM-DDTHH:MM:SS.mmmZ'.
    Naive values are interpreted in `tz` (None = local system time, DST-aware).
    Explicit offsets in the value always win."""
    if value is None or str(value).strip() == "":
        raise ValueError("empty timestamp")
    s = str(value).strip()
    dt: datetime | None = None

    if re.fullmatch(r"\d{10}(\.\d+)?", s):          # epoch seconds
        dt = datetime.fromtimestamp(float(s), tz=timezone.utc)
    elif re.fullmatch(r"\d{13}", s):                  # epoch milliseconds
        dt = datetime.fromtimestamp(int(s) / 1000, tz=timezone.utc)
    else:
        m = _DT_RE.match(s)
        if m:
            a, b, c = m.group("a"), m.group("b"), m.group("c")
            if len(a) == 4:
                y, mo, d = int(a), int(b), int(c)
            else:
                y = int(c) + (2000 if len(c) == 2 else 0)
                mo, d = (int(b), int(a)) if dayfirst else (int(a), int(b))
                if mo > 12 and d <= 12:  # value itself proves the order
                    mo, d = d, mo
            H = int(m.group("H") or 0)
            M = int(m.group("M") or 0)
            S = int(m.group("S") or 0)
            us = int((m.group("f") or "0")[:6].ljust(6, "0"))
            ampm = (m.group("ampm") or "").lower()
            if ampm == "pm" and H < 12:
                H += 12
            elif ampm == "am" and H == 12:
                H = 0
            dt = datetime(y, mo, d, H, M, S, us)
            tzs = m.group("tz")
            if tzs:
                if tzs == "Z":
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    sign = -1 if tzs[0] == "-" else 1
                    digits = tzs[1:].replace(":", "")
                    off = timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
                    dt = dt.replace(tzinfo=timezone(sign * off))
        else:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))

    if dt.tzinfo is None:
        if tz is None:
            dt = dt.astimezone()          # local system time, DST-aware
        else:
            dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ------------------------------------------------------------------- sides

_BUY = {"buy", "b", "bot", "bought", "long", "bid", "buytoopen", "buytoclose",
        "buytocover", "cover"}
_SELL = {"sell", "s", "sld", "sold", "short", "ask", "offer", "selltoopen",
         "selltoclose", "sellshort", "shortsell"}


def parse_side(value: str) -> str:
    v = re.sub(r"[^a-z0-9]", "", (value or "").lower())
    if v in _BUY:
        return "buy"
    if v in _SELL:
        return "sell"
    if v.startswith("buy"):
        return "buy"
    if v.startswith("sell"):
        return "sell"
    raise ValueError(f"unrecognized side {value!r}")


# ------------------------------------------------------------- instruments

_MONTHS = {"JAN": "F", "FEB": "G", "MAR": "H", "APR": "J", "MAY": "K", "JUN": "M",
           "JUL": "N", "AUG": "Q", "SEP": "U", "OCT": "V", "NOV": "X", "DEC": "Z"}
_MONTH_NUM = {f"{i:02d}": c for i, c in enumerate("FGHJKMNQUVXZ", start=1)}
_FUT_CODE = re.compile(r"^([A-Z0-9]{1,4}?)([FGHJKMNQUVXZ])(\d{1,4})$")
_PROJECTX = re.compile(r"^CON\.F\.[A-Z]+\.([A-Z0-9]+)\.([FGHJKMNQUVXZ])(\d{1,2})$")


def parse_instrument(value: str) -> tuple[str, str]:
    """Return (root symbol, normalized contract)."""
    s = (value or "").strip().upper()
    if not s:
        raise ValueError("empty instrument")
    m = _PROJECTX.match(s)
    if m:
        return m.group(1), f"{m.group(1)}{m.group(2)}{m.group(3)}"
    if ":" in s:                       # TradingView 'CME_MINI:MES1!', 'NASDAQ:AAPL'
        s = s.rsplit(":", 1)[1]
    s = re.sub(r"\d!$", "", s)         # continuous-contract suffix
    parts = s.split()
    if len(parts) == 2:
        root, exp = parts
        mm = re.fullmatch(r"(\d{2})-(\d{2})", exp)      # NinjaTrader '09-26'
        if mm and mm.group(1) in _MONTH_NUM:
            return root, f"{root}{_MONTH_NUM[mm.group(1)]}{mm.group(2)}"
        mm = re.fullmatch(r"([A-Z]{3})(\d{2})", exp)    # 'JUN26'
        if mm and mm.group(1) in _MONTHS:
            return root, f"{root}{_MONTHS[mm.group(1)]}{mm.group(2)}"
        return root, s
    m = _FUT_CODE.match(s)
    if m:
        return m.group(1), s
    return s, s


# --------------------------------------------------------------- utilities

def first(row: dict, *keys: str) -> str | None:
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            return v
    return None
