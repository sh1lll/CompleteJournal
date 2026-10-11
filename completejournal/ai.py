"""Optional AI layer (Claude). Nothing in Complete Journal requires it.

Without an API key every feature still works: similarity search and the daily
recap are local and deterministic (similar.py, recap.py). With a key, two
extras become available:

  * AI daily summary — a written narrative of the day, built on top of the
    data recap, citing [trade:N] / [entry:N] for its claims
  * Ask your journal — a question answered from your own retrieved entries,
    with citations

Guarantees:
  * AI output is stored ONLY in ai_artifacts (never in entries) with the
    model name and the source records it was given
  * citations are validated: any [trade:N]/[entry:N] the model cites that
    was not in its input is reported as unverified, not silently trusted
  * the API key is never written to the database; it comes from the
    ANTHROPIC_API_KEY environment variable, the OS keychain (if `keyring` is
    installed) or a private key file readable only by this user
  * the `anthropic` package is an optional install: pip install "completejournal[ai]"
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
from pathlib import Path

from . import recap, similar

DEFAULT_MODEL = "claude-opus-5-5"
_KEYRING_SERVICE = "completejournal"
_KEY_FILE = Path(os.environ.get("COMPLETEJOURNAL_HOME", Path.home() / ".completejournal")) / "anthropic_key"

SYSTEM_PROMPT = """You help a trader review their own trading journal.

The material you receive has two kinds of records:
- trade records: objective data imported from the trader's platform
- journal entries: the trader's own writing — what they believed, felt and
  intended at the time. Treat entries as records of belief, not as facts about
  the market; they may contain tentative, emotional or mistaken ideas.

Write plainly and briefly. Every factual claim must cite its source inline
using exactly the ids given, in the form [trade:12] or [entry:5]. Use no other
citation form and never cite an id that was not provided.

