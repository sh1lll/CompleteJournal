"""Credential storage for optional connections (live platform sync).

Order: OS keychain (if the `keyring` package is available) → a private JSON
file readable only by this user (0600). Never the journal database, never
logged, never returned by the API.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path


def _dir() -> Path:
    return Path(os.environ.get("COMPLETEJOURNAL_HOME", Path.home() / ".completejournal"))


def _keyring():
    try:
        import keyring
        return keyring
    except ImportError:
        return None


def save(name: str, data: dict) -> str:
    blob = json.dumps(data)
    kr = _keyring()
    if kr:
        try:
            kr.set_password("completejournal", name, blob)
            return "os-keychain"
        except Exception:
            pass
    d = _dir()
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"secret_{name}.json"
    f.write_text(blob, encoding="utf-8")
    os.chmod(f, stat.S_IRUSR | stat.S_IWUSR)
    return "private-file"


def load(name: str) -> dict | None:
    kr = _keyring()
    if kr:
        try:
            v = kr.get_password("completejournal", name)
            if v:
                return json.loads(v)
        except Exception:
            pass
    f = _dir() / f"secret_{name}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            return None
    return None


def delete(name: str) -> None:
    kr = _keyring()
    if kr:
        try:
            kr.delete_password("completejournal", name)
        except Exception:
            pass
    f = _dir() / f"secret_{name}.json"
    if f.exists():
        f.unlink()
