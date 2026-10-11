"""Sync adapter tests with mocked HTTP transports: full mapping + ingest flow,
token refresh, read-only surface. No network access required or used."""
import json

import httpx
import pytest

from completejournal import db as dbmod
from completejournal.sync import projectx, tradovate


@pytest.fixture()
def conn():
    c = dbmod.connect(":memory:")
    yield c
    c.close()


# ------------------------------------------------------------- Tradovate

def _tradovate_transport(state):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        state.setdefault("calls", []).append(path)
        if path.endswith("/auth/accesstokenrequest"):
            state["auths"] = state.get("auths", 0) + 1
            return httpx.Response(200, json={"accessToken": f"tok{state['auths']}",
                                             "expirationTime": "2099-01-01T00:00:00Z"})
        auth = request.headers.get("Authorization", "")
        if state.get("expire_first") and auth == "Bearer tok1":
            return httpx.Response(401)
        if path.endswith("/fill/list"):
            return httpx.Response(200, json=[
                {"id": 11, "orderId": 7, "contractId": 101, "timestamp": "2026-10-09T14:30:05.000Z",
                 "action": "Buy", "qty": 2, "price": 5000.25, "accountId": 5},
                {"id": 12, "orderId": 8, "contractId": 101, "timestamp": "2026-10-09T14:45:10.000Z",
                 "action": "Sell", "qty": 2, "price": 5005.50, "accountId": 5},
            ])
        if path.endswith("/fillFee/list"):
            return httpx.Response(200, json=[
                {"id": 11, "commission": 1.04, "exchangeFee": 0.30, "nfaFee": 0.02},
                {"id": 12, "commission": 1.04, "exchangeFee": 0.30, "nfaFee": 0.02},
            ])
        if path.endswith("/contract/item"):
            return httpx.Response(200, json={"id": 101, "name": "MESZ6"})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_tradovate_sync_end_to_end(conn):
    state = {}
    client = tradovate.TradovateClient("u", "p", "cid", "sec",
                                       transport=_tradovate_transport(state))
    result = tradovate.sync(conn, client, "Tradovate Live")
    assert result["fetched"] == 2 and result["new"] == 2
    assert result["trades_total"] == 1
    t = conn.execute("SELECT * FROM trades").fetchone()
    assert t["symbol"] == "MES"
    assert t["realized_pnl"] == pytest.approx(5.25 * 2 * 5.0)
    assert t["fees"] == pytest.approx(2.72)
    # raw payload preserved verbatim
    raw = json.loads(conn.execute("SELECT raw_payload FROM executions LIMIT 1").fetchone()[0])
    assert raw["contractId"] == 101
    # re-sync is idempotent
    r2 = tradovate.sync(conn, client, "Tradovate Live")
    assert r2["new"] == 0 and r2["duplicates"] == 2


def test_tradovate_reauth_on_401(conn):
    state = {"expire_first": True}
    client = tradovate.TradovateClient("u", "p", "cid", "sec",
                                       transport=_tradovate_transport(state))
    client.authenticate()           # gets tok1
    fills, _ = client.fetch_fills() # 401 on tok1 -> re-auth -> tok2
    assert state["auths"] >= 2 and len(fills) == 2


def test_tradovate_has_no_order_endpoints():
    src = open(tradovate.__file__).read()
    for forbidden in ("placeorder", "modifyorder", "cancelorder", "liquidate"):
        assert forbidden not in src.lower().replace(" ", "")


# -------------------------------------------------------------- ProjectX

def _projectx_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/Auth/loginKey":
            return httpx.Response(200, json={"success": True, "token": "px-tok"})
        if path == "/api/Account/search":
            return httpx.Response(200, json={"success": True, "accounts": [
                {"id": 42, "name": "TOPSTEP-50K-1", "balance": 50210.0}]})
        if path == "/api/Trade/search":
            body = json.loads(request.content)
            assert body["accountId"] == 42
            return httpx.Response(200, json={"success": True, "trades": [
                {"id": 901, "accountId": 42, "contractId": "CON.F.US.MNQ.Z25",
                 "creationTimestamp": "2026-10-09T14:31:00+00:00", "price": 21500.75,
                 "profitAndLoss": None, "fees": 0.74, "side": 0, "size": 1, "orderId": 55},
                {"id": 902, "accountId": 42, "contractId": "CON.F.US.MNQ.Z25",
                 "creationTimestamp": "2026-10-09T14:39:30+00:00", "price": 21510.25,
                 "profitAndLoss": 19.0, "fees": 0.74, "side": 1, "size": 1, "orderId": 56},
            ]})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_parse_contract_id():
    assert projectx.parse_contract_id("CON.F.US.MES.Z25") == ("MES", "MESZ25")
    assert projectx.parse_contract_id("CON.F.US.MNQ.H26") == ("MNQ", "MNQH26")
    assert projectx.parse_contract_id("weird")[0] == "weird"


def test_projectx_sync_end_to_end(conn):
    client = projectx.ProjectXClient("user", "key", transport=_projectx_transport())
    accounts = client.accounts()
    assert accounts[0]["id"] == 42
    result = projectx.sync(conn, client, "Topstep 50k #1", 42,
                           "2026-10-09T00:00:00Z", "2026-10-10T00:00:00Z")
    assert result["fetched"] == 2 and result["trades_total"] == 1
    assert result["platform_reported_pnl"] == 19.0
    t = conn.execute("SELECT * FROM trades").fetchone()
    assert t["symbol"] == "MNQ" and t["direction"] == "long"
    # our computed: 9.5 pts * $2 (MNQ) = $19.00 — matches platform P&L exactly
    assert t["realized_pnl"] == pytest.approx(19.0)
    assert t["net_pnl"] == pytest.approx(19.0 - 1.48)


def test_projectx_has_no_order_endpoints():
    src = open(projectx.__file__).read().lower().replace(" ", "")
    for forbidden in ("order/place", "order/modify", "order/cancel", "position/close"):
        assert forbidden not in src
