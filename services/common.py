import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright  # noqa: F401
    from playwright_stealth import Stealth  # noqa: F401

    PLAYWRIGHT_AVAILABLE = True
except ImportError as e:
    print(f"ImportError in common: {e}")
    PLAYWRIGHT_AVAILABLE = False

KIT_ROOT = Path(__file__).resolve().parent.parent
if str(KIT_ROOT) not in sys.path:
    sys.path.insert(0, str(KIT_ROOT))

# Re-export safe_filename for backward compatibility (moved to core.file_utils)
from core.file_utils import safe_filename  # noqa: E402, F401, I001


STORAGE_ROOT = str(KIT_ROOT / "data")

LINKEDIN_COLLECTIONS = {
    "linkedin-recommended": "https://www.linkedin.com/jobs/collections/recommended/",
    "linkedin-top-applicant": "https://www.linkedin.com/jobs/collections/top-applicant/",
    "linkedin-human-resources": "https://www.linkedin.com/jobs/collections/human-resources/",
    "linkedin-it-services-and-it-consulting": "https://www.linkedin.com/jobs/collections/it-services-and-it-consulting/",
    "linkedin-easy-apply": "https://www.linkedin.com/jobs/collections/easy-apply/",
    "linkedin-remote-jobs": "https://www.linkedin.com/jobs/collections/remote-jobs/",
}


def run_command(cmd, cwd=None):
    print(f"Executing: {' '.join(cmd)}")
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )

    output_lines = []
    while True:
        line = process.stdout.readline()
        if not line and process.poll() is not None:
            break
        if line:
            sys.stdout.write(line)
            sys.stdout.flush()
            output_lines.append(line)

    process.wait()

    class DummyResult:
        def __init__(self, returncode, stdout):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    return DummyResult(process.returncode, "".join(output_lines))


def get_run_dirs(keyword, location, source="linkedin"):
    """Returns all output directory paths for this run."""
    campaign_name = re.sub(r"[^\w]", "_", f"{source}_{keyword}_{location}")
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    run_dir = os.path.join(STORAGE_ROOT, "campaigns", campaign_name, date_str)
    tailored_dir = os.path.join(run_dir, "tailored")
    proof_dir = os.path.join(run_dir, "proof")
    scores_dir = os.path.join(run_dir, "scores")

    # services/common.py is under JobHunterKit/services/common.py
    services_dir = os.path.dirname(os.path.abspath(__file__))
    kit_dir = os.path.dirname(services_dir)
    local_scratch = os.path.join(kit_dir, "scratch")
    for d in [run_dir, tailored_dir, proof_dir, scores_dir, local_scratch]:
        os.makedirs(d, exist_ok=True)
    return {
        "run_dir": run_dir,
        "tailored_dir": tailored_dir,
        "proof_dir": proof_dir,
        "scores_dir": scores_dir,
        "local_scratch": local_scratch,
        "history_file": os.path.join(STORAGE_ROOT, "applied_history.json"),
        "master_report": os.path.join(STORAGE_ROOT, "master_report.md"),
        "report_file": os.path.join(run_dir, "report.md"),
        "jobs_file": os.path.join(run_dir, "scraped_jobs.json"),
    }


def _boot_playwright_context(p, state_file):
    """Boots the Chromium browser with the optional storage state."""
    headless = os.environ.get("JOBHUNTER_HEADLESS", "true").lower() not in (
        "false",
        "0",
    )
    browser = p.chromium.launch(headless=headless, channel="chrome")
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    if state_file and os.path.exists(state_file):
        context = browser.new_context(
            storage_state=state_file, user_agent=user_agent, ignore_https_errors=True
        )
    else:
        context = browser.new_context(user_agent=user_agent, ignore_https_errors=True)
    return browser, context


def _load_excluded_companies():
    """Helper to load excluded companies list from applicant_profile.json."""
    services_dir = os.path.dirname(os.path.abspath(__file__))
    kit_dir = os.path.dirname(services_dir)
    profile_path = os.path.join(kit_dir, "config", "applicant_profile.json")
    try:
        if os.path.exists(profile_path):
            with open(profile_path, encoding="utf-8") as f:
                profile = json.load(f)
                return {
                    c.strip().lower()
                    for c in profile.get("excluded_companies", [])
                    if c
                }
    except Exception as e:
        print(f"  [WARNING] Could not load excluded_companies: {e}")
    return {"vinsmart future"}


