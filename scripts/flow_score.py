"""
Flow 2: LLM-powered JD evaluation and scoring queue (AGY CLI via LLMProviderRouter).
"""

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "scripts"))

import pipeline

from core.db_client import get_connection
from shared_platform.cv_text import load_cv_text
from shared_platform.db import claim_next_job
from shared_platform.logging_setup import flow_entrypoint
from shared_platform.paths import get_job_dirs, get_master_cv_path

try:
    import score_jd
except ImportError:
    import scripts.score_jd as score_jd


def score_single_job(job, cv_text, cv_file, threshold, dynamic_rubric):
    print(f"  [Scoring] Starting scoring for: {job['title']} at {job['company']}...")

    # Fast filter: instant regex-based exclusion for non-target roles
    try:
        from fast_filter import should_exclude
    except ImportError:
        from scripts.fast_filter import should_exclude

    exclude, reason = should_exclude(job.get("title", ""), job.get("jd_text", ""), job.get("location", ""))
    if exclude:
        print(f"  [FAST-FILTER SKIP] {job['title']} at {job['company']}: {reason}")
        db_conn = None
        try:
            db_conn = get_connection()
            with db_conn.cursor() as cur:
                cur.execute(
                    "UPDATE job_hunter.jobs SET status_score = 'completed', status_apply = 'skipped' WHERE id = %s;",
                    (job["id"],),
                )
                rubric_used = {"is_irrelevant": True}
                cur.execute(
                    """
                    INSERT INTO job_hunter.scores (job_id, match_score, reasoning, rubric_used, top_strengths, key_gaps)
                    VALUES (%s, %s, %s, %s, %s, %s);
                    """,
                    (
                        job["id"],
                        0,
                        reason,
                        json.dumps(rubric_used),
                        json.dumps([]),
                        json.dumps([reason]),
                    ),
                )
                db_conn.commit()
        except Exception as db_err:
            print(
                f"  [ERROR] Database fast-filter update failed for {job['company']}: {db_err}"
            )
            if db_conn:
                db_conn.rollback()
            raise db_err
        finally:
            if db_conn:
                db_conn.close()
        return job["id"], True, 0

    # Run ATS pre-filter
    from core.ats_prefilter import should_skip_jd

    should_skip, ats_score = should_skip_jd(job["jd_text"])
    if should_skip:
        print(
            f"  [PRE-FILTER SKIP] {job['title']} at {job['company']} failed pre-filter (score: {ats_score:.3f} < 0.150). Skipping LLM scoring."
        )
        db_conn = None
        try:
            db_conn = get_connection()
            with db_conn.cursor() as cur:
                cur.execute(
                    "UPDATE job_hunter.jobs SET status_score = 'skipped_prefilter', status_apply = 'skipped' WHERE id = %s;",
                    (job["id"],),
                )
                db_conn.commit()
        except Exception as db_err:
            print(
                f"  [ERROR] Database pre-filter update failed for {job['company']}: {db_err}"
            )
            if db_conn:
                db_conn.rollback()
            raise db_err
        finally:
            if db_conn:
                db_conn.close()
        return job["id"], True, 0

    dirs = get_job_dirs(job)
    score_file = os.path.join(
        dirs["scores_dir"],
        f"{pipeline.safe_filename(job['company'])}__{job['id']}_score.json",
    )
    temp_jd = os.path.join(dirs["local_scratch"], f"{job['id']}_jd.txt")

    try:
        # Write JD text to temp file
        with open(temp_jd, "w", encoding="utf-8") as f:
            f.write(job["jd_text"])

        # Run rubric generation and scoring directly in Python
        rubric_data = None
        if dynamic_rubric:
            rubric_data = score_jd._handle_dynamic_rubric(
                job["jd_text"], score_file, job.get("title")
            )
        if rubric_data is None:
            rubric_data = score_jd.load_rubric()

        actual_threshold = (
            threshold
            if threshold is not None
            else rubric_data.get("pass_threshold", 70)
        )

        result = score_jd.score_job_description(
            job["jd_text"], cv_text, rubric_data, score_file
        )

        # Save score audit
        score_jd._save_score_audit(
            score_file, rubric_data, actual_threshold, result, temp_jd, cv_file
        )

        match_score = result.get("match_score", 0)
        reasoning = result.get("overall_reasoning", "")
        top_strengths = result.get("top_strengths", [])
        key_gaps = result.get("key_gaps", [])

        if "API Error" in reasoning:
            raise RuntimeError(f"Scoring engine API error: {reasoning}")

        success = match_score >= actual_threshold
        print(
            f"  [{'PASS' if success else 'FAIL'} {match_score}/100] {job['title']} at {job['company']}"
        )

        # Save score and update job state in DB
        db_conn = None
        try:
            db_conn = get_connection()
            with db_conn.cursor() as cur:
                # 1. Insert into scores
                cur.execute(
                    "INSERT INTO job_hunter.scores (job_id, match_score, reasoning, rubric_used, top_strengths, key_gaps) "
                    "VALUES (%s, %s, %s, %s, %s, %s);",
                    (
                        job["id"],
                        match_score,
                        reasoning,
                        json.dumps(rubric_data),
                        json.dumps(top_strengths),
                        json.dumps(key_gaps),
                    ),
                )
                # 2. Update job status
                status_score = "completed"
                status_apply = "pending" if success else "skipped"
                cur.execute(
                    "UPDATE job_hunter.jobs SET status_score = %s, status_apply = %s WHERE id = %s;",
                    (status_score, status_apply, job["id"]),
                )
                db_conn.commit()
        except Exception as db_err:
            print(f"  [ERROR] Database update failed for {job['company']}: {db_err}")
            if db_conn:
                db_conn.rollback()
            raise db_err
        finally:
            if db_conn:
                db_conn.close()

        return job["id"], True, match_score

    except Exception as e:
        print(f"  [ERROR] Scoring failed for {job['company']}: {e}")
        # Safe fallback DB connection handling to prevent OperationalError crashes
        try:
            db_conn = get_connection()
            try:
                with db_conn.cursor() as cur:
                    cur.execute(
                        "UPDATE job_hunter.jobs SET status_score = 'failed' WHERE id = %s;",
                        (job["id"],),
                    )
                    db_conn.commit()
            except Exception as inner_err:
                db_conn.rollback()
                print(f"  [ERROR] Inner rollback failed: {inner_err}")
            finally:
                db_conn.close()
        except Exception as db_err:
            print(
                f"  [CRITICAL ERROR] Failed to connect/mark status_score as failed for {job['company']}: {db_err}"
            )
        return job["id"], False, 0


