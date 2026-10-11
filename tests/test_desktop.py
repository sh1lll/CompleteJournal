"""Desktop launcher: data locations, port, server start, health, shutdown."""
import json
import sys
import urllib.request
from pathlib import Path

from completejournal import desktop


def test_data_dir_per_os(monkeypatch, tmp_path):
    monkeypatch.delenv("COMPLETEJOURNAL_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert desktop.data_dir() == tmp_path / "Library" / "Application Support" / "CompleteJournal"
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert desktop.data_dir() == tmp_path / "Roaming" / "CompleteJournal"
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert desktop.data_dir() == tmp_path / ".local" / "share" / "completejournal"
    monkeypatch.setenv("COMPLETEJOURNAL_HOME", str(tmp_path / "custom"))
    assert desktop.data_dir() == tmp_path / "custom"


def test_server_starts_serves_and_stops(tmp_path):
    port = desktop.free_port()
    server, thread = desktop.start_server(tmp_path / "journal.db", port)
    url = f"http://127.0.0.1:{port}"
    try:
        assert desktop.wait_until_up(url, timeout=15)
        assert json.load(urllib.request.urlopen(url + "/api/health"))["ok"] is True
        assert b"<title>Complete Journal</title>" in urllib.request.urlopen(url + "/").read()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert (tmp_path / "journal.db").exists()


def test_wait_until_up_times_out_cleanly():
    assert desktop.wait_until_up(f"http://127.0.0.1:{desktop.free_port()}", timeout=0.5) is False
