"""
Re-categorize historical application failures and log reasons.
"""

import sys
from pathlib import Path

# Add project root to python path to import core.db_client
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.db_client import get_connection


def recategorize():
    print("Connecting to database for historical re-categorization...")
    try:
        conn = get_connection()
    except Exception as e:
        print(f"[CRITICAL ERROR] Failed to connect: {e}")
        sys.exit(1)

    try:
        with conn.cursor() as cur:
            # Query all applications with potential manual intervention markers
            cur.execute("""
                SELECT id, job_id, status, error_message
                FROM job_hunter.applications
                WHERE status IN ('failed', 'manual_required') OR error_message IS NOT NULL;
            """)
            apps = cur.fetchall()
            print(
                f"Analyzing {len(apps)} applications for manual intervention re-categorization..."
            )

            recat_count = 0
            for app_id, job_id, status, err_msg in apps:
                err_msg_lower = str(err_msg).lower() if err_msg else ""
                reason = None

                if "external (manual required)" in err_msg_lower:
                    reason = (
                        "External application redirect (requires manual submission)"
                    )
                elif "stuck (manual intervention required)" in err_msg_lower:
                    reason = "Stuck in application flow / validation errors"
                elif (
                    "captcha" in err_msg_lower
                    or "confirm you are human" in err_msg_lower
                ):
                    reason = "CAPTCHA or Bot detection challenge detected"
                elif (
                    "auth" in err_msg_lower
                    or "logged out" in err_msg_lower
                    or "login" in err_msg_lower
                ):
                    reason = "Authentication required / Session expired"
                elif status == "manual_required":
                    reason = "Manual intervention requested by system"

                if reason:
                    # Update application
                    cur.execute(
                        """
                        UPDATE job_hunter.applications
                        SET status = 'needs_manual_intervention',
                            manual_intervention_reason = %s
                        WHERE id = %s;
                    """,
                        (reason, app_id),
                    )

                    # Update job
                    cur.execute(
                        """
                        UPDATE job_hunter.jobs
                        SET status_apply = 'needs_manual_intervention',
                            manual_intervention_reason = %s
                        WHERE id = %s;
                    """,
                        (reason, job_id),
                    )

                    recat_count += 1

            conn.commit()
            print(
                f"Re-categorization complete. Updated {recat_count} applications and corresponding jobs."
            )

    except Exception as e:
        print(f"[ERROR] Re-categorization failed: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    recategorize()
