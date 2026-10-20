"""
Flow 3: Auto-apply and tailored CV builder queue.
"""

import argparse
import concurrent.futures
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "scripts"))

import pipeline

from core.db_client import get_connection
from shared_platform.db import claim_next_job, with_db_transaction
from shared_platform.logging_setup import flow_entrypoint
from shared_platform.paths import STORAGE_ROOT
from shared_platform.paths import get_job_dirs as _get_job_dirs


def get_job_dirs(job):
    dirs = _get_job_dirs(job)
    dirs.update(
        {
            "history_file": os.path.join(STORAGE_ROOT, "applied_history.json"),
            "master_report": os.path.join(STORAGE_ROOT, "master_report.md"),
            "report_file": os.path.join(dirs["run_dir"], "report.md"),
            "jobs_file": os.path.join(dirs["run_dir"], "scraped_jobs.json"),
            "keyword": job.get("keyword") or "default",
            "location": job.get("search_location") or "default",
        }
    )
    return dirs


def process_job_application(job, cv_file, state_file, dry_run):
    print(f"\n=== [Applying] {job['title']} at {job['company']} (ID: {job['id']}) ===")

    dirs = get_job_dirs(job)
    script_dir_path = os.path.dirname(os.path.abspath(__file__))

    # Write temp JD file in scratch
    temp_jd = Path(dirs["local_scratch"]) / f"{job['id']}_jd.txt"
    with open(temp_jd, "w", encoding="utf-8") as f:
        f.write(job.get("jd_text", ""))

    tailored = {}
    error_msg = None
    app_status = "Failed"

    try:
        # 1. Tailor CV
        print("Step 1: Generating tailored CV...")
        tailored = pipeline.tailor_cvs(
            [job], cv_file, dirs, script_dir_path, force=False
        )
        tailored_cv_path = tailored.get(job["id"])

        if not tailored_cv_path or not os.path.exists(tailored_cv_path):
            print(
                f"[WARNING] Tailored CV generation failed for job ID {job['id']}. Falling back to Base CV: {cv_file}"
            )
            tailored_cv_path = cv_file
            tailored[job["id"]] = cv_file

        # 2. Auto Apply
        print("Step 2: Launching Playwright browser to apply...")
        pipeline.auto_apply(
            [job],
            cv_file,
            dirs,
            tailored_cvs=tailored,
            state_file=state_file,
            dry_run=dry_run,
        )

        # Read final apply status
        status_text = job.get("apply_status", "Failed")
        if "Submitted" in status_text or "Success" in status_text:
            app_status = "applied"
        elif "Already Applied" in status_text or "Already" in status_text:
            app_status = "already_applied"
        elif "Expired" in status_text or "Closed" in status_text or "No Longer Accepting" in status_text:
            app_status = "expired"
        elif "Dry Run" in status_text:
            app_status = "dry_run"
        elif "Skipped" in status_text:
            app_status = "skipped"
        elif (
            "Manual Required" in status_text
            or "Intervention Required" in status_text
            or "Manual" in status_text
        ):
            app_status = "needs_manual_intervention"
            error_msg = f"Application status returned: {status_text}"
        else:
            app_status = "failed"
            error_msg = f"Application status returned: {status_text}"

        # Step 3: Mandatory Universal Final Review Node via LLM-as-a-Judge (Prompt SSOT)
        print("Step 3: Executing Mandatory Universal Proof Review Node via LLM-as-a-Judge...")
        from shared_platform.llm_judge import evaluate_application_proof
        target_proof = job.get("proof_path")
        if not target_proof or not os.path.exists(target_proof):
            proof_dir = dirs.get("proof_dir")
            if proof_dir and os.path.exists(proof_dir):
                candidates = []
                for f in os.listdir(proof_dir):
                    if f.endswith(f"_{job['id']}.png") or f.endswith(f"__{job['id']}.png") or f == f"proof_submitted_{job['id']}.png":
                        candidates.append(os.path.join(proof_dir, f))
                error_keywords = ["no_modal", "stuck", "bug", "error", "failed", "timeout", "captcha", "unconfirmed"]
                candidates.sort(key=lambda p: (
                    any(err in os.path.basename(p).lower() for err in error_keywords),
                    -os.path.getmtime(p)
                ))
                if candidates:
                    target_proof = candidates[0]

        verdict = evaluate_application_proof(job, proof_path=target_proof)
        is_valid = verdict.get("is_valid_submission", False)
        eai_score = verdict.get("eai_score", 0.0)
        detected_status = verdict.get("detected_status", "needs_manual_intervention")
        reasoning = verdict.get("reasoning", "LLM Judge Evaluation")

        if dry_run:
            if detected_status == "staged_unsubmitted" or (target_proof and "external_dryrun_" in target_proof):
                app_status = "dry_run"
                print(f"  [DRY RUN PASSED] Staged form verified: {reasoning}")
            else:
                app_status = "needs_manual_intervention"
                error_msg = f"Dry-run proof rejected: {reasoning}"
                job["manual_intervention_reason"] = error_msg
                print(f"  [DRY RUN REJECT] Proof rejected for dry-run: {reasoning}")
        else:
            if detected_status == "already_applied":
                app_status = "already_applied"
                error_msg = f"Job already applied in prior session: {reasoning}"
                job["manual_intervention_reason"] = None
                print(f"  [ALREADY APPLIED DETECTED] Job {job['id']}: {reasoning}")
            elif detected_status == "expired":
                app_status = "expired"
                error_msg = f"Job posting closed/expired: {reasoning}"
                job["manual_intervention_reason"] = None
                print(f"  [EXPIRED JOB DETECTED] Job {job['id']}: {reasoning}")
            elif not is_valid or eai_score < 0.98 or detected_status != "applied":
                print(f"[FINAL REVIEW REJECT] Application proof rejected for Job {job['id']}: {reasoning}")
                app_status = "needs_manual_intervention"
                error_msg = f"Final Review Gatekeeper Rejected: {reasoning}"
                job["manual_intervention_reason"] = error_msg
            else:
                app_status = "applied"
                print(f"[FINAL REVIEW PASSED] Submission proof verified (EAI: {eai_score}, Conf: {verdict.get('confidence')})")

    except Exception as e:
        print(f"[ERROR] Application workflow failed for {job['company']}: {e}")
        error_msg = f"{e}\n{traceback.format_exc()}"
        app_status = "failed"

    # Write application record and update job status in DB
    tailored_path = tailored.get(job["id"]) if tailored else None
    try:
        save_application_results(
            job["id"],
            app_status,
            tailored_path,
            error_msg,
            manual_intervention_reason=job.get("manual_intervention_reason"),
        )
    except Exception as db_err:
        print(f"[ERROR] Failed to save application results: {db_err}")


