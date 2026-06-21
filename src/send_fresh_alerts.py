"""
send_fresh_alerts.py

Sends an instant Telegram alert for job postings discovered within
the freshness window defined in config.py (FRESH_POSTING_WINDOW_HOURS),
skipping the AI scoring step entirely so the alert goes out as fast
as possible. Citizenship-flagged postings are still excluded, since
that is a hard eligibility constraint, but no fit-score threshold is
applied here: this catches everything eligible early and leaves
scoring to catch up separately. Each alerted job is marked so it is
not sent again, and is still picked up normally by score_jobs.py and
send_digest.py afterward.

Usage:
    python src/send_fresh_alerts.py
"""

import sys
import os
import sqlite3
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH, FRESH_POSTING_WINDOW_HOURS
from send_digest import chunk_messages, send_telegram_message


def get_fresh_candidates():
    """
    Returns jobs posted within the freshness window that passed the
    role pre-filter, carry no citizenship/clearance flag from the
    cheap keyword check, and have not already received a fresh
    alert. NULL is checked explicitly alongside 'flagged' for the
    same reason covered in send_digest.py.
    """
    cutoff = (datetime.now() - timedelta(hours=FRESH_POSTING_WINDOW_HOURS)).isoformat()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, title, company, url, posted_at
        FROM jobs
        WHERE posted_at >= ?
          AND prefilter_passed = 1
          AND (citizenship_risk IS NULL OR citizenship_risk != 'flagged')
          AND alerted_fresh = 0
        ORDER BY posted_at DESC
        """,
        (cutoff,),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def format_fresh_block(job):
    """Formats one fresh job as a readable, clearly-unscored alert block."""
    job_id, title, company, url, posted_at = job
    posted_dt = datetime.fromisoformat(posted_at)
    hours_ago = (datetime.now() - posted_dt).total_seconds() / 3600

    return (
        f"Fresh ({hours_ago:.1f}h ago) - not yet scored\n"
        f"{title}\n"
        f"{company}\n"
        f"{url}"
    )


def mark_fresh_alerted(job_ids):
    """Marks the given jobs as having received the fresh-posting alert."""
    conn = sqlite3.connect(DB_PATH)
    conn.executemany(
        "UPDATE jobs SET alerted_fresh = 1 WHERE id = ?",
        [(job_id,) for job_id in job_ids],
    )
    conn.commit()
    conn.close()


def main():
    candidates = get_fresh_candidates()
    print(f"Found {len(candidates)} fresh job(s) within the {FRESH_POSTING_WINDOW_HOURS}h window.")

    if not candidates:
        return

    blocks = [format_fresh_block(job) for job in candidates]
    messages = chunk_messages(blocks)
    job_ids = [job[0] for job in candidates]
    all_sent = True

    for i, message in enumerate(messages, start=1):
        success = send_telegram_message(f"Fresh posting alert ({i}/{len(messages)}):\n\n{message}")
        print(f"Message {i}/{len(messages)} sent: {success}")
        if not success:
            all_sent = False

    if all_sent:
        mark_fresh_alerted(job_ids)
        print(f"Marked {len(job_ids)} job(s) as fresh-alerted.")
    else:
        print("Not marking jobs as alerted since at least one message failed to send.")


if __name__ == "__main__":
    main()