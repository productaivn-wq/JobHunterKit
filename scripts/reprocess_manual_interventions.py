"""
reprocess_manual_interventions.py — Re-runs Flow 3 live applications for jobs marked as needs_manual_intervention.
If a job succeeds -> marked as completed.
If a job still requires manual intervention -> notifies the user via Telegram with job URL & reason.

SAFETY NOTE: This script drives a live browser session and can submit real job
applications. It is NOT wired into any launcher or Scheduled Task by design.
Only run it manually after reviewing the flags below, or after the user has
explicitly approved scheduling it.

Safety controls (all tunable via CLI flags):
  --max-age-days          Only reprocess jobs whose manual-intervention state is
                           recent (default 3 days), based on claimed_at (fallback
                           scraped_at) since the jobs table has no dedicated
                           status-change timestamp column. Stale rows referencing
                           long-dead postings are left alone.
  --limit                 Hard cap on how many jobs are reset/processed in a
                           single run (default 20). The run only ever touches
                           the exact set of job IDs it reset in this invocation —
                           it never falls through to the general 'pending' queue.
  --delay-seconds         Pause between live application attempts (default 30s)
                           to avoid hammering job boards back-to-back.
  --max-consecutive-errors
                           Circuit breaker: abort the run (with one summary
                           Telegram alert) after this many consecutive
                           exceptions instead of burning through the whole
                           batch on a systemic failure (default 3).
  --skip-active-check     Skip the pre-flight check_jd_active.py pass that
                           marks postings which are no longer accepting
                           applications as 'skipped' instead of retrying them.
  --dry-run               Pass dry_run=True down to process_job_application so
                           no live submission actually happens (useful for a
                           safe rehearsal before trusting the batch).

Duplicate-application guard: jobs that already have an 'applied' / 'dry_run' /
'completed' row in job_hunter.applications are excluded from the reset query,
so a job the user already completed manually (or that already succeeded)
won't be silently re-driven through a live application.
"""

import argparse
import sys
import time
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv(project_root / ".env")

from core.db_client import get_connection
from scripts.flow_apply import claim_next_application_job, process_job_application
from shared_platform.notify import send_telegram
from shared_platform.paths import get_job_dirs, get_master_cv_path

DEFAULT_MAX_AGE_DAYS = 3
DEFAULT_LIMIT = 20
DEFAULT_DELAY_SECONDS = 30
DEFAULT_MAX_CONSECUTIVE_ERRORS = 3


def reset_manual_intervention_jobs(
    max_age_days=DEFAULT_MAX_AGE_DAYS, limit=DEFAULT_LIMIT
):
    """
    Reset a bounded, age-filtered batch of 'needs_manual_intervention' jobs to
    'pending', skipping any job that already has a completed/applied/dry_run
    record in job_hunter.applications (duplicate-application guard).

    Only jobs whose manual-intervention state is at most `max_age_days` old
    (measured from claimed_at, falling back to scraped_at when claimed_at is
    NULL) are eligible. At most `limit` jobs are reset per call.

    Returns the list of job IDs that were actually reset, so the caller can
    process exactly that set and nothing else.
    """
    conn = get_connection()
    try:
        from core.company_extractor import is_jd_text_expired

        with conn.cursor() as cur:
            # First fetch candidate rows to verify active posting status & expired signatures
            cur.execute(
                """
                SELECT j.id, j.title, j.company, j.jd_text
                FROM job_hunter.jobs j
                WHERE j.status_apply = 'needs_manual_intervention'
                  AND COALESCE(j.claimed_at, j.scraped_at) >= NOW() - (%s || ' days')::interval
                  AND NOT EXISTS (
                      SELECT 1 FROM job_hunter.applications a
                      WHERE a.job_id = j.id
                        AND a.status IN ('applied', 'dry_run', 'completed')
                  )
                ORDER BY COALESCE(j.claimed_at, j.scraped_at) ASC
                LIMIT %s
                FOR UPDATE SKIP LOCKED;
                """,
                (str(max_age_days), limit),
            )
            candidate_rows = cur.fetchall()

            reset_ids = []
            for j_id, j_title, j_comp, j_jd in candidate_rows:
                is_exp, exp_reason = is_jd_text_expired(j_jd or "", j_title or "")
                if is_exp:
                    print(
                        f"  [REPROCESS SKIP] Job ID {j_id} ({j_comp} - {j_title}) is expired ({exp_reason}). Marking skipped."
                    )
                    cur.execute(
                        "UPDATE job_hunter.jobs SET status_apply = 'skipped', status_score = 'skipped_expired' WHERE id = %s;",
                        (j_id,),
                    )
                else:
                    cur.execute(
                        "UPDATE job_hunter.jobs SET status_apply = 'pending' WHERE id = %s;",
                        (j_id,),
                    )
                    reset_ids.append(j_id)

            conn.commit()

            # Informational only: how many were left behind (too old, or already
            # accounted for by a completed/applied/dry_run application record).
            cur.execute(
                "SELECT COUNT(*) FROM job_hunter.jobs WHERE status_apply = 'needs_manual_intervention';"
            )
            remaining = cur.fetchone()[0]

            print(
                f"[REPROCESS] Reset {len(reset_ids)} job(s) from 'needs_manual_intervention' to 'pending' "
                f"(max_age_days={max_age_days}, limit={limit}). "
                f"{remaining} job(s) remain in 'needs_manual_intervention' "
                f"(too old, already applied/dry-run/completed, or beyond this run's limit)."
            )
            return reset_ids
    finally:
        conn.close()


