"""
score_jobs.py

Sends each unscored job in the database to Claude for a fit
assessment against the candidate profile, then stores the result
in the scores table. Uses the Haiku model tier to keep scoring cost
low, since this is a structured classification task rather than
open-ended generation.

Usage:
    python src/score_jobs.py
"""

import sys
import os
import re
import json
import sqlite3
import anthropic

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH, ANTHROPIC_API_KEY, CANDIDATE_PROFILE

MODEL = "claude-sonnet-4-6"
MAX_DESCRIPTION_CHARS = 3000

SYSTEM_PROMPT = """You evaluate how well a job posting matches a candidate's profile for a personal job search pipeline. Given a candidate profile and a job posting, return the assessment as a single JSON object only, with no extra text, no markdown code fences, and no commentary before or after the JSON.

The JSON object must have exactly these fields:
- fit_score: integer from 0 to 100, how well the candidate's actual background matches the role's core requirements
- reasoning: a one to two sentence explanation of the score
- missing_keywords: a list of strings, key skills or qualifications the posting asks for that are not part of the candidate's profile
- citizenship_flag: one of "clear", "flagged", or "unclear" - "flagged" if the posting explicitly requires EU/German/NATO citizenship, a security clearance, or states no visa sponsorship is available; "clear" if there is no such requirement or the posting explicitly offers visa sponsorship; "unclear" if work authorization is not mentioned at all"""

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def get_unscored_jobs():
    """
    Returns jobs that don't yet have a row in the scores table, via
    a LEFT JOIN that finds jobs with no matching score.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT jobs.id, jobs.title, jobs.company, jobs.description
        FROM jobs
        LEFT JOIN scores ON jobs.id = scores.job_id
        WHERE scores.id IS NULL
        """
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def clean_description(html_text):
    """Strips HTML tags and excess whitespace, then trims length to
    keep the prompt compact and the API call inexpensive."""
    text = re.sub(r"<[^<]+?>", " ", html_text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_DESCRIPTION_CHARS]


def parse_model_response(raw_text):
    """
    Parses the model's raw text output into a dict. Strips markdown
    code fences first in case the model wraps the JSON in them
    despite being instructed not to.
    """
    cleaned = re.sub(r"^```json|^```|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()
    return json.loads(cleaned)


def score_job(title, company, description):
    """
    Calls Claude with the candidate profile and one job posting, and
    returns the parsed assessment as a dict, or None if the call or
    the parsing failed.
    """
    user_message = (
        f"Candidate profile:\n{CANDIDATE_PROFILE}\n\n"
        f"Job posting:\n"
        f"Title: {title}\n"
        f"Company: {company}\n"
        f"Description: {clean_description(description)}"
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        return parse_model_response(response.content[0].text)

    except Exception as e:
        print(f"  Scoring failed: {e}")
        return None


def save_score(job_id, result):
    """Inserts one scoring result into the scores table."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT INTO scores
            (job_id, fit_score, reasoning, missing_keywords, citizenship_flag, model_used)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            result.get("fit_score"),
            result.get("reasoning"),
            json.dumps(result.get("missing_keywords", [])),
            result.get("citizenship_flag"),
            MODEL,
        ),
    )
    conn.commit()
    conn.close()


def main():
    jobs = get_unscored_jobs()
    print(f"Found {len(jobs)} unscored job(s).")

    for job_id, title, company, description in jobs:
        print(f"Scoring: {title} at {company}")
        result = score_job(title, company, description)

        if result is None:
            print("  Skipped due to an error.")
            continue

        save_score(job_id, result)
        print(f"  Fit score: {result.get('fit_score')} | "
              f"Citizenship: {result.get('citizenship_flag')} | "
              f"Missing: {', '.join(result.get('missing_keywords', []))}")


if __name__ == "__main__":
    main()