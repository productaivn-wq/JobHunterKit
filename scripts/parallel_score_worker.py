"""
parallel_score_worker.py — Partitioned worker process for parallel job candidate scoring.

Processes a designated slice of candidate jobs against candidate CV using dynamic LLM rubrics.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Add scripts directory and workspace root to path
SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
sys.path.insert(0, str(SKILL_ROOT))

import pipeline
import score_jd

from shared_platform.paths import get_master_cv_path, get_storage_root


def main() -> None:
    """CLI worker entry point executing rubric evaluation across a job index range."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-index", type=int, required=True)
    parser.add_argument("--end-index", type=int, required=True)
    args = parser.parse_args()

    storage_root = get_storage_root()
    campaign_dir = os.path.join(
        storage_root,
        "campaigns",
        "linkedin_AI_Product_Manager__Head_of_AI__AI_Director__AI_Transformation_Lead_Vietnam",
        "2026-06-15",
    )
    jobs_file = os.path.join(campaign_dir, "scraped_jobs.json")
    scores_dir = os.path.join(campaign_dir, "scores")
    local_scratch = str(SKILL_ROOT / "scratch")
    cv_file = get_master_cv_path()

    os.makedirs(scores_dir, exist_ok=True)
    os.makedirs(local_scratch, exist_ok=True)

    with open(jobs_file, encoding="utf-8") as f:
        jobs = json.load(f)

    with open(cv_file, encoding="utf-8") as f:
        cv_text = f.read()

    # Slice jobs
    sliced_jobs = jobs[args.start_index : args.end_index]
    print(
        f"Loaded {len(sliced_jobs)} jobs for indices {args.start_index} to {args.end_index}",
        flush=True,
    )

    start_time = time.time()

    # Process sequentially in foreground
    for i, job in enumerate(sliced_jobs):
        current_idx = args.start_index + i

        # Check if we should exit to stay in foreground (limit to 120.0 seconds elapsed)
        elapsed = time.time() - start_time
        if elapsed > 120.0:
            print(
                f"TIMEOUT_LIMIT_REACHED: Next index to process: {current_idx}",
                flush=True,
            )
            sys.exit(0)

        score_file = os.path.join(
            scores_dir,
            f"{pipeline.safe_filename(job['company'])}__{job['id']}_score.json",
        )

        # Check if already successfully scored
        is_scored = False
        if os.path.exists(score_file):
            try:
                with open(score_file, encoding="utf-8") as sf:
                    score_data = json.load(sf)
                    if score_data.get("match_score", 0) > 0:
                        is_scored = True
            except Exception as score_err:
                print(f"DEBUG: Failed reading {score_file}: {score_err}", flush=True)

        if is_scored:
            continue

        print(
            f"Scoring job {current_idx}: {job['title']} at {job['company']}...",
            flush=True,
        )
        temp_jd = os.path.join(local_scratch, f"{job['id']}_jd.txt")
        with open(temp_jd, "w", encoding="utf-8") as f:
            f.write(job["jd_text"])

        try:
            # Use dynamic rubric (JD-specific) instead of static rubric
            # This prevents all jobs from scoring 95+ on the static AI PM rubric
            rubric_data = score_jd._handle_dynamic_rubric(
                job["jd_text"], score_file, job.get("title")
            )
            if rubric_data is None:
                # Fallback to static rubric only if dynamic generation fails
                print(
                    f"WARNING {current_idx}: Dynamic rubric failed, falling back to static",
                    flush=True,
                )
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
                temp_jd,
                cv_file,
            )
            print(
                f"SUCCESS {current_idx}: score={result.get('match_score')}",
                flush=True,
            )
        except Exception as e:
            print(f"FAILED {current_idx}: {e}", flush=True)

    print("COMPLETED", flush=True)


if __name__ == "__main__":
    main()
