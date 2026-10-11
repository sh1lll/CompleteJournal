"""Turn saved credentials into a running live connection (used by the API)."""
from __future__ import annotations

from pathlib import Path

from . import db as dbmod, live, secrets_store

PLATFORMS = {
    "tradovate": ["username", "password", "cid", "sec"],
    "projectx": ["username", "api_key", "account_id"],
}


def validate(platform: str, creds: dict) -> dict:
    if platform not in PLATFORMS:
        raise ValueError(f"platform must be one of {sorted(PLATFORMS)}")
    missing = [k for k in PLATFORMS[platform] if not str(creds.get(k, "")).strip()]
    if missing:
        raise ValueError(f"missing: {', '.join(missing)}")
    clean = {k: (str(v).strip() if isinstance(v, str) else v) for k, v in creds.items()}
    clean["account_label"] = (clean.get("account_label") or "").strip() or \
        ("Tradovate (live)" if platform == "tradovate" else "TopstepX (live)")
    return clean


def build(platform: str, creds: dict, db_path: str | Path, *, transport=None):
    """Return (protocol, sweep). sweep() opens its own DB connection because it
    runs on the live thread."""
    label = creds["account_label"]
    if platform == "tradovate":
        from .sync import tradovate as tv
        client = tv.TradovateClient(creds["username"], creds["password"], creds["cid"], creds["sec"],
                                    base_url=tv.DEMO if creds.get("demo") else tv.LIVE,
                                    transport=transport)

        def sweep() -> int:
            conn = dbmod.connect(db_path)
            try:
                return tv.sync(conn, client, label)["new"]
            finally:
                conn.close()

        proto = live.TradovateProtocol(demo=bool(creds.get("demo")),
                                       credentials=client.fresh_credentials)
        return proto, sweep

    from .sync import projectx as px
    client = px.ProjectXClient(creds["username"], creds["api_key"],
                               base_url=creds.get("base_url") or px.TOPSTEPX, transport=transport)
    acct = int(creds["account_id"])

    def sweep() -> int:
        conn = dbmod.connect(db_path)
        try:
            start, end = live.today_window()
            return px.sync(conn, client, label, acct, start, end)["new"]
        finally:
            conn.close()

    proto = live.ProjectXProtocol(account_id=acct, hub=creds.get("hub") or "wss://rtc.topstepx.com/hubs/user",
                                  credentials=client.fresh_token)
    return proto, sweep


def saved(platform: str) -> dict | None:
    return secrets_store.load(f"live_{platform}")


def save(platform: str, creds: dict) -> str:
    return secrets_store.save(f"live_{platform}", creds)


def forget(platform: str) -> None:
    secrets_store.delete(f"live_{platform}")
