"""
db/setup_db.py

Creates the SQLite database for the Job Search Pipeline (using the
blueprint in schema.sql) and loads your bullet bank from
data/bullet_bank.json into the bullet_bank table.

Safe to re-run any time: CREATE TABLE IF NOT EXISTS won't wipe
existing tables, and INSERT OR IGNORE won't duplicate bullets that
are already loaded.

Run it from the project's root folder with:
    python db/setup_db.py
"""

import sqlite3
import json
import os
import sys

# This lets the script find config.py, which lives one folder up
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH, BULLET_BANK_JSON_PATH, SCHEMA_PATH


def create_tables(conn):
    """Read schema.sql and execute every CREATE TABLE statement in it."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    conn.executescript(schema_sql)
    print("Tables created (or already existed).")


def load_bullet_bank(conn):
    """Load bullet_bank.json into the bullet_bank table."""
    if not os.path.exists(BULLET_BANK_JSON_PATH):
        print(f"No bullet bank file found at {BULLET_BANK_JSON_PATH}, skipping.")
        return

    with open(BULLET_BANK_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    bullets = data.get("bullets", [])
    cursor = conn.cursor()
    inserted = 0

    for b in bullets:
        cursor.execute(
            """
            INSERT OR IGNORE INTO bullet_bank
                (bullet_id, role, company, dates, text, hard_skills, soft_skills, keywords)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                b["bullet_id"],
                b["role"],
                b["company"],
                b.get("dates"),
                b["text"],
                json.dumps(b.get("hard_skills", [])),
                json.dumps(b.get("soft_skills", [])),
                json.dumps(b.get("keywords", [])),
            ),
        )
        if cursor.rowcount > 0:
            inserted += 1

    conn.commit()
    print(f"Loaded {inserted} new bullets into bullet_bank (file contained {len(bullets)}).")


def main():
    # Make sure the db/ folder exists before SQLite tries to write into it
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    create_tables(conn)
    load_bullet_bank(conn)
    conn.close()
    print(f"\nDatabase ready at: {DB_PATH}")


if __name__ == "__main__":
    main()
