"""
send_digest.py

Sends a Telegram digest of newly scored jobs that clear the fit
score threshold and carry no citizenship/clearance red flag from
either the cheap keyword check or the AI assessment. Each job is
marked as alerted afterward so it is not sent again on a later run.

Usage:
    python src/send_digest.py
"""

import sys
import os
import json
import sqlite3
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, FIT_SCORE_THRESHOLD

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
MAX_MESSAGE_CHARS = 3500  # stays safely under Telegram's 4096-character limit per message


def get_digest_candidates():
    """
    Returns scored jobs that clear the fit threshold, carry no
    citizenship/clearance flag from either source, and have not
    already been alerted. NULL is checked explicitly alongside
    'flagged' because in SQL, NULL != 'flagged' evaluates to NULL
    rather than true, which would silently exclude a row instead
    of including it.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT jobs.id, jobs.title, jobs.company, jobs.url,
               scores.fit_score, scores.reasoning, scores.missing_keywords
        FROM jobs
        JOIN scores ON jobs.id = scores.job_id
        WHERE scores.fit_score >= ?
          AND (jobs.citizenship_risk IS NULL OR jobs.citizenship_risk != 'flagged')
          AND (scores.citizenship_flag IS NULL OR scores.citizenship_flag != 'flagged')
          AND jobs.alerted_digest = 0
        ORDER BY scores.fit_score DESC
        """,
        (FIT_SCORE_THRESHOLD,),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def format_job_block(job):
    """Formats one job as a readable block of text for the Telegram message."""
    job_id, title, company, url, fit_score, reasoning, missing_keywords_json = job
    missing = ", ".join(json.loads(missing_keywords_json or "[]"))

    return (
        f"Fit score: {fit_score}/100\n"
        f"{title}\n"
        f"{company}\n"
        f"Why: {reasoning}\n"
        f"Missing: {missing if missing else 'none noted'}\n"
        f"{url}"
    )


def chunk_messages(blocks, max_chars=MAX_MESSAGE_CHARS):
    """
    Groups job text blocks into messages that each stay under the
    character limit, so a large digest gets split into multiple
    Telegram messages instead of being rejected for being too long.
    """
    messages = []
    current = ""

    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > max_chars:
            messages.append(current)
            current = block
        else:
            current = candidate

    if current:
        messages.append(current)

    return messages


def send_telegram_message(text):
    """Sends one message to the configured Telegram chat. Returns True on success."""
    response = requests.post(
        TELEGRAM_API_URL,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
    )
    return response.status_code == 200


def mark_alerted(job_ids):
    """Marks the given jobs as having received the digest alert."""
    conn = sqlite3.connect(DB_PATH)
    conn.executemany(
        "UPDATE jobs SET alerted_digest = 1 WHERE id = ?",
        [(job_id,) for job_id in job_ids],
    )
    conn.commit()
    conn.close()


def main():
    candidates = get_digest_candidates()
    print(f"Found {len(candidates)} job(s) ready for the digest.")

    if not candidates:
        return

    blocks = [format_job_block(job) for job in candidates]
    messages = chunk_messages(blocks)
    job_ids = [job[0] for job in candidates]
    all_sent = True

    for i, message in enumerate(messages, start=1):
        success = send_telegram_message(f"Job digest ({i}/{len(messages)}):\n\n{message}")
        print(f"Message {i}/{len(messages)} sent: {success}")
        if not success:
            all_sent = False

    if all_sent:
        mark_alerted(job_ids)
        print(f"Marked {len(job_ids)} job(s) as alerted.")
    else:
        print("Not marking jobs as alerted since at least one message failed to send.")


if __name__ == "__main__":
    main()