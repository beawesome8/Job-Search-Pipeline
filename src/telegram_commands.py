"""
telegram_commands.py

Polls Telegram once for new messages since the last run and
processes any /tailor, /approve, or /reject commands found. Designed
to run periodically via Task Scheduler, consistent with the rest of
this pipeline, rather than as a long-running bot process. The last
processed update_id is persisted to a local file so re-running never
reprocesses the same message twice.

Usage:
    python src/telegram_commands.py
"""

import sys
import os
import json
import sqlite3
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH, TELEGRAM_BOT_TOKEN, TELEGRAM_OFFSET_PATH
from send_digest import send_telegram_message

TELEGRAM_GET_UPDATES_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"


def load_offset():
    """
    Returns the update_id to resume from, or None if no offset has
    been saved yet (first run). Telegram's getUpdates uses this to
    avoid returning messages that have already been processed.
    """
    if not os.path.exists(TELEGRAM_OFFSET_PATH):
        return None
    with open(TELEGRAM_OFFSET_PATH, "r") as f:
        content = f.read().strip()
    return int(content) if content else None


def save_offset(next_offset):
    """Persists the offset to use on the next run."""
    os.makedirs(os.path.dirname(TELEGRAM_OFFSET_PATH), exist_ok=True)
    with open(TELEGRAM_OFFSET_PATH, "w") as f:
        f.write(str(next_offset))


def get_new_messages(offset):
    """
    Calls Telegram's getUpdates endpoint and returns a list of
    (update_id, text) tuples for new text messages. Passing offset
    tells Telegram that all earlier updates have already been
    handled and should not be returned again.
    """
    params = {}
    if offset is not None:
        params["offset"] = offset

    response = requests.get(TELEGRAM_GET_UPDATES_URL, params=params)
    data = response.json()

    messages = []
    for update in data.get("result", []):
        update_id = update["update_id"]
        text = update.get("message", {}).get("text")
        if text:
            messages.append((update_id, text))
    return messages


def get_draft(job_id):
    """Returns a job's title, company, and tailoring draft as one joined row, or None if not found."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT jobs.title, jobs.company,
               tailoring_drafts.id, tailoring_drafts.drafted_bullets,
               tailoring_drafts.cover_letter_hook, tailoring_drafts.status
        FROM jobs
        JOIN tailoring_drafts ON jobs.id = tailoring_drafts.job_id
        WHERE jobs.id = ?
        """,
        (job_id,),
    )
    row = cursor.fetchone()
    conn.close()
    return row


def update_draft_status(draft_id, status):
    """Sets a draft's status and stamps reviewed_at with the current time."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE tailoring_drafts SET status = ?, reviewed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (status, draft_id),
    )
    conn.commit()
    conn.close()


def job_exists(job_id):
    """Returns True if a job with this id exists in the jobs table."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def get_job_basic_info(job_id):
    """Returns (title, company) for a job, or None if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT title, company FROM jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()
    return row


def ensure_application_row(job_id):
    """
    Creates an applications row for this job if one doesn't already
    exist, defaulting to the start of the funnel. Safe to call
    repeatedly; INSERT OR IGNORE relies on the UNIQUE constraint on
    applications.job_id.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT OR IGNORE INTO applications (job_id, tailored, applied, status, last_updated)
        VALUES (?, 0, 0, 'not_applied', CURRENT_TIMESTAMP)
        """,
        (job_id,),
    )
    conn.commit()
    conn.close()


def update_application_status(job_id, status, mark_tailored=False, mark_applied=False):
    """
    Updates an application's funnel status, and stamps the tailored
    or applied milestone with the current time only the first time
    each is set (the WHERE ... = 0 guard makes this idempotent, so
    sending the same command twice by accident doesn't overwrite an
    earlier, real timestamp).
    """
    ensure_application_row(job_id)
    conn = sqlite3.connect(DB_PATH)

    if mark_tailored:
        conn.execute(
            "UPDATE applications SET tailored = 1, tailored_date = CURRENT_TIMESTAMP "
            "WHERE job_id = ? AND tailored = 0",
            (job_id,),
        )
    if mark_applied:
        conn.execute(
            "UPDATE applications SET applied = 1, applied_date = CURRENT_TIMESTAMP "
            "WHERE job_id = ? AND applied = 0",
            (job_id,),
        )

    conn.execute(
        "UPDATE applications SET status = ?, last_updated = CURRENT_TIMESTAMP WHERE job_id = ?",
        (status, job_id),
    )
    conn.commit()
    conn.close()


def build_tailor_message(title, company, draft_data, cover_letter_hook, status):
    """
    Formats a draft's bullets, cover letter hook, and any validation
    flags into a readable Telegram message. A pure formatting
    function kept separate from the database and network calls
    around it, so it can be tested directly with sample data.
    """
    bullets = draft_data.get("bullets", [])
    validation_notes = draft_data.get("validation_notes", [])

    lines = [f"{title} at {company}", f"Status: {status}", ""]
    for b in bullets:
        lines.append(f"[{b.get('bullet_id')}] {b.get('drafted_text')}")
    lines.append("")
    lines.append(f"Cover letter hook: {cover_letter_hook}")

    if validation_notes:
        lines.append("")
        lines.append("Validation flags (review before using):")
        for note in validation_notes:
            lines.append(f"- {note}")

    return "\n".join(lines)


def handle_tailor(job_id):
    """Returns the formatted draft for a job, or an explanatory message if none exists."""
    row = get_draft(job_id)
    if row is None:
        return f"No draft found for job {job_id}. It may not have been scored or drafted yet."

    title, company, draft_id, drafted_bullets_json, cover_letter_hook, status = row
    draft_data = json.loads(drafted_bullets_json)
    return build_tailor_message(title, company, draft_data, cover_letter_hook, status)


def handle_approve(job_id):
    """Marks a job's draft as approved and starts tracking it in the application funnel."""
    row = get_draft(job_id)
    if row is None:
        return f"No draft found for job {job_id}."

    title, company, draft_id, _, _, _ = row
    update_draft_status(draft_id, "approved")
    update_application_status(job_id, "not_applied", mark_tailored=True)
    return f"Approved: {title} at {company}. Ready to build the actual document next."