@with_db_transaction
def save_application_results(
    job_id,
    app_status,
    tailored_path,
    error_msg,
    manual_intervention_reason=None,
    conn=None,
):
    with conn.cursor() as cur:
        # 1. Insert into applications
        cur.execute(
            "INSERT INTO job_hunter.applications (job_id, status, tailored_cv_path, error_message, manual_intervention_reason) "
            "VALUES (%s, %s, %s, %s, %s);",
            (job_id, app_status, tailored_path, error_msg, manual_intervention_reason),
        )

        # 2. Update job status with attempt-based routing and strict state isolation
        cur.execute("SELECT COALESCE(apply_attempts, 0) FROM job_hunter.jobs WHERE id = %s;", (job_id,))
        row = cur.fetchone()
        current_attempts = (row[0] if row else 0) + 1

        if app_status == "applied":
            job_status = "applied"
        elif app_status == "already_applied":
            job_status = "already_applied"
        elif app_status == "expired":
            job_status = "expired"
        elif app_status == "dry_run":
            job_status = "dry_run_verified"
        elif app_status == "skipped":
            job_status = "skipped"
        elif current_attempts >= 2:
            # Route to Autonomous Batch Analysis & Self-Healing Pipeline
            job_status = "quarantined_batch_analysis"
        else:
            job_status = (
                "needs_manual_intervention"
                if app_status == "needs_manual_intervention"
                else "failed_manual"
            )


        cur.execute(
            "UPDATE job_hunter.jobs SET status_apply = %s, manual_intervention_reason = %s, apply_attempts = %s WHERE id = %s;",
            (job_status, manual_intervention_reason, current_attempts, job_id),
        )
        print(
            f"[DB Update] Completed. Job ID {job_id} (attempt #{current_attempts}) status_apply set to '{job_status}'."
        )


def claim_next_application_job(job_id=None):
    """
    Atomically checks out a single pending application job, marks it as 'applying'
    using SELECT ... FOR UPDATE SKIP LOCKED.
    Prioritizes 100% automatable direct channels (Easy Apply, VietnamWorks, TopCV, ITviec, WWR, Glints)
    ahead of external LinkedIn redirect links.
    """
    order_by = (
        "CASE "
        "WHEN source = 'linkedin-easy-apply' THEN 1 "
        "WHEN source = 'vietnamworks' THEN 2 "
        "WHEN source = 'topcv' THEN 3 "
        "WHEN source = 'itviec' THEN 4 "
        "WHEN source = 'glints' THEN 5 "
        "WHEN source = 'weworkremotely' THEN 6 "
        "WHEN source = 'jobright_gmail' THEN 7 "
        "ELSE 8 END, scraped_at DESC"
    )
    return claim_next_job(
        status_column="status_apply",
        pending_value="pending",
        active_value="applying",
        extra_where_clause="status_score = 'completed'",
        order_by_clause=order_by,
        job_id=job_id,
    )


