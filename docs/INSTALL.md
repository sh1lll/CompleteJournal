# Installing Complete Journal

Complete Journal is a local-first desktop app. Your journal lives on your
computer in one file (`journal.db`) plus an attachments folder:

| System | Data folder |
|---|---|
| Windows | `%APPDATA%\CompleteJournal` |
| macOS | `~/Library/Application Support/CompleteJournal` |
| Linux | `~/.local/share/completejournal` |

Nothing is sent anywhere unless you turn on an optional feature that needs the
internet (API sync with your platform, price bars, or AI).

## Option 1 — Download the app (no Python needed)

Builds for Windows, macOS and Linux are produced by the **Desktop apps**
GitHub workflow (`.github/workflows/desktop.yml`) and attached to each GitHub
Release (push a tag like `v0.2.0`, or run the workflow manually from the
Actions tab).

- **Windows:** unzip `CompleteJournal-windows.zip`, run `CompleteJournal.exe`.
- **macOS:** unzip `CompleteJournal-macos.zip`, move *Complete Journal* to
  Applications, open it.
- **Linux:** extract `CompleteJournal-linux.tar.gz`, run `CompleteJournal/CompleteJournal`.

The app opens in its own window: a native window on Windows (Edge WebView2)
and macOS (WebKit); on Linux it uses Chrome/Chromium/Edge in app mode if
installed, otherwise your browser.

**First-launch warnings:** the builds are not yet code-signed, so Windows
SmartScreen ("More info → Run anyway") and macOS Gatekeeper (right-click →
Open) will ask you to confirm once. Signing requires paid developer
certificates — see ROADMAP.md.

## Option 2 — Run from source (any OS with Python 3.11+)

```bash
pip install ".[desktop]"          # app + native window support
completejournal-desktop           # opens the app window
# or, browser tab instead of a window:
completejournal serve --db journal.db
```

## Optional extras

| Extra | What it adds | Install |
|---|---|---|
| AI | Written daily summaries and "Ask your journal" (Claude). Everything works without it. | included in downloaded apps; from source: `pip install ".[ai]"`, then add your key in **Settings** |
| desktop | Native window when running from source | `pip install ".[desktop]"` |

## Live connection (optional)

Settings → **Live connection**. Fills appear within about a second.

- **TopstepX / ProjectX:** username, API key (subscribe to the ProjectX API in
  your TopstepX dashboard) and the account ID.
- **Tradovate:** username, password and an API key (cid + secret) created in
  your Tradovate account settings (API access is a paid add-on).

Read-only: the app has no ability to place, change or cancel orders. If the
connection drops it reconnects and catches up, so fills are never lost.
Credentials are stored in your system keychain or a private file only you can
read. Importing export files keeps working for every platform.

## Phone quick-capture

Settings → **Phone quick-capture** → *Turn on*, then scan the QR code with
your phone (same Wi-Fi) and choose "Add to Home Screen". The phone can only
add notes and photos — it can't read your journal. Notes typed without signal
are kept on the phone and sent automatically later. *Unpair all phones*
disconnects every paired phone at once. On public Wi-Fi, use a private network
such as Tailscale rather than turning this on.

## Updates

The app asks once whether to check for new versions. If you agree, it checks
GitHub at most once a day (only the public version number is requested) and
shows a download link when a newer version exists. Your journal is kept when
you install a new version.

## Backups

See [BACKUP.md](BACKUP.md). Copying the data folder is a complete backup.
