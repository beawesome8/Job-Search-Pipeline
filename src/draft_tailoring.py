"""
draft_tailoring.py

For digest-alerted jobs without an existing tailoring draft, selects
the most relevant bullets from the bullet bank by keyword overlap,
sends them to Claude with the job posting for a rewrite, runs a
cheap validation pass on the result, and stores the draft for review.

Usage:
    python src/draft_tailoring.py
"""

import sys
import os
import re
import json
import sqlite3
import anthropic

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH, ANTHROPIC_API_KEY

MODEL = "claude-sonnet-4-6"
MAX_RELEVANT_BULLETS = 5

DRAFTING_SYSTEM_PROMPT = """You draft tailored resume bullet points for a personal job application pipeline. You will be given a job posting and a set of the candidate's existing, verified resume bullets. Rewrite each given bullet to better highlight relevance to this specific job, using only facts already present in the original bullet. Do not invent accomplishments, tools, metrics, or skills that are not in the original bullet text. Do not mirror the job posting's exact phrasing aggressively; keep the tone natural and truthful. Never use an em dash anywhere in the output.

Return a single JSON object only, no extra text, no markdown code fences, with exactly these fields:
- drafted_bullets: a list of objects, each with "bullet_id" (matching the input bullet_id) and "drafted_text" (the rewritten bullet)
- cover_letter_hook: one engaging opening sentence for a cover letter, specific to this role and company, avoiding generic phrases like "I am writing to apply" """

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def get_jobs_needing_drafts():
    """
    Returns jobs that have been digest-alerted but don't yet have a
    tailoring draft, via a LEFT JOIN that finds jobs with no
    matching row in tailoring_drafts.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT jobs.id, jobs.title, jobs.company, jobs.description
        FROM jobs
        LEFT JOIN tailoring_drafts ON jobs.id = tailoring_drafts.job_id
        WHERE jobs.alerted_digest = 1
          AND tailoring_drafts.id IS NULL
        """
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_bullet_bank_vocabulary():
    """
    Returns a lowercased set of every hard skill, soft skill, and
    keyword across the whole bullet bank, used to sanity-check
    drafted text against the candidate's verified vocabulary.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT hard_skills, soft_skills, keywords FROM bullet_bank")
    rows = cursor.fetchall()
    conn.close()

    vocabulary = set()
    for hard_json, soft_json, keywords_json in rows:
        for source in (hard_json, soft_json, keywords_json):
            for term in json.loads(source or "[]"):
                vocabulary.add(term.lower())
    return vocabulary


def select_relevant_bullets(job_title, job_description, max_bullets=MAX_RELEVANT_BULLETS):
    """
    Selects the bullets most relevant to a job posting by counting
    how many of each bullet's keywords appear in the job's title and
    description. A free, local pre-filter that runs before any API
    call, narrowing the full bullet bank down to a handful of
    bullets actually worth sending to the model.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT bullet_id, role, company, text, keywords FROM bullet_bank")
    rows = cursor.fetchall()
    conn.close()

    job_text = f"{job_title} {job_description}".lower()
    scored = []

    for bullet_id, role, company, text, keywords_json in rows:
        keywords = json.loads(keywords_json or "[]")
        match_count = sum(1 for kw in keywords if kw.lower() in job_text)
        if match_count > 0:
            scored.append({
                "match_count": match_count,
                "bullet_id": bullet_id,
                "role": role,
                "company": company,
                "text": text,
            })

    scored.sort(key=lambda b: b["match_count"], reverse=True)
    return scored[:max_bullets]


def clean_description(html_text, max_chars=3000):
    """Strips HTML tags and trims length, same approach as score_jobs.py."""
    text = re.sub(r"<[^<]+?>", " ", html_text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def draft_for_job(title, company, description, relevant_bullets):
    """
    Calls Claude to draft tailored bullets and a cover letter hook
    from the given relevant bullets only. Returns the parsed dict,
    or None if the call or parsing failed.
    """
    bullet_lines = "\n".join(
        f"- bullet_id: {b['bullet_id']} | {b['role']} at {b['company']}: {b['text']}"
        for b in relevant_bullets
    )

    user_message = (
        f"Job posting:\nTitle: {title}\nCompany: {company}\n"
        f"Description: {clean_description(description)}\n\n"
        f"Candidate's verified bullets to rewrite:\n{bullet_lines}"
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=800,
            system=DRAFTING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        raw_text = response.content[0].text.strip()
        cleaned = re.sub(r"^```json|^```|```$", "", raw_text, flags=re.MULTILINE).strip()
        return json.loads(cleaned)
    except Exception as e:
        print(f"  Drafting failed: {e}")
        return None


def validate_bullet(original_text, drafted_text, vocabulary):
    """
    Runs cheap mechanical checks on one drafted bullet. Catches an
    em dash slipping in despite instructions, and flags capitalized
    terms in the draft that weren't in the original bullet and
    aren't part of the verified bullet bank vocabulary, a rough but
    useful tripwire for fabricated detail. Not a guarantee of
    correctness, a signal for human review.
    """
    issues = []

    if "—" in drafted_text:
        issues.append("contains an em dash")

    original_words_lower = {
        w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9+.#]*", original_text)
    }
    drafted_words = drafted_text.split()
    first_word = drafted_words[0].rstrip(".,;:") if drafted_words else ""

    candidate_terms = re.findall(r"\b[A-Z][A-Za-z0-9+.#]*\b", drafted_text)
    new_terms = sorted({
        term for term in candidate_terms
        if term != first_word
        and len(term) > 2
        and term.lower() not in original_words_lower
        and term.lower() not in vocabulary
    })

    if new_terms:
        issues.append(f"unverified term(s): {', '.join(new_terms)}")

    return issues


def save_draft(job_id, result, validation_notes):
    """Inserts one tailoring draft into the tailoring_drafts table."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT INTO tailoring_drafts
            (job_id, drafted_bullets, cover_letter_hook, status)
        VALUES (?, ?, ?, 'pending')
        """,
        (
            job_id,
            json.dumps({
                "bullets": result.get("drafted_bullets", []),
                "validation_notes": validation_notes,
            }),
            result.get("cover_letter_hook"),
        ),
    )
    conn.commit()
    conn.close()


def main():
    vocabulary = get_bullet_bank_vocabulary()
    jobs = get_jobs_needing_drafts()
    print(f"Found {len(jobs)} job(s) needing a tailoring draft.")

    for job_id, title, company, description in jobs:
        print(f"Drafting: {title} at {company}")
        relevant_bullets = select_relevant_bullets(title, description)

        if not relevant_bullets:
            print("  No relevant bullets found, skipping.")
            continue

        result = draft_for_job(title, company, description, relevant_bullets)
        if result is None:
            print("  Skipped due to an error.")
            continue

        validation_notes = []
        bullet_lookup = {b["bullet_id"]: b for b in relevant_bullets}

        for drafted in result.get("drafted_bullets", []):
            bullet = bullet_lookup.get(drafted.get("bullet_id"), {})
            original_context = (
                f"{bullet.get('role', '')} {bullet.get('company', '')} {bullet.get('text', '')}"
            )
            issues = validate_bullet(original_context, drafted.get("drafted_text", ""), vocabulary)
            if issues:
                validation_notes.append(f"{drafted.get('bullet_id')}: {'; '.join(issues)}")

        save_draft(job_id, result, validation_notes)

        print(f"  Draft saved with {len(result.get('drafted_bullets', []))} bullet(s).")
        if validation_notes:
            print(f"  Validation flags: {validation_notes}")
        else:
            print("  No validation issues found.")


if __name__ == "__main__":
    main()
    