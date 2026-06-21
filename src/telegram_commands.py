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
    """Marks a job's draft as approved."""
    row = get_draft(job_id)
    if row is None:
        return f"No draft found for job {job_id}."

    title, company, draft_id, _, _, _ = row
    update_draft_status(draft_id, "approved")
    return f"Approved: {title} at {company}. Ready to build the actual document next."


def handle_reject(job_id):
    """Marks a job's draft as rejected."""
    row = get_draft(job_id)
    if row is None:
        return f"No draft found for job {job_id}."

    title, company, draft_id, _, _, _ = row
    update_draft_status(draft_id, "rejected")
    return f"Rejected: {title} at {company}."


COMMAND_HANDLERS = {
    "/tailor": handle_tailor,
    "/approve": handle_approve,
    "/reject": handle_reject,
}


def process_message(text):
    """
    Parses a message in the form "/command job_id" and dispatches it
    to the matching handler. Returns None if the message's first
    word isn't a recognized command at all (so ordinary chat text is
    silently ignored), or a usage message if the command is
    recognized but malformed.
    """
    parts = text.strip().split()
    if not parts:
        return None

    command = parts[0].lower()
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
