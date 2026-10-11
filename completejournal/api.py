"""Local HTTP API + web UI. Read/write for journal data; read-only toward
brokers (this app contains no order-placement code anywhere, by design)."""
from __future__ import annotations

import sqlite3
import tempfile
from datetime import timedelta, timezone
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, Form
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from fastapi.responses import Response

from . import __version__
from . import ai, excursions, plan as planmod, recap as recapmod, reports, similar
from . import analytics, attachments as attmod, bars as barsmod, behavior, db as dbmod, journal, reconstruction
from .importers import base as impbase
from .importers import auto as impauto
from .importers.platforms import FORCE_FORMAT, REGISTRY  # noqa: F401


class EntryIn(BaseModel):
    body_md: str
    kind: str | None = None
    title: str | None = None
    about_date: str | None = None


class EntryEdit(BaseModel):
    body_md: str
    title: str | None = None


class LinkIn(BaseModel):
    target_type: str
    target_id: str


class AddendumIn(BaseModel):
    body_md: str


class CaptureIn(BaseModel):
    body: str = ""
    client_id: str
    captured_at: str | None = None
    attachment_ids: list[int] = []


class PhoneEnableIn(BaseModel):
    port: int | None = None


class UpdatePrefIn(BaseModel):
    enabled: bool


class LiveConnectIn(BaseModel):
    platform: str
    credentials: dict = {}
    remember: bool = True


class LivePlatformIn(BaseModel):
    platform: str


class EconIn(BaseModel):
    when: str
    event: str
    impact: str = "high"
    currency: str = "USD"
    tz: str | None = "America/New_York"


class StatusIn(BaseModel):
    status: str


class TagIn(BaseModel):
    tag: str


class KeyIn(BaseModel):
    key: str


class AskIn(BaseModel):
    question: str


class GradeIn(BaseModel):
    grade: str
    note: str | None = None


