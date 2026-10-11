"""Live connection runner, tested against scripted fake servers."""
import asyncio
import json

import pytest

from completejournal import live

RS = live.RS


class FakeWS:
    """Scripted server: `script` is a list of frames to deliver; when it runs
    out, recv() either blocks (stay connected) or raises (drop)."""

    def __init__(self, script, drop_after=False):
        self.script, self.drop_after, self.sent, self.closed = list(script), drop_after, [], False

    async def send(self, msg):
        self.sent.append(msg)

    async def recv(self):
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        if self.drop_after:
            raise ConnectionResetError("network dropped")
        await asyncio.sleep(3600)

    async def close(self):
        self.closed = True


async def _run(protocol, sockets, *, until, timeout=5.0, **kw):
    status = live.LiveStatus(protocol.name)
    stop = asyncio.Event()
    sweeps = []
    conns = iter(sockets)

    async def connect(url):
        return next(conns)

    def sweep():
        sweeps.append(1)
        return 1

    task = asyncio.create_task(live.run_stream(protocol, sweep, status, stop, connect=connect,
                                               debounce_seconds=0.05, max_backoff=0.05, **kw))
    deadline = asyncio.get_event_loop().time() + timeout
    while not until(status, sweeps) and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.02)
    stop.set()
    await asyncio.wait_for(task, 3)
    return status, sweeps


def tv_fill_frame():
    return "a" + json.dumps([{"e": "props", "d": {"entityType": "fill", "eventType": "Created",
                                                  "entity": {"id": 1, "qty": 1}}}])


def test_tradovate_authorize_sync_and_fill_triggers_sweep():
    ws = FakeWS(["o", 'a[{"s":200,"i":0}]', "h", tv_fill_frame()])
    proto = live.TradovateProtocol("tok", 42)
    status, sweeps = asyncio.run(_run(proto, [ws], until=lambda s, sw: len(sw) >= 2))
    assert ws.sent[0] == "authorize\n0\n\ntok"
    assert ws.sent[1].startswith("user/syncrequest\n1\n\n") and '"users": [42]' in ws.sent[1]
    assert len(sweeps) >= 2           # one catch-up on connect, one for the fill
    assert status.fills_added >= 2 and status.last_event_at and status.state == "stopped"


def test_tradovate_bad_credentials_stop_without_retry_storm():
    ws = FakeWS(["o", 'a[{"s":401,"i":0,"d":"Access denied"}]'])
    status, sweeps = asyncio.run(_run(live.TradovateProtocol("bad", 1), [ws],
                                      until=lambda s, sw: s.state == "error"))
    assert status.state == "error" and "authorization failed" in status.last_error
    assert sweeps == [] and status.reconnects == 0


def test_reconnects_and_catches_up_after_drop():
    first = FakeWS(["o", 'a[{"s":200,"i":0}]'], drop_after=True)
    second = FakeWS(["o", 'a[{"s":200,"i":0}]'])
    status, sweeps = asyncio.run(_run(live.TradovateProtocol("t", 1), [first, second],
                                      until=lambda s, sw: s.reconnects >= 1 and len(sw) >= 2))
    assert status.reconnects == 1
    assert len(sweeps) >= 2            # each (re)connect runs a catch-up sync
    assert first.closed
    assert any("network dropped" in h for h in status.history)


def test_projectx_signalr_handshake_subscribe_and_trade_event():
    trade = json.dumps({"type": 1, "target": "GatewayUserTrade", "arguments": [{"id": 9}]}) + RS
    other = json.dumps({"type": 1, "target": "GatewayUserOrder", "arguments": [{}]}) + RS
    ws = FakeWS(["{}" + RS, other, trade])
    proto = live.ProjectXProtocol("jwt", 777)
    status, sweeps = asyncio.run(_run(proto, [ws], until=lambda s, sw: len(sw) >= 2))
    assert ws.sent[0] == json.dumps({"protocol": "json", "version": 1}) + RS
    targets = [json.loads(m.rstrip(RS))["target"] for m in ws.sent[1:5]]
    assert targets == ["SubscribeAccounts", "SubscribeOrders", "SubscribePositions", "SubscribeTrades"]
    assert json.loads(ws.sent[4].rstrip(RS))["arguments"] == [777]
    assert proto.url().endswith("?access_token=jwt")
    assert len(sweeps) >= 2


def test_projectx_order_events_alone_do_not_trigger_sync():
    proto = live.ProjectXProtocol("jwt", 1)
    assert proto.fill_events(json.dumps({"type": 1, "target": "GatewayUserOrder"}) + RS) == 0
    assert proto.fill_events(json.dumps({"type": 6}) + RS) == 0
    with pytest.raises(ConnectionError):
        proto.fill_events(json.dumps({"type": 7, "error": "bye"}) + RS)


