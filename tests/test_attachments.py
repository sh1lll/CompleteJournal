"""Attachment store + API tests: content addressing, integrity, serving."""
import hashlib

import pytest
from fastapi.testclient import TestClient

from completejournal import attachments, db as dbmod
from completejournal.api import create_app

PNG = b"\x89PNG\r\n\x1a\n" + b"fakepngdata" * 10


@pytest.fixture()
def conn():
    c = dbmod.connect(":memory:")
    yield c
    c.close()


def test_store_is_content_addressed(conn, tmp_path):
    a = attachments.store(conn, tmp_path, PNG, filename="chart.png", media_type="image/png")
    b = attachments.store(conn, tmp_path, PNG, filename="chart-again.png", media_type="image/png")
    assert a["sha256"] == b["sha256"] == hashlib.sha256(PNG).hexdigest()
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert len(files) == 1  # same content stored once
    data, meta = attachments.load(conn, tmp_path, a["id"])
    assert data == PNG and meta["media_type"] == "image/png"


def test_empty_and_oversize_rejected(conn, tmp_path):
    with pytest.raises(ValueError):
        attachments.store(conn, tmp_path, b"")
    with pytest.raises(ValueError):
        attachments.store(conn, tmp_path, b"x" * (attachments.MAX_BYTES + 1))


def test_integrity_check(conn, tmp_path):
    a = attachments.store(conn, tmp_path, PNG, media_type="image/png")
    sha = a["sha256"]
    path = tmp_path / sha[:2] / sha[2:4] / f"{sha}.png"
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="integrity"):
        attachments.load(conn, tmp_path, a["id"])


def test_api_upload_and_serve(tmp_path):
    client = TestClient(create_app(tmp_path / "t.db", attachments_root=tmp_path / "att"))
    r = client.post("/api/attachments", files={"file": ("c.png", PNG, "image/png")})
    assert r.status_code == 200
    aid = r.json()["id"]
    r2 = client.get(f"/api/attachments/{aid}")
    assert r2.status_code == 200 and r2.content == PNG
    assert r2.headers["content-type"].startswith("image/png")
    assert client.get("/api/attachments/999").status_code == 404
