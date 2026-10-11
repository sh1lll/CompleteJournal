"""Tradovate REST adapter (read-only).

Endpoints used (base https://live.tradovateapi.com/v1 or demo.…):
  POST /auth/accesstokenrequest     — username/password + API key cid/sec
  GET  /account/list
  GET  /fill/list                   — CURRENT SESSION ONLY (platform limit:
                                      after ~5pm ET the session archives and
                                      this returns []); sweep daily and persist
  GET  /fillFee/list                — fees per fill, matched by fill id
  GET  /contract/item?id=           — contract name resolution (cached)

No order-placement endpoint exists in this module by design.
⚠️ Built from official docs + community references; not yet validated live.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import httpx

from ..db import get_or_create_account
from ..importers.base import NormalizedExecution, contract_root, ingest, to_utc_iso
from ..reconstruction import rebuild

LIVE = "https://live.tradovateapi.com/v1"
DEMO = "https://demo.tradovateapi.com/v1"


class TradovateClient:
    def __init__(
        self,
        username: str,
        password: str,
        cid: str,
        sec: str,
        *,
        base_url: str = LIVE,
        app_id: str = "CompleteJournal",
        app_version: str = "0.1.0",
        device_id: str = "completejournal",
        transport: httpx.BaseTransport | None = None,
    ):
        self._auth_body = {
            "name": username, "password": password,
            "appId": app_id, "appVersion": app_version,
            "deviceId": device_id, "cid": cid, "sec": sec,
        }
        self._http = httpx.Client(base_url=base_url, timeout=30, transport=transport)
        self._token: str | None = None
        self._contract_cache: dict[int, str] = {}

    # -------------------------------------------------------------- auth
    def authenticate(self) -> None:
        r = self._http.post("/auth/accesstokenrequest", json=self._auth_body)
        r.raise_for_status()
        data = r.json()
        if "errorText" in data and data["errorText"]:
            raise RuntimeError(f"Tradovate auth failed: {data['errorText']}")
        self._token = data["accessToken"]
        self.user_id = data.get("userId")

    def _get(self, path: str, **params) -> list | dict:
        if not self._token:
            self.authenticate()
        r = self._http.get(path, params=params or None,
                           headers={"Authorization": f"Bearer {self._token}"})
        if r.status_code == 401:  # token expired (~80-90 min) — re-auth once
            self.authenticate()
            r = self._http.get(path, params=params or None,
                               headers={"Authorization": f"Bearer {self._token}"})
        r.raise_for_status()
        return r.json()

    def fresh_credentials(self) -> tuple[str, int]:
        """Re-authenticate and return (token, userId) for the live connection."""
        self.authenticate()
        return self._token, int(self.user_id or 0)

    # -------------------------------------------------------------- data
    def accounts(self) -> list[dict]:
        return self._get("/account/list")

    def _contract_name(self, contract_id: int) -> str | None:
        if contract_id not in self._contract_cache:
            try:
                item = self._get("/contract/item", id=contract_id)
                self._contract_cache[contract_id] = item.get("name")
            except httpx.HTTPError:
                self._contract_cache[contract_id] = None
        return self._contract_cache[contract_id]

    def fetch_fills(self, account_id: int | None = None) -> tuple[list[NormalizedExecution], list[str]]:
        """Current-session fills, normalized. Fees joined from /fillFee/list."""
        warnings: list[str] = []
        fills = self._get("/fill/list")
        fees_by_fill: dict[int, float] = {}
        try:
            for ff in self._get("/fillFee/list"):
                total = sum(
                    float(ff.get(k) or 0.0)
                    for k in ("clearingFee", "exchangeFee", "nfaFee", "brokerageFee",
                              "commission", "orderRoutingFee", "ipFee")
                )
                fees_by_fill[ff.get("id")] = total
        except httpx.HTTPError as e:
            warnings.append(f"fillFee/list unavailable ({e}); fees recorded as 0")

        out: list[NormalizedExecution] = []
        for f in fills:
            if account_id is not None and f.get("accountId") != account_id:
                continue
            contract = self._contract_name(f["contractId"]) or str(f["contractId"])
            ts = f["timestamp"]
            if isinstance(ts, (int, float)):  # epoch ms
                ts = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()
            ts = to_utc_iso(ts)
            out.append(NormalizedExecution(
                symbol=contract_root(contract),
                contract=contract,
                side="buy" if str(f.get("action", "")).lower() == "buy" else "sell",
                qty=int(f["qty"]),
                price=float(f["price"]),
                ts_utc=ts,
                exec_id=str(f["id"]),
                order_id=str(f.get("orderId")) if f.get("orderId") else None,
                fees=fees_by_fill.get(f["id"], 0.0),
                raw=f,
            ))
        return out, warnings

    def close(self):
        self._http.close()


def sync(conn: sqlite3.Connection, client: TradovateClient, account_name: str,
         tradovate_account_id: int | None = None) -> dict:
    """One sweep: fetch current-session fills, ingest (idempotent), rebuild."""
    executions, warnings = client.fetch_fills(tradovate_account_id)
    acct_id = get_or_create_account(conn, account_name, platform="tradovate")
    res = ingest(conn, acct_id, account_name, "api:tradovate", "tradovate",
                 executions, warnings=warnings)
    report = rebuild(conn)
    return {"fetched": len(executions), "new": res.rows_new, "duplicates": res.rows_dup,
            "warnings": res.warnings, "trades_total": report.trades_created}
