"""Web server for the job application tracker.

Run it with:
    uvicorn app:app --reload
then open http://127.0.0.1:8000 in your browser.

The server exposes a small REST API under /api and serves the web page
(static/index.html) at the root URL.
"""

import uuid
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

import db

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Upload rules for CV files.
ALLOWED_CV_EXTENSIONS = {".pdf", ".doc", ".docx"}
MAX_CV_BYTES = 10 * 1024 * 1024  # 10 MB

app = FastAPI(title="Job Tracker")

# Make sure the table exists before the first request arrives.
db.init_db()


def _check_status(value: Optional[str]) -> Optional[str]:
    """Shared validator: reject statuses that are not in db.STATUSES."""
    if value is not None and value not in db.STATUSES:
        raise ValueError(f"status must be one of {', '.join(db.STATUSES)}")
    return value


class ApplicationCreate(BaseModel):
    """Body expected by POST /api/applications.

    Pydantic validates types automatically: for example applied_date must be
    a real date, otherwise FastAPI answers 422 with a clear error message.
    """

    company: str = Field(min_length=1, max_length=200)
    position: str = Field(min_length=1, max_length=200)
    applied_date: Optional[date] = None  # empty while the job is only "saved"
    contact_email: Optional[str] = None
    cv_version: Optional[str] = None
    cv_file_id: Optional[int] = None
    status: str = "sent"
    job_url: Optional[str] = None
    notes: Optional[str] = None
    job_type: Optional[str] = Field(default=None, max_length=50)
    location: Optional[str] = Field(default=None, max_length=200)
    salary: Optional[str] = Field(default=None, max_length=100)
    rating: Optional[int] = Field(default=None, ge=1, le=5)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value):
        return _check_status(value)


class ApplicationUpdate(BaseModel):
    """Body expected by PATCH /api/applications/{id}: every field is optional."""

    company: Optional[str] = Field(default=None, min_length=1, max_length=200)
    position: Optional[str] = Field(default=None, min_length=1, max_length=200)
    applied_date: Optional[date] = None
    contact_email: Optional[str] = None
    cv_version: Optional[str] = None
    cv_file_id: Optional[int] = None
    status: Optional[str] = None
    job_url: Optional[str] = None
    notes: Optional[str] = None
    job_type: Optional[str] = Field(default=None, max_length=50)
    location: Optional[str] = Field(default=None, max_length=200)
    salary: Optional[str] = Field(default=None, max_length=100)
    rating: Optional[int] = Field(default=None, ge=1, le=5)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value):
        return _check_status(value)


def _to_db(model: BaseModel, only_set: bool = False) -> dict:
    """Convert a Pydantic model to a plain dict that db.py can store.

    Dates become ISO strings ("2026-10-14"). With only_set=True we keep only
    the fields the client actually sent, which is what PATCH needs.
    """
    data = model.model_dump(exclude_unset=only_set)
    if data.get("applied_date") is not None:
        data["applied_date"] = data["applied_date"].isoformat()
    return data


def _check_cv_exists(data: dict) -> None:
    """Answer 400 if the request points to a CV file that does not exist."""
    cv_id = data.get("cv_file_id")
    if cv_id is not None and db.get_cv_file(cv_id) is None:
        raise HTTPException(status_code=400, detail="This CV file does not exist")


@app.get("/api/statuses")
def list_statuses():
    """Return the allowed status values, so the page does not hard-code them."""
    return list(db.STATUSES)


@app.get("/api/stats")
def stats():
    """Counts per status and the response rate, for the header of the board."""
    return db.get_stats()


@app.get("/api/applications")
def list_applications(
    status: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
):
    """List applications, optionally filtered: /api/applications?status=sent&search=paul"""
    if status is not None and status not in db.STATUSES:
        raise HTTPException(status_code=400, detail="Unknown status")
    return db.list_applications(status=status, search=search)


@app.post("/api/applications", status_code=201)
def create_application(payload: ApplicationCreate):
    """Create a new application. Returns 201 Created and the stored row."""
    data = _to_db(payload)
    _check_cv_exists(data)
    return db.create_application(data)


@app.patch("/api/applications/{app_id}")
def update_application(app_id: int, payload: ApplicationUpdate):
    """Change some fields of an application, for example only its status."""
    changes = _to_db(payload, only_set=True)
    _check_cv_exists(changes)
    updated = db.update_application(app_id, changes)
    if updated is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return updated


@app.delete("/api/applications/{app_id}", status_code=204)
def delete_application(app_id: int):
    """Delete an application. Returns 204 No Content on success."""
    if not db.delete_application(app_id):
        raise HTTPException(status_code=404, detail="Application not found")


@app.get("/api/cvs")
def list_cvs():
    """List every uploaded CV, newest first."""
    return db.list_cv_files()


@app.post("/api/cvs", status_code=201)
async def upload_cv(file: UploadFile = File(...)):
    """Upload a CV (multipart/form-data, field name "file").

    The file is saved under a random name so two uploads called "CV.pdf"
    never overwrite each other; the original name is kept for display.
    """
    original_name = Path(file.filename or "").name  # drop any folder part
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_CV_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PDF, DOC or DOCX files are accepted")

    content = await file.read(MAX_CV_BYTES + 1)
    if len(content) > MAX_CV_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 10 MB")
    if not content:
        raise HTTPException(status_code=400, detail="File is empty")

    stored_name = f"{uuid.uuid4().hex}{extension}"
    db.CV_DIR.mkdir(parents=True, exist_ok=True)
    (db.CV_DIR / stored_name).write_bytes(content)
    return db.create_cv_file(original_name, stored_name)


@app.get("/api/cvs/{cv_id}/file")
def download_cv(cv_id: int):
    """Open a CV in the browser (PDFs display inline, Word files download)."""
    cv = db.get_cv_file(cv_id)
    path = db.CV_DIR / cv["stored_name"] if cv else None
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="CV file not found")
    return FileResponse(path, filename=cv["original_name"], content_disposition_type="inline")


@app.get("/")
def index():
    """Serve the single-page front end."""
    return FileResponse(STATIC_DIR / "index.html")
