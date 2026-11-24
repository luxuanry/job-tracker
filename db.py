"""Database layer for the job application tracker.

All data is stored in a single SQLite file (job_tracker.db) next to this script.
Uploaded CV files are stored on disk in the cv_files/ folder; the database only
keeps their names. This module knows nothing about HTTP or HTML.
"""

import os
import sqlite3
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent

# Set JOB_TRACKER_DB / JOB_TRACKER_FILES to use other locations (useful for tests and demos).
DB_PATH = Path(os.environ.get("JOB_TRACKER_DB", BASE_DIR / "job_tracker.db"))
CV_DIR = Path(os.environ.get("JOB_TRACKER_FILES", BASE_DIR / "cv_files"))

# Allowed values for the "status" column, in pipeline order (one board column each).
# The CHECK constraint in the table below enforces this list at the database level.
STATUSES = ("saved", "sent", "replied", "interview", "offer", "no_response", "rejected")

# Columns the user is allowed to write (id and updated_at are managed by us).
EDITABLE_FIELDS = (
    "company", "position", "applied_date", "contact_email",
    "cv_version", "cv_file_id", "status", "job_url", "notes",
    "job_type", "location", "salary", "rating",
)

# One row per uploaded CV file.
# original_name is what the user sees; stored_name is the unique name on disk.
SCHEMA_CV_FILES = """
CREATE TABLE IF NOT EXISTS cv_files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    original_name TEXT NOT NULL,
    stored_name   TEXT NOT NULL UNIQUE,
    uploaded_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

SCHEMA_APPLICATIONS = f"""
CREATE TABLE IF NOT EXISTS applications (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    company       TEXT NOT NULL,
    position      TEXT NOT NULL,
    applied_date  TEXT,                       -- ISO format: YYYY-MM-DD, empty while "saved"
    contact_email TEXT,
    cv_version    TEXT,                       -- legacy free-text label
    cv_file_id    INTEGER REFERENCES cv_files(id),
    status        TEXT NOT NULL DEFAULT 'sent'
                  CHECK (status IN ({", ".join(repr(s) for s in STATUSES)})),
    job_url       TEXT,
    notes         TEXT,
    job_type      TEXT,                       -- Alternance, Stage, CDI...
    location      TEXT,
    salary        TEXT,
    rating        INTEGER CHECK (rating BETWEEN 1 AND 5),  -- how excited the user is
    updated_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

# Every application query joins cv_files so the page can show the CV's name.
SELECT_APPLICATIONS = """
SELECT a.*, c.original_name AS cv_file_name
FROM applications AS a
LEFT JOIN cv_files AS c ON c.id = a.cv_file_id
"""


def get_connection() -> sqlite3.Connection:
    """Open a connection to the database.

    row_factory = sqlite3.Row lets us read columns by name, e.g. row["company"].
    foreign_keys = ON makes SQLite reject a cv_file_id that does not exist.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate_applications(conn: sqlite3.Connection) -> None:
    """Upgrade an applications table created by an older version of this script.

    SQLite cannot change a CHECK constraint or drop NOT NULL in place, so when the
    old table lacks the "saved" status we rebuild it: create the new table under a
    temporary name, copy every row, then swap the names.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'applications'"
    ).fetchone()
    if row is None or "'saved'" in row["sql"]:
        return
    old_columns = [r["name"] for r in conn.execute("PRAGMA table_info(applications)")]
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(SCHEMA_APPLICATIONS.replace("applications", "applications_new", 1))
    new_columns = {r["name"] for r in conn.execute("PRAGMA table_info(applications_new)")}
    shared = ", ".join(c for c in old_columns if c in new_columns)
    conn.execute(f"INSERT INTO applications_new ({shared}) SELECT {shared} FROM applications")
    conn.execute("DROP TABLE applications")
    conn.execute("ALTER TABLE applications_new RENAME TO applications")
    conn.execute("PRAGMA foreign_keys = ON")


def init_db() -> None:
    """Create the tables if needed and upgrade databases from older versions."""
    with get_connection() as conn:
        conn.execute(SCHEMA_CV_FILES)
        _migrate_applications(conn)
        conn.execute(SCHEMA_APPLICATIONS)
    CV_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- applications