def handle_reject(job_id):
    """Marks a job's draft as rejected."""
    row = get_draft(job_id)
    if row is None:
        return f"No draft found for job {job_id}."

    title, company, draft_id, _, _, _ = row
    update_draft_status(draft_id, "rejected")
    return f"Rejected: {title} at {company}."


def handle_applied(job_id):
    """Marks a job as actually applied to."""
    info = get_job_basic_info(job_id)
    if info is None:
        return f"No job found with ID {job_id}."

    title, company = info
    update_application_status(job_id, "applied", mark_applied=True)
    return f"Marked applied: {title} at {company}."


def handle_interview(job_id):
    """Moves a job to the interview stage."""
    info = get_job_basic_info(job_id)
    if info is None:
        return f"No job found with ID {job_id}."

    title, company = info
    update_application_status(job_id, "interview")
    return f"Interview stage: {title} at {company}. Good luck."


def handle_rejected(job_id):
    """Marks a job as rejected after applying (distinct from rejecting a draft before applying)."""
    info = get_job_basic_info(job_id)
    if info is None:
        return f"No job found with ID {job_id}."

    title, company = info
    update_application_status(job_id, "rejected")
    return f"Marked rejected: {title} at {company}."


def handle_offer(job_id):
    """Marks a job as having received an offer."""
    info = get_job_basic_info(job_id)
    if info is None:
        return f"No job found with ID {job_id}."

    title, company = info
    update_application_status(job_id, "offer")
    return f"Offer: {title} at {company}. Congratulations."


def handle_noresponse(job_id):
    """Marks a job as having gone quiet after applying."""
    info = get_job_basic_info(job_id)
    if info is None:
        return f"No job found with ID {job_id}."

    title, company = info
    update_application_status(job_id, "no_response")
    return f"Marked no response: {title} at {company}."


def handle_pipeline():
    """Returns every tracked application with its job title, company, and current status."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT jobs.title, jobs.company, applications.status
        FROM applications
        JOIN jobs ON applications.job_id = jobs.id
        ORDER BY applications.last_updated DESC
        """
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return "No applications tracked yet."

    lines = ["Application pipeline:"]
    for title, company, status in rows:
        lines.append(f"[{status}] {title} at {company}")
    return "\n".join(lines)


COMMAND_HANDLERS = {
    "/tailor": handle_tailor,
    "/approve": handle_approve,
    "/reject": handle_reject,
    "/applied": handle_applied,
    "/interview": handle_interview,
    "/rejected": handle_rejected,
    "/offer": handle_offer,
    "/noresponse": handle_noresponse,
}

NO_ARG_COMMANDS = {
    "/pipeline": handle_pipeline,
}


def process_message(text):
    """
    Parses a message in the form "/command job_id" and dispatches it
    to the matching handler. Commands in NO_ARG_COMMANDS (like
    /pipeline) take no job_id and are dispatched directly. Returns
    None if the message's first word isn't a recognized command at
    all (so ordinary chat text is silently ignored), or a usage
    message if a job_id command is recognized but malformed.
    """
    parts = text.strip().split()
    if not parts:
        return None

    command = parts[0].lower()

    if command in NO_ARG_COMMANDS:
        return NO_ARG_COMMANDS[command]()

    handler = COMMAND_HANDLERS.get(command)
    if handler is None:
        return None

    if len(parts) != 2 or not parts[1].isdigit():
        return f"Usage: {command} <job_id>"

    return handler(int(parts[1]))


def main():
    offset = load_offset()
    messages = get_new_messages(offset)
    print(f"Found {len(messages)} new message(s).")

    if not messages:
        return

    next_offset = offset
    for update_id, text in messages:
        print(f"Processing: {text}")
        reply = process_message(text)
        if reply:
            send_telegram_message(reply)
            print("  Replied.")
        else:
            print("  Not a recognized command, ignored.")
        next_offset = update_id + 1

    save_offset(next_offset)
    print(f"Offset saved at {next_offset}.")


if __name__ == "__main__":
    main()
