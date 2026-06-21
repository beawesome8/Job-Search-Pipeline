"""
fetch_arbeitnow.py

Fetches job postings from the Arbeitnow public job board API,
filters them by target role, and prints a summary of matches.
Used as a connectivity and data-shape check before results are
persisted to the database.

Usage:
    python src/fetch_arbeitnow.py
    python src/fetch_arbeitnow.py --role "AI Engineer"
"""

import sys
import os
import argparse
import requests
from datetime import datetime

# Makes config.py (one directory up, at the project root) importable
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import TARGET_ROLES

# Arbeitnow's public job board API. No API key or login needed.
ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"


def parse_args():
    """Defines and reads command-line arguments for this script."""
    parser = argparse.ArgumentParser(description="Fetch and filter Arbeitnow job postings.")
    parser.add_argument(
        "--role",
        type=str,
        default=None,
        help="Search for a single role instead of the full TARGET_ROLES list in config.py",
    )
    return parser.parse_args()


def fetch_jobs():
    """
    Calls the Arbeitnow API and returns the list of job postings.
    Returns an empty list if the request fails, so the rest of the
    program can keep running instead of crashing.
    """
    response = requests.get(ARBEITNOW_URL)

    if response.status_code != 200:
        print(f"Request failed with status code {response.status_code}")
        return []

    data = response.json()
    return data.get("data", [])


def filter_by_role(jobs, target_roles):
    """
    Returns only the jobs whose title contains at least one of the
    target role phrases, matched case-insensitively. Title-only
    matching is a cheap first pass; it will miss postings that use
    different wording for the same role, a gap the later AI scoring
    step is expected to catch instead.
    """
    matched = []
    for job in jobs:
        title_lower = job["title"].lower()
        if any(role.lower() in title_lower for role in target_roles):
            matched.append(job)
    return matched


def print_job_summary(job):
    """Prints one job posting in a clean, readable format."""
    posted_date = datetime.fromtimestamp(job["created_at"])

    print(f"Title:    {job['title']}")
    print(f"Company:  {job['company_name']}")
    print(f"Location: {job['location']}")
    print(f"Posted:   {posted_date.strftime('%Y-%m-%d %H:%M')}")
    print(f"URL:      {job['url']}")
    print("-" * 50)


def main():
    args = parse_args()
    roles_to_match = [args.role] if args.role else TARGET_ROLES

    jobs = fetch_jobs()
    print(f"Fetched {len(jobs)} total job postings.")

    matched_jobs = filter_by_role(jobs, roles_to_match)
    print(f"{len(matched_jobs)} matched target role(s): {', '.join(roles_to_match)}\n")

    for job in matched_jobs[:5]:
        print_job_summary(job)


if __name__ == "__main__":
    main()