def _run_active_posting_check(limit):
    """
    Best-effort pre-flight: mark postings that are no longer accepting
    applications as 'skipped' so the reset step doesn't try to re-drive a
    live browser session against a dead listing. Never fatal to the overall
    run — if the check itself fails (e.g. Playwright/browser unavailable),
    log a warning and continue; the age filter and duplicate guard still
    apply regardless.
    """
    try:
        from scripts.check_jd_active import check_jobs_status

        print(
            "[REPROCESS] Running pre-flight posting-liveness check (check_jd_active)..."
        )
        check_jobs_status(limit=limit)
    except Exception as err:
        print(f"[REPROCESS WARNING] Posting-liveness check failed/skipped: {err}")


def run_live_applications(
    max_age_days=DEFAULT_MAX_AGE_DAYS,
    limit=DEFAULT_LIMIT,
    delay_seconds=DEFAULT_DELAY_SECONDS,
    max_consecutive_errors=DEFAULT_MAX_CONSECUTIVE_ERRORS,
    skip_active_check=False,
    dry_run=False,
):
    if not skip_active_check:
        _run_active_posting_check(limit)

    reset_ids = reset_manual_intervention_jobs(max_age_days=max_age_days, limit=limit)
    if not reset_ids:
        print("[REPROCESS] No jobs requiring reprocessing.")
        return

    state_file = project_root / "scripts" / "state.json"
    cv_file = get_master_cv_path()

    print(
        f"=== Starting Live Applications for {len(reset_ids)} Job(s) (dry_run={dry_run}) ==="
    )

    success_count = 0
    manual_count = 0
    consecutive_errors = 0
    aborted = False

    for idx, job_id in enumerate(reset_ids):
        # Rate limit: pause between attempts (not before the very first one).
        if idx > 0:
            time.sleep(delay_seconds)

        # Only ever claim the specific job we reset in this run — never fall
        # through to whatever else happens to be sitting in the general
        # 'pending' queue.
        job = claim_next_application_job(job_id=job_id)
        if not job:
            print(
                f"[REPROCESS] Job ID {job_id} could not be claimed (already claimed elsewhere?). Skipping."
            )
            continue

        print(
            f"\n[REPROCESS] Attempting Job ID {job['id']}: {job['title']} at {job['company']}"
        )
        try:
            process_job_application(job, str(cv_file), str(state_file), dry_run=dry_run)

            # Check resulting status in DB
            conn = get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT status_apply, manual_intervention_reason FROM job_hunter.jobs WHERE id = %s;",
                        (job["id"],),
                    )
                    row = cur.fetchone()
                    status_apply, reason = row[0], row[1]
            finally:
                conn.close()

            if status_apply == "completed":
                success_count += 1
                consecutive_errors = 0
                print(f"[REPROCESS SUCCESS] Job ID {job['id']} applied successfully!")
            elif status_apply == "needs_manual_intervention":
                manual_count += 1
                consecutive_errors = 0
                print(
                    f"[REPROCESS MANUAL NEEDED] Job ID {job['id']} requires user intervention: {reason}"
                )

                # Resolve the actual tailored PDF from the campaign's tailored_dir.
                # The DB tailored_cv_path may hold the base CV fallback path.
                import os

                tailored_cv_path = None
                pdf_path = None
                try:
                    dirs = get_job_dirs(job)
                    t_dir = dirs.get("tailored_dir")
                    if t_dir and os.path.exists(t_dir):
                        pdfs = [
                            os.path.join(t_dir, f)
                            for f in os.listdir(t_dir)
                            if f.endswith(f"_{job['id']}.pdf")
                            or f.endswith(f"__{job['id']}.pdf")
                        ]
                        if pdfs:
                            pdf_path = pdfs[0]
                except Exception:
                    pass
                # Fall back to DB tailored_cv_path only if no file-system PDF found
                if not pdf_path:
                    try:
                        conn_cv = get_connection()
                        with conn_cv.cursor() as cur_cv:
                            cur_cv.execute(
                                "SELECT tailored_cv_path FROM job_hunter.applications WHERE job_id = %s ORDER BY id DESC LIMIT 1;",
                                (job["id"],),
                            )
                            app_row = cur_cv.fetchone()
                            if app_row:
                                tailored_cv_path = app_row[0]
                        conn_cv.close()
                    except Exception:
                        pass
                    if (
                        tailored_cv_path
                        and str(tailored_cv_path).endswith(".pdf")
                        and os.path.exists(tailored_cv_path)
                    ):
                        pdf_path = tailored_cv_path

                # Enqueue to manual_application_queue for 30-minute batched digest
                try:
                    from core.screenshot_apply_analyzer import find_job_screenshot

                    screenshot_file = job.get("proof_path") or find_job_screenshot(
                        job, dirs
                    )
                    conn_eq = get_connection()
                    with conn_eq.cursor() as cur_eq:
                        cur_eq.execute(
                            """
                            INSERT INTO job_hunter.manual_application_queue (job_id, status, screenshot_path, instructions, queued_at)
                            VALUES (%s, 'pending_batch', %s, %s, NOW())
                            ON CONFLICT (job_id) DO UPDATE
                            SET status = 'pending_batch',
                                screenshot_path = COALESCE(EXCLUDED.screenshot_path, job_hunter.manual_application_queue.screenshot_path),
                                instructions = COALESCE(EXCLUDED.instructions, job_hunter.manual_application_queue.instructions),
                                queued_at = NOW();
                            """,
                            (
                                job["id"],
                                screenshot_file,
                                reason or "Manual intervention required",
                            ),
                        )
                        conn_eq.commit()
                    conn_eq.close()
                except Exception as eq_err:
                    print(
                        f"[WARNING] Failed to enqueue manual job {job['id']}: {eq_err}"
                    )
            else:
                # skipped / failed_manual / other terminal states: not a repeat
                # failure of the same kind, so don't trip the circuit breaker.
                consecutive_errors = 0

        except Exception as err:
            print(
                f"[REPROCESS ERROR] Exception while applying for Job ID {job['id']}: {err}"
            )
            manual_count += 1
            consecutive_errors += 1

            # Resolve the actual tailored PDF from the campaign's tailored_dir.
            import os

            pdf_path = None
            tailored_cv_path = None
            try:
                dirs = get_job_dirs(job)
                t_dir = dirs.get("tailored_dir")
                if t_dir and os.path.exists(t_dir):
                    pdfs = [
                        os.path.join(t_dir, f)
                        for f in os.listdir(t_dir)
                        if f.endswith(f"_{job['id']}.pdf")
                        or f.endswith(f"__{job['id']}.pdf")
                    ]
                    if pdfs:
                        pdf_path = pdfs[0]
            except Exception:
                pass
            # Fall back to DB tailored_cv_path only if no file-system PDF found
            if not pdf_path:
                try:
                    conn_cv = get_connection()
                    with conn_cv.cursor() as cur_cv:
                        cur_cv.execute(
                            "SELECT tailored_cv_path FROM job_hunter.applications WHERE job_id = %s ORDER BY id DESC LIMIT 1;",
                            (job["id"],),
                        )
                        app_row = cur_cv.fetchone()
                        if app_row:
                            tailored_cv_path = app_row[0]
                    conn_cv.close()
                except Exception:
                    pass
            # Enqueue to manual_application_queue for 30-minute batched digest
            try:
                from core.screenshot_apply_analyzer import find_job_screenshot

                screenshot_file = job.get("proof_path") or find_job_screenshot(
                    job, dirs
                )
                conn_eq = get_connection()
                with conn_eq.cursor() as cur_eq:
                    cur_eq.execute(
                        """
                        INSERT INTO job_hunter.manual_application_queue (job_id, status, screenshot_path, instructions, queued_at)
                        VALUES (%s, 'pending_batch', %s, %s, NOW())
                        ON CONFLICT (job_id) DO UPDATE
                        SET status = 'pending_batch',
                            screenshot_path = COALESCE(EXCLUDED.screenshot_path, job_hunter.manual_application_queue.screenshot_path),
                            instructions = COALESCE(EXCLUDED.instructions, job_hunter.manual_application_queue.instructions),
                            queued_at = NOW();
                        """,
                        (job["id"], screenshot_file, f"Reprocess Exception: {err}"),
                    )
                    conn_eq.commit()
                conn_eq.close()
            except Exception as eq_err:
                print(f"[WARNING] Failed to enqueue manual job {job['id']}: {eq_err}")

            if consecutive_errors >= max_consecutive_errors:
                aborted = True
                remaining = len(reset_ids) - (idx + 1)
                print(
                    f"[REPROCESS CIRCUIT BREAKER] {consecutive_errors} consecutive errors reached "
                    f"(limit={max_consecutive_errors}). Aborting run with {remaining} job(s) left unprocessed."
                )
                send_telegram(
                    "🛑 <b>JobHunterKit — Reprocess Aborted (Circuit Breaker)</b>\n\n"
                    f"{consecutive_errors} consecutive failures while reprocessing manual-intervention jobs. "
                    f"Stopped after {idx + 1}/{len(reset_ids)} job(s) to avoid burning through the rest of the "
                    f"batch on what looks like a systemic failure. {remaining} job(s) left in 'pending' — check "
                    f"logs (bad CV path, expired session cookies in state.json, site UI change, etc.) before "
                    f"re-running."
                )
                break

    status_line = "ABORTED (circuit breaker)" if aborted else "Completed"
    print(
        f"\n=== Summary [{status_line}]: {success_count} Applied Automatically | "
        f"{manual_count} Queued for 30-min Manual Batch Digest ==="
    )

    # Trigger consolidated manual batch digest if manual jobs were queued
    if manual_count > 0 and not dry_run:
        try:
            from scripts.batch_manual_jobs_reporter import process_manual_batch

            print(
                "\n[BATCH REPORTER] Triggering consolidated manual application digest..."
            )
            process_manual_batch(window_minutes=30)
        except Exception as batch_err:
            print(f"[WARNING] Batch reporter execution failed: {batch_err}")


