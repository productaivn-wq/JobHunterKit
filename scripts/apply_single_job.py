"""
Standalone single-job applicant runner for JobHunterKit.
Allows applying directly to a specific job ID (e.g. 124439 for 9PAY on TopCV)
with optional headed browser mode for live debugging and verification.
"""

import argparse
import os
import sys
from pathlib import Path

# Setup paths
PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "scripts"))
sys.path.insert(0, str(PROJECT_DIR))

from pipeline import auto_apply, tailor_cvs

from core.db_client import get_connection
from shared_platform.paths import STORAGE_ROOT, get_master_cv_path


def load_job_from_db(job_id: int | str) -> dict | None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, job_key, title, company, location, url, source, jd_text, keyword, search_location
                FROM job_hunter.jobs
                WHERE id = %s;
                """,
                (int(job_id),),
            )
            row = cur.fetchone()
            if not row:
                return None
            desc = [d[0] for d in cur.description]
            return dict(zip(desc, row))
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Run JobHunterKit application for a single job ID"
    )
    parser.add_argument("--job-id", type=int, required=True, help="Job ID to apply to")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute in dry-run mode (stages application without clicking submit)",
    )
    parser.add_argument(
        "--headed", action="store_true", help="Launch browser in headed visible mode"
    )
    parser.add_argument(
        "--force-tailor", action="store_true", help="Force regenerate tailored CV PDF"
    )
    args = parser.parse_args()

    print("=== JobHunterKit Single Job Application Runner ===")
    print(f"Job ID: {args.job_id}")
    print(f"Dry Run: {args.dry_run}")
    print(f"Headed Mode: {args.headed}")

    job = load_job_from_db(args.job_id)
    if not job:
        print(f"[ERROR] Job ID {args.job_id} not found in database.")
        sys.exit(1)

    print(
        f"Found Job: '{job['title']}' at '{job['company']}' (Source: {job['source']})"
    )
    print(f"URL: {job['url']}")

    # Setup directories
    campaign_name = f"{job['source']}_{job.get('keyword') or 'default'}_{job.get('search_location') or 'default'}"
    from datetime import datetime

    today_str = datetime.now().strftime("%Y-%m-%d")
    run_dir = Path(STORAGE_ROOT) / "campaigns" / campaign_name / today_str

    dirs = {
        "run_dir": str(run_dir),
        "proof_dir": str(run_dir / "proof"),
        "tailored_dir": str(run_dir / "tailored"),
        "scores_dir": str(run_dir / "scores"),
        "local_scratch": str(PROJECT_DIR / "scratch"),
        "jobs_file": str(run_dir / "scraped_jobs.json"),
        "history_file": str(Path(STORAGE_ROOT) / "applied_history.json"),
    }

    os.makedirs(dirs["proof_dir"], exist_ok=True)
    os.makedirs(dirs["tailored_dir"], exist_ok=True)
    os.makedirs(dirs["local_scratch"], exist_ok=True)

    # Master CV
    cv_file = get_master_cv_path()
    if not os.path.exists(cv_file):
        alt_cv = Path(STORAGE_ROOT).parent / "20_ACTIVE_CONTINUOUS" / "cv_text.txt"
        if alt_cv.exists():
            cv_file = str(alt_cv)

    print(f"Using Master CV: {cv_file}")

    # Tailor CV
    script_dir_path = str(PROJECT_DIR / "scripts")
    state_file = str(PROJECT_DIR / "scripts" / "state.json")
    if not os.path.exists(state_file):
        state_file = None

    print("\n--- Step 1: Tailoring CV ---")
    tailored = tailor_cvs(
        [job], cv_file, dirs, script_dir_path, force=args.force_tailor
    )
    tailored_pdf = tailored.get(job["id"])
    print(f"Tailored CV PDF: {tailored_pdf}")

    # Set Headless environment variable if headed requested
    if args.headed:
        os.environ["JOBHUNTER_HEADLESS"] = "0"

    print("\n--- Step 2: Executing Application Flow ---")
    auto_apply(
        [job],
        cv_file,
        dirs,
        tailored_cvs=tailored,
        state_file=state_file,
        dry_run=args.dry_run,
    )

    status = job.get("apply_status", "Unknown")
    reason = job.get("manual_intervention_reason")
    proof = job.get("proof_path")

    print("\n=== Application Run Results ===")
    print(f"Apply Status: {status}")
    if reason:
        print(f"Reason: {reason}")
    if proof:
        print(f"Proof Screenshot: {proof}")


if __name__ == "__main__":
    main()