def is_company_excluded(company_name: str, excluded: set = None) -> bool:
    """Checks if a company name matches any entry in the excluded blacklist."""
    if not company_name:
        return False
    if excluded is None:
        excluded = _load_excluded_companies()
    if not excluded:
        return False

    c_clean = company_name.strip().lower()
    c_norm = re.sub(r"[^a-z0-9]", "", c_clean)
    words = re.findall(r"[a-z0-9]+", c_clean)

    for entry in excluded:
        p_clean = entry.strip().lower()
        if not p_clean:
            continue
        p_norm = re.sub(r"[^a-z0-9]", "", p_clean)

        # Exact match
        if c_clean == p_clean or c_norm == p_norm:
            return True

        # Word boundary / Token match (e.g. 'GSM' in 'GSM Logistics' or 'OneMount' in 'One Mount Group')
        if len(p_clean) <= 3:
            if p_clean in words or p_norm in words:
                return True
        else:
            # Substring match on normalized or raw strings
            if p_clean in c_clean or (p_norm and p_norm in c_norm):
                return True

    return False


def _should_dedup(status, dry_run) -> bool:
    valid_statuses = {
        "Submitted",
        "External",
        "Skipped",
        "Success",
        "Stuck",
        "Failed",
    }
    if dry_run:
        valid_statuses.add("Dry Run")
    return any(s in status for s in valid_statuses)


def _read_history_file(history_file) -> list:
    if not os.path.exists(history_file):
        return []
    try:
        with open(history_file, encoding="utf-8") as f:
            records = json.load(f)
            if records and isinstance(records[0], str):
                return [{"job_key": k} for k in records]
            return records
    except json.JSONDecodeError as e:
        backup_file = f"{history_file}.bak_{int(time.time())}"
        import shutil

        shutil.copy2(history_file, backup_file)
        print(f"  [CRITICAL ERROR] Failed to parse applied history JSON: {e}")
        print(f"  [CRITICAL ERROR] Corrupted file backed up to: {backup_file}")
        return []
    except Exception as e:
        print(f"  [WARNING] Error reading applied history: {e}")
        return []


def _load_applied_history(history_file, dry_run):
    existing_records = _read_history_file(history_file)
    already_submitted = {
        r.get("job_key").strip().lower()
        for r in existing_records
        if r.get("job_key") and _should_dedup(r.get("status", ""), dry_run)
    }
    already_submitted_companies = {
        r.get("company", "").strip().lower()
        for r in existing_records
        if r.get("company") and _should_dedup(r.get("status", ""), dry_run)
    }
    already_submitted_urls = {
        r.get("url").split("?")[0].strip().lower()
        for r in existing_records
        if r.get("url") and _should_dedup(r.get("status", ""), dry_run)
    }
    return (
        existing_records,
        already_submitted,
        already_submitted_companies,
        already_submitted_urls,
    )


def _save_applied_history(history_file, passed_jobs, tailored_cvs, cv_file, dirs):
    """Saves updated history records concurrently safely using atomic writes with retries and fallbacks."""
    existing_records = _read_history_file(history_file)
    key_to_index = {
        r.get("job_key", "").strip().lower(): i for i, r in enumerate(existing_records)
    }
    for job in passed_jobs:
        job_key = f"{job['title'].strip()} @ {job['company'].strip()}".lower()
        status = job.get("apply_status", "Unknown")
        saveable_statuses = (
            "Submitted",
            "Dry Run",
            "External",
            "Success",
            "Skipped",
            "Stuck",
            "Failed",
        )
        if any(s in status for s in saveable_statuses):
            record = {
                "job_key": job_key,
                "applied_date": datetime.datetime.now().strftime("%Y-%m-%d"),
                "title": job["title"],
                "company": job["company"],
                "url": job.get("url", ""),
                "match_score": job.get("match_score", 0),
                "top_strengths": job.get("top_strengths", []),
                "key_gaps": job.get("key_gaps", []),
                "status": status,
                "cv_used": tailored_cvs.get(job["id"], cv_file)
                if tailored_cvs
                else cv_file,
                "proof": job.get("proof_path", ""),
                "score_file": job.get("score_file", ""),
                "keyword": dirs.get("keyword", ""),
                "location": dirs.get("location", ""),
            }
            if job_key in key_to_index:
                existing_records[key_to_index[job_key]] = record
            else:
                existing_records.append(record)
                key_to_index[job_key] = len(existing_records) - 1

    tmp_file = f"{history_file}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(existing_records, f, indent=2, ensure_ascii=False)

    import shutil

    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            os.replace(tmp_file, history_file)
            return
        except PermissionError as pe:
            if attempt == max_attempts - 1:
                # Fallback: copy2 and remove
                try:
                    shutil.copy2(tmp_file, history_file)
                    os.remove(tmp_file)
                    return
                except Exception:
                    raise pe
            time.sleep(0.1 * (attempt + 1))


