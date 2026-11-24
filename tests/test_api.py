"""API tests. Run with: pytest

Each test gets a fresh SQLite file and CV folder in a temporary directory,
so the real job_tracker.db is never touched.
"""

import importlib
import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_TRACKER_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("JOB_TRACKER_FILES", str(tmp_path / "cv_files"))
    import db
    import app
    importlib.reload(db)
    importlib.reload(app)
    return TestClient(app.app)


def test_create_and_list(client):
    res = client.post("/api/applications", json={
        "company": "Acme", "position": "Dev", "status": "saved", "rating": 4, "job_type": "Stage",
    })
    assert res.status_code == 201
    body = res.json()
    assert body["applied_date"] is None and body["rating"] == 4
    assert [a["company"] for a in client.get("/api/applications").json()] == ["Acme"]


def test_rejects_bad_values(client):
    base = {"company": "Acme", "position": "Dev"}
    assert client.post("/api/applications", json={**base, "status": "nope"}).status_code == 422
    assert client.post("/api/applications", json={**base, "rating": 9}).status_code == 422
    assert client.post("/api/applications", json={"position": "Dev"}).status_code == 422


def test_patch_status_and_stats(client):
    app_id = client.post("/api/applications", json={"company": "A", "position": "B", "status": "saved"}).json()["id"]
    client.post("/api/applications", json={"company": "C", "position": "D", "status": "sent"})
    res = client.patch(f"/api/applications/{app_id}", json={"status": "interview"})
    assert res.json()["status"] == "interview"
    stats = client.get("/api/stats").json()
    assert stats["total"] == 2 and stats["sent"] == 2 and stats["response_rate"] == 50


def test_delete_and_404(client):
    app_id = client.post("/api/applications", json={"company": "A", "position": "B"}).json()["id"]
    assert client.delete(f"/api/applications/{app_id}").status_code == 204
    assert client.delete(f"/api/applications/{app_id}").status_code == 404
    assert client.patch(f"/api/applications/{app_id}", json={"status": "sent"}).status_code == 404


def test_cv_upload(client):
    res = client.post("/api/cvs", files={"file": ("cv.pdf", b"%PDF-1.4 demo", "application/pdf")})
    assert res.status_code == 201
    cv_id = res.json()["id"]
    app_res = client.post("/api/applications", json={"company": "A", "position": "B", "cv_file_id": cv_id})
    assert app_res.json()["cv_file_name"] == "cv.pdf"
    assert client.get(f"/api/cvs/{cv_id}/file").content == b"%PDF-1.4 demo"
    bad = client.post("/api/cvs", files={"file": ("cv.exe", b"x", "application/octet-stream")})
    assert bad.status_code == 400


def test_migrates_old_database(tmp_path, monkeypatch):
    """A database from the first version (no 'saved' status, NOT NULL date) is upgraded."""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT NOT NULL, position TEXT NOT NULL,
        applied_date TEXT NOT NULL, contact_email TEXT, cv_version TEXT, cv_file_id INTEGER,
        status TEXT NOT NULL DEFAULT 'sent' CHECK (status IN ('sent','replied','interview','offer','rejected','no_response')),
        job_url TEXT, notes TEXT, updated_at TEXT NOT NULL DEFAULT (datetime('now')))""")
    conn.execute("INSERT INTO applications (company, position, applied_date, notes) VALUES ('Old', 'Dev', '2026-10-14', 'keep me')")
    conn.commit(); conn.close()

    monkeypatch.setenv("JOB_TRACKER_DB", str(path))
    monkeypatch.setenv("JOB_TRACKER_FILES", str(tmp_path / "cv_files"))
    import db
    importlib.reload(db)
    db.init_db()
    rows = db.list_applications()
    assert rows[0]["notes"] == "keep me"
    db.create_application({"company": "New", "position": "Dev", "status": "saved", "rating": 5})
    assert len(db.list_applications()) == 2
