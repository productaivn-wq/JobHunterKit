"""
recover_all_pipeline_jobs.py — Comprehensive Auto-Recovery for JobHunterKit

Recovers:
  1. All jobs in 'needs_manual_intervention' and 'failed_manual' back to 'pending'.
  2. All jobs in 'failed' status back to 'pending'.
  3. High-scoring false-negatives (match_score >= 70 in job_hunter.scores) previously marked 'skipped'.
  4. Resets apply attempt counters and cleans transient failure records in applications table.
"""

import sys
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv(project_root / ".env")

from core.db_client import get_connection


def recover_jobs() -> None:
    """Executes database reconciliation resetting stuck, failed, and false-negative jobs back to pending."""
    print("=" * 60)
    print("JobHunterKit Pipeline Auto-Recovery")
    print("=" * 60)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # 1. Recover Manual Interventions, Failures, and Stale Applying Claims
            cur.execute(
                """
                UPDATE job_hunter.jobs
                SET status_apply = 'pending',
                    manual_intervention_reason = NULL,
                    claimed_at = NULL,
                    apply_attempts = 0
                WHERE (
                    status_apply IN ('needs_manual_intervention', 'failed_manual', 'failed')
                    OR (status_apply = 'applying' AND (claimed_at IS NULL OR claimed_at < NOW() - INTERVAL '30 minutes'))
                )
                  AND id NOT IN (
                      SELECT job_id FROM job_hunter.applications
                      WHERE status IN ('applied', 'completed', 'dry_run')
                  )
                RETURNING id;
                """
            )
            recovered_manual_failed = cur.fetchall()
            print(
                f"[RECOVERED] Manual Interventions, Failures & Stale Applying Claims: {len(recovered_manual_failed)} jobs reset to 'pending'."
            )

            # 2. Recover High-Score False Negatives (match_score >= 70 in job_hunter.scores) from skipped status
            cur.execute(
                """
                UPDATE job_hunter.jobs j
                SET status_apply = 'pending',
                    manual_intervention_reason = NULL,
                    apply_attempts = 0
                FROM job_hunter.scores s
                WHERE s.job_id = j.id
                  AND j.status_apply = 'skipped'
                  AND s.match_score >= 70
                  AND j.id NOT IN (
                      SELECT job_id FROM job_hunter.applications
                      WHERE status IN ('applied', 'completed', 'dry_run')
                  )
                RETURNING j.id;
                """
            )
            recovered_false_skips = cur.fetchall()
            print(
                f"[RECOVERED] High-Scoring False Skips (match_score >= 70): {len(recovered_false_skips)} jobs reset to 'pending'."
            )

            # 3. Clean up transient failed application log rows to maintain clean analytics
            cur.execute(
                """
                DELETE FROM job_hunter.applications
                WHERE status = 'failed'
                  AND job_id NOT IN (
                      SELECT id FROM job_hunter.jobs
                      WHERE status_apply IN ('applied', 'completed', 'dry_run')
                  );
                """
            )
            deleted_failed_logs = cur.rowcount
            print(
                f"[CLEANED] Removed {deleted_failed_logs} transient failed log entries."
            )

            conn.commit()

            # 4. Show updated queue status
            cur.execute(
                """
                SELECT status_apply, COUNT(*)
                FROM job_hunter.jobs
                GROUP BY status_apply
                ORDER BY COUNT(*) DESC;
                """
            )
            print("\nUpdated Application Queue Status:")
            for status, count in cur.fetchall():
                print(f"  • {status}: {count} jobs")

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Recovery failed: {e}")
        raise e
    finally:
        conn.close()


if __name__ == "__main__":
    recover_jobs()
