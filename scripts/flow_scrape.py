"""
Flow 1: Scrape jobs exhaustively and enqueue them in the Supabase jobs table.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "scripts"))

import pipeline

from shared_platform.db import with_db_transaction
from shared_platform.logging_setup import flow_entrypoint


def make_job_key(job):
    url = job.get("url")
    if url:
        return url.split("?")[0].strip().lower()
    # Fallback to source + company + title
    return f"{job.get('source', 'unknown')}:{job.get('company', 'unknown')}:{job.get('title', 'unknown')}".lower().strip()


@with_db_transaction
def enqueue_scraped_jobs(all_jobs, keyword, location, default_source, conn=None):
    new_jobs_count = 0
    duplicate_jobs_count = 0
    prefilter_skipped_count = 0
    with conn.cursor() as cur:
        for idx, job in enumerate(all_jobs):
            job_key = make_job_key(job)
            title = job.get("title", "Unknown Title")[:255]
            company = job.get("company", "Unknown Company")[:255]
            location_val = str(job.get("location", location))[:255]
            url = job.get("url", "")
            source_name = job.get("source", default_source)[:100]
            jd_text = job.get("jd_text", "")

            # Instant ingestion pre-filtering: Drop non-target/expired/low-match JDs immediately
            status_score = "pending"
            status_apply = "standby"
            exclude = False
            try:
                from fast_filter import should_exclude
                exclude, _ = should_exclude(title, jd_text, location_val)
            except Exception:
                pass

            if not exclude:
                try:
                    from core.ats_prefilter import should_skip_jd
                    ats_skip, _ = should_skip_jd(jd_text)
                    if ats_skip:
                        exclude = True
                except Exception:
                    pass

            if exclude:
                status_score = "skipped_prefilter"
                status_apply = "skipped"

            sp_name = f"job_insert_{idx}"
            cur.execute(f"SAVEPOINT {sp_name};")
            try:
                cur.execute(
                    "INSERT INTO job_hunter.jobs (job_key, title, company, location, url, source, jd_text, status_score, status_apply, keyword, search_location) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (job_key) DO NOTHING "
                    "RETURNING id;",
                    (
                        job_key,
                        title,
                        company,
                        location_val,
                        url,
                        source_name,
                        jd_text,
                        status_score,
                        status_apply,
                        keyword,
                        location,
                    ),
                )
                res = cur.fetchone()
                if res:
                    new_jobs_count += 1
                    if exclude:
                        prefilter_skipped_count += 1
                else:
                    duplicate_jobs_count += 1
                cur.execute(f"RELEASE SAVEPOINT {sp_name};")
            except Exception as insert_err:
                cur.execute(f"ROLLBACK TO SAVEPOINT {sp_name};")
                print(
                    f"[flow_scrape] Error enqueuing job '{title}' ({job_key}): {insert_err}"
                )

        print("Flow 1 Scrape & Enqueue Completed:")
        print(f"  - Total aggregated: {len(all_jobs)}")
        print(f"  - Newly enqueued: {new_jobs_count} ({new_jobs_count - prefilter_skipped_count} pending score, {prefilter_skipped_count} pre-filtered)")
        print(f"  - Already existed (skipped): {duplicate_jobs_count}")

        pending_new = new_jobs_count - prefilter_skipped_count
        if pending_new > 0:
            print(f"[flow_scrape] Cascading: Triggering Flow 2 to score {pending_new} newly enqueued jobs...")
            try:
                creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                subprocess.run(
                    ["schtasks", "/run", "/tn", r"\JobHunterKit\Flow2_Score"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    creationflags=creationflags,
                )
            except Exception as trigger_err:
                print(f"[flow_scrape] Warning: Could not trigger Flow 2 scheduled task: {trigger_err}")



@flow_entrypoint("flow1")
def run_scrape(args):
    print(
        f"=== Flow 1: Scraping Jobs for Keyword='{args.keyword}' | Location='{args.location}' | Source='{args.source}' ==="
    )

    from shared_platform.pipeline_state import is_paused

    if is_paused():
        print("Pipeline is paused. Skipping Flow 1 execution.", flush=True)
        return

    script_dir_path = os.path.dirname(os.path.abspath(__file__))
    state_file = os.path.join(script_dir_path, "state.json")

    source = args.source.lower()
    limit = args.limit

    if source == "all":
        sources_to_run = [
            "linkedin",
            "linkedin-recommended",
            "linkedin-top-applicant",
            "linkedin-human-resources",
            "linkedin-it-services-and-it-consulting",
            "linkedin-easy-apply",
            "linkedin-remote-jobs",
            "linkedin-post",
            "itviec",
            "indeed",
            "topcv",
            "careerjet",
            "vietnamworks",
            "glints",
            "remotive",
            "weworkremotely",
            "remoteok",
            "jsremotely",
            "jobright_gmail",
        ]
    else:
        sources_to_run = [source]

    all_jobs = []

    for src in sources_to_run:
        if is_paused():
            print(
                "Pipeline was paused mid-run. Stopping further scraping sources.",
                flush=True,
            )
            break
        print(f"\n--- Scraping source: '{src}' ---")
        try:
            # Get campaign run directories
            dirs = pipeline.get_run_dirs(args.keyword, args.location, src)
            dirs["keyword"] = args.keyword
            dirs["location"] = args.location
            jobs_file = dirs["jobs_file"]

            if src.startswith("linkedin"):
                jobs_file = pipeline.live_linkedin_scrape(
                    args.keyword,
                    args.location,
                    dirs,
                    limit=limit,
                    state_file=state_file,
                    date_posted=args.date_posted,
                    source=src,
                )
            else:
                import importlib

                scraper_module = importlib.import_module(f"scrapers.{src}")
                jobs_file = scraper_module.scrape_jobs(
                    args.keyword,
                    args.location,
                    dirs,
                    limit=limit,
                    state_file=state_file,
                    date_posted=args.date_posted,
                )

            if jobs_file and os.path.exists(jobs_file):
                with open(jobs_file, encoding="utf-8") as f:
                    src_jobs = json.load(f)
                print(f"Scraped {len(src_jobs)} jobs from '{src}'.")
                for j in src_jobs:
                    if "source" not in j:
                        j["source"] = src
                all_jobs.extend(src_jobs)

                if src_jobs:
                    print(f"  [STREAMING ENQUEUE] Progressively enqueuing {len(src_jobs)} jobs from '{src}' into database...")
                    try:
                        enqueue_scraped_jobs(src_jobs, args.keyword, args.location, src)
                    except Exception as eq_err:
                        print(f"  [WARNING] Progressive enqueue failed for source '{src}': {eq_err}")
            else:
                print(f"[WARNING] Jobs file not found for source '{src}'.")
        except Exception as e:
            print(f"[ERROR] Failed scraping source '{src}': {e}")

    if not all_jobs:
        print("[WARNING] No jobs scraped from any source.")
        return

    print(
        f"\nFlow 1 Scraping Finished. Total aggregated scraped jobs across all sources: {len(all_jobs)}."
    )



if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Flow 1: Exhaustive Job Scraper & DB Enqueuer"
    )
    parser.add_argument("--keyword", required=True, help="Job search keyword")
    parser.add_argument("--location", required=True, help="Job location")
    parser.add_argument(
        "--source",
        default="linkedin",
        choices=[
            "linkedin",
            "linkedin-recommended",
            "linkedin-top-applicant",
            "linkedin-human-resources",
            "linkedin-it-services-and-it-consulting",
            "linkedin-easy-apply",
            "linkedin-remote-jobs",
            "linkedin-post",
            "itviec",
            "indeed",
            "topcv",
            "careerjet",
            "vietnamworks",
            "glints",
            "remotive",
            "weworkremotely",
            "remoteok",
            "jsremotely",
            "jobright_gmail",
            "all",
        ],
        help="Job board source to scrape from",
    )
    parser.add_argument(
        "--date-posted",
        choices=["all", "day", "week", "month"],
        default="week",
        help="Filter jobs by date posted (default: week)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=999999,
        help="Limit the number of jobs scraped (default: 999999)",
    )
    parser.add_argument(
        "--log",
        action="store_true",
        help="Enable file logging instead of console output",
    )

    args = parser.parse_args()
    run_scrape(args)