def create_app(db_path: str | Path, attachments_root: str | Path | None = None) -> FastAPI:
    from contextlib import asynccontextmanager
    from . import live as livemod, live_setup, phone as phonemod
    manager = livemod.LiveManager()

    class PhoneServer:
        """Second listener on the local network, same app, phone-only access."""
        def __init__(self):
            self.server = self.thread = None
            self.port = None

        def start(self, port: int):
            import threading
            import uvicorn
            self.stop()
            # lifespan off: the main server owns startup/shutdown; running it here
            # would start a second phone listener from inside this one
            cfg = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning",
                                 access_log=False, lifespan="off")
            server = uvicorn.Server(cfg)
            server.install_signal_handlers = lambda: None
            def run():
                try:
                    server.run()
                except SystemExit:  # uvicorn exits on bind failure; reported below instead
                    pass
            thread = threading.Thread(target=run, daemon=True, name="phone-listener")
            thread.start()
            import time
            deadline = time.time() + 5
            while not server.started and thread.is_alive() and time.time() < deadline:
                time.sleep(0.02)
            if not server.started:
                server.should_exit = True
                thread.join(timeout=2)
                raise OSError(f"could not listen on port {port} (is another program using it?)")
            self.server, self.thread, self.port = server, thread, port

        def stop(self):
            if self.server:
                self.server.should_exit = True
                self.thread.join(timeout=5)
            self.server = self.thread = self.port = None

        @property
        def running(self) -> bool:
            return bool(self.thread and self.thread.is_alive())

    phone_server = PhoneServer()

    def _start_live(platform: str, creds: dict):
        proto, sweep = live_setup.build(platform, creds, db_path)
        return manager.start(platform, proto, sweep)

    @asynccontextmanager
    async def lifespan(_app):
        # reconnect platforms the user chose to remember (credentials stay in
        # the OS keychain / private file, never in the database)
        for platform in live_setup.PLATFORMS:
            creds = live_setup.saved(platform)
            if creds and creds.get("autoconnect", True):
                try:
                    _start_live(platform, creds)
                except Exception:
                    pass
        c0 = dbmod.connect(db_path)
        try:
            if phonemod.setting(c0, "phone_enabled") == "1":
                try:
                    phone_server.start(int(phonemod.setting(c0, "phone_port", str(phonemod.PHONE_PORT_DEFAULT))))
                except OSError:
                    pass
        finally:
            c0.close()
        yield
        manager.stop_all()
        phone_server.stop()

    app = FastAPI(title="Complete Journal", version=__version__, lifespan=lifespan)
    att_root = Path(attachments_root) if attachments_root else Path(str(db_path) + ".attachments")
    # ----------------------------------------------- device access gate
    from fastapi import Request
    from fastapi.responses import RedirectResponse

    @app.middleware("http")
    async def phone_gate(request: Request, call_next):
        host = request.client.host if request.client else None
        if phonemod.is_loopback(host):
            return await call_next(request)
        c = dbmod.connect(db_path)
        try:
            enabled = phonemod.setting(c, "phone_enabled") == "1"
            path = request.url.path
            if enabled and path == "/capture" and request.query_params.get("pair"):
                if phonemod.token_ok(c, request.query_params["pair"]):
                    resp = RedirectResponse("/capture", status_code=303)  # drop the token from the URL
                    resp.set_cookie(phonemod.COOKIE, request.query_params["pair"], max_age=365 * 86400,
                                    httponly=True, samesite="strict")
                    return resp
            paired = enabled and phonemod.token_ok(c, request.cookies.get(phonemod.COOKIE))
        finally:
            c.close()
        if paired and phonemod.phone_may_access(request.method, path):
            return await call_next(request)
        if path == "/capture":
            return HTMLResponse(
                "<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
                "<title>Pair this phone</title><body style='font-family:system-ui;padding:24px;max-width:30em'>"
                "<h2>Pair this phone first</h2><p>On your computer open Complete Journal &rarr; "
                "Settings &rarr; Phone, and scan the QR code with this phone.</p></body>", status_code=403)
        return JSONResponse(status_code=403, content={"detail": "not available from this device"})

    # create/upgrade the database at launch so a locked or corrupt file fails
    # immediately and clearly, not halfway through someone's writing
    dbmod.connect(db_path).close()

    def conn() -> sqlite3.Connection:
        # SQLite per-request connection: simple and safe for a single user.
        return dbmod.connect(db_path)

    @app.get("/api/health")
    def health():
        from . import __version__
        return {"ok": True, "version": __version__}

    @app.get("/", response_class=HTMLResponse)
    def index():
        return resources.files("completejournal").joinpath("web/index.html").read_text(encoding="utf-8")

    # ----------------------------------------------------------- journal
    @app.post("/api/entries")
    def create_entry(e: EntryIn):
        c = conn()
        try:
            eid = journal.create_entry(c, e.body_md, kind=e.kind, title=e.title, about_date=e.about_date)
            return {"id": eid}
        except ValueError as err:
            raise HTTPException(400, str(err))
        finally:
            c.close()

    @app.get("/api/entries")
    def list_entries(limit: int = 100, kind: str | None = None):
        c = conn()
        try:
            q = "SELECT * FROM entries WHERE deleted_at IS NULL"
            params: list = []
            if kind:
                q += " AND kind=?"
                params.append(kind)
            q += " ORDER BY written_at DESC LIMIT ?"
            params.append(limit)
            return [dict(r) for r in c.execute(q, params)]
        finally:
            c.close()

    @app.get("/api/entries/{entry_id}")
    def get_entry(entry_id: int):
        c = conn()
        try:
            row = c.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
            if not row:
                raise HTTPException(404, "entry not found")
            addenda = c.execute(
                "SELECT * FROM entry_addenda WHERE entry_id=? ORDER BY written_at", (entry_id,)
            ).fetchall()
            links = c.execute("SELECT * FROM links WHERE entry_id=?", (entry_id,)).fetchall()
            n_versions = c.execute(
                "SELECT COUNT(*) FROM entry_versions WHERE entry_id=?", (entry_id,)
            ).fetchone()[0]
            return {"entry": dict(row), "addenda": [dict(a) for a in addenda],
                    "links": journal.describe_links(c, entry_id), "n_versions": n_versions,
                    "tags": journal.tags_of(c, entry_id), "backlinks": journal.backlinks(c, entry_id)}
        finally:
            c.close()

    @app.put("/api/entries/{entry_id}")
    def edit_entry(entry_id: int, e: EntryEdit):
        c = conn()
        try:
            journal.edit_entry(c, entry_id, e.body_md, e.title)
            return {"ok": True}
        except KeyError as err:
            raise HTTPException(404, str(err))
        finally:
            c.close()

    @app.get("/api/entries/{entry_id}/versions")
    def entry_versions(entry_id: int):
        c = conn()
        try:
            return [dict(r) for r in journal.versions(c, entry_id)]
        finally:
            c.close()

    @app.post("/api/entries/{entry_id}/addenda")
    def add_addendum(entry_id: int, a: AddendumIn):
        c = conn()
        try:
            return {"id": journal.add_addendum(c, entry_id, a.body_md)}
        finally:
            c.close()

    @app.post("/api/entries/{entry_id}/links")
    def add_link(entry_id: int, l: LinkIn):
        c = conn()
        try:
            journal.link(c, entry_id, l.target_type, l.target_id)
            return {"ok": True}
        finally:
            c.close()

    from . import theses as thesesmod

    @app.get("/api/theses")
    def theses_list():
        c = conn()
        try:
            return thesesmod.list_theses(c)
        finally:
            c.close()

    @app.get("/api/theses/{entry_id}")
    def thesis_thread(entry_id: int):
        c = conn()
        try:
            return thesesmod.thread(c, entry_id)
        except KeyError as e:
            raise HTTPException(404, str(e))
        finally:
            c.close()

    @app.post("/api/theses/{entry_id}/status")
    def thesis_status(entry_id: int, body: StatusIn):
        c = conn()
        try:
            thesesmod.set_status(c, entry_id, body.status)
            return thesesmod.thread(c, entry_id)
        except ValueError as e:
            raise HTTPException(400, str(e))
        finally:
            c.close()

    from . import econ as econmod

    @app.get("/api/econ/{date}")
    def econ_day(date: str, min_impact: str = "low"):
        c = conn()
        try:
            return {"events": econmod.for_session(c, date, min_impact=min_impact),
                    "trades_near_high_impact": econmod.trades_near_events(c, date)}
        finally:
            c.close()

    @app.post("/api/econ/import")
    async def econ_import(file: UploadFile, tz: str = Form("America/New_York")):
        data = await file.read()
        c = conn()
        try:
            if (file.filename or "").lower().endswith(".json") or data.lstrip()[:1] == b"[":
                return econmod.import_ff_json(c, data)
            return econmod.import_csv(c, data, tz=tz)
        except ValueError as e:
            raise HTTPException(400, str(e))
        finally:
            c.close()

    @app.post("/api/econ/fetch-week")
    def econ_fetch():
        c = conn()
        try:
            return econmod.fetch_feed(c)
        finally:
            c.close()

    @app.post("/api/econ/event")
    def econ_add(body: EconIn):
        c = conn()
        try:
            return {"id": econmod.add_manual(c, when=body.when, event=body.event, impact=body.impact,
                                             currency=body.currency, tz=body.tz)}
        except ValueError as e:
            raise HTTPException(400, str(e))
        finally:
            c.close()

    @app.get("/api/stats/slippage")
    def slippage_stats():
        from . import stats as statsmod
        c = conn()
        try:
            return statsmod.slippage(c)
        finally:
            c.close()

    @app.get("/api/stats/events")
    def econ_stats(minutes: int = 5):
        c = conn()
        try:
            return econmod.near_vs_away(c, minutes=minutes)
        finally:
            c.close()

    @app.get("/api/tags")
    def list_tags():
        c = conn()
        try:
            return journal.all_tags(c)
        finally:
            c.close()

    @app.post("/api/entries/{entry_id}/tags")
    def add_tag(entry_id: int, body: TagIn):
        c = conn()
        try:
            journal.tag(c, entry_id, body.tag)
            return {"tags": journal.tags_of(c, entry_id)}
        except ValueError as e:
            raise HTTPException(400, str(e))
        finally:
            c.close()

    @app.delete("/api/entries/{entry_id}/tags/{tag:path}")
    def remove_tag(entry_id: int, tag: str):
        c = conn()
        try:
            journal.untag(c, entry_id, tag)
            return {"tags": journal.tags_of(c, entry_id)}
        finally:
            c.close()

    @app.delete("/api/entries/{entry_id}/links/{target_type}/{target_id}")
    def remove_link(entry_id: int, target_type: str, target_id: str):
        c = conn()
        try:
            journal.unlink(c, entry_id, target_type, target_id)
            return {"ok": True}
        finally:
            c.close()

    @app.delete("/api/entries/{entry_id}")
    def delete_entry(entry_id: int):
        c = conn()
        try:
            journal.soft_delete(c, entry_id)
            return {"ok": True, "note": "soft-deleted; versions preserved"}
        finally:
            c.close()

    @app.get("/api/mention")
    def mention(q: str = ""):
        c = conn()
        try:
            return journal.mention_candidates(c, q)
        finally:
            c.close()

    @app.get("/api/bars/trade/{trade_id}")
    def trade_bars(trade_id: int, resolution: str | None = None, pad_minutes: int = 45):
        c = conn()
        try:
            t = c.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
            if not t:
                raise HTTPException(404, "trade not found")
            data = barsmod.bars_around(c, t["symbol"], t["entry_ts"], t["exit_ts"],
                                       pad_minutes=pad_minutes, resolution=resolution)
            fills = c.execute(
                """SELECT e.ts_utc, e.side, te.qty AS qty, e.price FROM trade_executions te
                   JOIN executions e ON e.id=te.execution_id WHERE te.trade_id=? ORDER BY e.ts_utc""",
                (trade_id,)).fetchall()
            data["executions"] = [dict(f) for f in fills]
            data["trade"] = {"id": t["id"], "direction": t["direction"],
                             "avg_entry": t["avg_entry"], "avg_exit": t["avg_exit"]}
            return data
        finally:
            c.close()

    @app.post("/api/bars/import")
    async def import_bars(
        file: UploadFile,
        symbol: str = Form(...),
        resolution: str = Form("1m"),
        tz_offset_minutes: int = Form(0),
    ):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        c = conn()
        try:
            n = barsmod.import_bars_csv(c, tmp_path, symbol, resolution,
                                        tz_offset_minutes=tz_offset_minutes)
            return {"bars_new": n, "symbol": symbol.upper(), "resolution": resolution}
        except ValueError as e:
            raise HTTPException(400, str(e))
        finally:
            c.close()
            Path(tmp_path).unlink(missing_ok=True)

    @app.get("/api/search")
    def search(q: str):
        c = conn()
        try:
            return journal.search(c, q)
        finally:
            c.close()

    # ------------------------------------------------------------ trading
    @app.get("/api/sessions/{date}")
    def session(date: str):
        c = conn()
        try:
            return journal.session_timeline(c, date)
        finally:
            c.close()

    @app.get("/api/trades")
    def trades(date: str | None = None, limit: int = 200):
        c = conn()
        try:
            q = ("SELECT t.*, a.name AS account_name FROM trades t "
                 "JOIN accounts a ON a.id=t.account_id")
            params: list = []
            if date:
                q += " WHERE t.session_date=?"
                params.append(date)
            q += " ORDER BY t.entry_ts DESC LIMIT ?"
            params.append(limit)
            return [dict(r) for r in c.execute(q, params)]
        finally:
            c.close()

    @app.get("/api/trades/{trade_id}")
    def trade(trade_id: int):
        c = conn()
        try:
            row = c.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
            if not row:
                raise HTTPException(404, "trade not found")
            fills = c.execute(
                """SELECT e.*, te.qty AS attributed_qty FROM trade_executions te
                   JOIN executions e ON e.id=te.execution_id WHERE te.trade_id=?
                   ORDER BY e.ts_utc""", (trade_id,)).fetchall()
            notes = journal.entries_for_target(c, "trade", str(trade_id))
            return {"trade": dict(row), "executions": [dict(f) for f in fills],
                    "entries": [dict(n) for n in notes],
                    "grade": analytics.get_grade(c, trade_id)}
        finally:
            c.close()

    @app.get("/api/stats")
    def stats():
        c = conn()
        try:
            return analytics.overall(c).to_dict()
        finally:
            c.close()

    @app.get("/api/stats/breakdown/{dimension}")
    def stats_breakdown(dimension: str):
        c = conn()
        try:
            return analytics.breakdown(c, dimension)
        except ValueError as e:
            raise HTTPException(400, str(e))
        finally:
            c.close()

    @app.get("/api/behavior")
    def behavior_flags():
        c = conn()
        try:
            return behavior.all_flags(c)
        finally:
            c.close()

    @app.get("/api/stats/process-vs-outcome")
    def pvo():
        c = conn()
        try:
            return analytics.process_vs_outcome(c)
        finally:
            c.close()

    @app.post("/api/trades/{trade_id}/grade")
    def grade_trade(trade_id: int, g: GradeIn):
        c = conn()
        try:
            analytics.set_grade(c, trade_id, g.grade, g.note)
            return {"ok": True}
        except ValueError as e:
            raise HTTPException(400, str(e))
        except KeyError as e:
            raise HTTPException(404, str(e))
        finally:
            c.close()

    # ------------------------------------------- review tools (no AI)
    @app.get("/api/similar")
    def similar_entries(text: str | None = None, entry_id: int | None = None, limit: int = 5):
        c = conn()
        try:
            return similar.find_similar(c, text=text, entry_id=entry_id, limit=limit)
        except KeyError as e:
            raise HTTPException(404, str(e))
        finally:
            c.close()

    @app.get("/api/recap/{date}")
    def daily_recap(date: str):
        c = conn()
        try:
            return recapmod.daily(c, date)
        finally:
            c.close()

    @app.get("/api/plan/template")
    def plan_template():
        return {"template": planmod.PLAN_TEMPLATE}

    @app.get("/api/plan/{date}")
    def plan_vs_actual(date: str):
        c = conn()
        try:
            return planmod.plan_vs_actual(c, date)
        finally:
            c.close()

    @app.get("/api/reports/{kind}/{date}")
    def report(kind: str, date: str, format: str = "json"):
        c = conn()
        try:
            r = reports.build(c, kind, date)
            if format == "md":
                return Response(content=reports.to_markdown(r), media_type="text/markdown")
            return r
        except ValueError as e:
            raise HTTPException(400, str(e))
        finally:
            c.close()

    @app.get("/api/excursions/summary")
    def excursion_summary():
        c = conn()
        try:
            return excursions.summary(c)
        finally:
            c.close()

    @app.get("/api/excursions/trade/{trade_id}")
    def excursion(trade_id: int):
        c = conn()
        try:
            return excursions.trade_excursion(c, trade_id) or {"trade_id": trade_id, "available": False,
                    "reason": "no price bars stored for this trade's window"}
        finally:
            c.close()

    # --------------------------------------------------------- updates
    from . import updates as updmod

    @app.get("/api/updates")
    def updates_status():
        c = conn()
        try:
            return updmod.check(c)
        finally:
            c.close()

    @app.post("/api/updates/preference")
    def updates_pref(body: UpdatePrefIn):
        c = conn()
        try:
            updmod.set_preference(c, body.enabled)
            return updmod.check(c)
        finally:
            c.close()

    @app.post("/api/updates/check")
    def updates_check_now():
        c = conn()
        try:
            return updmod.check(c, force=True)
        finally:
            c.close()

    # ---------------------------------------------- phone quick-capture
    def _web(name: str) -> str:
        return resources.files("completejournal").joinpath(f"web/{name}").read_text(encoding="utf-8")

    @app.get("/capture", response_class=HTMLResponse)
    def capture_page():
        return _web("capture.html")

    @app.get("/manifest.webmanifest")
    def manifest():
        return Response(_web("manifest.webmanifest"), media_type="application/manifest+json")

    @app.get("/sw.js")
    def service_worker():
        return Response(_web("sw.js"), media_type="text/javascript")

    @app.get("/icon.svg")
    def icon():
        return Response(_web("icon.svg"), media_type="image/svg+xml")

    @app.post("/api/capture")
    def capture(body: CaptureIn):
        c = conn()
        try:
            return phonemod.save_capture(c, body.body, client_id=body.client_id,
                                         captured_at=body.captured_at, attachment_ids=body.attachment_ids)
        except ValueError as e:
            raise HTTPException(400, str(e))
        finally:
            c.close()

    @app.get("/api/capture/recent")
    def capture_recent():
        c = conn()
        try:
            return phonemod.recent(c)
        finally:
            c.close()

    @app.get("/api/phone/status")
    def phone_status():
        c = conn()
        try:
            enabled = phonemod.setting(c, "phone_enabled") == "1"
            port = int(phonemod.setting(c, "phone_port", str(phonemod.PHONE_PORT_DEFAULT)))
            out = {"enabled": enabled, "listening": phone_server.running, "port": port}
            if enabled:
                url = f"http://{phonemod.lan_ip()}:{port}/capture?pair={phonemod.get_token(c)}"
                out.update({"pair_url": url, "qr_svg": phonemod.qr_svg(url)})
            return out
        finally:
            c.close()

    @app.post("/api/phone/enable")
    def phone_enable(body: PhoneEnableIn):
        c = conn()
        try:
            port = body.port or int(phonemod.setting(c, "phone_port", str(phonemod.PHONE_PORT_DEFAULT)))
            try:
                phone_server.start(port)
            except OSError as e:
                raise HTTPException(409, f"port {port} unavailable: {e}")
            phonemod.set_setting(c, "phone_enabled", "1")
            phonemod.set_setting(c, "phone_port", str(port))
            phonemod.get_token(c)
        finally:
            c.close()
        return phone_status()

    @app.post("/api/phone/disable")
    def phone_disable():
        phone_server.stop()
        c = conn()
        try:
            phonemod.set_setting(c, "phone_enabled", "0")
        finally:
            c.close()
        return {"enabled": False}

    @app.post("/api/phone/unpair-all")
    def phone_unpair():
        c = conn()
        try:
            phonemod.rotate_token(c)
        finally:
            c.close()
        return phone_status()

    # ---------------------------------------------- live connections
    app.state.live = manager

    @app.get("/api/live/status")
    def live_status():
        st = manager.status()
        return {"connections": st,
                "saved": {p: bool(live_setup.saved(p)) for p in live_setup.PLATFORMS},
                "note": "Read-only: live connections can never place, change or cancel orders."}

    @app.post("/api/live/connect")
    def live_connect(body: LiveConnectIn):
        try:
            creds = live_setup.validate(body.platform, body.credentials)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if body.remember:
            live_setup.save(body.platform, {**creds, "autoconnect": True})
        _start_live(body.platform, creds)
        return {"started": True, "platform": body.platform, "remembered": body.remember}

    @app.post("/api/live/disconnect")
    def live_disconnect(body: LivePlatformIn):
        manager.stop(body.platform)
        creds = live_setup.saved(body.platform)
        if creds:
            live_setup.save(body.platform, {**creds, "autoconnect": False})
        return {"stopped": True}

    @app.post("/api/live/forget")
    def live_forget(body: LivePlatformIn):
        manager.stop(body.platform)
        live_setup.forget(body.platform)
        return {"forgotten": True}

    # --------------------------------------------------- optional AI
    @app.get("/api/ai/status")
    def ai_status():
        c = conn()
        try:
            return ai.status(c)
        finally:
            c.close()

    @app.post("/api/ai/key")
    def ai_set_key(body: KeyIn):
        try:
            where = ai.save_key(body.key)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"saved": True, "stored_in": where}

    @app.delete("/api/ai/key")
    def ai_del_key():
        ai.delete_key()
        return {"deleted": True}

    @app.post("/api/ai/summary/{date}")
    def ai_summary(date: str):
        c = conn()
        try:
            return ai.daily_summary(c, date)
        except ai.AIUnavailable as e:
            raise HTTPException(409, str(e))
        finally:
            c.close()

    @app.post("/api/ai/ask")
    def ai_ask(body: AskIn):
        c = conn()
        try:
            return ai.ask(c, body.question)
        except ai.AIUnavailable as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
        finally:
            c.close()

    @app.get("/api/ai/artifacts")
    def ai_artifacts():
        c = conn()
        try:
            return ai.list_artifacts(c)
        finally:
            c.close()

    @app.get("/api/equity")
    def equity():
        c = conn()
        try:
            return analytics.equity_curve(c)
        finally:
            c.close()

    @app.get("/api/reconciliation")
    def reconciliation():
        c = conn()
        try:
            return analytics.reconciliation(c)
        finally:
            c.close()

    @app.get("/api/calendar")
    def calendar():
        """Per-day P&L + writing density for the calendar view."""
        c = conn()
        try:
            days: dict[str, dict] = {}
            for r in c.execute(
                "SELECT session_date AS d, COUNT(*) n, ROUND(SUM(net_pnl),2) pnl "
                "FROM trades WHERE is_open=0 GROUP BY session_date"):
                days.setdefault(r["d"], {})["trades"] = r["n"]
                days[r["d"]]["net_pnl"] = r["pnl"]
            for r in c.execute(
                "SELECT COALESCE(about_date, substr(written_at,1,10)) AS d, COUNT(*) n "
                "FROM entries WHERE deleted_at IS NULL GROUP BY d"):
                days.setdefault(r["d"], {})["entries"] = r["n"]
            return days
        finally:
            c.close()

    # -------------------------------------------------------- attachments
    @app.post("/api/attachments")
    async def upload_attachment(file: UploadFile, entry_id: int | None = Form(None)):
        c = conn()
        try:
            data = await file.read()
            return attmod.store(c, att_root, data, filename=file.filename,
                                media_type=file.content_type, entry_id=entry_id)
        except ValueError as e:
            raise HTTPException(400, str(e))
        finally:
            c.close()

    @app.get("/api/attachments/{attachment_id}")
    def get_attachment(attachment_id: int):
        c = conn()
        try:
            data, meta = attmod.load(c, att_root, attachment_id)
            return Response(content=data, media_type=meta["media_type"] or "application/octet-stream")
        except KeyError as e:
            raise HTTPException(404, str(e))
        except (ValueError, FileNotFoundError) as e:
            raise HTTPException(500, str(e))
        finally:
            c.close()

    # ------------------------------------------------------------- import
    @app.post("/api/import")
    async def import_csv(
        file: UploadFile,
        format: str = Form("auto"),
        account: str | None = Form(None),
        tz: str | None = Form(None),
        tz_offset_minutes: int | None = Form(None),
    ):
        """Import any platform export. format='auto' detects the platform;
        tz is an IANA name (the browser sends its own); account is optional —
        accounts named inside the file are used and never mixed."""
        if format not in FORCE_FORMAT:
            raise HTTPException(400, f"unknown format; choose one of {sorted(FORCE_FORMAT)}")
        tzv = tz or (timezone(timedelta(minutes=tz_offset_minutes))
                     if tz_offset_minutes is not None else None)
        data = await file.read()
        c = conn()
        try:
            return impauto.import_file(c, data, account_label=(account or None),
                                       tz=tzv, force_format=FORCE_FORMAT[format],
                                       filename=file.filename)
        except ValueError as e:
            raise HTTPException(400, str(e))
        finally:
            c.close()

    @app.post("/api/demo")
    def demo_seed():
        from . import demo
        c = conn()
        try:
            return demo.seed(c)
        finally:
            c.close()

    @app.delete("/api/demo")
    def demo_remove():
        from . import demo
        c = conn()
        try:
            return demo.remove_demo(c)
        finally:
            c.close()

    @app.get("/api/import/formats")
    def import_formats():
        return sorted(FORCE_FORMAT)

    @app.exception_handler(sqlite3.Error)
    def _sql_err(_, exc):
        return JSONResponse(status_code=500, content={"detail": f"database error: {exc}"})

    return app
