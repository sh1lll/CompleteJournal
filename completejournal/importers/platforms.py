"""Named platform presets — thin wrappers over the auto-detecting engine.

Kept for explicit selection (CLI --format / API format=...). All parsing logic
lives in auto.py + parsing.py, so presets and auto-detect can never diverge.
"""
from __future__ import annotations

from datetime import timedelta, timezone
from pathlib import Path

from .auto import parse_file


def _wrap(force_format: str | None):
    def parser(path: str | Path, *, tz_offset_minutes: int | None = None, tz: str | None = None):
        if tz is None and tz_offset_minutes is not None:
            tz = timezone(timedelta(minutes=tz_offset_minutes))
        res = parse_file(path, tz=tz, force_format=force_format)
        return res.executions, res.warnings
    return parser


parse_auto = _wrap(None)
parse_tradovate_orders = _wrap("tradovate_orders")
parse_tradovate_position_history = _wrap("paired")
parse_ninjatrader_executions = _wrap("ninjatrader_executions")
parse_ninjatrader_trades = _wrap("ninjatrader_trades")
parse_rithmic_orders = _wrap("rithmic_orders")
parse_projectx_orders = _wrap("projectx_orders")
parse_projectx_trades = _wrap("projectx_trades")
parse_tradingview_performance = _wrap("paired")

# name -> (parser, source label). "auto" is the recommended default.
REGISTRY = {
    "auto": (parse_auto, "file:auto"),
    "tradovate": (parse_tradovate_orders, "csv:tradovate"),
    "tradovate-positions": (parse_tradovate_position_history, "csv:tradovate-positions"),
    "ninjatrader": (parse_ninjatrader_executions, "csv:ninjatrader"),
    "ninjatrader-trades": (parse_ninjatrader_trades, "csv:ninjatrader-trades"),
    "rithmic": (parse_rithmic_orders, "csv:rithmic"),
    "projectx": (parse_projectx_orders, "csv:projectx"),
    "projectx-trades": (parse_projectx_trades, "csv:projectx-trades"),
    "tradingview": (parse_tradingview_performance, "csv:tradingview"),
}

FORCE_FORMAT = {
    "auto": None,
    "tradovate": "tradovate_orders",
    "tradovate-positions": "paired",
    "ninjatrader": "ninjatrader_executions",
    "ninjatrader-trades": "ninjatrader_trades",
    "rithmic": "rithmic_orders",
    "projectx": "projectx_orders",
    "projectx-trades": "projectx_trades",
    "tradingview": "paired",
}
