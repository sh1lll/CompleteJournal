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


class GradeIn(BaseModel):
    grade: str
    note: str | None = None


def create_app(db_path: str | Path, attachments_root: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="Complete Journal", version="0.1.0")
    att_root = Path(attachments_root) if attachments_root else Path(str(db_path) + ".attachments")

    def conn() -> sqlite3.Connection:
        # SQLite per-request connection: simple and safe for a single user.
        return dbmod.connect(db_path)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return resources.files("completejournal").joinpath("web/index.html").read_text()

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
                    "links": [dict(l) for l in links], "n_versions": n_versions}
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
