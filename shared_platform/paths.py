"""
Shared Paths & File-system Platform Layer for JobHunterKit.
Manages run directories, scratch paths, and filenames safely across different flow scripts.
"""

import os
import re
from pathlib import Path


# Root storage directory for scraped files, campaigns, tailored CVs, and reports
def get_project_root() -> Path:
    """Resolves project root directory, defaulting to the repository root."""
    env_root = os.getenv("JOBHUNTER_PROJECT_ROOT")
    if env_root and Path(env_root).exists():
        return Path(env_root)
    return Path(__file__).resolve().parent.parent


def get_storage_root() -> str:
    """Resolves data storage root directory."""
    custom = os.getenv("JOBHUNTER_STORAGE_ROOT")
    if custom and os.path.exists(custom):
        return custom
    p_root = get_project_root()
    data_dir = p_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir)


def get_master_cv_path() -> str:
    """Resolves the Master CV path for tailoring and scoring."""
    custom = os.getenv("JOB_HUNTER_CV_PATH")
    if custom and os.path.exists(custom):
        return custom
    p_root = get_project_root()

    for candidate in (
        p_root / "master_cv.pdf",
        p_root / "cv.pdf",
        p_root / "20_ACTIVE_CONTINUOUS" / "master_cv.pdf",
        p_root / "20_ACTIVE_CONTINUOUS" / "cv.pdf",
        p_root / "20_ACTIVE_CONTINUOUS" / "cv_text.pdf",
        p_root / "master_cv.txt",
        p_root / "cv_text.txt",
        p_root / "20_ACTIVE_CONTINUOUS" / "cv_text.txt",
    ):
        if candidate.exists():
            return str(candidate)

    return str(p_root / "cv_text.txt")


_SKILL_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = get_project_root()
STORAGE_ROOT = get_storage_root()


def get_job_dirs(job: dict) -> dict:
    """
    Resolves and creates the directories required for a specific job application run.
    Uses the job's keyword, location, source, and scraped_at timestamp.
    """
    keyword = job.get("keyword") or "default"
    location = job.get("search_location") or "default"
    source = job.get("source") or "default"

    # Format campaign name
    campaign_name = re.sub(r"[^\w]", "_", f"{source}_{keyword}_{location}")

    # Resolve date string safely
    scraped_at = job.get("scraped_at")
    if isinstance(scraped_at, str):
        import dateutil.parser

        dt = dateutil.parser.parse(scraped_at)
    elif scraped_at is not None:
        dt = scraped_at
    else:
        import datetime

        dt = datetime.datetime.now()
    date_str = dt.strftime("%Y-%m-%d")

    # Layout relative to STORAGE_ROOT
    run_dir = os.path.join(STORAGE_ROOT, "campaigns", campaign_name, date_str)
    tailored_dir = os.path.join(run_dir, "tailored")
    proof_dir = os.path.join(run_dir, "proof")
    scores_dir = os.path.join(run_dir, "scores")

    # Local scratch workspace under the JobHunterKit root
    kit_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    local_scratch = os.path.join(kit_dir, "scratch")

    # Create directories recursively
    for d in [run_dir, tailored_dir, proof_dir, scores_dir, local_scratch]:
        os.makedirs(d, exist_ok=True)

    return {
        "run_dir": run_dir,
        "tailored_dir": tailored_dir,
        "proof_dir": proof_dir,
        "scores_dir": scores_dir,
        "local_scratch": local_scratch,
    }
