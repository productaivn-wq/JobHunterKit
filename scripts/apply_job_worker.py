import json
import os
import sys
from pathlib import Path

# Setup paths
PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "scripts"))
sys.path.insert(0, str(PROJECT_DIR))

import pipeline
from pipeline import auto_apply, tailor_cvs

from shared_platform.paths import get_master_cv_path, get_storage_root


def load_applied_history():
    history_file = PROJECT_DIR / "data" / "applied_history.json"
    if not history_file.exists():
        return set(), set(), set()
    try:
        with open(history_file, encoding="utf-8") as f:
            history = json.load(f)
        submitted = set()
        companies = set()
        urls = set()
        for h in history:
            submitted.add(f"{h['title'].strip()} @ {h['company'].strip()}".lower())
            companies.add(h["company"].strip().lower())
            if h.get("url"):
                urls.add(h["url"].split("?")[0].strip().lower())
        return submitted, companies, urls
    except Exception as e:
        print(f"Error loading applied history: {e}")
        return set(), set(), set()


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--start-idx", type=int, default=0)
    parser.add_argument("--end-idx", type=int, default=999999)
    parser.add_argument("--find-next", action="store_true")
    args = parser.parse_args()

    storage_root = Path(get_storage_root())
    campaign_dir = (
        storage_root
        / "campaigns"
        / "linkedin_AI_Product_Manager__Head_of_AI__AI_Director__AI_Transformation_Lead_Vietnam"
        / "2026-06-15"
    )
    jobs_file = campaign_dir / "scraped_jobs.json"
    scores_dir = campaign_dir / "scores"
    cv_file = get_master_cv_path()

    if not jobs_file.exists():
        print(f"Jobs file not found: {jobs_file}")
        sys.exit(1)

    with open(jobs_file, encoding="utf-8") as f:
        jobs = json.load(f)

    already_submitted, already_submitted_companies, already_submitted_urls = (
        load_applied_history()
    )

    # Find the first scored and passed job that hasn't been applied to within range
    target_job = None
    for idx, job in enumerate(jobs):
        if not (args.start_idx <= idx <= args.end_idx):
            continue

        # Check if already applied
        job_key = f"{job['title'].strip()} @ {job['company'].strip()}".lower()
        company_lower = job["company"].strip().lower()
        job_url = job.get("url")
        clean_url = job_url.split("?")[0].strip().lower() if job_url else ""
        if (
            job_key in already_submitted
            or company_lower in already_submitted_companies
            or (clean_url and clean_url in already_submitted_urls)
        ):
            continue

        # Check score
        score_file = (
            scores_dir
            / f"{pipeline.safe_filename(job['company'])}__{job['id']}_score.json"
        )
        if score_file.exists():
            try:
                with open(score_file, encoding="utf-8") as sf:
                    score_data = json.load(sf)
                score = score_data.get("match_score", 0)
                if score >= 70:  # Benchmark pass threshold
                    job["match_score"] = score
                    job["top_strengths"] = score_data.get("top_strengths", [])
                    job["key_gaps"] = score_data.get("key_gaps", [])
                    target_job = job
                    print(
                        f"Selected job at index {idx}: {job['title']} at {job['company']}",
                    )
                    break
            except Exception as e:
                print(f"Error reading score for {job['id']}: {e}")

    if not target_job:
        print("NO_JOBS_READY_TO_APPLY")
        sys.exit(0)

    print(
        f"Found ready job: {target_job['title']} at {target_job['company']} (Score: {target_job['match_score']})",
    )

    # Setup directories for pipeline
    dirs = {
        "proof_dir": str(campaign_dir / "proof"),
        "history_file": str(PROJECT_DIR / "data" / "applied_history.json"),
        "scores_dir": str(scores_dir),
        "tailored_dir": str(campaign_dir / "tailored"),
        "local_scratch": str(PROJECT_DIR / "scratch"),
        "jobs_file": str(jobs_file),
    }

    os.makedirs(dirs["proof_dir"], exist_ok=True)
    os.makedirs(dirs["tailored_dir"], exist_ok=True)
    os.makedirs(dirs["local_scratch"], exist_ok=True)

    # Write temp JD file in scratch
    temp_jd = Path(dirs["local_scratch"]) / f"{target_job['id']}_jd.txt"
    with open(temp_jd, "w", encoding="utf-8") as f:
        f.write(target_job.get("jd_text", ""))

    if args.find_next:
        pdf_path = (
            Path(dirs["tailored_dir"])
            / f"{pipeline.safe_filename(target_job['company'])}__{target_job['id']}.pdf"
        )
        print(f"JOB_ID:{target_job['id']}")
        print(f"COMPANY:{target_job['company']}")
        print(f"JD_FILE:{temp_jd}")
        print(f"PDF_PATH:{pdf_path}")
        sys.exit(0)

    script_dir_path = str(PROJECT_DIR / "scripts")
    state_file = str(PROJECT_DIR / "scripts" / "state.json")

    # Tailor CV
    tailored = tailor_cvs([target_job], cv_file, dirs, script_dir_path, force=False)

    # Apply
    auto_apply(
        [target_job],
        cv_file,
        dirs,
        tailored_cvs=tailored,
        state_file=state_file,
        dry_run=False,
    )

    print("SUCCESS")


if __name__ == "__main__":
    main()
