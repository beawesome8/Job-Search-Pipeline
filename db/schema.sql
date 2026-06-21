-- =====================================================================
-- Job Search Pipeline - Database Schema
-- =====================================================================
-- This file is a blueprint, not a program. It describes what tables
-- should exist and what columns each table has. setup_db.py reads
-- this file and hands it to SQLite, which actually builds the
-- database from these instructions.
-- =====================================================================

-- ---------------------------------------------------------------------
-- jobs: one row per unique job posting the pipeline has discovered.
-- This is the central table everything else links back to.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,   -- unique number SQLite assigns automatically
    source TEXT NOT NULL,                   -- e.g. 'arbeitnow', 'adzuna', 'company:bmw'
    external_id TEXT,                       -- the ID the source itself uses for this posting
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    url TEXT NOT NULL UNIQUE,               -- UNIQUE = SQLite blocks duplicate URLs automatically
    description TEXT,
    language TEXT,                          -- 'de' or 'en', drives which resume language to use
    posted_at TIMESTAMP,                    -- when the job was actually posted (may be unknown)
    date_scraped TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- when WE found it
    prefilter_passed INTEGER DEFAULT 0,     -- 0/1: did it clear the cheap role-match check?
    citizenship_risk TEXT DEFAULT 'clear',  -- 'clear' or 'flagged', from the keyword pre-scan
    alerted_fresh INTEGER DEFAULT 0,        -- 0/1: have you already gotten the instant alert for this?
    alerted_digest INTEGER DEFAULT 0        -- 0/1: have you already gotten the scored digest alert?
);

-- ---------------------------------------------------------------------
-- scores: the AI's fit-scoring verdict for a job. Separate from jobs
-- because a job is a fact (it exists), a score is a judgment (it
-- might change if we improve the scoring prompt later).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    fit_score INTEGER,                      -- 0-100
    reasoning TEXT,                         -- short explanation from the model
    missing_keywords TEXT,                  -- stored as a JSON list, e.g. '["MLOps", "LangGraph"]'
    citizenship_flag TEXT,                  -- 'clear', 'flagged', or 'unclear'
    model_used TEXT,                        -- which Claude model produced this, for cost tracking
    scored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES jobs(id)  -- links this row back to a specific job
);

-- ---------------------------------------------------------------------
-- bullet_bank: your verified, true resume bullets. This is the
-- "ground truth" the tailoring step is only ever allowed to rewrite
-- from, never invent beyond.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bullet_bank (
    bullet_id TEXT PRIMARY KEY,             -- e.g. 'INF_FT_01', matches your reviewed JSON
    role TEXT NOT NULL,
    company TEXT NOT NULL,
    dates TEXT,
    text TEXT NOT NULL,
    hard_skills TEXT,                       -- JSON list
    soft_skills TEXT,                       -- JSON list
    keywords TEXT                           -- JSON list, used by the cheap pre-filter
);

-- ---------------------------------------------------------------------
-- tailoring_drafts: AI-drafted bullet rewrites for a specific job,
-- waiting for your review before anything becomes a real document.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tailoring_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    drafted_bullets TEXT,                   -- JSON list of rewritten bullet text
    cover_letter_hook TEXT,                 -- suggested opening line
    status TEXT DEFAULT 'pending',          -- 'pending', 'approved', or 'rejected'
    drafted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

-- ---------------------------------------------------------------------
-- applications: tracks what actually happened after a job was
-- tailored. This is what eventually lets you measure your own funnel.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL UNIQUE,
    tailored INTEGER DEFAULT 0,
    tailored_date TIMESTAMP,
    applied INTEGER DEFAULT 0,
    applied_date TIMESTAMP,
    status TEXT DEFAULT 'not_applied',      -- not_applied, applied, no_response, interview, rejected, offer
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

-- ---------------------------------------------------------------------
-- Indexes: these make lookups on frequently-searched columns much
-- faster as the database grows. Not critical at 50 rows, genuinely
-- useful at 5,000.
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_jobs_url ON jobs(url);
CREATE INDEX IF NOT EXISTS idx_scores_job_id ON scores(job_id);
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
