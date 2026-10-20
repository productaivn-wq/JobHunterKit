import json
import os
import re
import sys

from services.common import (
    _load_applied_history,
    _load_excluded_companies,
    run_command,
    safe_filename,
)

services_dir = os.path.dirname(os.path.abspath(__file__))
kit_dir = os.path.dirname(services_dir)
scripts_dir = os.path.join(kit_dir, "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)


def _load_cached_score(job, score_file, threshold):
    """Loads a cached score from score_file and populates job dictionary."""
    try:
        with open(score_file, encoding="utf-8") as sf:
            score_data = json.load(sf)
        job["match_score"] = score_data.get("match_score", 0)
        job["top_strengths"] = score_data.get("top_strengths", [])
        job["key_gaps"] = score_data.get("key_gaps", [])
        job["overall_reasoning"] = score_data.get("overall_reasoning", "")
        job["score_file"] = score_file
        t = threshold if threshold is not None else score_data.get("threshold", 70)
        passed = score_data.get("passed", job["match_score"] >= t)
        if passed:
            print(
                f"  [CACHED PASS {job['match_score']}/100] {job['title']} at {job['company']}"
            )
            return True
        else:
            print(
                f"  [CACHED FAIL {job['match_score']}/100] {job['title']} at {job['company']}"
            )
            return False
    except Exception as ce:
        print(f"  [WARNING] Failed to load cached score for {job['company']}: {ce}")
        return None


def _parse_score_result(result, score_file, job):
    """Robustly parses the match score result from disk or stdout."""
    score_data = {}
    if (
        result.returncode == 0
        and os.path.exists(score_file)
        and os.path.getsize(score_file) > 0
    ):
        try:
            with open(score_file, encoding="utf-8") as sf:
                score_data = json.load(sf)
        except Exception as fe:
            print(f"  [WARNING] Failed to load score from file: {fe}")

    if not score_data:
        try:
            marker = "--- Evaluation Result ---"
            if marker in result.stdout:
                json_str = result.stdout.split(marker)[-1].strip()
                json_match = re.search(r"(\{.*\})", json_str, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                score_data = json.loads(json_str)
        except Exception as se:
            print(f"  [WARNING] Failed to parse score from stdout: {se}")

    job["match_score"] = score_data.get("match_score", 0)
    job["top_strengths"] = score_data.get("top_strengths", [])
    job["key_gaps"] = score_data.get("key_gaps", [])
    job["overall_reasoning"] = score_data.get("overall_reasoning", "")
    job["score_file"] = score_file
    return score_data


def _run_scoring_script(
    job, temp_jd, cv_file, score_file, threshold, dynamic_rubric, script_dir
):
    """Executes the external scoring script and parses results robustly."""
    score_cmd = [
        sys.executable,
        os.path.join(script_dir, "score_jd.py"),
        "--jd-file",
        temp_jd,
        "--cv-file",
        cv_file,
        "--output-score",
        score_file,
    ]
    if threshold is not None:
        score_cmd += ["--threshold", str(threshold)]
    if dynamic_rubric:
        score_cmd += ["--dynamic-rubric"]

    result = run_command(score_cmd)
    score_data = _parse_score_result(result, score_file, job)
    parsed_successfully = len(score_data) > 0 and job["match_score"] > 0

    if result.returncode == 0 and parsed_successfully:
        print(f"  [PASS {job['match_score']}/100] {job['title']} at {job['company']}")
        return True
    elif result.returncode == 2:
        print(f"  [FAIL {job['match_score']}/100] {job['title']} at {job['company']}")
        return False
    else:
        print(
            f"  [ERROR] {job['title']} at {job['company']} (Script Bug, API Error, or Parsing Failure)"
        )
        if result.stdout:
            print(f"    Stdout: {result.stdout.strip()}")
        if result.stderr:
            print(f"    Stderr: {result.stderr.strip()}")
        return False


def _check_cache_passed(job, score_file, threshold, force) -> tuple[bool, bool]:
    """Returns (is_cached, passed) for a job's scoring cache."""
    if force or not os.path.exists(score_file) or os.path.getsize(score_file) == 0:
        return False, False
    cache_result = _load_cached_score(job, score_file, threshold)
    if cache_result is True:
        return True, True
    if cache_result is False:
        return True, False
    return False, False


def evaluate_jobs(
    jobs_file,
    cv_file,
    script_dir,
    local_scratch,
    scores_dir,
    threshold=None,
    dynamic_rubric=False,
    force=False,
    dirs=None,
    dry_run=False,
    on_pass_callback=None,
):
    """Runs the LLM scoring script on each job. Saves full score JSON to scores_dir."""
    print("[Phase 2: Evaluate] Evaluating jobs against CV...")
    print("[UTOP|func|evaluate_jobs|cp-fr-009]")

    # Load CV text once
    cv_text = ""
    try:
        if cv_file.lower().endswith(".pdf"):
            import fitz

            doc = fitz.open(cv_file)
            cv_text = "".join(page.get_text() for page in doc)
            doc.close()
        else:
            with open(cv_file, encoding="utf-8") as f:
                cv_text = f.read()
    except Exception as e:
        print(f"  [CRITICAL ERROR] Failed to read CV file: {e}")
        return []

    with open(jobs_file, encoding="utf-8") as f:
        jobs = json.load(f)

    passed_jobs = []
    seen_jobs = set()

    already_submitted = set()
    already_submitted_companies = set()
    already_submitted_urls = set()
    if dirs and "history_file" in dirs:
        _, already_submitted, already_submitted_companies, already_submitted_urls = (
            _load_applied_history(dirs["history_file"], dry_run)
        )
    excluded = _load_excluded_companies()

    jobs_to_eval = []
    for job in jobs:
        job_key = f"{job['title'].strip()} @ {job['company'].strip()}".lower()
        if job_key in seen_jobs:
            print(
                f"  [DEDUP] Skipping duplicate scraped job in same run: {job['title']} at {job['company']}"
            )
            continue
        seen_jobs.add(job_key)

        company_lower = job["company"].strip().lower()
        if company_lower in excluded:
            print(
                f"  [BLACKLIST] Skipping job from excluded company: {job['title']} at {job['company']}"
            )
            continue

        job_url = job.get("url")
        clean_url = job_url.split("?")[0].strip().lower() if job_url else ""
        if clean_url and clean_url in already_submitted_urls:
            print(
                f"  [APPLIED] Skipping already submitted job by URL: {job['title']} at {job['company']}"
            )
            continue

        if job_key in already_submitted:
            print(
                f"  [APPLIED] Skipping already submitted job: {job['title']} at {job['company']}"
            )
            continue

        score_file = os.path.join(
            scores_dir, f"{safe_filename(job['company'])}__{job['id']}_score.json"
        )
        is_cached, cached_pass = _check_cache_passed(job, score_file, threshold, force)
        if is_cached:
            if cached_pass:
                passed_jobs.append(job)
                if on_pass_callback:
                    on_pass_callback(job)
            continue

        temp_jd = os.path.join(local_scratch, f"{job['id']}_jd.txt")
        jobs_to_eval.append((job, temp_jd, score_file))

    def eval_single_job(item):
        job, temp_jd, score_file = item
        try:
            try:
                import scripts.score_jd as score_jd
            except ImportError:
                import score_jd

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

            # Parse result into job structure
            job["match_score"] = result.get("match_score", 0)
            job["top_strengths"] = result.get("top_strengths", [])
            job["key_gaps"] = result.get("key_gaps", [])
            job["overall_reasoning"] = result.get("overall_reasoning", "")
            job["score_file"] = score_file

            success = job["match_score"] >= actual_threshold
            print(
                f"  [{'PASS' if success else 'FAIL'} {job['match_score']}/100] {job['title']} at {job['company']}"
            )
            return job, success
        except Exception as e:
            print(f"  [ERROR] Parallel evaluation failed for {job['company']}: {e}")
            return job, False

    if jobs_to_eval:
        import concurrent.futures
        from concurrent.futures import ThreadPoolExecutor

        print(f"  Evaluating {len(jobs_to_eval)} jobs in parallel (In-Process mode)...")
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(eval_single_job, item): item for item in jobs_to_eval
            }
            for future in concurrent.futures.as_completed(futures):
                try:
                    job, success = future.result()
                    if success:
                        passed_jobs.append(job)
                        if on_pass_callback:
                            on_pass_callback(job)
                except Exception as e:
                    print(f"  [ERROR] Future evaluation result failed: {e}")

    print(
        f"[Phase 2: Evaluate] {len(passed_jobs)} out of {len(seen_jobs)} unique jobs passed the threshold.\n"
    )
    return passed_jobs


def rescore_only(args, dirs, script_dir_path):
    """Re-scores already-scraped jobs without re-scraping. Useful for rubric tuning."""
    print("=== JobHunterKit Rescore Mode ===")
    jobs_file = dirs["jobs_file"]
    if not os.path.exists(jobs_file):
        print(
            f"No scraped_jobs.json found at {jobs_file}. Run without --rescore first."
        )
        sys.exit(1)
    print(f"Re-scoring jobs from {jobs_file}\n")
    threshold = (
        args.threshold if hasattr(args, "threshold") and args.threshold else None
    )
    dynamic_rub = args.dynamic_rubric if hasattr(args, "dynamic_rubric") else False
    passed = evaluate_jobs(
        jobs_file,
        args.cv,
        script_dir_path,
        dirs["local_scratch"],
        dirs["scores_dir"],
        threshold,
        dynamic_rub,
        args.force,
        dirs,
        False,
    )
    print(f"\nRescore complete. {len(passed)} jobs would pass with current rubric.")
    print(f"Score JSONs saved to: {dirs['scores_dir']}")
