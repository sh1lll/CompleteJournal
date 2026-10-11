"""Tests for the Databento fetcher (mocked transport) and screenshot import."""
import json

import httpx
import pytest

from completejournal import db as dbmod, screenshots
from completejournal.sync import databento

PNG = b"\x89PNG\r\n\x1a\n" + b"shotdata" * 8


@pytest.fixture()
def conn():
    c = dbmod.connect(":memory:")
    yield c
    c.close()


def test_databento_fetch_and_store(conn):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v0/timeseries.get_range"
        assert request.url.params["schema"] == "ohlcv-1m"
        assert request.url.params["symbols"] == "MES.c.0"
        # one JSON object per line, fixed-point 1e-9 prices, ns timestamps
        base_ns = 1791639000_000000000  # 2026-10-10T13:30:00Z-ish
        lines = []
        for i in range(3):
            lines.append(json.dumps({
                "hd": {"ts_event": base_ns + i * 60_000000000},
                "open": int(5000.25e9) + i, "high": int(5002.00e9) + i,
                "low": int(4999.50e9), "close": int(5001.00e9) + i, "volume": 120 + i,
            }))
        return httpx.Response(200, text="\n".join(lines))

    n = databento.fetch_ohlcv(conn, "mes", "2026-10-10T13:00:00Z", "2026-10-10T14:00:00Z",
                              api_key="db-test-key", transport=httpx.MockTransport(handler))
    assert n == 3
    row = conn.execute("SELECT * FROM bars ORDER BY ts_utc LIMIT 1").fetchone()
    assert row["symbol"] == "MES" and row["source"] == "databento"
    assert row["open"] == pytest.approx(5000.25, abs=1e-6)


def test_databento_requires_key(conn, monkeypatch):
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DATABENTO_API_KEY"):
        databento.fetch_ohlcv(conn, "MES", "a", "b")


def test_screenshot_folder_import(conn, tmp_path):
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "esz_entry.png").write_bytes(PNG)
    (shots / "esz_exit.png").write_bytes(PNG + b"2")
    (shots / "notes.txt").write_text("not an image", encoding="utf-8")
    root = tmp_path / "att"

    res = screenshots.import_folder(conn, root, shots, date="2026-10-09")
    assert res["imported"] == 2 and res["days"] == ["2026-10-09"]
    assert len(res["entry_ids"]) == 1
    entry = conn.execute("SELECT * FROM entries WHERE id=?", (res["entry_ids"][0],)).fetchone()
    assert entry["kind"] == "intraday" and entry["about_date"] == "2026-10-09"
    assert "/api/attachments/" in entry["body_md"]
    # the index entry auto-links to the session via the @date mention
    links = conn.execute("SELECT target_type, target_id FROM links WHERE entry_id=?",
                         (entry["id"],)).fetchall()
    assert ("session", "2026-10-09") in {(l[0], l[1]) for l in links}
    # attachments attributed to the entry
    assert conn.execute("SELECT COUNT(*) FROM attachments WHERE entry_id=?",
                        (entry["id"],)).fetchone()[0] == 2

    # second run: duplicates skipped, no new entry
    res2 = screenshots.import_folder(conn, root, shots, date="2026-10-09")
    assert res2["imported"] == 0 and res2["skipped_duplicates"] == 2 and res2["entry_ids"] == []
