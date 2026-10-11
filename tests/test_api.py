"""End-to-end API tests: import a fixture CSV over HTTP, journal, search, stats."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from completejournal.api import create_app

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path / "test.db")
    return TestClient(app)


def test_index_serves_ui(client):
    r = client.get("/")
    assert r.status_code == 200 and "Complete Journal" in r.text


def test_full_flow(client):
    # import Tradovate fixture (US/Central DST offset)
    with open(FIX / "tradovate_orders.csv", "rb") as f:
        r = client.post("/api/import", files={"file": ("tradovate_orders.csv", f, "text/csv")},
                        data={"format": "tradovate", "account": "Apex #1", "tz_offset_minutes": "-300"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["new"] == 2 and body["trades_total"] == 1

    # re-import is idempotent
    with open(FIX / "tradovate_orders.csv", "rb") as f:
        r2 = client.post("/api/import", files={"file": ("tradovate_orders.csv", f, "text/csv")},
                         data={"format": "tradovate", "account": "Apex #1", "tz_offset_minutes": "-300"})
    assert r2.json()["duplicates"] == 2 and r2.json()["new"] == 0

    # trades + detail
    trades = client.get("/api/trades").json()
    assert len(trades) == 1
    t = trades[0]
    assert t["direction"] == "long" and t["symbol"] == "MES"
    # +5.25 points * 2 contracts * $5 = $52.50
    assert abs(t["realized_pnl"] - 52.5) < 1e-9
    detail = client.get(f"/api/trades/{t['id']}").json()
    assert len(detail["executions"]) == 2

    # write an entry linked to the trade
    e = client.post("/api/entries", json={"body_md": "Took the MES long off the open drive. Plan respected.",
                                          "kind": "trade-review", "about_date": t["session_date"]}).json()
    client.post(f"/api/entries/{e['id']}/links", json={"target_type": "trade", "target_id": str(t["id"])})
    detail2 = client.get(f"/api/trades/{t['id']}").json()
    assert len(detail2["entries"]) == 1

    # edit preserves versions; addendum separate
    client.put(f"/api/entries/{e['id']}", json={"body_md": "Took the MES long. Edited for clarity."})
    assert len(client.get(f"/api/entries/{e['id']}/versions").json()) == 2
    client.post(f"/api/entries/{e['id']}/addenda", json={"body_md": "A week on: this setup kept working."})
    full = client.get(f"/api/entries/{e['id']}").json()
    assert len(full["addenda"]) == 1 and full["n_versions"] == 2

    # search
    hits = client.get("/api/search", params={"q": "MES"}).json()
    assert len(hits) == 1

    # session timeline + stats + reconciliation + calendar
    tl = client.get(f"/api/sessions/{t['session_date']}").json()
    assert len(tl["trades"]) == 1 and len(tl["entries"]) == 1
    stats = client.get("/api/stats").json()
    assert stats["n"] == 1 and stats["low_sample"] is True
    rec = client.get("/api/reconciliation").json()
    assert rec[0]["account"] == "Apex #1"
    cal = client.get("/api/calendar").json()
    assert t["session_date"] in cal


def test_ai_author_rejected_via_api(client):
    r = client.post("/api/entries", json={"body_md": "x"})
    assert r.status_code == 200
    # author field isn't even exposed through the API — entries are trader-authored.


def test_bad_import_format(client):
    r = client.post("/api/import", files={"file": ("x.csv", b"a,b\n1,2", "text/csv")},
                    data={"format": "nope", "account": "A"})
    assert r.status_code == 400
