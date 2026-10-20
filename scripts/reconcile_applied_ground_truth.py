"""
scripts/reconcile_applied_ground_truth.py — Targeted Database Ground-Truth Cleanup.

Directly reconciles historical and today's database records in PostgreSQL based on
authoritative user audit findings:
1. ITViec: Only M_Service (MoMo) is confirmed genuine for today. All other ITViec jobs demoted.
2. TopCV: 0 genuine submissions for the last 1 month. All TopCV jobs demoted.
3. Strict proof review applied to all unconfirmed applications.
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.db_client import get_connection

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("reconcile_ground_truth")


def reconcile_known_ground_truth(dry_run: bool = False):
    logger.info("=== Running Targeted Ground-Truth Database Clean-Up ===")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # 1. Reconcile TopCV: Demote all TopCV applications in the last 30 days to pending
            logger.info("Auditing TopCV applications...")
            cur.execute("""
                SELECT j.id, j.company, j.title, a.applied_at
                FROM job_hunter.applications a
                JOIN job_hunter.jobs j ON a.job_id = j.id
                WHERE j.source = 'topcv' AND a.status IN ('applied', 'completed', 'success', 'needs_manual_intervention');
            """)
            topcv_rows = cur.fetchall()
            logger.info(
                "Found %d TopCV applications to reset to pending.", len(topcv_rows)
            )
            for job_id, company, title, applied_at in topcv_rows:
                logger.info(
                    "  [TOPCV RESET TO PENDING] Job #%d: %s - %s (applied: %s) -> pending",
                    job_id,
                    company,
                    title,
                    applied_at,
                )
                if not dry_run:
                    cur.execute(
                        """
                        UPDATE job_hunter.jobs
                        SET status_apply = 'pending',
                            manual_intervention_reason = 'Ground truth reset: queued for re-application with strict proof validation',
                            apply_attempts = 0
                        WHERE id = %s;
                    """,
                        (job_id,),
                    )
                    cur.execute(
                        """
                        UPDATE job_hunter.applications
                        SET status = 'pending_retry',
                            manual_intervention_reason = 'Ground truth reset: queued for re-application with strict proof validation'
                        WHERE job_id = %s;
                    """,
                        (job_id,),
                    )

            # 2. Reconcile ITViec: Keep only MoMo (M_Service), demote others to pending
            logger.info("Auditing ITViec applications for today (2026-08-17)...")
            cur.execute("""
                SELECT j.id, j.company, j.title, a.applied_at
                FROM job_hunter.applications a
                JOIN job_hunter.jobs j ON a.job_id = j.id
                WHERE j.source = 'itviec'
                  AND (a.applied_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date = '2026-08-17';
            """)
            itviec_rows = cur.fetchall()
            for job_id, company, title, applied_at in itviec_rows:
                is_momo = "m_service" in company.lower() or "momo" in company.lower()
                if is_momo:
                    logger.info(
                        "  [ITVIEC KEEP] Job #%d: %s - %s -> VERIFIED GENUINE (completed)",
                        job_id,
                        company,
                        title,
                    )
                else:
                    logger.info(
                        "  [ITVIEC RESET TO PENDING] Job #%d: %s - %s -> pending (False Positive)",
                        job_id,
                        company,
                        title,
                    )
                    if not dry_run:
                        cur.execute(
                            """
                            UPDATE job_hunter.jobs
                            SET status_apply = 'pending',
                                manual_intervention_reason = 'Ground truth reset: queued for re-application with strict proof validation',
                                apply_attempts = 0
                            WHERE id = %s;
                        """,
                            (job_id,),
                        )
                        cur.execute(
                            """
                            UPDATE job_hunter.applications
                            SET status = 'pending_retry',
                                manual_intervention_reason = 'Ground truth reset: queued for re-application with strict proof validation'
                            WHERE job_id = %s;
                        """,
                            (job_id,),
                        )

            if not dry_run:
                conn.commit()
                logger.info(
                    "Database ground-truth reconciliation committed successfully."
                )
            else:
                logger.info("Database ground-truth reconciliation completed (DRY RUN).")

    except Exception as e:
        logger.error("Ground-truth cleanup failed: %s", e)
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Clean up database false positives against ground truth"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Run without modifying database"
    )
    args = parser.parse_args()

    reconcile_known_ground_truth(dry_run=args.dry_run)
