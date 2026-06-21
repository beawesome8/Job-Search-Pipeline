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
            INSERT OR