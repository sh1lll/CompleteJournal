"""CLI: python -m completejournal <command>

Commands:
  init --db journal.db
  import --db journal.db --file fills.csv --format tradovate|ninjatrader|rithmic --account "Name" [--tz-offset-minutes N]
  rebuild --db journal.db
  stats --db journal.db
  reconcile --db journal.db
  write --db journal.db [--kind end-of-day] [--title T] [--about 2026-10-11] (body from stdin)
  search --db journal.db --query "failed breakout"
  serve --db journal.db [--port 8321]
"""
from __future__ import annotations

import argparse
import json
import sys

from . import analytics, db as dbmod, journal, reconstruction
from .importers import base as impbase
from .importers.platforms import REGISTRY


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="completejournal")
    p.add_argument("command", choices=["init", "import", "rebuild", "stats", "reconcile", "write",
                                       "search", "serve", "export", "sync", "fetch-bars",
                                       "import-screenshots"])
    p.add_argument("--out", default="export", help="output directory for export")
    p.add_argument("--platform", choices=["tradovate", "projectx"], help="sync platform")
    p.add_argument("--demo", action="store_true", help="tradovate demo environment")
    p.add_argument("--px-account-id", type=int, help="ProjectX account id (see sync output)")
    p.add_argument("--start", help="ISO start timestamp (projectx sync / fetch-bars)")
    p.add_argument("--end", help="ISO end timestamp (projectx sync / fetch-bars)")
    p.add_argument("--symbol", help="instrument root for fetch-bars, e.g. MES")
    p.add_argument("--resolution", default="1m")
    p.add_argument("--dir", help="screenshot folder for import-screenshots")
    p.add_argument("--date", help="force session date for import-screenshots")
    p.add_argument("--db", default="journal.db")
    p.add_argument("--file")
    p.add_argument("--format", dest="fmt", choices=sorted(REGISTRY))
    p.add_argument("--account")
    p.add_argument("--tz-offset-minutes", type=int, default=0)
    p.add_argument("--kind")
    p.add_argument("--title")
    p.add_argument("--about")
    p.add_argument("--query")
    p.add_argument("--port", type=int, default=8321)
    args = p.parse_args(argv)

    conn = dbmod.connect(args.db)

    if args.command == "init":
        print(f"initialized {args.db}")
    elif args.command == "import":
        if not (args.file and args.fmt and args.account):
            p.error("import requires --file, --format, --account")
        parser, source = REGISTRY[args.fmt]
        executions, warnings = parser(args.file, tz_offset_minutes=args.tz_offset_minutes)
        acct_id = dbmod.get_or_create_account(conn, args.account, platform=args.fmt)
        res = impbase.ingest(conn, acct_id, args.account, source, args.fmt,
                             executions, filename=args.file, warnings=warnings)
        report = reconstruction.rebuild(conn)
        print(json.dumps({
            "batch": res.batch_id, "rows": res.rows_total, "new": res.rows_new,
            "duplicates": res.rows_dup, "warnings": res.warnings,
            "trades": report.trades_created, "open": report.open_trades,
            "unknown_instruments": report.unknown_instruments,
        }, indent=2))
    elif args.command == "rebuild":
        report = reconstruction.rebuild(conn)
        print(json.dumps(report.__dict__, indent=2))
    elif args.command == "stats":
        print(json.dumps(analytics.overall(conn).to_dict(), indent=2))
    elif args.command == "reconcile":
        print(json.dumps(analytics.reconciliation(conn), indent=2))
    elif args.command == "write":
        body = sys.stdin.read().strip()
        if not body:
            print("empty entry — nothing saved", file=sys.stderr)
            return 1
        eid = journal.create_entry(conn, body, kind=args.kind, title=args.title, about_date=args.about)
        print(f"entry {eid} saved")
    elif args.command == "search":
        if not args.query:
            p.error("search requires --query")
        print(json.dumps(journal.search(conn, args.query), indent=2))
    elif args.command == "export":
        from . import export
        counts = export.export_full(conn, args.out)
        print(json.dumps(counts, indent=2))
    elif args.command == "sync":
        # Credentials come from environment variables at call time, never stored:
        #   tradovate: TRADOVATE_USER, TRADOVATE_PASS, TRADOVATE_CID, TRADOVATE_SEC
        #   projectx:  PROJECTX_USER, PROJECTX_API_KEY (+ --px-account-id, --start, --end)
        import os
        if not (args.platform and args.account):
            p.error("sync requires --platform and --account")
        if args.platform == "tradovate":
            from .sync import tradovate as tv
            missing = [k for k in ("TRADOVATE_USER", "TRADOVATE_PASS", "TRADOVATE_CID", "TRADOVATE_SEC")
                       if not os.environ.get(k)]
            if missing:
                p.error(f"missing environment variables: {', '.join(missing)}")
            client = tv.TradovateClient(
                os.environ["TRADOVATE_USER"], os.environ["TRADOVATE_PASS"],
                os.environ["TRADOVATE_CID"], os.environ["TRADOVATE_SEC"],
                base_url=tv.DEMO if args.demo else tv.LIVE)
            try:
                print(json.dumps(tv.sync(conn, client, args.account), indent=2))
            finally:
                client.close()
        else:
            from .sync import projectx as px
            missing = [k for k in ("PROJECTX_USER", "PROJECTX_API_KEY") if not os.environ.get(k)]
            if missing:
                p.error(f"missing environment variables: {', '.join(missing)}")
            client = px.ProjectXClient(os.environ["PROJECTX_USER"], os.environ["PROJECTX_API_KEY"])
            try:
                if not args.px_account_id:
                    print(json.dumps({"accounts": client.accounts()}, indent=2))
                    print("re-run with --px-account-id <id> --start <iso> --end <iso>")
                else:
                    if not (args.start and args.end):
                        p.error("projectx sync requires --start and --end")
                    print(json.dumps(px.sync(conn, client, args.account,
                                             args.px_account_id, args.start, args.end), indent=2))
            finally:
                client.close()
    elif args.command == "fetch-bars":
        from .sync import databento
        if not (args.symbol and args.start and args.end):
            p.error("fetch-bars requires --symbol, --start, --end (and DATABENTO_API_KEY)")
        n = databento.fetch_ohlcv(conn, args.symbol, args.start, args.end,
                                  resolution=args.resolution)
        print(json.dumps({"bars_new": n, "symbol": args.symbol.upper(),
                          "resolution": args.resolution}, indent=2))
    elif args.command == "import-screenshots":
        from . import screenshots
        if not args.dir:
            p.error("import-screenshots requires --dir")
        root = str(args.db) + ".attachments"
        print(json.dumps(screenshots.import_folder(conn, root, args.dir, date=args.date), indent=2))
    elif args.command == "serve":
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(args.db), host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
