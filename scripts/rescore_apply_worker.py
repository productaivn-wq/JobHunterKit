"""Unified rescore-and-apply worker.
Re-scores each job with a dynamic rubric, and if >= 70, proceeds to tailor & apply.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "scripts"))
sys.path.insert(0, str(PROJECT_DIR))

import pipeline
import score_jd

from shared_platform.paths import get_master_cv_path, get_storage_root

STORAGE_ROOT = Path(get_storage_root())
CAMPAIGN_DIR = (
    STORAGE_ROOT
    / "campaigns"
    / "linkedin_AI_Product_Manager__Head_of_AI__AI_Director__AI_Transformation_Lead_Vietnam"
    / "2026-06-15"
)
JOBS_FILE = CAMPAIGN_DIR / "scraped_jobs.json"
SCORES_DIR = CAMPAIGN_DIR / "scores"
TAILORED_DIR = CAMPAIGN_DIR / "tailored"
PROOF_DIR = CAMPAIGN_DIR / "proof"
CV_FILE = get_master_cv_path()
HISTORY_FILE = STORAGE_ROOT / "applied_history.json"
LOCAL_SCRATCH = PROJECT_DIR / "scratch"


def load_applied_urls():
    """Returns a set of already-applied URLs."""
    if not HISTORY_FILE.exists():
        return set()
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            history = json.load(f)
        urls = set()
        for h in history:
            if h.get("url"):
                urls.add(h["url"].split("?")[0].strip().lower())
        return urls
    except Exception as e:
        print(f"Error loading applied history: {e}")
        return set()


def is_already_scored(score_file):
    """Returns (is_scored, score_value)."""
    if os.path.exists(score_file):
        try:
            with open(score_file, encoding="utf-8") as sf:
                data = json.load(sf)
                ms = data.get("match_score", 0)
                if ms > 0:
                    return True, ms
        except:
            pass
    return False, 0


def score_job(job, cv_text, score_file, temp_jd):
    """Scores a single job using dynamic rubric. Returns (score, rubric_data, result)."""
    # Write JD temp file
    with open(temp_jd, "w", encoding="utf-8") as f:
        f.write(job.get("jd_text", ""))

    # Generate dynamic rubric
    rubric_data = score_jd._handle_dynamic_rubric(
        job["jd_text"], score_file, job.get("title")
    )
    if rubric_data is None:
        print("  WARNING: Dynamic rubric failed, using static fallback", flush=True)
        rubric_data = score_jd.load_rubric()

    result = score_jd.score_job_description(
        job["jd_text"],
        cv_text,
        rubric_data,
        score_file,
    )
    score_jd._save_score_audit(
        score_file,
        rubric_data,
        70,
        result,
        str(temp_jd),
        CV_FILE,
    )
    return result.get("match_score", 0), rubric_data, result


def apply_to_job(job, cv_text):
    """Tailors CV and applies to a job via Playwright."""
    dirs = {
        "proof_dir": str(PROOF_DIR),
        "history_file": str(HISTORY_FILE),
        "scores_dir": str(SCORES_DIR),
        "tailored_dir": str(TAILORED_DIR),
        "local_scratch": str(LOCAL_SCRATCH),
        "jobs_file": str(JOBS_FILE),
    }
    os.makedirs(dirs["proof_dir"], exist_ok=True)
    os.makedirs(dirs["tailored_dir"], exist_ok=True)
    os.makedirs(dirs["local_scratch"], exist_ok=True)

    script_dir_path = str(PROJECT_DIR / "scripts")
    state_file = str(PROJECT_DIR / "scripts" / "state.json")

    # Tailor CV
    tailored = pipeline.tailor_cvs([job], CV_FILE, dirs, script_dir_path, force=False)

    # Apply
    pipeline.auto_apply(
        [job],
        CV_FILE,
        dirs,
        tailored_cvs=tailored,
        state_file=state_file,
        dry_run=False,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-idx", type=int, required=True)
    parser.add_argument("--end-idx", type=int, required=True)
    parser.add_argument(
        "--score-only",
        action="store_true",
        help="Only re-score, don't apply",
    )
    args = parser.parse_args()

    os.makedirs(SCORES_DIR, exist_ok=True)
    os.makedirs(LOCAL_SCRATCH, exist_ok=True)

    with open(JOBS_FILE, encoding="utf-8") as f:
        jobs = json.load(f)

    with open(CV_FILE, encoding="utf-8") as f:
        cv_text = f.read()

    applied_urls = load_applied_urls()

    sliced_jobs = jobs[args.start_idx : args.end_idx + 1]
    print(
        f"Processing {len(sliced_jobs)} jobs (indices {args.start_idx} to {args.end_idx})",
        flush=True,
    )

    scored_count = 0
    applied_count = 0
    skipped_count = 0

    for i, job in enumerate(sliced_jobs):
        idx = args.start_idx + i
        job_id = job.get("id", f"job_{idx}")
        title = job.get("title", "Unknown")
        company = job.get("company", "Unknown")

        score_file = str(
            SCORES_DIR / f"{pipeline.safe_filename(company)}__{job_id}_score.json",
        )
        temp_jd = LOCAL_SCRATCH / f"{job_id}_jd.txt"

        # Check if already scored with dynamic rubric
        already_scored, existing_score = is_already_scored(score_file)
        if already_scored:
            score = existing_score
            print(f"[{idx}] Already scored: {score} | {company} | {title}", flush=True)
        else:
            # Score with dynamic rubric
            print(f"[{idx}] Scoring: {company} | {title}...", flush=True)
            try:
                score, _, _ = score_job(job, cv_text, score_file, temp_jd)
                scored_count += 1
                print(f"[{idx}] Score: {score} | {company} | {title}", flush=True)
            except Exception as e:
                print(f"[{idx}] SCORING FAILED: {e} | {company} | {title}", flush=True)
                continue

        if args.score_only:
            continue

        # Check if eligible to apply
        if score < 70:
            print(f"[{idx}] SKIP (score {score} < 70): {company} | {title}", flush=True)
            skipped_count += 1
            continue

        # Check if already applied
        job_url = job.get("url", "")
        clean_url = job_url.split("?")[0].strip().lower() if job_url else ""
        if clean_url and clean_url in applied_urls:
            print(f"[{idx}] SKIP (already applied): {company} | {title}", flush=True)
            skipped_count += 1
            continue

        # Apply
        print(f"[{idx}] APPLYING: {company} | {title} (score={score})...", flush=True)
        try:
            apply_to_job(job, cv_text)
            applied_count += 1
            applied_urls.add(clean_url)
            print(f"[{idx}] APPLIED: {company} | {title}", flush=True)
        except Exception as e:
            print(f"[{idx}] APPLICATION FAILED: {e} | {company} | {title}", flush=True)

        time.sleep(2)

    print("\n=== WORKER COMPLETE ===", flush=True)
    print(f"Scored: {scored_count}", flush=True)
    print(f"Applied: {applied_count}", flush=True)
    print(f"Skipped: {skipped_count}", flush=True)


if __name__ == "__main__":
    main()
