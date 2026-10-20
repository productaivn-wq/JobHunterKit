"""
recover_false_negatives.py — Recovers false negative jobs in JobHunterKit.
1. Resets 293 jobs with match_score >= 70 marked status_apply = 'skipped' to 'pending'.
2. Resets 83 target jobs with match_score 60-69 marked status_apply = 'skipped' to 'pending'.
3. Resets 11 empty/error scraped JDs marked status_score = 'skipped_prefilter' to 'pending'.
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv(project_root / ".env")

from core.db_client import get_connection


def recover_high_scoring_skipped():
    """Recover jobs with match_score >= 70 marked status_apply = 'skipped'."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            query = """
                UPDATE job_hunter.jobs j
                SET status_apply = 'pending'
                FROM (
                    SELECT DISTINCT ON (job_id) job_id, match_score
                    FROM job_hunter.scores
                    ORDER BY job_id, scored_at DESC
                ) s
                WHERE j.id = s.job_id
                  AND s.match_score >= 70
                  AND j.status_apply = 'skipped';
            """
            cur.execute(query)
            count = cur.rowcount
            conn.commit()
            print(
                f"[RECOVERY] Successfully recovered {count} high-scoring jobs (match_score >= 70) to status_apply = 'pending'."
            )
            return count
    finally:
        conn.close()


def recover_near_pass_target_jobs():
    """Recover target roles with match_score 60-69 marked status_apply = 'skipped'."""
    target_keywords = [
        "%ai%",
        "%product manager%",
        "%head of product%",
        "%lead%product%",
        "%director%",
        "%group%pm%",
        "%technical product manager%",
        "%product operations%",
    ]
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            query = """
                UPDATE job_hunter.jobs j
                SET status_apply = 'pending'
                FROM (
                    SELECT DISTINCT ON (job_id) job_id, match_score
                    FROM job_hunter.scores
                    ORDER BY job_id, scored_at DESC
                ) s
                WHERE j.id = s.job_id
                  AND s.match_score >= 60 AND s.match_score < 70
                  AND j.status_apply = 'skipped'
                  AND (
                      LOWER(j.title) LIKE ANY(%s)
                  );
            """
            cur.execute(query, (target_keywords,))
            count = cur.rowcount
            conn.commit()
            print(
                f"[RECOVERY] Successfully recovered {count} near-pass target jobs (match_score 60-69) to status_apply = 'pending'."
            )
            return count
    finally:
        conn.close()


def recover_scraping_error_jds():
    """Reset empty/419-byte error JDs marked skipped_prefilter back to pending scoring."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            query = """
                UPDATE job_hunter.jobs
                SET status_score = 'pending', status_apply = 'pending'
                WHERE status_score = 'skipped_prefilter'
                  AND (
                      jd_text IS NULL
                      OR LENGTH(jd_text) < 100
                      OR LOWER(jd_text) LIKE '%could not process this request%'
                  );
            """
            cur.execute(query)
            count = cur.rowcount
            conn.commit()
            print(
                f"[RECOVERY] Successfully reset {count} scraping-error JDs to status_score = 'pending'."
            )
            return count
    finally:
        conn.close()


def print_updated_db_summary():
    """Print updated database queue summary."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            print("\n=== UPDATED DATABASE QUEUE STATS ===")
            cur.execute("""
                SELECT status_score, status_apply, COUNT(*)
                FROM job_hunter.jobs
                GROUP BY status_score, status_apply
                ORDER BY status_score, status_apply;
            """)
            for r in cur.fetchall():
                print(f"Score: {r[0]:<20} | Apply: {r[1]:<25} | Count: {r[2]}")
    finally:
        conn.close()


if __name__ == "__main__":
    print("=== Executing False Negative Job Recovery ===")
    h_count = recover_high_scoring_skipped()
    n_count = recover_near_pass_target_jobs()
    s_count = recover_scraping_error_jds()
    print_updated_db_summary()
    print(f"\nTotal recovered jobs queued for Flow 3: {h_count + n_count + s_count}")
