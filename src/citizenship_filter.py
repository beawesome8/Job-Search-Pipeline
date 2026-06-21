"""
citizenship_filter.py

Scans a job posting's title and description for phrases commonly
associated with EU/German citizenship, NATO membership, or security
clearance requirements. This is a cheap, free heuristic intended to
run before any paid AI call, not a reliable legal determination: it
can produce false positives (text discussing visa support positively)
and false negatives (requirements phrased in ways not on this list).
Flagged postings are surfaced for review, not discarded outright.

Usage:
    from citizenship_filter import check_citizenship_risk
    risk = check_citizenship_risk(job)
"""

CITIZENSHIP_RED_FLAGS = [
    # English phrasing
    "eu citizenship",
    "eu nationality",
    "eu national",
    "german citizenship",
    "nato member state",
    "security clearance",
    "no visa sponsorship",
    "without visa sponsorship",
    "unrestricted work permit",
    "valid eu work permit",
    "right to work in the eu",
    # German phrasing, as actually seen in German job postings
    "eu-staatsangehörigkeit",
    "deutsche staatsangehörigkeit",
    "staatsangehörigkeit eines eu",
    "nato-mitgliedstaat",
    "sicherheitsüberprüfung",
    "ausgenommen usa",
]


def check_citizenship_risk(job):
    """
    Returns 'flagged' if any red-flag phrase appears in the job's
    title or description (case-insensitive), otherwise 'clear'.
    """
    text = f"{job.get('title', '')} {job.get('description', '')}".lower()

    for phrase in CITIZENSHIP_RED_FLAGS:
        if phrase in text:
            return "flagged"

    return "clear"