"""
db/setup_db.py

Creates the SQLite database for the Job Search Pipeline (using the
blueprint in schema.sql) and loads the bullet bank from
data/bullet_bank.json into the bullet_bank table.

Safe to re-run any time: CREATE TABLE IF NOT EXISTS won't wipe
existing tables, ensure_column() only adds columns that don't
already exist, and INSERT OR IGNORE won't duplicate bullets that
are already loaded.

Run from the project's root folder with:
    python db/setup_db.py
"""

import sqlite3
import json
import os
import sys

# Allows config.py, one folder up, to be importable from this script
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH, BULLET_BANK_JSON_PATH, SCHEMA_PATH


def create_tables(conn):
    """Reads schema.sql and executes every CREATE TABLE statement in it."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    conn.executescript(schema_sql)
    print("Tables created (or already existed).")


def ensure_column(conn, table, column, column_definition):
    """
    Adds a column to an existing table if it isn't already there.
    SQLite has no "ADD COLUMN IF NOT EXISTS" syntax, so the table's
    current columns are checked first via PRAGMA table_info before
    deciding whether to run ALTER TABLE. Allows the schema to evolve
    over time without losing data already stored in the table.
    """
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table})")
    existing_columns = [row[1] for row in cursor.fetchall()]

    if column not in existing_columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_definition}")
        conn.commit()
        print(f"Migration: added column '{column}' to '{table}'.")


def load_bullet_bank(conn):
    """Loads bullet_bank.json into the bullet_bank table."""
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
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    create_tables(conn)
    ensure_column(conn, "jobs", "citizenship_risk", "TEXT DEFAULT 'clear'")
    load_bullet_bank(conn)
    conn.close()
    print(f"\nDatabase ready at: {DB_PATH}")


if __name__ == "__main__":
    main()