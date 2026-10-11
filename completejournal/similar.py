"""'When have I seen this before?' — local, private, no AI required.

TF-IDF cosine similarity over the trader's own entries, computed on this
machine. Mentions (@MES, @trade:12) and tags count as strong features.
Every result explains itself with the shared terms that produced the match,
so the trader can judge relevance instead of trusting a black box.
"""
from __future__ import annotations

import math
import re
import sqlite3
from collections import Counter

_STOP = set("""a about above after again against all am an and any are as at be because been before
being below between both but by can could did do does doing down during each few for from further
had has have having he her here hers herself him himself his how i if in into is it its itself just
me more most my myself no nor not now of off on once only or other our ours ourselves out over own
same she should so some such than that the their theirs them themselves then there these they this
those through to too under until up very was we were what when where which while who whom why will
with would you your yours yourself yourselves also got get going went really like today day still
one two think thought maybe much many well back even way see""".split())


def _stem(w: str) -> str:
    for suf in ("ing", "edly", "ed", "ies", "es", "s", "ly"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def tokens(text: str) -> Counter:
    text = text or ""
    c: Counter = Counter()
    for m in re.finditer(r"@((?:trade|entry):\d+|\d{4}-\d{2}-\d{2}|[A-Z0-9]{1,5})\b", text):
        tok = m.group(1)
        if tok[0].isalpha() and ":" not in tok:
            c[f"#{tok.lower()}"] += 3          # instrument mention: strong feature
    clean = re.sub(r"@\S+|!\[[^\]]*\]\([^)]*\)|https?://\S+", " ", text.lower())
    for w in re.findall(r"[a-z][a-z'\-]{2,}", clean):
        w = w.strip("'-")
        if w and w not in _STOP:
            c[_stem(w)] += 1
    # bigrams carry trading phrases: 'failed breakout', 'open drive', 'stop loss'
    words = [_stem(w) for w in re.findall(r"[a-z]{3,}", clean) if w not in _STOP]
    for a, b in zip(words, words[1:]):
        c[f"{a} {b}"] += 1
    return c


def surface_forms(text: str) -> dict[str, str]:
    """Map stemmed terms back to a word the trader actually wrote."""
    out: dict[str, str] = {}
    words = [w.strip("'-") for w in re.findall(r"[a-z][a-z'\-]{2,}", (text or "").lower())]
    for w in words:
        out.setdefault(_stem(w), w)
    plain = [w for w in re.findall(r"[a-z]{3,}", (text or "").lower()) if w not in _STOP]
    for a, b in zip(plain, plain[1:]):
        out.setdefault(f"{_stem(a)} {_stem(b)}", f"{a} {b}")
    return out


def _corpus(conn: sqlite3.Connection) -> list[tuple[int, Counter, sqlite3.Row]]:
    rows = conn.execute(
        "SELECT e.*, (SELECT GROUP_CONCAT(tag, ' ') FROM tags WHERE entry_id=e.id) AS tagstr "
        "FROM entries e WHERE e.deleted_at IS NULL").fetchall()
    out = []
    for r in rows:
        t = tokens(f"{r['title'] or ''}\n{r['body_md']}")
        for tag in (r["tagstr"] or "").split():
            if tag != "demo":
                t[f"tag:{tag}"] += 2
        out.append((r["id"], t, r))
    return out


def find_similar(conn: sqlite3.Connection, *, text: str | None = None,
                 entry_id: int | None = None, limit: int = 5, min_score: float = 0.05) -> list[dict]:
    corpus = _corpus(conn)
    if not corpus:
        return []
    n = len(corpus)
    df: Counter = Counter()
    for _, t, _ in corpus:
        df.update(t.keys())
    idf = {term: math.log((1 + n) / (1 + c)) + 1.0 for term, c in df.items()}

    if entry_id is not None:
        found = next(((t, r) for i, t, r in corpus if i == entry_id), None)
        if found is None:
            raise KeyError(f"entry {entry_id} not found")
        query = found[0]
        surface = surface_forms(f"{found[1]['title'] or ''} {found[1]['body_md']}")
    else:
        query = tokens(text or "")
        surface = surface_forms(text or "")
    if not query:
        return []

    def vec(t: Counter) -> dict:
        return {k: (1 + math.log(v)) * idf.get(k, math.log(1 + n) + 1.0) for k, v in t.items()}

    qv = vec(query)
    qn = math.sqrt(sum(v * v for v in qv.values())) or 1.0
    results = []
    for i, t, row in corpus:
        if i == entry_id:
            continue
        dv = vec(t)
        dot = sum(qv[k] * dv[k] for k in qv.keys() & dv.keys())
        if not dot:
            continue
        score = dot / (qn * (math.sqrt(sum(v * v for v in dv.values())) or 1.0))
        if score < min_score:
            continue
        shared = sorted(qv.keys() & dv.keys(), key=lambda k: -(qv[k] * dv[k]))[:6]
        results.append({
            "id": i, "score": round(score, 3), "kind": row["kind"], "title": row["title"],
            "about_date": row["about_date"], "written_at": row["written_at"],
            "excerpt": (row["body_md"] or "")[:240],
            "why": [surface.get(s, s).replace("#", "@").replace("tag:", "tag ") for s in shared],
        })
    results.sort(key=lambda r: -r["score"])
    return results[:limit]
