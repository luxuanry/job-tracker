"""Fill a separate demo database with fictional applications.

Usage:
    JOB_TRACKER_DB=demo.db python seed_demo.py
    JOB_TRACKER_DB=demo.db uvicorn app:app --reload

Every company below is invented, so the demo can be shown publicly
without exposing real contacts. Your real job_tracker.db is not touched
unless you point JOB_TRACKER_DB at it.
"""

import db

DEMO_APPLICATIONS = [
    {"company": "Lumen Retail", "position": "Alternance Développeur Fullstack", "status": "saved",
     "job_type": "Alternance", "location": "Paris", "rating": 5,
     "notes": "E-commerce platform, Symfony + TypeScript. Prepare a small Symfony project first."},
    {"company": "Nordwave Studio", "position": "Stage Développeur Frontend", "status": "sent",
     "job_type": "Stage", "location": "Lyon", "applied_date": "2026-11-12", "rating": 3},
    {"company": "Atelier Kumo", "position": "Backend Python Intern", "status": "sent",
     "job_type": "Stage", "location": "Remote", "applied_date": "2026-11-18", "rating": 4,
     "salary": "1300 €/month"},
    {"company": "Brightpath AI", "position": "AI Engineer Apprentice", "status": "interview",
     "job_type": "Alternance", "location": "Paris", "applied_date": "2026-11-03", "rating": 5,
     "notes": "Technical interview: build a small RAG demo. Ask about the team size."},
    {"company": "Céleste Data", "position": "Data Engineer Intern", "status": "replied",
     "job_type": "Stage", "location": "Paris", "applied_date": "2026-11-07", "rating": 3},
    {"company": "Orbis Logistics", "position": "Développeur PHP", "status": "no_response",
     "job_type": "Alternance", "location": "Nanterre", "applied_date": "2026-10-20", "rating": 2},
    {"company": "Pixel & Pine", "position": "Fullstack React / Node", "status": "rejected",
     "job_type": "Stage", "location": "Bordeaux", "applied_date": "2026-10-15", "rating": 3,
     "notes": "Looking for more Node experience. Follow up in 6 months."},
    {"company": "Helio Fintech", "position": "Software Engineer Apprentice", "status": "offer",
     "job_type": "Alternance", "location": "Paris", "applied_date": "2026-10-10", "rating": 4},
]


def main() -> None:
    db.init_db()
    if db.list_applications():
        print(f"{db.DB_PATH} already has data, nothing added.")
        return
    for application in DEMO_APPLICATIONS:
        db.create_application(application)
    print(f"Added {len(DEMO_APPLICATIONS)} demo applications to {db.DB_PATH}")


if __name__ == "__main__":
    main()