def test_heartbeats_are_sent():
    ws = FakeWS(["o", 'a[{"s":200,"i":0}]'])
    proto = live.TradovateProtocol("t", 1)
    proto.heartbeat_seconds = 0.05
    asyncio.run(_run(proto, [ws], until=lambda s, sw: ws.sent.count("[]") >= 2))
    assert ws.sent.count("[]") >= 2


def test_manager_start_status_stop():
    mgr = live.LiveManager()
    ws = FakeWS(["o", 'a[{"s":200,"i":0}]'])

    async def connect(url):
        return ws

    mgr.start("tradovate", live.TradovateProtocol("t", 1), lambda: 0, connect=connect)
    for _ in range(100):
        if mgr.status().get("tradovate", {}).get("state") == "live":
            break
        import time; time.sleep(0.02)
    assert mgr.status()["tradovate"]["state"] == "live"
    mgr.stop("tradovate")
    assert "tradovate" not in mgr.status()


def test_end_to_end_projectx_live_fill_lands_in_journal(tmp_path):
    """Credentials -> REST login -> live socket -> trade event -> REST sync -> trades table."""
    import httpx
    from completejournal import db as dbmod, live_setup

    logins = []

    def rest(request):
        if request.url.path == "/api/Auth/loginKey":
            logins.append(1)
            return httpx.Response(200, json={"success": True, "token": f"jwt{len(logins)}"})
        if request.url.path == "/api/Trade/search":
            return httpx.Response(200, json={"success": True, "trades": [
                {"id": 1, "contractId": "CON.F.US.MES.Z26", "creationTimestamp": "2026-10-09T14:31:00Z",
                 "price": 5000.0, "fees": 0.37, "side": 0, "size": 1, "orderId": 1},
                {"id": 2, "contractId": "CON.F.US.MES.Z26", "creationTimestamp": "2026-10-09T14:39:00Z",
                 "price": 5004.0, "fees": 0.37, "side": 1, "size": 1, "orderId": 2, "profitAndLoss": 20.0}]})
        return httpx.Response(404)

    creds = live_setup.validate("projectx", {"username": "u", "api_key": "k", "account_id": "777"})
    proto, sweep = live_setup.build("projectx", creds, tmp_path / "j.db",
                                    transport=httpx.MockTransport(rest))
    trade_evt = json.dumps({"type": 1, "target": "GatewayUserTrade", "arguments": [{}]}) + RS
    ws = FakeWS(["{}" + RS, trade_evt])

    async def connect(url):
        assert url.endswith("access_token=jwt1")       # fresh token used for the socket
        return ws

    mgr = live.LiveManager()
    mgr.start("projectx", proto, sweep, connect=connect, debounce_seconds=0.05)
    import time
    for _ in range(150):
        if mgr.status()["projectx"]["fills_added"] >= 2:
            break
        time.sleep(0.02)
    mgr.stop("projectx")
    conn = dbmod.connect(tmp_path / "j.db")
    t = conn.execute("SELECT * FROM trades").fetchone()
    assert t["symbol"] == "MES" and t["realized_pnl"] == pytest.approx(20.0)
    assert conn.execute("SELECT name FROM accounts").fetchone()[0] == "TopstepX (live)"
    assert conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0] == 2   # deduped across sweeps


def test_live_api_validates_and_reports(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from completejournal.api import create_app
    monkeypatch.setenv("COMPLETEJOURNAL_HOME", str(tmp_path / "home"))
    c = TestClient(create_app(tmp_path / "t.db"))
    r = c.post("/api/live/connect", json={"platform": "tradovate", "credentials": {"username": "u"}})
    assert r.status_code == 400 and "missing" in r.json()["detail"]
    r = c.post("/api/live/connect", json={"platform": "nope", "credentials": {}})
    assert r.status_code == 400
    st = c.get("/api/live/status").json()
    assert st["connections"] == {} and "Read-only" in st["note"]


def test_rejected_login_stops_instead_of_retrying_forever(tmp_path):
    import httpx
    from completejournal import live_setup

    def rest(request):
        return httpx.Response(200, json={"success": False, "errorCode": 3, "errorMessage": "Invalid credentials"})

    creds = live_setup.validate("projectx", {"username": "u", "api_key": "wrong", "account_id": "1"})
    proto, sweep = live_setup.build("projectx", creds, tmp_path / "j.db", transport=httpx.MockTransport(rest))

    async def connect(url):
        raise AssertionError("must not open a socket without a valid login")

    status, sweeps = asyncio.run(_run(proto, [], until=lambda s, sw: s.state == "error"))
    assert status.state == "error" and "auth failed" in status.last_error
    assert status.reconnects == 0 and sweeps == []
