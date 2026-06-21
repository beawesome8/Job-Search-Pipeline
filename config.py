"""
config.py

Central place for paths and settings used across the pipeline.
Every other file imports from here instead of hardcoding paths or
settings itself. If you ever want to change something (a folder
location, a scoring threshold), you change it once, here, and it
takes effect everywhere.
"""

import os
import sqlite3
import json
from dotenv import load_dotenv

# load_dotenv() reads your .env file and makes its values available
# through os.getenv(). This is how secrets stay out of your code.
load_dotenv()

# --- Paths ---
# os.path.dirname(os.path.abspath(__file__)) finds the folder this
# file itself lives in, so these paths work no matter where the
# project folder is on your computer.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "db", "job_pipeline.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "db", "schema.sql")
BULLET_BANK_JSON_PATH = os.path.join(BASE_DIR, "data", "bullet_bank.json")
TELEGRAM_OFFSET_PATH = os.path.join(BASE_DIR, "data", "telegram_offset.txt")

# --- Secrets ---
# These come from .env (which you create from .env.example).
# They will be None until you fill in your real .env file.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- Job search targeting (used starting Stage 2) ---
TARGET_ROLES = [
    "AI Engineer",
    "ML Engineer",
    "Data Scientist",
    "Data Analyst",
    "Data Engineer",
    "Business Analyst",
]
TARGET_LOCATIONS = ["Munich", "Germany", "Remote"]

# --- Scoring thresholds (used starting Stage 3) ---
FIT_SCORE_THRESHOLD = 65          # jobs scoring at/above this trigger a digest alert
FRESH_POSTING_WINDOW_HOURS = 5    # jobs posted within this window trigger the instant alert

try:
    from candidate_profile import CANDIDATE_PROFILE
except ImportError:
    CANDIDATE_PROFILE = (
        "No profile configured. Copy candidate_profile.example.py to "
        "candidate_profile.py and fill in real candidate details before "
        "running score_jobs.py."
    )


def _load_skills_from_bullet_bank():
    """
    Builds a deduplicated list of hard and soft skills directly from
    the bullet_bank table, so the scoring profile reflects what is
    actually documented as verified experience, with no separate
    list to maintain by hand. Returns an empty list if the database
    or table doesn't exist yet, so this never blocks other scripts
    that don't need it (e.g. before the first setup_db.py run).
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT hard_skills, soft_skills FROM bullet_bank")
        rows = cursor.fetchall()
        conn.close()
    except sqlite3.Error:
        return []

    skills = set()
    for hard_skills_json, soft_skills_json in rows:
        skills.update(json.loads(hard_skills_json or "[]"))
        skills.update(json.loads(soft_skills_json or "[]"))
    return sorted(skills)


_bullet_bank_skills = _load_skills_from_bullet_bank()
if _bullet_bank_skills:
    CANDIDATE_PROFILE = (
        f"{CANDIDATE_PROFILE} Additional verified skills and tools from "
        f"work history: {', '.join(_bullet_bank_skills)}."
    )