"""
migrate_indexes.py — Database index migration and optimization runner for JobHunterKit.

Applies composite queue indexes and foreign key indexes for low-latency concurrency.
"""

import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.db_client import get_connection


def apply_index_optimizations() -> None:
    """Creates composite and foreign-key performance indexes in PostgreSQL schema."""
    print("=== APPLYING DATABASE INDEX OPTIMIZATIONS ===")
    conn = get_connection()
    conn.autocommit = True
    cur = conn.cursor()

    statements = [
        # Composite queue indexes for O(1) FOR UPDATE SKIP LOCKED checkout
        (
            "idx_jobs_apply_queue",
            "CREATE INDEX IF NOT EXISTS idx_jobs_apply_queue ON job_hunter.jobs (status_apply, scraped_at DESC NULLS LAST, id DESC);",
        ),
        (
            "idx_jobs_scoring_queue",
            "CREATE INDEX IF NOT EXISTS idx_jobs_scoring_queue ON job_hunter.jobs (status_score, scraped_at DESC NULLS LAST, id DESC);",
        ),
        # Foreign key indexes on child tables
        (
            "idx_scores_job_id",
            "CREATE INDEX IF NOT EXISTS idx_scores_job_id ON job_hunter.scores (job_id);",
        ),
        (
            "idx_applications_job_id",
            "CREATE INDEX IF NOT EXISTS idx_applications_job_id ON job_hunter.applications (job_id);",
        ),
        (
            "idx_applications_job_id_status",
            "CREATE INDEX IF NOT EXISTS idx_applications_job_id_status ON job_hunter.applications (job_id, status);",
        ),
        (
            "idx_discovered_channels_source_job_id",
            "CREATE INDEX IF NOT EXISTS idx_discovered_channels_source_job_id ON job_hunter.discovered_channels (source_job_id);",
        ),
        (
            "idx_applications_applied_at",
            "CREATE INDEX IF NOT EXISTS idx_applications_applied_at ON job_hunter.applications (applied_at DESC);",
        ),
    ]

    for name, sql in statements:
        try:
            print(f"Applying {name}...")
            cur.execute(sql)
            print(f"  [OK] {name}")
        except Exception as e:
            print(f"  [ERROR] {name}: {e}")

    cur.close()
    conn.close()
    print("All index optimizations processed.")


if __name__ == "__main__":
    apply_index_optimizations()
