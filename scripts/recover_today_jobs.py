"""
Auto-recovery script for JobHunterKit today's applications.
1. Re-verifies jobs marked 'needs_manual_intervention' that have valid proof screenshots on disk, setting them back to 'completed'.
2. Resets false-positive / interrupted manual intervention jobs back to 'pending' for Flow 3 auto-apply.
"""

import os
import sys
from pathlib import Path

if sys.stdout:
    sys.stdout.reconfigure(encoding="utf-8")

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.db_client import get_connection
from scripts.verify_application_proofs import verify_proof_file


def recover_jobs() -> None:
    """Reconciles today's manual intervention applications against disk proofs and resets unapplied jobs to pending."""
    print("=== Starting Auto-Recovery for Today's Jobs ===")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # 1. Audit current status breakdown
            cur.execute("""
                SELECT status_apply, COUNT(*)
                FROM job_hunter.jobs
                GROUP BY status_apply
                ORDER BY COUNT(*) DESC;
            """)
            print("\nInitial Database status_apply counts:")
            for status, count in cur.fetchall():
                print(f"  - {status}: {count}")

            # 2. Find jobs in needs_manual_intervention with valid proof screenshots on disk
            cur.execute("""
                SELECT id, company, title
                FROM job_hunter.jobs
                WHERE status_apply = 'needs_manual_intervention'
            """)
            intervention_jobs = cur.fetchall()

            campaigns_dir = os.path.join(project_root, "data", "campaigns")
            recompleted_count = 0

            for job_id, company, title in intervention_jobs:
                target_filename = f"proof_submitted_{job_id}.png"
                found_proof = False
                if os.path.exists(campaigns_dir):
                    for root, _, files in os.walk(campaigns_dir):
                        for f in files:
                            if (
                                f == target_filename
                                or f.startswith(f"proof_submitted_{job_id}")
                            ) and verify_proof_file(os.path.join(root, f)):
                                found_proof = True
                                break
                        if found_proof:
                            break

                if found_proof:
                    recompleted_count += 1
                    print(
                        f"  [PROOF RE-VERIFIED] Restoring Job {job_id} ({title} @ {company}) -> status_apply = 'completed'"
                    )
                    cur.execute(
                        """
                        UPDATE job_hunter.jobs
                        SET status_apply = 'completed', manual_intervention_reason = NULL
                        WHERE id = %s
                    """,
                        (job_id,),
                    )
                    cur.execute(
                        """
                        UPDATE job_hunter.applications
                        SET status = 'completed', manual_intervention_reason = NULL
                        WHERE job_id = %s
                    """,
                        (job_id,),
                    )

            # 3. Reset false positive manual interventions to pending
            recoverable_reasons = (
                "Proof review failed: Submission confirmation signature not detected",
                "JSONDecodeError",
                "name 'context' is not defined",
                "NoneType",
                "Unexpected token",
                "Browser.new_context",
                "Connection closed",
            )

            cur.execute("""
                SELECT id, company, title, manual_intervention_reason
                FROM job_hunter.jobs
                WHERE status_apply IN ('needs_manual_intervention', 'failed_manual')
            """)
            remaining_intervention_jobs = cur.fetchall()

            reset_pending_count = 0
            for job_id, company, title, reason in remaining_intervention_jobs:
                reason_str = str(reason or "")
                if (
                    not reason
                    or any(r.lower() in reason_str.lower() for r in recoverable_reasons)
                    or "error" in reason_str.lower()
                    or "timeout" in reason_str.lower()
                ):
                    reset_pending_count += 1
                    print(
                        f"  [QUEUE RECOVERED] Resetting Job {job_id} ({title} @ {company}) -> status_apply = 'pending'"
                    )
                    cur.execute(
                        """
                        UPDATE job_hunter.jobs
                        SET status_apply = 'pending', manual_intervention_reason = NULL
                        WHERE id = %s
                    """,
                        (job_id,),
                    )

            conn.commit()
            print("\nRecovery Summary:")
            print(f"  - Re-verified to completed: {recompleted_count}")
            print(f"  - Reset to pending queue: {reset_pending_count}")

            # 4. Final Database status breakdown
            cur.execute("""
                SELECT status_apply, COUNT(*)
                FROM job_hunter.jobs
                GROUP BY status_apply
                ORDER BY COUNT(*) DESC;
            """)
            print("\nUpdated Database status_apply counts:")
            for status, count in cur.fetchall():
                print(f"  - {status}: {count}")

            # 5. Ready for apply queue depth
            cur.execute("""
                SELECT COUNT(*)
                FROM job_hunter.jobs
                WHERE status_score = 'completed' AND status_apply = 'pending';
            """)
            ready_count = cur.fetchone()[0]
            print(
                f"\nPending queue depth ready for Flow 3 auto-apply: {ready_count} jobs."
            )

    except Exception as e:
        print(f"Error during auto-recovery: {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    recover_jobs()
