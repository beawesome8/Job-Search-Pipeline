"""
save_jobs.py

Fetches Arbeitnow postings, filters them by target role, and inserts
new matches into the jobs table. Postings whose URL already exists
are skipped, so this script can be run repeatedly (e.g. on a
schedule) without creating duplicate rows.

Usage:
    python src/save_jobs.py
    python src/save_jobs.py --role "AI Engineer"
"""

import sys
import os
import sqlite3
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH, TARGET_ROLES
from fetch_arbeitnow import fetch_jobs, filter_by_role, parse_args
from citizenship_filter import check_citizenship_risk


def save_jobs(jobs):
    """
    Inserts new job postings into the jobs table. Rows with a URL
    that already exists are silently skipped (INSERT OR IGNORE
    relies on the UNIQUE constraint on jobs.url defined in
    schema.sql). Returns a tuple of (inserted_count, flagged_count).
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    inserted = 0
    flagged = 0

    for job in jobs:
        posted_at = datetime.fromtimestamp(job["created_at"]).isoformat()
        risk = check_citizenship_risk(job)
        if risk == "flagged":
            flagged += 1

        cursor.execute(
            """
            INSERT OR IGNORE INTO jobs
                (source, external_id, title, company, location, url,
                 description, posted_at, prefilter_passed, citizenship_risk)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "arbeitnow",
                job.get("slug"),
                job["title"],
                job["company_name"],
                job["location"],
                job["url"],
                job["description"],
                posted_at,
                1,
                risk,
            ),
        )
        if cursor.rowcount > 0:
            inserted += 1

    conn.commit()
    conn.close()
    return inserted, flagged


def main():
    args = parse_args()
    roles_to_match = [args.role] if args.role else TARGET_ROLES

    jobs = fetch_jobs()
    print(f"Fetched {len(jobs)} total job postings.")

    matched_jobs = filter_by_role(jobs, roles_to_match)
    print(f"{len(matched_jobs)} matched target role(s): {', '.join(roles_to_match)}")

    inserted_count, flagged_count = save_jobs(matched_jobs)
    skipped_count = len(matched_jobs) - inserted_count
    print(f"Inserted {inserted_count} new job(s) into the database "
          f"({skipped_count} already existed and were skipped).")
    print(f"{flagged_count} of the inserted jobs were flagged for possible "
          f"citizenship/clearance requirements, review these before tailoring.")


if __name__ == "__main__":
    main()