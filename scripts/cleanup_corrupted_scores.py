import sys
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "scripts"))

from core.db_client import get_connection

if sys.stdout:
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr:
    sys.stderr.reconfigure(encoding="utf-8")


def find_corrupted_jobs(conn):
    """
    Finds jobs with status_score='completed' whose match_score=0 (in jobs or scores table)
    and whose claimed_at / score scored_at timestamp falls in 2026-07-26 18:13–22:20 window.
    """
    with conn.cursor() as cur:
        query = """
        SELECT j.id, j.title, j.company, j.status_score, j.status_apply, j.claimed_at, s.match_score, s.scored_at
        FROM job_hunter.jobs j
        LEFT JOIN job_hunter.scores s ON j.id = s.job_id
        WHERE j.status_score = 'completed'
          AND (s.match_score = 0 OR s.match_score IS NULL)
          AND (
            (j.claimed_at >= '2026-07-26 18:13:00' AND j.claimed_at <= '2026-07-26 22:20:00')
            OR
            (s.scored_at >= '2026-07-26 18:13:00' AND s.scored_at <= '2026-07-26 22:20:00')
          );
        """
        cur.execute(query)
        rows = cur.fetchall()
        return rows


def reset_corrupted_jobs(conn, job_ids):
    if not job_ids:
        print("No job IDs to reset.")
        return 0

    with conn.cursor() as cur:
        # Delete invalid 0 match_score records from scores table for these job_ids
        cur.execute(
            "DELETE FROM job_hunter.scores WHERE job_id = ANY(%s) AND match_score = 0;",
            (job_ids,),
        )
        # Reset status_score and status_apply to pending
        cur.execute(
            "UPDATE job_hunter.jobs SET status_score = 'pending', status_apply = 'pending' WHERE id = ANY(%s);",
            (job_ids,),
        )
        conn.commit()
        return len(job_ids)


def main():
    dry_run = "--execute" not in sys.argv
    conn = get_connection()
    try:
        jobs = find_corrupted_jobs(conn)
        print(
            f"Found {len(jobs)} corrupted jobs scored between 2026-07-26 18:13:00 and 22:20:00:"
        )
        for j in jobs:
            print(
                f"  - ID {j[0]}: {j[1]} at {j[2]} (claimed_at: {j[5]}, scored_at: {j[7]}, score: {j[6]})"
            )

        if dry_run:
            print("\n[DRY RUN] To execute reset, run with --execute")
        else:
            job_ids = [j[0] for j in jobs]
            reset_count = reset_corrupted_jobs(conn, job_ids)
            print(
                f"\n[SUCCESS] Reset {reset_count} jobs back to status_score='pending' and status_apply='pending'."
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
