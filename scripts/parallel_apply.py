"""
parallel_apply.py — Parallel application runner for JobHunterKit campaigns.

Dispatches job applications in parallel subtask batches while enforcing deduplication.
"""

import glob
import json
import os
import subprocess
import sys
from pathlib import Path

# Setup paths
PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
CAMPAIGNS_DIR = DATA_DIR / "campaigns"
HISTORY_FILE = DATA_DIR / "applied_history.json"
STATE_FILE = PROJECT_DIR / "scripts" / "state.json"
CV_FILE = Path(os.environ.get("JOB_HUNTER_CV_PATH", str(PROJECT_DIR / "cv_text.txt")))
SCRATCH_DIR = PROJECT_DIR / "scratch"


def load_applied_history() -> tuple[set[str], set[str]]:
    """Loads previous application records to prevent duplicate applications."""
    if not HISTORY_FILE.exists():
        return set(), set()
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            history = json.load(f)
        submitted = set()
        companies = set()
        for h in history:
            submitted.add(f"{h['title'].strip()} @ {h['company'].strip()}".lower())
            companies.add(h["company"].strip().lower())
        return submitted, companies
    except Exception as e:
        print(f"Error loading applied history: {e}")
        return set(), set()


def find_latest_campaign_dir() -> Path:
    """Discovers the most recent LinkedIn campaign output directory."""
    # Search for linkedin campaigns folders
    folders = [
        f
        for f in glob.glob(str(CAMPAIGNS_DIR / "*linkedin*"))
        if "Product_Director" in f
    ]
    if not folders:
        raise FileNotFoundError(
            "No LinkedIn campaign folders found containing Product_Director.",
        )
    folders.sort(key=os.path.getmtime)
    latest_folder = Path(folders[-1])

    # Get the latest date subfolder (e.g., 2026-06-10)
    date_folders = glob.glob(str(latest_folder / "2026-*"))
    if not date_folders:
        raise FileNotFoundError(f"No date subfolders found in {latest_folder}")
    date_folders.sort(key=os.path.getmtime)
    return Path(date_folders[-1])


def main() -> None:
    """Main entry point to partition high-scoring candidates into parallel chunks."""
    # Load already applied jobs
    already_submitted, already_submitted_companies = load_applied_history()

    # Find latest campaign directory
    campaign_dir = find_latest_campaign_dir()
    print(f"Using campaign directory: {campaign_dir}")

    scraped_jobs_file = campaign_dir / "scraped_jobs.json"
    if not scraped_jobs_file.exists():
        print(f"Scraped jobs file not found: {scraped_jobs_file}")
        sys.exit(1)

    with open(scraped_jobs_file, encoding="utf-8") as f:
        scraped_jobs = json.load(f)

    # Filter passed jobs (Score >= 90)
    passed_jobs = []
    scores_dir = campaign_dir / "scores"
    for job in scraped_jobs:
        job_id = job.get("id")
        score_file = glob.glob(str(scores_dir / f"*_{job_id}_score.json"))
        if score_file:
            try:
                with open(score_file[0], encoding="utf-8") as sf:
                    score_data = json.load(sf)
                score = score_data.get("match_score", 0)
                if score >= 90:
                    job["match_score"] = score
                    job["top_strengths"] = score_data.get("top_strengths", [])
                    job["key_gaps"] = score_data.get("key_gaps", [])
                    passed_jobs.append(job)
            except Exception as e:
                print(f"Error reading score for job {job_id}: {e}")

    print(f"Total passed jobs with score >= 90: {len(passed_jobs)}")

    # Filter out already applied jobs
    to_apply = []
    for job in passed_jobs:
        job_key = f"{job['title'].strip()} @ {job['company'].strip()}".lower()
        company_lower = job["company"].strip().lower()
        if job_key in already_submitted or company_lower in already_submitted_companies:
            print(
                f"Skipping already submitted/processed job: {job['title']} at {job['company']}",
            )
            continue
        to_apply.append(job)

    print(f"Passed jobs remaining to apply: {len(to_apply)}")
    if not to_apply:
        print("No jobs to apply to.")
        sys.exit(0)

    # Define directories dictionary for pipeline
    tailored_dir = campaign_dir / "tailored"
    dirs = {
        "proof_dir": str(campaign_dir / "proof"),
        "history_file": str(HISTORY_FILE),
        "scores_dir": str(scores_dir),
        "tailored_dir": str(tailored_dir),
        "local_scratch": str(SCRATCH_DIR),
    }

    # Ensure all temp_jd files exist in scratch directory
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    for job in to_apply:
        temp_jd = SCRATCH_DIR / f"{job['id']}_jd.txt"
        if not temp_jd.exists():
            with open(temp_jd, "w", encoding="utf-8") as f:
                f.write(job.get("jd_text", ""))

    # Import and run parallel CV tailoring phase
    sys.path.insert(0, str(PROJECT_DIR / "scripts"))
    from pipeline import tailor_cvs

    print(f"Generating tailored CVs for {len(to_apply)} jobs in parallel...")
    tailored_cvs = tailor_cvs(
        to_apply,
        str(CV_FILE),
        dirs,
        str(PROJECT_DIR / "scripts"),
        force=False,
    )

    # Split to_apply list into 2 chunks for parallel agents
    N = 2
    chunks = [to_apply[i::N] for i in range(N)]

    processes = []

    for idx, chunk in enumerate(chunks):
        if not chunk:
            continue
        chunk_data = {
            "passed_jobs": chunk,
            "cv_file": str(CV_FILE),
            "dirs": dirs,
            "tailored_cvs": tailored_cvs,
            "state_file": str(STATE_FILE),
            "dry_run": False,
        }

        chunk_path = SCRATCH_DIR / f"chunk_{idx}.json"
        with open(chunk_path, "w", encoding="utf-8") as cf:
            json.dump(chunk_data, cf, ensure_ascii=False, indent=2)

        print(f"Launching Agent {idx + 1} in parallel to process {len(chunk)} jobs...")
        log_file = open(SCRATCH_DIR / f"agent_{idx}.log", "w", encoding="utf-8")
        p = subprocess.Popen(
            [
                sys.executable,
                str(PROJECT_DIR / "scripts" / "apply_chunk.py"),
                str(chunk_path),
            ],
            stdout=log_file,
            stderr=log_file,
        )
        processes.append((p, log_file))

    # Wait for all processes to complete
    print("All parallel agents launched. Waiting for completion...")
    for idx, (p, lf) in enumerate(processes):
        p.wait()
        lf.close()
        print(f"Agent {idx + 1} finished.")

    print("Parallel application run completed!")


if __name__ == "__main__":
    main()
