"""Importer tests on synthetic fixtures matching documented export layouts.

⚠️ Roadmap A4: these fixtures mirror vendor-documented layouts; real export
files from each platform must still be run through the importers to confirm.
"""
from pathlib import Path

import pytest

from completejournal.importers import generic
from completejournal.importers.base import contract_root, parse_money, to_utc_iso
from completejournal.importers.platforms import (
    parse_ninjatrader_executions,
    parse_rithmic_orders,
    parse_tradovate_orders,
)

FIX = Path(__file__).parent / "fixtures"


def test_contract_root():
    assert contract_root("ESZ6") == "ES"
    assert contract_root("MESZ26") == "MES"
    assert contract_root("MNQH2026") == "MNQ"
    assert contract_root("6EZ5") == "6E"
    assert contract_root("ES") == "ES"


def test_parse_money():
    assert parse_money("$1,234.50") == 1234.5
    assert parse_money("(12.30)") == -12.3
    assert parse_money("") == 0.0
    assert parse_money(None) == 0.0


def test_to_utc_iso_applies_timezone():
    # 09:30 US/Central (UTC-5 in October) -> 14:30 UTC
    from datetime import timedelta, timezone
    out = to_utc_iso("10/09/2026 09:30:00", assume_tz=timezone(timedelta(hours=-5)))
    assert out.startswith("2026-10-09T14:30:00")


def test_tradovate_orders_csv():
    executions, warnings = parse_tradovate_orders(FIX / "tradovate_orders.csv", tz_offset_minutes=-300)
    assert warnings == []
    assert len(executions) == 2  # canceled + zero-fill rows skipped
    e = executions[0]
    assert e.symbol == "MES" and e.contract == "MESZ6"
    assert e.side == "buy" and e.qty == 2 and e.price == 5000.25
    assert e.ts_utc.startswith("2026-10-09T14:30:05")
    assert e.order_id == "100001"


def test_ninjatrader_executions_csv():
    executions, warnings = parse_ninjatrader_executions(FIX / "nt8_executions.csv", tz_offset_minutes=-300)
    # "10/9/2026" is genuinely ambiguous and nothing in the file proves the
    # order — the importer must say so rather than guess silently
    assert warnings == ["date order not provable from data; assumed month-first"]
    assert len(executions) == 2
    e = executions[0]
    assert e.symbol == "ES" and e.contract == "ESZ26"
    assert e.exec_id == "abc123"
    assert e.fees == 2.09


def test_rithmic_completed_orders_csv():
    executions, warnings = parse_rithmic_orders(FIX / "rtrader_completed.csv", tz_offset_minutes=-300)
    assert warnings == []
    assert len(executions) == 2
    e = executions[0]
    assert e.symbol == "NQ" and e.contract == "NQZ6"
    assert e.order_id == "RT-9001"


def test_generic_mapping_importer():
    executions, warnings = generic.parse(
        FIX / "weird_platform.csv",
        mapping={"contract": "Sym", "side": "Direction", "qty": "Lots",
                 "price": "FillPx", "ts": "When", "fees": "Comm"},
        side_values={"buy": ["long"], "sell": ["short"]},
        tz_offset_minutes=0,
    )
    assert warnings == []
    assert len(executions) == 2
    assert executions[0].symbol == "GC" and executions[0].side == "buy"
    assert executions[1].side == "sell"


def test_generic_importer_warns_not_crashes_on_bad_rows(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("Sym,Direction,Lots,FillPx,When\nESZ6,hold,1,100,2026-10-09 09:30:00\n", encoding="utf-8")
    executions, warnings = generic.parse(
        bad, mapping={"contract": "Sym", "side": "Direction", "qty": "Lots",
                      "price": "FillPx", "ts": "When"})
    assert executions == []
    assert len(warnings) == 1 and "side" in warnings[0]
