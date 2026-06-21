"""
run_pipeline.py

Runs the full job search pipeline in one command: fetch, filter,
save, and citizenship-flag new postings; score the ones not yet
scored; then send a digest of qualifying matches. Each stage reuses
the same functions already used when running its script
individually, so this file is a thin orchestration layer, not a
reimplementation. A failure in one stage is reported but does not
stop the remaining stages from running, since each stage's work is
independently useful even if a later stage fails.

Usage:
    python src/run_pipeline.py
"""

import sys
import os
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import save_jobs
import score_jobs
import send_digest


def run_stage(stage_name, stage_function):
    """Runs one pipeline stage, reporting failure without stopping the run."""
    print(f"--- {stage_name} ---")
    try:
        stage_function()
    except Exception as e:
        print(f"  Stage failed: {e}")
    print()


def main():
    start = datetime.now()
    print(f"=== Pipeline run started: {start.strftime('%Y-%m-%d %H:%M:%S')} ===\n")

    run_stage("Stage 1/3: Fetch, filter, save, and citizenship-flag new jobs", save_jobs.main)
    run_stage("Stage 2/3: Score new jobs", score_jobs.main)
    run_stage("Stage 3/3: Send digest of qualifying matches", send_digest.main)

    duration = (datetime.now() - start).total_seconds()
    print(f"=== Pipeline run finished in {duration:.1f}s ===")


if __name__ == "__main__":
    main()