Do not grade the trader, assign blame, or tell them what they should have done.
Do not invent market context that is not in the material. Where the material is
silent, say so. End with two or three open questions the trader could reflect on."""


# ------------------------------------------------------------------ config

def sdk_installed() -> bool:
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def _keyring():
    try:
        import keyring
        return keyring
    except ImportError:
        return None


def get_key() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    kr = _keyring()
    if kr:
        try:
            k = kr.get_password(_KEYRING_SERVICE, "anthropic")
            if k:
                return k
        except Exception:
            pass
    if _KEY_FILE.exists():
        return _KEY_FILE.read_text(encoding="utf-8").strip() or None
    return None


def save_key(key: str) -> str:
    key = key.strip()
    if not key:
        raise ValueError("empty key")
    kr = _keyring()
    if kr:
        try:
            kr.set_password(_KEYRING_SERVICE, "anthropic", key)
            return "os-keychain"
        except Exception:
            pass
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _KEY_FILE.write_text(key, encoding="utf-8")
    os.chmod(_KEY_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    return "private-file"


def delete_key() -> None:
    kr = _keyring()
    if kr:
        try:
            kr.delete_password(_KEYRING_SERVICE, "anthropic")
        except Exception:
            pass
    if _KEY_FILE.exists():
        _KEY_FILE.unlink()


def get_model(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM meta WHERE key='ai_model'").fetchone()
    return row[0] if row else DEFAULT_MODEL


def status(conn: sqlite3.Connection) -> dict:
    return {"sdk_installed": sdk_installed(), "configured": bool(get_key()),
            "model": get_model(conn), "required": False,
            "note": "AI is optional. Every feature works without it."}


# ------------------------------------------------------------------ calls

class AIUnavailable(RuntimeError):
    pass


def _client():
    if not sdk_installed():
        raise AIUnavailable('AI extras not installed. Run: pip install "completejournal[ai]"')
    key = get_key()
    if not key:
        raise AIUnavailable("No Anthropic API key configured (Settings → AI).")
    import anthropic
    return anthropic.Anthropic(api_key=key)


def _complete(client, model: str, user_content: str) -> tuple[str, str]:
    """Single request. Returns (text, model_that_served). Raises on refusal."""
    resp = client.beta.messages.create(
        model=model,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": user_content}],
    )
    if resp.stop_reason == "refusal":
        raise AIUnavailable("The model declined this request; nothing was saved.")
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    if not text:
        raise AIUnavailable("The model returned no text; nothing was saved.")
    return text, getattr(resp, "model", model)


_CITE = re.compile(r"\[(trade|entry):(\d+)\]")


def _validate_citations(text: str, allowed: set[str]) -> tuple[list[str], list[str]]:
    cited = {f"{k}:{v}" for k, v in _CITE.findall(text)}
    return sorted(cited & allowed), sorted(cited - allowed)


def _store(conn, kind: str, model: str, text: str, sources: list[str], unverified: list[str]) -> dict:
    meta = {"sources": sources, "unverified_citations": unverified}
    cur = conn.execute(
        "INSERT INTO ai_artifacts(kind, model, content_md, sources) VALUES (?,?,?,?)",
        (kind, model, text, json.dumps(meta)))
    conn.commit()
    row = conn.execute("SELECT * FROM ai_artifacts WHERE id=?", (cur.lastrowid,)).fetchone()
    out = dict(row)
    out.update(meta)
    return out


def _entries_block(rows) -> str:
    parts = []
    for e in rows:
        label = e["title"] or e["kind"] or "entry"
        parts.append(f"[entry:{e['id']}] ({e['kind'] or 'no kind'}, written {e['written_at'][:16]}Z) "
                     f"{label}\n{e['body_md']}")
    return "\n\n".join(parts) or "(no journal entries)"


def daily_summary(conn: sqlite3.Connection, date: str, *, client=None) -> dict:
    client = client or _client()
    model = get_model(conn)
    data = recap.daily(conn, date)
    entries = conn.execute(
        "SELECT * FROM entries WHERE deleted_at IS NULL AND "
        "(about_date=? OR (about_date IS NULL AND substr(written_at,1,10)=?)) ORDER BY written_at",
        (date, date)).fetchall()
    trades = conn.execute(
        "SELECT id, symbol, direction, qty_max, entry_ts, exit_ts, avg_entry, avg_exit, net_pnl "
        "FROM trades WHERE session_date=? ORDER BY entry_ts", (date,)).fetchall()
    allowed = {f"entry:{e['id']}" for e in entries} | {f"trade:{t['id']}" for t in trades}
    allowed |= set(data["citations"])
    trades_txt = "\n".join(
        f"[trade:{t['id']}] {t['symbol']} {t['direction']} x{t['qty_max']} "
        f"in {t['entry_ts'][11:16]}Z @ {t['avg_entry']} out {(t['exit_ts'] or '')[11:16]}Z "
        f"@ {t['avg_exit']} net {t['net_pnl']:.2f}" for t in trades) or "(no trades)"
    content = (f"Session {date}.\n\n## Computed recap (from records)\n{data['markdown']}\n\n"
               f"## Trades\n{trades_txt}\n\n## Journal entries\n{_entries_block(entries)}\n\n"
               "Write a short summary of this session for the trader.")
    text, served = _complete(client, model, content)
    sources, unverified = _validate_citations(text, allowed)
    return _store(conn, "daily-summary", served, text, sources, unverified)


def ask(conn: sqlite3.Connection, question: str, *, client=None, k: int = 8) -> dict:
    """Answer a question from the trader's own retrieved entries (local retrieval)."""
    question = (question or "").strip()
    if not question:
        raise ValueError("empty question")
    client = client or _client()
    model = get_model(conn)
    hits = similar.find_similar(conn, text=question, limit=k, min_score=0.02)
    ids = [h["id"] for h in hits]
    rows = [conn.execute("SELECT * FROM entries WHERE id=?", (i,)).fetchone() for i in ids]
    allowed = {f"entry:{i}" for i in ids}
    content = (f"Question from the trader: {question}\n\n"
               f"## Retrieved journal entries (most relevant first)\n{_entries_block(rows)}\n\n"
               "Answer only from these entries. If they do not answer the question, say so.")
    text, served = _complete(client, model, content)
    sources, unverified = _validate_citations(text, allowed)
    art = _store(conn, "ask", served, f"**Q:** {question}\n\n{text}", sources, unverified)
    art["retrieved"] = ids
    return art


def list_artifacts(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    out = []
    for r in conn.execute("SELECT * FROM ai_artifacts ORDER BY id DESC LIMIT ?", (limit,)):
        d = dict(r)
        try:
            d.update(json.loads(d["sources"]))
        except (TypeError, ValueError):
            pass
        out.append(d)
    return out
