"""ProjectX Gateway adapter (TopstepX, The Futures Desk, …) — read-only.

Endpoints used (per-firm base, e.g. https://api.topstepx.com):
  POST /api/Auth/loginKey        — {userName, apiKey} -> session token
  POST /api/Account/search       — accounts
  POST /api/Trade/search         — half-turn fills with fees and P&L
                                   {accountId, startTimestamp, endTimestamp}

Trade/search rows (per gateway docs and community SDKs): id, accountId,
contractId (e.g. "CON.F.US.MES.Z25"), creationTimestamp, price, size,
side (0=buy/bid, 1=sell/ask), fees, profitAndLoss (null for the opening
half-turn), orderId.

We ingest HALF-TURNS as executions and let our own reconstruction build the
round trips; ProjectX's own profitAndLoss stays in raw_payload for
reconciliation. No order-placement endpoint exists in this module by design.
⚠️ Built from gateway docs + community SDKs; not yet validated live. The side
encoding (0=buy) is documented but must be confirmed on first live sync.
"""
from __future__ import annotations

import re
import sqlite3

import httpx

from ..db import get_or_create_account
from ..importers.base import NormalizedExecution, ingest, to_utc_iso
from ..reconstruction import rebuild

TOPSTEPX = "https://api.topstepx.com"

# "CON.F.US.MES.Z25" -> symbol MES, contract MESZ25
_CONTRACT_ID_RE = re.compile(r"^CON\.F\.[A-Z]+\.([A-Z0-9]+)\.([FGHJKMNQUVXZ]\d{1,2})$")


def parse_contract_id(contract_id: str) -> tuple[str, str]:
    m = _CONTRACT_ID_RE.match(contract_id or "")
    if m:
        return m.group(1), f"{m.group(1)}{m.group(2)}"
    return (contract_id or "?"), (contract_id or "?")


class ProjectXClient:
    def __init__(
        self,
        username: str,
        api_key: str,
        *,
        base_url: str = TOPSTEPX,
        transport: httpx.BaseTransport | None = None,
    ):
        self._creds = {"userName": username, "apiKey": api_key}
        self._http = httpx.Client(base_url=base_url, timeout=30, transport=transport)
        self._token: str | None = None

    def authenticate(self) -> None:
        r = self._http.post("/api/Auth/loginKey", json=self._creds)
        r.raise_for_status()
        data = r.json()
        if not data.get("success", False):
            raise RuntimeError(f"ProjectX auth failed: {data.get('errorMessage')}")
        self._token = data["token"]

    def _post(self, path: str, body: dict) -> dict:
        if not self._token:
            self.authenticate()
        headers = {"Authorization": f"Bearer {self._token}"}
        r = self._http.post(path, json=body, headers=headers)
        if r.status_code == 401:
            self.authenticate()
            r = self._http.post(path, json=body,
                                headers={"Authorization": f"Bearer {self._token}"})
        r.raise_for_status()
        data = r.json()
        if not data.get("success", True):
            raise RuntimeError(f"ProjectX {path} failed: {data.get('errorMessage')}")
        return data

    def accounts(self, only_active: bool = True) -> list[dict]:
        return self._post("/api/Account/search", {"onlyActiveAccounts": only_active}).get("accounts", [])

    def fetch_fills(
        self, account_id: int, start_iso: str, end_iso: str
    ) -> tuple[list[NormalizedExecution], list[str]]:
        warnings: list[str] = []
        data = self._post("/api/Trade/search", {
            "accountId": account_id,
            "startTimestamp": start_iso,
            "endTimestamp": end_iso,
        })
        out: list[NormalizedExecution] = []
        for t in data.get("trades", []):
            symbol, contract = parse_contract_id(t.get("contractId", ""))
            side_code = t.get("side")
            if side_code not in (0, 1):
                warnings.append(f"trade {t.get('id')}: unknown side {side_code!r}, skipped")
                continue
            out.append(NormalizedExecution(
                symbol=symbol,
                contract=contract,
                side="buy" if side_code == 0 else "sell",
                qty=int(t["size"]),
                price=float(t["price"]),
                ts_utc=to_utc_iso(t.get("creationTimestamp", "")),
                exec_id=str(t["id"]),
                order_id=str(t.get("orderId")) if t.get("orderId") else None,
                fees=float(t.get("fees") or 0.0),
                raw=t,  # keeps platform profitAndLoss for reconciliation
            ))
        return out, warnings

    def close(self):
        self._http.close()


def sync(conn: sqlite3.Connection, client: ProjectXClient, account_name: str,
         px_account_id: int, start_iso: str, end_iso: str) -> dict:
    executions, warnings = client.fetch_fills(px_account_id, start_iso, end_iso)
    acct_id = get_or_create_account(conn, account_name, platform="projectx")
    res = ingest(conn, acct_id, account_name, "api:projectx", "projectx",
                 executions, warnings=warnings)
    report = rebuild(conn)
    # reconciliation hint: compare our computed net to the platform's own P&L
    platform_pnl = sum(
        float(e.raw.get("profitAndLoss") or 0.0) for e in executions
    )
    return {"fetched": len(executions), "new": res.rows_new, "duplicates": res.rows_dup,
            "warnings": res.warnings, "trades_total": report.trades_created,
            "platform_reported_pnl": round(platform_pnl, 2)}