def claim_next_scoring_job():
    """
    Atomically checks out a single pending job, marking it as 'scoring'.
    Prioritizes high-intent direct sources (jobright email digest, linkedin easy apply) first,
    then by newest scraped_at.
    """
    order_by = (
        "CASE "
        "WHEN source = 'jobright_gmail' THEN 1 "
        "WHEN source LIKE 'linkedin-easy%' THEN 2 "
        "WHEN source LIKE 'linkedin%' THEN 3 "
        "ELSE 4 END, scraped_at DESC"
    )
    return claim_next_job("status_score", "pending", "scoring", order_by_clause=order_by)


@flow_entrypoint("flow2")
def run_scoring(args):
    print("=== Flow 2: Evaluating Pending Jobs ===")

    # Load CV text using shared platform utility
    try:
        cv_text = load_cv_text(args.cv)
    except Exception as e:
        print(f"[CRITICAL ERROR] Failed to read CV file: {e}")
        sys.exit(1)

    # Dynamic worker allocation based on pending queue size (clamped between 2 and 8)
    user_workers = getattr(args, "workers", None)
    if user_workers:
        max_workers = max(1, min(int(user_workers), 16))
        print(f"Scoring with user-configured concurrency: {max_workers} workers")
    else:
        pending_count = 0
        try:
            db_conn = get_connection()
            with db_conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM job_hunter.jobs WHERE status_score = 'pending';")
                pending_count = cur.fetchone()[0]
            db_conn.close()
        except Exception:
            pending_count = 0

        # Auto-scaling heuristic:
        # < 50 pending -> 2 workers
        # 50 - 199 pending -> 4 workers
        # 200 - 499 pending -> 6 workers
        # >= 500 pending -> 8 workers
        if pending_count >= 500:
            max_workers = 8
        elif pending_count >= 200:
            max_workers = 6
        elif pending_count >= 50:
            max_workers = 4
        else:
            max_workers = 2

        print(
            f"Auto-scaled scoring workers: {max_workers} (Pending queue depth: {pending_count})"
        )

    print(f"Scoring pending jobs in parallel via dynamic lock (pool={max_workers})...")

    def worker_loop():
        # Reconfigure output to utf-8 inside threads too
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
        from shared_platform.pipeline_state import is_paused

        while True:
            if is_paused():
                print(
                    "  [INFO] Pipeline is paused. Exiting scoring worker loop.",
                    flush=True,
                )
                break
            job = claim_next_scoring_job()
            if not job:
                if getattr(args, "continuous", False):
                    import time

                    time.sleep(getattr(args, "poll_interval", 15))
                    continue
                break
            try:
                score_single_job(
                    job,
                    cv_text,
                    args.cv,
                    args.threshold,
                    args.dynamic_rubric,
                )
            except Exception as score_exc:
                print(
                    f"  [ERROR] Worker thread caught exception for job {job.get('id')}: {score_exc}",
                    flush=True,
                )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(worker_loop) for _ in range(max_workers)]
        concurrent.futures.wait(futures)

    print("\nFlow 2 Evaluation Queue Summary: Completed.")

    # Check if there are passing jobs ready to apply in Flow 3
    try:
        ready_apply_count = 0
        db_conn = get_connection()
        with db_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM job_hunter.jobs WHERE status_score = 'completed' AND status_apply = 'pending';")
            ready_apply_count = cur.fetchone()[0]
        db_conn.close()

        if ready_apply_count > 0:
            print(f"[flow_score] Cascading: Found {ready_apply_count} passing jobs ready for Flow 3. Triggering Flow3_Apply...")
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            subprocess.run(
                ["schtasks", "/run", "/tn", r"\JobHunterKit\Flow3_Apply"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=creationflags,
            )
    except Exception as cascade_err:
        print(f"[flow_score] Warning: Cascade trigger to Flow 3 failed: {cascade_err}")



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Flow 2: Gemini JD Scorer Queue")
    default_cv = get_master_cv_path()
    parser.add_argument(
        "--cv",
        default=default_cv,
        help="Path to base CV file",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=None,
        help="Override pass threshold from rubric",
    )
    parser.add_argument(
        "--dynamic-rubric",
        action="store_true",
        dest="dynamic_rubric",
        default=True,
        help="Generate scoring rubric dynamically tailored to each JD",
    )
    parser.add_argument(
        "--no-dynamic-rubric",
        action="store_false",
        dest="dynamic_rubric",
        default=True,
        help="Disable dynamic rubric",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Explicit worker pool concurrency (default: auto-scaled 2-8)",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Continuously poll database for pending scoring jobs instead of exiting when queue is empty",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=15,
        help="Seconds to wait between polls when queue is empty in continuous mode (default: 15s)",
    )
    parser.add_argument(
        "--log",
        action="store_true",
        help="Enable file logging instead of console output",
    )

    args = parser.parse_args()
    run_scoring(args)
