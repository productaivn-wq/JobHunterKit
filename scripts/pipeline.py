import argparse
import datetime
import logging
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# Add project root to sys.path so we can import services
script_dir = os.path.dirname(os.path.abspath(__file__))
kit_dir = os.path.dirname(script_dir)
if kit_dir not in sys.path:
    sys.path.insert(0, kit_dir)

from pathlib import Path


# Setup path for importing shared_platform
def _setup_sys_path():
    curr = Path(__file__).resolve()
    for parent in curr.parents:
        if (parent / "shared_platform").is_dir():
            root_path = str(parent)
            if root_path not in sys.path:
                sys.path.insert(0, root_path)
            break


_setup_sys_path()


# Import shared functions to maintain backwards compatibility for other scripts
from services.applying import auto_apply
from services.common import (
    STORAGE_ROOT,
    generate_report,
    get_run_dirs,
    safe_filename,
)
from services.scoring import evaluate_jobs, rescore_only
from services.scraping import live_linkedin_scrape
from services.tailoring import tailor_cvs

__all__ = [
    "auto_apply",
    "STORAGE_ROOT",
    "generate_report",
    "get_run_dirs",
    "safe_filename",
    "evaluate_jobs",
    "rescore_only",
    "live_linkedin_scrape",
    "tailor_cvs",
]

# Setup logging
log_file = os.path.join(kit_dir, "scratch", "jobhunter_execution.log")
os.makedirs(os.path.dirname(log_file), exist_ok=True)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

for h in list(root_logger.handlers):
    root_logger.removeHandler(h)

file_handler = logging.FileHandler(log_file, encoding="utf-8", delay=False)
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
root_logger.addHandler(file_handler)

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
)
root_logger.addHandler(stream_handler)


def _execute_phases(args, dirs, state_file, script_dir_path):
    """Executes the standard end-to-end phases of the pipeline."""
    print("=== JobHunterKit Pipeline Started ===")
    print(f"  Output directory: {dirs['run_dir']}\n")

    jobs_file = dirs["jobs_file"]
    if os.path.exists(jobs_file) and os.path.getsize(jobs_file) > 0 and not args.force:
        print(f"  [CACHE] Reusing existing scraped jobs from: {jobs_file}")
    else:
        if args.force:
            print("  [FORCE] Bypassing scraped jobs cache. Starting fresh scrape...")

        source = getattr(args, "source", "linkedin").lower()
        if source.startswith("linkedin"):
            jobs_file = live_linkedin_scrape(
                args.keyword,
                args.location,
                dirs,
                limit=999999,
                state_file=state_file,
                date_posted=args.date_posted,
                source=source,
                cli_mode=True,
            )
        else:
            try:
                import importlib

                scraper_module = importlib.import_module(f"scrapers.{source}")
                jobs_file = scraper_module.scrape_jobs(
                    args.keyword,
                    args.location,
                    dirs,
                    limit=999999,
                    state_file=state_file,
                    date_posted=args.date_posted,
                )
            except Exception as e:
                print(f"Failed to load or execute scraper for source '{source}': {e}")
                jobs_file = None

        if not jobs_file or not os.path.exists(jobs_file):
            print("Failed to scrape jobs. Pipeline ending.")
            sys.exit(1)

    import queue
    import threading

    passed_queue = queue.Queue()
    tailored_all = {}

    def apply_consumer_worker():
        while True:
            job = passed_queue.get()
            if job is None:
                passed_queue.task_done()
                break
            try:
                # Tailor CV and apply to this job immediately
                tailored = tailor_cvs([job], args.cv, dirs, script_dir_path, args.force)
                tailored_all.update(tailored)
                auto_apply(
                    [job],
                    args.cv,
                    dirs,
                    tailored_cvs=tailored,
                    state_file=state_file,
                    dry_run=args.dry_run,
                    cli_mode=True,
                )
            except Exception as e:
                print(f"  [ERROR] Continuous apply failed for {job['company']}: {e}")
            finally:
                passed_queue.task_done()

    consumer_thread = threading.Thread(target=apply_consumer_worker, daemon=True)
    consumer_thread.start()

    def on_pass(job):
        passed_queue.put(job)

    passed_jobs = evaluate_jobs(
        jobs_file,
        args.cv,
        script_dir_path,
        dirs["local_scratch"],
        dirs["scores_dir"],
        args.threshold,
        args.dynamic_rubric,
        args.force,
        dirs,
        args.dry_run,
        on_pass_callback=on_pass,
    )

    # Signal consumer thread to exit and wait for it
    passed_queue.put(None)
    consumer_thread.join()

    print("=== JobHunterKit Pipeline Completed ===")
    generate_report(args, passed_jobs, tailored_all, dirs)


def main():
    parser = argparse.ArgumentParser(description="JobHunterKit End-to-End Orchestrator")
    parser.add_argument("--keyword", required=True, help="Job search keyword")
    parser.add_argument("--location", required=True, help="Job location")
    parser.add_argument(
        "--source",
        default="linkedin",
        help="Job board source to scrape from (e.g. linkedin, itviec, remotive, weworkremotely, remoteok, indeed, etc.)",
    )
    parser.add_argument(
        "--cv",
        default=str(Path(kit_dir).parents[2] / "cv_text.txt"),
        help="Path to base CV file",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Run without final submission"
    )
    parser.add_argument(
        "--rescore",
        action="store_true",
        help="Re-score already-scraped jobs without re-scraping",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=None,
        help="Override pass threshold from rubric",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Date folder to rescore (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--dynamic-rubric",
        action="store_true",
        help="Generate scoring rubric dynamically tailored to each JD",
    )
    parser.add_argument(
        "--date-posted",
        choices=["all", "day", "week", "month"],
        default="week",
        help="Filter jobs by date posted (default: week)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force a fresh execution, bypassing scraped jobs and scores cache",
    )

    args = parser.parse_args()

    script_dir_path = os.path.dirname(os.path.abspath(__file__))
    state_file = os.path.join(script_dir_path, "state.json")
    dirs = get_run_dirs(
        args.keyword, args.location, getattr(args, "source", "linkedin")
    )
    dirs["keyword"] = args.keyword
    dirs["location"] = args.location

    if args.date and args.date != datetime.datetime.now().strftime("%Y-%m-%d"):
        campaign_name = re.sub(
            r"[^\w]", "_", f"{args.source}_{args.keyword}_{args.location}"
        )
        dirs["run_dir"] = os.path.join(
            STORAGE_ROOT, "campaigns", campaign_name, args.date
        )
        dirs["jobs_file"] = os.path.join(dirs["run_dir"], "scraped_jobs.json")
        dirs["scores_dir"] = os.path.join(dirs["run_dir"], "scores")
        dirs["tailored_dir"] = os.path.join(dirs["run_dir"], "tailored")
        dirs["proof_dir"] = os.path.join(dirs["run_dir"], "proof")
        dirs["local_scratch"] = os.path.join(
            os.path.dirname(script_dir_path), "scratch"
        )
        os.makedirs(dirs["scores_dir"], exist_ok=True)

    if args.rescore:
        rescore_only(args, dirs, script_dir_path)
    else:
        _execute_phases(args, dirs, state_file, script_dir_path)


if __name__ == "__main__":
    main()
