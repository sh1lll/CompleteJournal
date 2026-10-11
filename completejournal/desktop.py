"""Desktop launcher: Complete Journal in its own window, data in the OS's
standard per-user location. Same app as `serve`, packaged for double-click.

Window strategy (first that works):
  1. native window via pywebview (Edge WebView2 on Windows, WebKit on macOS,
     GTK/Qt on Linux) — installed with the `desktop` extra
  2. an installed Chromium-family browser in --app mode (Edge, Chrome,
     Chromium, Brave): its own window with no tabs or address bar
  3. the default browser

The server binds to 127.0.0.1 on a free port only — never reachable from
the network.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP_NAME = "Complete Journal"


def data_dir() -> Path:
    """Standard per-user data directory for each OS (override with
    COMPLETEJOURNAL_HOME)."""
    override = os.environ.get("COMPLETEJOURNAL_HOME")
    if override:
        p = Path(override)
    elif sys.platform == "win32":
        p = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "CompleteJournal"
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "CompleteJournal"
    else:
        p = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "completejournal"
    p.mkdir(parents=True, exist_ok=True)
    return p


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_until_up(url: str, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1) as r:
                if r.status == 200:
                    return True
        except OSError:
            time.sleep(0.15)
    return False


def start_server(db_path: Path, port: int):
    import uvicorn
    from .api import create_app
    config = uvicorn.Config(create_app(db_path), host="127.0.0.1", port=port,
                            log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True, name="completejournal-server")
    t.start()
    return server, t


def _app_mode_browser() -> list[str] | None:
    candidates: list[str] = []
    if sys.platform == "win32":
        for base in (os.environ.get("PROGRAMFILES(X86)", ""), os.environ.get("PROGRAMFILES", ""),
                     os.environ.get("LOCALAPPDATA", "")):
            if base:
                candidates += [rf"{base}\Microsoft\Edge\Application\msedge.exe",
                               rf"{base}\Google\Chrome\Application\chrome.exe",
                               rf"{base}\BraveSoftware\Brave-Browser\Application\brave.exe"]
    elif sys.platform == "darwin":
        candidates += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                       "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                       "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                       "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                     "microsoft-edge", "brave-browser"):
            found = shutil.which(name)
            if found:
                candidates.append(found)
    for c in candidates:
        if c and Path(c).exists():
            return [c]
    return None


def open_window(url: str, profile_dir: Path) -> str:
    """Open the UI; returns which strategy was used. Blocks while a native
    or app-mode window is open."""
    try:
        import webview  # pywebview
        webview.create_window(APP_NAME, url, width=1280, height=860, min_size=(420, 600))
        webview.start()
        return "native"
    except Exception:
        pass
    browser = _app_mode_browser()
    if browser:
        proc = subprocess.Popen(browser + [f"--app={url}", f"--user-data-dir={profile_dir}",
                                           "--no-first-run", "--window-size=1280,860"])
        proc.wait()
        return "app-mode"
    webbrowser.open(url)
    return "browser"


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="completejournal-desktop")
    p.add_argument("--data-dir", help="where the journal is stored (default: OS standard location)")
    p.add_argument("--no-window", action="store_true", help="start the server only and print its URL")
    args = p.parse_args(argv)

    home = Path(args.data_dir) if args.data_dir else data_dir()
    home.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.stderr is None:
        # windowed builds (Windows/macOS) have no console: log to a file instead
        log = open(home / "desktop.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log
    db_path = home / "journal.db"
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    server, thread = start_server(db_path, port)
    if not wait_until_up(url):
        print("Complete Journal could not start its local server.", file=sys.stderr)
        return 1
    line = f"{APP_NAME} running at {url}  (data: {home})"
    print(line, flush=True)
    with open(home / "desktop.log", "a", encoding="utf-8") as f:  # also lets tools find the port
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")

    if args.no_window:
        try:
            while thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
    else:
        how = open_window(url, home / ".window-profile")
        if how == "browser":
            print("Opened in your browser. Close this window (or press Ctrl+C) to quit.", flush=True)
            try:
                while thread.is_alive():
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
    server.should_exit = True
    thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
