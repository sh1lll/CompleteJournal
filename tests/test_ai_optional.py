"""Optional AI layer — tested with a fake client (no network, no key)."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from completejournal import ai, db as dbmod, journal, reconstruction
from completejournal.api import create_app
from completejournal.importers.base import NormalizedExecution, ingest


class FakeClient:
    def __init__(self, text, stop_reason="end_turn"):
        self.calls = []
        self._text, self._stop = text, stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(stop_reason=self._stop, model=kw["model"],
                               content=[SimpleNamespace(type="text", text=self._text)])


@pytest.fixture()
def conn():
    c = dbmod.connect(":memory:")
    yield c
    c.close()


def _day(conn):
    a = dbmod.get_or_create_account(conn, "A")
    ingest(conn, a, "A", "test", "test", [
        NormalizedExecution("MES", "buy", 1, 5000.0, "2026-10-09T13:30:00.000Z"),
        NormalizedExecution("MES", "sell", 1, 5010.0, "2026-10-09T13:40:00.000Z"),
    ])
    reconstruction.rebuild(conn)
    return journal.create_entry(conn, "Patient open drive long on @MES.", kind="end-of-day",
                                about_date="2026-10-09")


def test_daily_summary_stored_only_as_ai_artifact_with_validated_citations(conn):
    eid = _day(conn)
    fake = FakeClient(f"A calm session [trade:1], consistent with your note [entry:{eid}]. "
                      "Also see [trade:999].")
    art = ai.daily_summary(conn, "2026-10-09", client=fake)
    assert art["kind"] == "daily-summary" and art["model"] == ai.DEFAULT_MODEL
    assert art["sources"] == sorted(["trade:1", f"entry:{eid}"])
    assert art["unverified_citations"] == ["trade:999"]          # hallucinated id flagged
    # entries untouched; nothing AI-authored in the journal
    assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM ai_artifacts").fetchone()[0] == 1
    call = fake.calls[0]
    assert call["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in call["betas"]
    assert "records of belief" in call["system"]
    assert "[entry:%d]" % eid in call["messages"][0]["content"]


def test_refusal_saves_nothing(conn):
    _day(conn)
    with pytest.raises(ai.AIUnavailable, match="declined"):
        ai.daily_summary(conn, "2026-10-09", client=FakeClient("", stop_reason="refusal"))
    assert conn.execute("SELECT COUNT(*) FROM ai_artifacts").fetchone()[0] == 0


def test_ask_uses_local_retrieval(conn):
    a = journal.create_entry(conn, "Failed breakout chase after CPI again.")
    journal.create_entry(conn, "Bought groceries.")
    art = ai.ask(conn, "when did I chase failed breakouts?",
                 client=FakeClient(f"You described it here [entry:{a}]."))
    assert art["retrieved"][0] == a and art["sources"] == [f"entry:{a}"]


def test_unconfigured_ai_is_clear_and_optional(conn, monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(ai, "_KEY_FILE", tmp_path / "none")
    monkeypatch.setattr(ai, "_keyring", lambda: None)
    st = ai.status(conn)
    assert st["configured"] is False and st["required"] is False
    with pytest.raises(ai.AIUnavailable):
        ai.daily_summary(conn, "2026-10-09")


def test_key_file_is_private(monkeypatch, tmp_path):
    import os, stat
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(ai, "_KEY_FILE", tmp_path / "k" / "anthropic_key")
    monkeypatch.setattr(ai, "_keyring", lambda: None)
    assert ai.save_key("sk-test") == "private-file"
    mode = stat.S_IMODE(os.stat(tmp_path / "k" / "anthropic_key").st_mode)
    assert mode == 0o600 and ai.get_key() == "sk-test"
    ai.delete_key()
    assert ai.get_key() is None


def test_api_works_fully_without_ai(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(ai, "_KEY_FILE", tmp_path / "none")
    monkeypatch.setattr(ai, "_keyring", lambda: None)
    c = TestClient(create_app(tmp_path / "t.db"))
    c.post("/api/entries", json={"body_md": "Failed breakout on @MES", "about_date": "2026-10-09"})
    assert c.get("/api/ai/status").json()["configured"] is False
    assert c.get("/api/similar", params={"text": "failed breakout"}).json()
    assert c.get("/api/recap/2026-10-09").json()["source"].endswith("(no AI)")
    assert c.get("/api/plan/2026-10-09").status_code == 200
    assert c.get("/api/reports/week/2026-10-09").json()["kind"] == "week"
    r = c.post("/api/ai/summary/2026-10-09")
    assert r.status_code == 409 and "key" in r.json()["detail"].lower()