def _parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Reprocess jobs stuck in 'needs_manual_intervention' with bounded, "
            "rate-limited, age-filtered live re-applications. Not wired into any "
            "scheduler by design — run manually only."
        )
    )
    parser.add_argument(
        "--max-age-days",
        type=float,
        default=DEFAULT_MAX_AGE_DAYS,
        help=f"Only reprocess jobs whose manual-intervention state is at most this many days old (default {DEFAULT_MAX_AGE_DAYS}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximum number of jobs to reset/process in this run (default {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help=f"Delay in seconds between live application attempts (default {DEFAULT_DELAY_SECONDS}).",
    )
    parser.add_argument(
        "--max-consecutive-errors",
        type=int,
        default=DEFAULT_MAX_CONSECUTIVE_ERRORS,
        help=f"Abort the run after this many consecutive exceptions (default {DEFAULT_MAX_CONSECUTIVE_ERRORS}).",
    )
    parser.add_argument(
        "--skip-active-check",
        action="store_true",
        help="Skip the pre-flight check_jd_active.py posting-liveness pass.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run process_job_application in dry-run mode (no live submission).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if args.max_age_days <= 0:
        print("[REPROCESS] --max-age-days must be positive.")
        sys.exit(1)
    if args.limit <= 0:
        print("[REPROCESS] --limit must be positive.")
        sys.exit(1)

    run_live_applications(
        max_age_days=args.max_age_days,
        limit=args.limit,
        delay_seconds=args.delay_seconds,
        max_consecutive_errors=args.max_consecutive_errors,
        skip_active_check=args.skip_active_check,
        dry_run=args.dry_run,
    )
