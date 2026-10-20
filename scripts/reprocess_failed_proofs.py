"""
Reprocess false manual interventions and misattributed company names in JobHunterKit.
"""

import sys
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from core.company_extractor import extract_company_name
from core.db_client import get_connection


def fix_misattributed_itviec_companies():
    print("=== Checking & Fixing Misattributed ITviec Company Names ===")
    conn = get_connection()
    fixed_count = 0
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, title, company, url, jd_text
                FROM job_hunter.jobs
                WHERE source = 'itviec' AND (company = 'MB Bank' OR company = 'Unknown Company');
            """)
            rows = cur.fetchall()
            print(
                f"Found {len(rows)} ITviec jobs with potential company misattribution."
            )

            for job_id, title, current_comp, url, jd_text in rows:
                extracted = extract_company_name(
                    jd_text=jd_text, page_title=f"{title} | ITviec", page_url=url
                )
                if extracted and extracted not in ("MB Bank", "Unknown Company"):
                    print(
                        f"  [FIX COMPANY] Job {job_id} ('{title}'): '{current_comp}' => '{extracted}'"
                    )
                    cur.execute(
                        "UPDATE job_hunter.jobs SET company = %s WHERE id = %s;",
                        (extracted, job_id),
                    )
                    fixed_count += 1

            conn.commit()
            print(f"Successfully fixed {fixed_count} misattributed company names.\n")
    except Exception as e:
        print(f"[ERROR] Company fix failed: {e}")
        conn.rollback()
    finally:
        conn.close()


def reset_target_failed_jobs(target_ids=None):
    print("=== Resetting Target Jobs to Pending for Autonomous Re-Execution ===")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if target_ids:
                cur.execute(
                    """
                    UPDATE job_hunter.jobs
                    SET status_apply = 'pending', manual_intervention_reason = NULL
                    WHERE id = ANY(%s);
                """,
                    (target_ids,),
                )
                print(
                    f"Reset {cur.rowcount} specific jobs ({target_ids}) to 'pending'."
                )
            else:
                cur.execute("""
                    UPDATE job_hunter.jobs
                    SET status_apply = 'pending', manual_intervention_reason = NULL
                    WHERE status_apply = 'needs_manual_intervention'
                      AND manual_intervention_reason LIKE '%Submission confirmation signature not detected%';
                """)
                print(
                    f"Reset {cur.rowcount} jobs with false proof rejections to 'pending'."
                )
            conn.commit()
    except Exception as e:
        print(f"[ERROR] Reset failed: {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Fix company names and reset failed proof jobs"
    )
    parser.add_argument(
        "--job-ids", nargs="+", type=int, default=None, help="Specific job IDs to reset"
    )
    parser.add_argument(
        "--all-false-proofs",
        action="store_true",
        help="Reset all false proof rejection jobs",
    )
    args = parser.parse_args()

    fix_misattributed_itviec_companies()
    if args.job_ids or args.all_false_proofs:
        reset_target_failed_jobs(args.job_ids)
