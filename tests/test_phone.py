"""Phone quick-capture: pairing, least-privilege access, idempotent capture."""
import socket
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from completejournal import db as dbmod, phone
from completejournal.api import create_app

PHONE_IP = ("192.168.1.50", 50123)
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 40


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPLETEJOURNAL_HOME", str(tmp_path / "home"))
    db = tmp_path / "j.db"
    app = create_app(db)
    local = TestClient(app)
    remote = TestClient(app, client=PHONE_IP)
    return db, local, remote


def _enable_without_listener(db):
    c = dbmod.connect(db)
    phone.set_setting(c, "phone_enabled", "1")
    tok = phone.get_token(c)
    c.close()
    return tok


def test_remote_device_blocked_when_phone_access_off(env):
    db, local, remote = env
    assert remote.get("/capture").status_code == 403
    assert remote.get("/api/entries").status_code == 403
    assert remote.get("/api/health").status_code == 403
    assert local.get("/api/entries").status_code == 200        # the computer itself is unaffected


def test_pairing_flow_and_least_privilege(env):
    db, local, remote = env
    tok = _enable_without_listener(db)
    assert remote.get("/capture").status_code == 403            # not paired yet
    assert "Pair this phone" in remote.get("/capture").text
    assert remote.get("/capture?pair=wrong", follow_redirects=False).status_code == 403
    r = remote.get(f"/capture?pair={tok}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/capture"   # token removed from URL
    assert "httponly" in r.headers["set-cookie"].lower()
    assert remote.get("/capture").status_code == 200           # cookie now set

    # allowed: capture, photo upload, recent captures, PWA files
    up = remote.post("/api/attachments", files={"file": ("p.png", PNG, "image/png")})
    assert up.status_code == 200
    cap = remote.post("/api/capture", json={"body": "Level holding at 5010 @MES", "client_id": "a1",
                                             "attachment_ids": [up.json()["id"]]})
    assert cap.status_code == 200, cap.text
    assert remote.get("/api/capture/recent").status_code == 200
    for p in ("/manifest.webmanifest", "/sw.js", "/icon.svg"):
        assert remote.get(p).status_code == 200

    # forbidden even when paired: reading the journal, trades, settings, keys, exports, photos
    for method, path in [("GET", "/"), ("GET", "/api/entries"), ("GET", "/api/trades"),
                         ("GET", "/api/search?q=x"), ("GET", "/api/phone/status"),
                         ("POST", "/api/phone/unpair-all"), ("POST", "/api/ai/key"),
                         ("GET", "/api/live/status"), ("GET", f"/api/attachments/{up.json()['id']}"),
                         ("DELETE", "/api/demo"), ("GET", "/api/reports/week/2026-10-09")]:
        assert remote.request(method, path).status_code == 403, path

    # unpair-all from the computer cuts the phone off
    assert local.post("/api/phone/unpair-all").status_code == 200
    assert remote.post("/api/capture", json={"body": "x", "client_id": "a2"}).status_code == 403


def test_capture_is_idempotent_and_keeps_phone_time(env):
    db, local, remote = env
    tok = _enable_without_listener(db)
    remote.get(f"/capture?pair={tok}")
    written = (datetime.now(timezone.utc) - timedelta(minutes=42)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    a = remote.post("/api/capture", json={"body": "Offline note", "client_id": "q-1", "captured_at": written}).json()
    b = remote.post("/api/capture", json={"body": "Offline note", "client_id": "q-1", "captured_at": written}).json()
    assert a["entry_id"] == b["entry_id"] and b["duplicate"] is True     # retried send lands once
    e = local.get(f"/api/entries/{a['entry_id']}").json()["entry"]
    assert e["written_at"] == written and e["kind"] == "intraday"
    assert local.get("/api/entries").json()[0]["id"] == a["entry_id"]


def test_capture_rejects_empty_and_clamps_future_clock(env):
    db, local, remote = env
    c = dbmod.connect(db)
    with pytest.raises(ValueError):
        phone.save_capture(c, "  ", client_id="x")
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    r = phone.save_capture(c, "clock is wrong", client_id="y", captured_at=future)
    assert r["written_at"] < future                               # phone clock ignored when implausible
    c.close()


def test_enable_listener_status_qr_and_disable(env):
    db, local, remote = env
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    st = local.post("/api/phone/enable", json={"port": port}).json()
    try:
        assert st["enabled"] and st["port"] == port
        assert "/capture?pair=" in st["pair_url"] and st["qr_svg"].startswith("<svg")
        for _ in range(50):
            if local.get("/api/phone/status").json()["listening"]:
                break
            import time; time.sleep(0.05)
        assert local.get("/api/phone/status").json()["listening"] is True
    finally:
        assert local.post("/api/phone/disable").json()["enabled"] is False
    assert local.get("/api/phone/status").json()["listening"] is False


def test_loopback_detection():
    assert phone.is_loopback("127.0.0.1") and phone.is_loopback("::1")
    assert not phone.is_loopback("192.168.1.50") and not phone.is_loopback("10.0.0.2")
    assert not phone.is_loopback(None) and not phone.is_loopback("garbage")


def test_enable_reports_port_conflict(env):
    db, local, remote = env
    with socket.socket() as blocker:
        blocker.bind(("0.0.0.0", 0))
        blocker.listen()
        port = blocker.getsockname()[1]
        r = local.post("/api/phone/enable", json={"port": port})
        assert r.status_code == 409 and "could not listen" in r.json()["detail"]
    assert local.get("/api/phone/status").json()["enabled"] is False
