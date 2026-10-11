"""Live connections: fills arrive within about a second of happening.

Design: the WebSocket is a *trigger*, not a second parser. When the platform
pushes "a fill happened", we immediately run the already-tested REST sync for
that platform (sync/tradovate.py, sync/projectx.py), which normalizes fills,
attaches fees and deduplicates. The same sync runs on every (re)connect and
every few minutes as a safety net, so a dropped connection can delay a fill
but never lose one.

Protocols (from official docs and official example clients):
  Tradovate   wss://{live|demo}.tradovateapi.com/v1/websocket
              frames: 'o' open, 'h' heartbeat, 'a[...]' data, 'c' close
              send 'authorize\\n0\\n\\n<token>', then
                   'user/syncrequest\\n1\\n\\n{"users":[<userId>]}'
              client heartbeat '[]' every ~2.5 s
              fill events: {"e":"props","d":{"entityType":"fill",...}}
  ProjectX    wss://rtc.topstepx.com/hubs/user?access_token=<token>  (SignalR JSON)
              handshake '{"protocol":"json","version":1}\\x1e'
              invoke SubscribeAccounts / SubscribeOrders / SubscribePositions /
                     SubscribeTrades(accountId)
              trade events: {"type":1,"target":"GatewayUserTrade",...}
              ping '{"type":6}\\x1e' every ~15 s

⚠️ Not yet run against the live platforms (no accounts in the build
environment); protocol handling is tested against scripted servers.
Read-only: nothing here can place, change or cancel orders.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

RS = "\x1e"  # SignalR record separator


# ----------------------------------------------------------- protocols

class TradovateProtocol:
    name = "tradovate"
    heartbeat_seconds = 2.5

    def __init__(self, token: str = "", user_id: int = 0, *, demo: bool = False,
                 credentials: Callable[[], tuple[str, int]] | None = None):
        self.token, self.user_id = token, user_id
        self.base = "demo" if demo else "live"
        self.credentials = credentials  # fresh (token, user_id) per connect; tokens expire

    def url(self) -> str:
        if self.credentials:
            self.token, self.user_id = self.credentials()
        return f"wss://{self.base}.tradovateapi.com/v1/websocket"

    def heartbeat(self) -> str:
        return "[]"

    async def open(self, ws) -> None:
        first = await ws.recv()
        if first != "o":
            raise ConnectionError(f"unexpected open frame {first!r}")
        await ws.send(f"authorize\n0\n\n{self.token}")
        while True:
            kind, items = parse_tradovate_frame(await ws.recv())
            if kind == "a":
                for it in items:
                    if it.get("i") == 0:
                        if it.get("s") != 200:
                            raise PermissionError(f"Tradovate authorization failed: {it}")
                        await ws.send("user/syncrequest\n1\n\n" + json.dumps({"users": [self.user_id]}))
                        return
            elif kind == "c":
                raise ConnectionError("closed during authorization")

    def fill_events(self, raw: str) -> int:
        kind, items = parse_tradovate_frame(raw)
        if kind == "c":
            raise ConnectionError("server closed the connection")
        n = 0
        for it in items:
            d = it.get("d") if isinstance(it, dict) else None
            if it.get("e") == "props" and isinstance(d, dict) and d.get("entityType") == "fill":
                n += 1
        return n


def parse_tradovate_frame(raw: str) -> tuple[str, list]:
    if not raw:
        return "h", []
    kind = raw[0]
    if kind == "a":
        try:
            data = json.loads(raw[1:])
        except ValueError:
            return "a", []
        return "a", data if isinstance(data, list) else [data]
    return kind, []


class ProjectXProtocol:
    name = "projectx"
    heartbeat_seconds = 15.0

    def __init__(self, token: str = "", account_id: int = 0, *,
                 hub: str = "wss://rtc.topstepx.com/hubs/user",
                 credentials: Callable[[], str] | None = None):
        self.token, self.account_id, self.hub = token, account_id, hub
        self.credentials = credentials  # fresh token per connect

    def url(self) -> str:
        if self.credentials:
            self.token = self.credentials()
        return f"{self.hub}?access_token={self.token}"

    def heartbeat(self) -> str:
        return json.dumps({"type": 6}) + RS

    async def open(self, ws) -> None:
        await ws.send(json.dumps({"protocol": "json", "version": 1}) + RS)
        for msg in parse_signalr(await ws.recv()):
            if msg.get("error"):
                raise ConnectionError(f"SignalR handshake failed: {msg['error']}")
        for i, target in enumerate(("SubscribeAccounts", "SubscribeOrders",
                                    "SubscribePositions", "SubscribeTrades")):
            args = [] if target == "SubscribeAccounts" else [self.account_id]
            await ws.send(json.dumps({"type": 1, "invocationId": str(i), "target": target,
                                      "arguments": args}) + RS)

    def fill_events(self, raw: str) -> int:
        n = 0
        for msg in parse_signalr(raw):
            if msg.get("type") == 7:
                raise ConnectionError(f"server closed: {msg.get('error') or 'no reason'}")
            if msg.get("type") == 1 and msg.get("target") == "GatewayUserTrade":
                n += 1
        return n


def parse_signalr(raw: str) -> list[dict]:
    out = []
    for part in (raw or "").split(RS):
        if part.strip():
            try:
                out.append(json.loads(part))
            except ValueError:
                pass
    return out


# ------------------------------------------------------------- runner

@dataclass
class LiveStatus:
    platform: str
    state: str = "stopped"          # connecting | live | reconnecting | stopped | error
    connected_since: str | None = None
    last_event_at: str | None = None
    last_sweep_at: str | None = None
    fills_added: int = 0
    reconnects: int = 0
    last_error: str | None = None
    history: list = field(default_factory=list)

    def note(self, state: str, error: str | None = None):
        self.state = state
        if error:
            self.last_error = error
        self.history = (self.history + [f"{_now()} {state}" + (f": {error}" if error else "")])[-20:]

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def run_stream(
    protocol,
    sweep: Callable[[], int],
    status: LiveStatus,
    stop: asyncio.Event,
    *,
    connect: Callable[[str], Awaitable[Any]] | None = None,
    safety_sweep_seconds: float = 300.0,
    max_backoff: float = 60.0,
    debounce_seconds: float = 1.0,
) -> None:
    """Keep a live connection open until `stop` is set. `sweep` runs the REST
    sync and returns how many new fills it stored."""
    if connect is None:
        from websockets.asyncio.client import connect as ws_connect

        async def connect(url):  # noqa: F811
            return await ws_connect(url, ping_interval=None, open_timeout=20)

    async def do_sweep():
        try:
            added = await asyncio.to_thread(sweep)
            status.fills_added += added
            status.last_sweep_at = _now()
        except Exception as e:  # sweep failure is reported, connection kept
            status.last_error = f"sync failed: {e}"

    backoff = 1.0
    first = True
    while not stop.is_set():
        status.note("connecting" if first else "reconnecting")
        ws = None
        try:
            ws = await connect(protocol.url())
            await protocol.open(ws)
            status.note("live")
            status.connected_since = _now()
            backoff = 1.0
            await do_sweep()                       # catch up on anything missed
            last_hb = last_safety = time.monotonic()
            pending_since: float | None = None
            while not stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                except asyncio.TimeoutError:
                    raw = None
                now = time.monotonic()
                if raw is not None and protocol.fill_events(raw):
                    status.last_event_at = _now()
                    pending_since = pending_since or now
                if pending_since is not None and now - pending_since >= debounce_seconds:
                    pending_since = None
                    await do_sweep()
                    last_safety = now
                if now - last_hb >= protocol.heartbeat_seconds:
                    await ws.send(protocol.heartbeat())
                    last_hb = now
                if now - last_safety >= safety_sweep_seconds:
                    await do_sweep()
                    last_safety = now
        except PermissionError as e:
            status.note("error", str(e))           # bad credentials: don't hammer the server
            break
        except Exception as e:
            if stop.is_set():
                break
            status.reconnects += 1
            status.note("reconnecting", f"{type(e).__name__}: {e}")
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(max_backoff, backoff * 2)
        finally:
            first = False
            if ws is not None:
                try:
                    await ws.close()
                except Exception:
                    pass
    if status.state != "error":
        status.note("stopped")


class LiveManager:
    """Runs one live connection per platform on a background thread."""

    def __init__(self):
        self._runs: dict[str, tuple[threading.Thread, asyncio.AbstractEventLoop, asyncio.Event, LiveStatus]] = {}

    def start(self, platform: str, protocol, sweep: Callable[[], int], **kw) -> LiveStatus:
        self.stop(platform)
        status = LiveStatus(platform)
        loop = asyncio.new_event_loop()
        stop = asyncio.Event()

        def runner():
            asyncio.set_event_loop(loop)
            loop.run_until_complete(run_stream(protocol, sweep, status, stop, **kw))
            loop.close()

        t = threading.Thread(target=runner, daemon=True, name=f"live-{platform}")
        self._runs[platform] = (t, loop, stop, status)
        t.start()
        return status

    def stop(self, platform: str, timeout: float = 5.0) -> None:
        run = self._runs.pop(platform, None)
        if not run:
            return
        t, loop, stop, _ = run
        try:
            loop.call_soon_threadsafe(stop.set)
        except RuntimeError:
            pass
        t.join(timeout=timeout)

    def stop_all(self) -> None:
        for p in list(self._runs):
            self.stop(p)

    def status(self) -> dict:
        return {p: run[3].to_dict() for p, run in self._runs.items()}


def today_window(days_back: int = 1) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ"), (now + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