def _preload_applied_history_sets(dirs):
    """Loads applied history file and extracts unique job keys and split URLs."""
    already_submitted_keys = set()
    already_submitted_urls = set()
    history_file = dirs.get("history_file")
    if history_file and os.path.exists(history_file):
        try:
            _, already_submitted_keys, _, already_submitted_urls = (
                _load_applied_history(history_file, dry_run=False)
            )
            print(
                f"  [APPLIED PRELOAD] Loaded {len(already_submitted_keys)} job keys and {len(already_submitted_urls)} URLs from history."
            )
        except Exception as e:
            print(f"  [WARNING] Could not preload applied history: {e}")
    return already_submitted_keys, already_submitted_urls


def _write_job_report_details(rf, job, tailored_cvs):
    status = job.get("apply_status", "Unknown")
    score = job.get("match_score", "N/A")
    rf.write(f"### {job['title']} at {job['company']}\n")
    rf.write(f"- **Score:** {score}/100\n")
    rf.write(f"- **URL:** {job.get('url', 'N/A')}\n")
    rf.write(f"- **Status:** {status}\n")
    if job.get("top_strengths"):
        rf.write(f"- **Top Strengths:** {', '.join(job['top_strengths'])}\n")
    if job.get("key_gaps"):
        rf.write(f"- **Key Gaps:** {', '.join(job['key_gaps'])}\n")
    if job.get("overall_reasoning"):
        rf.write(f"- **AI Reasoning:** {job['overall_reasoning']}\n")
    if tailored_cvs and job["id"] in tailored_cvs:
        cv_path = tailored_cvs[job["id"]].replace("\\", "/")
        rf.write(f"- **Tailored CV:** [View PDF](file:///{cv_path})\n")
    if job.get("score_file") and os.path.exists(job["score_file"]):
        score_path = job["score_file"].replace("\\", "/")
        rf.write(f"- **Full Score JSON:** [View Breakdown](file:///{score_path})\n")
    if "proof_path" in job:
        proof_path = job["proof_path"].replace("\\", "/")
        rf.write(f"- **Proof Screenshot:**\n![Proof](file:///{proof_path})\n")
    rf.write("\n")


def _write_run_report(rf, args, passed_jobs, tailored_cvs):
    rf.write("| Field | Value |\n|---|---|\n")
    rf.write(f"| Keyword | {args.keyword} |\n")
    rf.write(f"| Location | {args.location} |\n")
    rf.write(f"| Jobs Passed | {len(passed_jobs)} |\n")
    rf.write(f"| Mode | {'Dry Run' if args.dry_run else 'Live'} |\n\n")
    rf.write("---\n\n## Results\n\n")
    for job in passed_jobs:
        _write_job_report_details(rf, job, tailored_cvs)


def _append_master_report(master_file, now_str, args, passed_jobs, tailored_cvs):
    os.makedirs(os.path.dirname(master_file), exist_ok=True)
    with open(master_file, "a", encoding="utf-8") as mf:
        mf.write(f"\n## {now_str} — {args.keyword} in {args.location}\n")
        mf.write(
            "| Job | Score | Status | Tailored CV | Score Breakdown |\n|---|---|---|---|---|\n"
        )
        for job in passed_jobs:
            status = job.get("apply_status", "Unknown")
            score = job.get("match_score", "N/A")
            cv_link = ""
            score_link = ""
            if tailored_cvs and job["id"] in tailored_cvs:
                cv_path = tailored_cvs[job["id"]].replace("\\", "/")
                cv_link = f"[PDF](file:///{cv_path})"
            if job.get("score_file") and os.path.exists(job.get("score_file", "")):
                s_path = job["score_file"].replace("\\", "/")
                score_link = f"[JSON](file:///{s_path})"
            mf.write(
                f"| {job['title']} at {job['company']} | {score}/100 | {status} | {cv_link} | {score_link} |\n"
            )


def generate_report(args, passed_jobs, tailored_cvs, dirs):
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    report_file = dirs["report_file"]
    with open(report_file, "w", encoding="utf-8") as rf:
        rf.write(f"# JobHunterKit Report — {now_str}\n\n")
        _write_run_report(rf, args, passed_jobs, tailored_cvs)
    print(f"Run report saved to {report_file}")
    _append_master_report(
        dirs["master_report"], now_str, args, passed_jobs, tailored_cvs
    )
    print(f"Master report updated at {dirs['master_report']}")
