# Complete Journal

A trading journal built around what you write, with your trades filled in automatically.

Most trading journals are spreadsheets of fills with a notes box added on.
Complete Journal starts from the writing: what you planned, what you saw and
what you learned. Your trades are pulled in automatically and linked to those
notes, so months later you can read what you were thinking next to what
actually happened.

The app runs on your own computer, and your journal is a single file you own.
You don't need an account or a subscription, and nothing is stored in the cloud.

## What it does

### Writing

You can keep a pre-market plan, notes during the session, an end-of-day review
and theses (market ideas that play out over weeks). Editing an entry saves a
new version and keeps the old ones. If you see something differently later,
add a dated "learned later" note and the original stays as you wrote it.

Mention a market with `@MES`, tag with `#tags`, or link to a trade or another
entry, and backlinks show where an idea came up again. Search covers
everything you've written. Screenshots and attachments are stored next to
your journal on your computer.

### Trade capture

Import an export file and the app works out which platform it came from, the
number format (`1,234.50` or `1.234,50`), the date order and the timezone.
Importing the same file twice doesn't create duplicates.

These exports are recognized directly:

- Tradovate (Orders, Position History)
- TopstepX / ProjectX (Orders, Trades)
- NinjaTrader 8 (Executions, Trades, in any locale)
- Rithmic R|Trader (Order History)
- TradingView (Performance)

Other files with recognizable fill or round-trip columns are read too, and a
column-mapping importer handles anything left over, so any prop firm,
platform or account type can be brought in.

You can also connect Tradovate or TopstepX/ProjectX directly, and new fills
show up within about a second. The connection only reads data; the codebase
has no code for placing orders.

Trades are rebuilt from the raw fills, including partial exits and reversals,
with fees split across them. Session days follow the futures calendar, which
rolls over at 5 pm Chicago time.

### Review

- Plan vs. actual: put rules in your morning plan (for example "max 3 trades"
  or "stop after 2 losses") and the day review shows which ones you kept.
- A daily recap built from your data, linking back to each trade and note,
  with a few questions to reflect on.
- Weekly and monthly reports and a calendar view.
- "Seen this before?" finds past entries similar to the one you're writing.
- Trade grading, so you can rate your process apart from the result and see
  how often good process led to a good outcome.
- Flags for overtrading, revenge trades and trading after a losing streak.
- Price excursions (MAE/MFE), slippage against your intended price, and an
  economic calendar.

### Analytics

Win rate and expectancy come with confidence intervals. With too few trades
to say anything, the app shows "can't tell yet" in place of a precise-looking
number.

### Phone notes

Pair your phone by scanning a QR code on your home network, then write quick
notes from it. Notes written offline are held on the phone and sent when it's
back in range. A paired phone can add notes and see the ones it sent, and
can't open the rest of your journal.

### AI (optional)

Everything above works without AI. If you want it, add your own Anthropic API
key in Settings → AI to get written daily summaries and "Ask your journal".
AI text is stored apart from your own writing and cites the trades and entries
it used; a reference that doesn't match a real record is flagged. The key is
kept in your system keychain or a private file, never in the journal.

## Install

Windows, macOS and Linux builds are attached to each
[GitHub Release](../../releases). [docs/INSTALL.md](docs/INSTALL.md) has the
details. The builds aren't code-signed yet, so your system will ask you to
confirm the first time you open the app.

To run from source (Python 3.11+, any OS):

```bash
pip install ".[desktop]"      # add ",ai" for the optional AI features
completejournal-desktop       # opens the app in its own window
```

Then click Import and choose an export file, or Load demo data to look around
first.

### Command line

```bash
completejournal serve  --db journal.db                       # browser tab at http://127.0.0.1:8321
completejournal import --db journal.db --file any_export.csv  # auto-detected
completejournal demo   --db journal.db                       # sample data
```

## Your data

| System  | Where your journal lives |
|---------|--------------------------|
| Windows | `%APPDATA%\CompleteJournal` |
| macOS   | `~/Library/Application Support/CompleteJournal` |
| Linux   | `~/.local/share/completejournal` |

The folder holds one SQLite file (`journal.db`) and an `attachments` folder,
so copying it backs up everything ([docs/BACKUP.md](docs/BACKUP.md)). You can
also export the whole journal to CSV, JSON and Markdown at any time.

The app only goes online for features you turn on: live sync, price data, AI,
and the daily update check, which stays off until you agree to it.

## How it's built

The app is a small local web app served by Python and FastAPI. It opens in
the system web view through pywebview, or in a browser when that isn't
available. Data is stored in SQLite (WAL mode, FTS5 for search).

Raw fills are never modified. Trades are derived from them and can be rebuilt
at any time. Journal entries are versioned, and AI output has its own table.

Builds are packaged with PyInstaller. A GitHub Actions workflow tests, builds
and launch-checks the app on Windows, macOS and Linux on every push.

```bash
pip install -e ".[dev]"
python -m pytest              # 172 tests
```

The importers are tested against real platform export files, and the P&L they
produce matches each platform's own figures to the cent.

## Documentation

- [docs/INSTALL.md](docs/INSTALL.md): installing, live connections, extras
- [docs/BACKUP.md](docs/BACKUP.md): backing up and moving your journal
- [docs/SIGNING.md](docs/SIGNING.md): code signing for releases
- [docs/assessment/](docs/assessment/): the research behind the design
  (existing products, platform APIs, architecture, costs)
- [ROADMAP.md](ROADMAP.md): what's done and what's next

## Credits

- The real export samples used in the tests come from the
  [TradeTally](https://github.com/GeneBO98/tradetally) project (Apache-2.0);
  see [tests/fixtures/real/README.md](tests/fixtures/real/README.md).
- Built with help from Claude (Anthropic).

## License

[Apache License 2.0](LICENSE)
