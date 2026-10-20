"""
reset_unverified_applications.py — Unverified application reset utility.

Resets jobs previously marked as needs_manual_intervention back to pending.
"""

import sys
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.db_client import get_connection


def reset_unverified_jobs(dry_run: bool = False) -> int:
    """Resets jobs stuck in needs_manual_intervention status back to pending."""
    print("=== Resetting Unverified / Proof-Failed Jobs to Pending ===")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Query target jobs in needs_manual_intervention
            cur.execute("""
                SELECT id, company, title, manual_intervention_reason
                FROM job_hunter.jobs
                WHERE status_apply = 'needs_manual_intervention'
            """)
            jobs = cur.fetchall()
            print(
                f"Found {len(jobs)} jobs in 'needs_manual_intervention' state to reset."
            )

            if not jobs:
                print("No jobs found matching unverified proof criteria.")
                return 0

            job_ids = [j[0] for j in jobs]

            if dry_run:
                print(f"[DRY RUN] Would reset {len(job_ids)} jobs to pending.")
                return len(job_ids)

            # Reset job_hunter.jobs
            cur.execute(
                """
                UPDATE job_hunter.jobs
                SET status_apply = 'pending', manual_intervention_reason = NULL
                WHERE id = ANY(%s)
            """,
                (job_ids,),
            )

            # Reset or remove unverified application records
            cur.execute(
                """
                DELETE FROM job_hunter.applications
                WHERE job_id = ANY(%s)
                  AND status IN ('needs_manual_intervention', 'failed', 'failed_manual')
            """,
                (job_ids,),
            )

            conn.commit()
            print(f"Successfully reset {len(job_ids)} jobs back to 'pending'.")
            return len(job_ids)
    except Exception as e:
        print(f"[ERROR] Failed to reset jobs: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Reset unverified/proof-failed jobs back to pending queue"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview reset actions without modifying database",
    )
    args = parser.parse_args()
    reset_unverified_jobs(dry_run=args.dry_run)
