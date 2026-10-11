"""Update checks: opt-in, cached daily, honest about failures."""
import pytest

from completejournal import __version__, db as dbmod, updates


@pytest.fixture()
def conn():
    c = dbmod.connect(":memory:")
    yield c
    c.close()


def rel(tag):
    return {"tag_name": tag, "html_url": f"https://github.com/x/releases/{tag}",
            "published_at": "2026-10-11T00:00:00Z",
            "assets": [{"name": "CompleteJournal-windows.zip", "browser_download_url": "https://dl/win"},
                       {"name": "CompleteJournal-macos.zip", "browser_download_url": "https://dl/mac"},
                       {"name": "CompleteJournal-linux.tar.gz", "browser_download_url": "https://dl/linux"}]}


def test_nothing_is_fetched_until_the_user_opts_in(conn):
    calls = []
    r = updates.check(conn, fetch=lambda repo: calls.append(repo) or rel("v9.9.9"))
    assert r["preference"] == "ask" and r["update_available"] is False and calls == []
    updates.set_preference(conn, False)
    assert updates.check(conn, fetch=lambda repo: calls.append(1)) ["preference"] == "off" and calls == []


def test_newer_release_offered_with_os_download(conn, monkeypatch):
    monkeypatch.setattr(updates.sys, "platform", "darwin")
    updates.set_preference(conn, True)
    r = updates.check(conn, fetch=lambda repo: rel("v99.0.0"))
    assert r["update_available"] is True and r["latest"] == "v99.0.0"
    assert r["download_url"] == "https://dl/mac" and r["cached"] is False


def test_same_or_older_release_is_not_an_update(conn):
    updates.set_preference(conn, True)
    assert updates.check(conn, fetch=lambda repo: rel("v" + __version__))["update_available"] is False
    assert updates.check(conn, force=True, fetch=lambda repo: rel("v0.0.1"))["update_available"] is False


def test_daily_cache_and_force(conn):
    updates.set_preference(conn, True)
    calls = []
    f = lambda repo: calls.append(1) or rel("v99.0.0")  # noqa: E731
    updates.check(conn, fetch=f)
    assert updates.check(conn, fetch=f)["cached"] is True and len(calls) == 1
    updates.check(conn, fetch=f, force=True)
    assert len(calls) == 2


def test_no_release_yet_and_network_failure(conn):
    updates.set_preference(conn, True)
    assert updates.check(conn, fetch=lambda repo: None)["note"] == "no release published yet"

    def boom(repo):
        raise OSError("offline")
    r = updates.check(conn, fetch=boom, force=True)
    assert "could not check" in r["error"] and r["update_available"] is False


def test_parse_version():
    assert updates.parse_version("v1.2.3") == (1, 2, 3)
    assert updates.parse_version("0.2") == (0, 2, 0)
    assert updates.parse_version("v1.10.0") > updates.parse_version("v1.9.9")
    assert updates.parse_version("nonsense") is None