def list_applications(status: Optional[str] = None, search: Optional[str] = None) -> list:
    """Return applications, newest first, optionally filtered by status and text.

    Values are passed as "?" parameters, never pasted into the SQL string,
    which protects against SQL injection.
    """
    sql = SELECT_APPLICATIONS + " WHERE 1 = 1"
    params = []
    if status:
        sql += " AND a.status = ?"
        params.append(status)
    if search:
        sql += " AND (a.company LIKE ? OR a.position LIKE ? OR a.notes LIKE ? OR a.location LIKE ?)"
        like = f"%{search}%"
        params += [like, like, like, like]
    # Saved jobs have no date yet: list them first, then the most recent applications.
    sql += " ORDER BY a.applied_date IS NOT NULL, a.applied_date DESC, a.id DESC"
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(sql, params)]


def get_application(app_id: int) -> Optional[dict]:
    """Return one application as a dict, or None if the id does not exist."""
    with get_connection() as conn:
        row = conn.execute(SELECT_APPLICATIONS + " WHERE a.id = ?", (app_id,)).fetchone()
    return dict(row) if row else None


def create_application(data: dict) -> dict:
    """Insert a new application and return it (including its new id)."""
    fields = [f for f in EDITABLE_FIELDS if data.get(f) is not None]
    placeholders = ", ".join("?" for _ in fields)
    sql = f"INSERT INTO applications ({', '.join(fields)}) VALUES ({placeholders})"
    with get_connection() as conn:
        cursor = conn.execute(sql, [data[f] for f in fields])
        new_id = cursor.lastrowid
    return get_application(new_id)


def update_application(app_id: int, changes: dict) -> Optional[dict]:
    """Update only the given fields of one application.

    Returns the updated row, or None if the id does not exist.
    """
    fields = [f for f in EDITABLE_FIELDS if f in changes]
    if not fields:
        return get_application(app_id)
    assignments = ", ".join(f"{f} = ?" for f in fields)
    sql = (
        f"UPDATE applications SET {assignments}, "
        "updated_at = datetime('now', 'localtime') WHERE id = ?"
    )
    with get_connection() as conn:
        cursor = conn.execute(sql, [changes[f] for f in fields] + [app_id])
        if cursor.rowcount == 0:
            return None
    return get_application(app_id)


def delete_application(app_id: int) -> bool:
    """Delete one application. Returns True if something was deleted.

    The CV file it used is kept, because other applications may share it.
    """
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
        return cursor.rowcount > 0


def get_stats() -> dict:
    """Return counts per status plus a response rate, computed in SQL."""
    with get_connection() as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM applications GROUP BY status")
        by_status = {s: 0 for s in STATUSES}
        by_status.update({r["status"]: r["n"] for r in rows})
    total = sum(by_status.values())
    sent = total - by_status["saved"]
    answered = sum(by_status[s] for s in ("replied", "interview", "offer", "rejected"))
    return {
        "total": total,
        "sent": sent,
        "by_status": by_status,
        "response_rate": round(answered / sent * 100) if sent else 0,
    }


# ---------------------------------------------------------------- CV files

def create_cv_file(original_name: str, stored_name: str) -> dict:
    """Record a CV file that has already been written to CV_DIR."""
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO cv_files (original_name, stored_name) VALUES (?, ?)",
            (original_name, stored_name),
        )
        new_id = cursor.lastrowid
    return get_cv_file(new_id)


def get_cv_file(cv_id: int) -> Optional[dict]:
    """Return one CV record, or None if the id does not exist."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM cv_files WHERE id = ?", (cv_id,)).fetchone()
    return dict(row) if row else None


def list_cv_files() -> list:
    """Return all CVs, newest first, with how many applications use each one."""
    sql = """
    SELECT c.*, COUNT(a.id) AS used_count
    FROM cv_files AS c
    LEFT JOIN applications AS a ON a.cv_file_id = c.id
    GROUP BY c.id
    ORDER BY c.uploaded_at DESC, c.id DESC
    """
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(sql)]


if __name__ == "__main__":
    init_db()
    print(f"Database ready: {DB_PATH}")
    print(f"CV files folder: {CV_DIR}")
