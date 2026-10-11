# Complete Journal

**A trading journal that puts your writing first, and fills in the trades for you.**

Most trading journals are spreadsheets of fills with a notes box bolted on.
Complete Journal works the other way round. It is a place to write down what
you planned, what you saw and what you learned. Your trades are pulled in
automatically and linked to that writing, so you can look back months later
and see what you were thinking alongside what actually happened.

It runs on your own computer. Your journal is one file that belongs to you.
There are no accounts, no subscriptions and no cloud.

---

## What it does

### Write
- **Daily notes:** a pre-market plan, notes during the session, an end-of-day
  review and **theses** (longer-running market ideas).
- **Nothing is silently rewritten.** Every edit is kept as a new version with
  full history. To add hindsight, write a dated "learned later" note instead of
  changing what you originally wrote.
- **Linking:** use `@MES`, `#tags` and links to trades or other entries.
  Backlinks show where each idea came up again.
- **Full-text search** across everything you've written.
- **Screenshots and attachments** are stored next to your journal, never on
  someone else's server.

### Capture trades automatically
- **Import any export file.** The platform, number format (`1,234.50` or
  `1.234,50`), date order and timezone are detected for you, and re-importing
  the same file never creates duplicates.
- **Recognized exports:**
  - Tradovate (Orders, Position History)
  - TopstepX / ProjectX (Orders, Trades)
  - NinjaTrader 8 (Executions, Trades, in any locale)
  - Rithmic R|Trader (Order History)
  - TradingView (Performance)
- **Anything else:** any other file with recognizable fill or round-trip
  columns is handled too, and a column-mapping importer covers the rest.
  It works with any prop firm, platform or account type.
- **Live connection (optional):** link Tradovate or TopstepX/ProjectX and fills
  appear within about a second. The connection is **read-only**: this codebase
  contains no order-placement code at all.
- Trades are rebuilt from the raw fills: partial exits, reversals and fees
  split fairly across them. Session days follow the futures calendar, which
  rolls over at 5 pm Chicago time.

### Review
- **Plan vs. actual:** write rules in your morning plan (such as "max 3 trades",
  "stop after 2 losses") and the day review checks which you kept or broke.
- **Daily recap:** a summary built from your data, with links back to each
  trade and note, plus questions to reflect on.
- **Weekly and monthly reports, and a calendar view.**
- **"Seen this before?"** finds past entries similar to what you're writing now.
- **Trade grading:** grade your process separately from the result, then
  compare good process against good outcome.
- **Behavior flags:** overtrading, revenge trades and trading after a losing
  streak.
- **Price excursions (MAE/MFE), slippage against your intended price,
  economic calendar.**

### Honest analytics
Win rate and expectancy are shown with **confidence intervals**. When there
aren't enough trades to tell, the app says *"can't tell yet"* instead of
showing a number that looks precise but isn't.

### Phone quick-notes
Pair your phone by scanning a QR code on your home network, then jot notes
from it. Notes written offline are saved and sent once you're back in range.
The phone can only add notes and see the ones it sent. It can't open the rest of
your journal.

### AI: optional, never required
Everything above works without AI. If you want it, add your own Anthropic API
key in **Settings → AI** to get written daily summaries and "Ask your journal".
AI text is kept separate from your own writing. It cites the trades and
entries it draws on, and any reference that doesn't match a real record is
flagged. Your key is stored in the system keychain (or a private file), never
in the journal.

---

## Install

**Download the app:** Windows, macOS and Linux builds are attached to each
[GitHub Release](../../releases). See [docs/INSTALL.md](docs/INSTALL.md) for
details and first-launch notes. The builds are not code-signed yet, so your
system will ask you to confirm once.

**Or run from source** (Python 3.11+, any OS):

```bash
pip install ".[desktop]"      # add ",ai" for the optional AI features
completejournal-desktop       # opens the app in its own window
```

Then click **Import** and choose an export file, or **Load demo data** to look
around first.

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

It is a single SQLite file (`journal.db`) plus an `attachments` folder. Copy
the folder and you've backed up everything. See [docs/BACKUP.md](docs/BACKUP.md).
You can also export everything to open formats (CSV, JSON and Markdown) at any
time.

Nothing leaves your computer unless you turn on a feature that needs the
internet: live sync, price data, AI, or the daily update check, which is off
until you say yes.

---

## How it's built

- **Python + FastAPI** serves a small local web app. The window opens through
  the system web view (pywebview), or a browser if that isn't available.
- **SQLite** in WAL mode, with FTS5 for search.
- **Design rules:**
  - Raw fills are immutable.
  - Trades are derived from the fills and can always be rebuilt.
  - Journal entries are versioned.
  - AI output lives only in its own table.
- **Packaging:** PyInstaller. A GitHub Actions workflow tests, builds and
  launch-checks the app on Windows, macOS and Linux for every push.

```bash
pip install -e ".[dev]"
python -m pytest              # 172 tests
```

Importers are tested against real platform export files, and the P&L is
reproduced to the cent against each platform's own numbers.

## Documentation

- [docs/INSTALL.md](docs/INSTALL.md): installing, live connections, extras
- [docs/BACKUP.md](docs/BACKUP.md): backing up and moving your journal
- [docs/SIGNING.md](docs/SIGNING.md): code signing for releases
- [docs/assessment/](docs/assessment/): the research behind the design
  (existing products, platform APIs, architecture, costs)
- [ROADMAP.md](ROADMAP.md): what's done and what's next

## Credits

- Real-world export samples used in the tests come from the
  [TradeTally](https://github.com/GeneBO98/tradetally) project (Apache-2.0).
  See [tests/fixtures/real/README.md](tests/fixtures/real/README.md).
- Built with help from Claude (Anthropic).

## License

[Apache License 2.0](LICENSE)