@flow_entrypoint("flow3")
def run_apply(args):
    print("=== Flow 3: Running Application Queue (SELECT FOR UPDATE SKIP LOCKED) ===")

    script_dir_path = os.path.dirname(os.path.abspath(__file__))
    state_file = os.path.join(script_dir_path, "state.json")

    # Worker pool configuration
    user_workers = getattr(args, "workers", None)
    if user_workers:
        max_workers = max(1, min(int(user_workers), 8))
        print(f"Applying with user-configured concurrency: {max_workers} workers")
    else:
        # Dynamic concurrency based on ready-to-apply queue depth
        pending_count = 0
        try:
            db_conn = get_connection()
            with db_conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM job_hunter.jobs WHERE status_score = 'completed' AND status_apply = 'pending';")
                pending_count = cur.fetchone()[0]
            db_conn.close()
        except Exception:
            pending_count = 0

        if pending_count >= 50:
            max_workers = 3
        elif pending_count >= 10:
            max_workers = 2
        else:
            max_workers = 1

        print(f"Auto-scaled apply workers: {max_workers} (Ready queue depth: {pending_count})")

    # Pre-flight LLM Provider Health Probe (Fast-fail before claiming jobs)
    print("--- [PRE-FLIGHT HEALTH CHECK: LLM PROVIDER] ---")
    try:
        from shared_platform.llm_client import GeminiClient
        probe_client = GeminiClient()
        probe_res = probe_client.call("respond with the word OK only", timeout=15.0)
        print(f"  • LLM Provider Auth: 🟢 Online ({probe_res.strip()[:20]})")
    except Exception as llm_err:
        print(f"  • LLM Provider Auth: 🔴 FAILED ({llm_err})")
        print("[PRE-FLIGHT HALT] LLM Provider is unauthenticated or timed out. Halting Flow 3 to prevent browser popup loops.")
        return

    def worker_loop():
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

        from shared_platform.pipeline_state import is_paused

        while True:
            if is_paused():
                print("Pipeline is paused. Exiting Flow 3 worker loop.", flush=True)
                break
            job = claim_next_application_job()
            if not job:
                if getattr(args, "continuous", False):
                    import time

                    print(
                        f"No pending applications in queue. Waiting {getattr(args, 'poll_interval', 30)}s in continuous mode...",
                        flush=True,
                    )
                    time.sleep(getattr(args, "poll_interval", 30))
                    continue
                print("No pending applications found in queue. Exiting Flow 3 worker.")
                break

            print(
                f"Acquired lock on job: {job['title']} at {job['company']} (ID: {job['id']} | Source: {job.get('source')})"
            )

            try:
                process_job_application(job, args.cv, state_file, args.dry_run)
            except Exception as e:
                print(
                    f"[ERROR] Application failed for job {job['id']} ({job['company']}): {e}"
                )
                try:
                    db_conn = get_connection()
                    try:
                        with db_conn.cursor() as cur:
                            cur.execute(
                                "UPDATE job_hunter.jobs SET status_apply = 'failed_manual', apply_attempts = COALESCE(apply_attempts, 0) + 1 WHERE id = %s;",
                                (job["id"],),
                            )
                            db_conn.commit()
                    except Exception as inner_db_err:
                        db_conn.rollback()
                        print(
                            f"[ERROR] Failed to rollback/reset status_apply for job {job['id']}: {inner_db_err}"
                        )
                    finally:
                        db_conn.close()
                except Exception as conn_err:
                    print(
                        f"[CRITICAL ERROR] Failed to connect database to reset job status: {conn_err}"
                    )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(worker_loop) for _ in range(max_workers)]
        concurrent.futures.wait(futures)

    print("\nFlow 3 Application Queue Summary: Completed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Flow 3: Playwright Auto-Apply Queue")
    from shared_platform.paths import get_master_cv_path

    parser.add_argument(
        "--cv",
        default=get_master_cv_path(),
        help="Path to base CV file",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Run without final submission"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Explicit worker pool concurrency (default: auto-scaled 1-3)",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Continuously poll database for pending jobs instead of exiting when queue is empty",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=30,
        help="Seconds to wait between polls when queue is empty in continuous mode (default: 30s)",
    )
    parser.add_argument(
        "--log",
        action="store_true",
        help="Enable file logging instead of console output",
    )

    args = parser.parse_args()
    run_apply(args)
