import sys
from pathlib import Path

from dotenv import load_dotenv

skill_dir = Path(__file__).resolve().parent.parent
load_dotenv(skill_dir / ".env")
sys.path.insert(0, str(skill_dir))

sys.stdout.reconfigure(encoding="utf-8")

from core.db_client import get_connection


def recover_jobs(threshold=0):
    conn = get_connection()
    cur = conn.cursor()

    query = """
    SELECT id, title, company, status_apply, manual_intervention_reason
    FROM job_hunter.jobs
    WHERE status_apply IN ('needs_manual_intervention', 'failed_manual')
    ORDER BY id DESC;
    """
    cur.execute(query)
    rows = cur.fetchall()

    if threshold > 0 and len(rows) < threshold:
        print(
            f"ℹ️ [THRESHOLD CHECK] Needs manual intervention count ({len(rows)}) is below threshold ({threshold}). Skipping recovery."
        )
        cur.close()
        conn.close()
        return 0

    recovered_ids = []

    for row in rows:
        job_id, title, company, status, reason = row
        reason_str = str(reason) if reason else ""

        # Recover transient errors, null pointer bugs, visual loop timeouts, proof review false negatives, and watchdog timeouts
        should_recover = False
        if not reason or reason_str in ("", "None", "No reason specified"):
            should_recover = True
        elif "JSONDecodeError" in reason_str:
            should_recover = True
        elif "LLM action error" in reason_str:
            should_recover = True
        elif "browser has been closed" in reason_str or "Page.screenshot" in reason_str:
            should_recover = True
        elif "Visual agent hit maximum iterations" in reason_str:
            should_recover = True
        elif "'NoneType' object has no attribute" in reason_str:
            should_recover = True
        elif "unsupported operand type(s)" in reason_str:
            should_recover = True
        elif "missing 1 required positional argument" in reason_str:
            should_recover = True
        elif "Proof review failed" in reason_str:
            should_recover = True
        elif "Timed out after" in reason_str or "watchdog" in reason_str.lower():
            should_recover = True
        elif "Action execution repeatedly failed" in reason_str:
            should_recover = True

        if should_recover:
            recovered_ids.append(job_id)
            print(
                f"  [RECOVERING] Job #{job_id}: '{title}' at '{company}' (Reason: {reason_str[:60]})"
            )

    if recovered_ids:
        update_query = """
        UPDATE job_hunter.jobs
        SET status_apply = 'pending',
            manual_intervention_reason = NULL
        WHERE id = ANY(%s)
          AND id NOT IN (SELECT job_id FROM job_hunter.applications WHERE status IN ('applied', 'completed', 'dry_run'));
        """
        cur.execute(update_query, (recovered_ids,))
        conn.commit()
        print(
            f"\n✅ Successfully recovered {len(recovered_ids)} false-positive / interrupted manual intervention jobs back to status_apply='pending'!"
        )
    else:
        print("\nℹ️ No recoverable manual intervention jobs found.")

    cur.close()
    conn.close()
    return len(recovered_ids)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Auto-recover manual intervention jobs"
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=0,
        help="Minimum count of manual intervention jobs before triggering recovery",
    )
    args = parser.parse_args()
    recover_jobs(threshold=args.threshold)
