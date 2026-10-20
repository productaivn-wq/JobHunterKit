"""
scripts/sync_channel_trackers.py — Synchronizes channel application trackers with PostgreSQL.

Connects to LinkedIn, ITViec, and TopCV applied dashboards using session state,
fetches ground truth, and reconciles database records to eliminate false positives.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(project_root / "scripts") not in sys.path:
    sys.path.insert(0, str(project_root / "scripts"))

from core.channel_tracker import (
    is_job_verified_by_channel_tracker,
    scrape_itviec_applied_tracker,
    scrape_linkedin_applied_tracker,
    scrape_topcv_applied_tracker,
)
from core.db_client import get_connection
from shared_platform.paths import STORAGE_ROOT

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("sync_channel_trackers")


def sync_trackers(dry_run: bool = False, channel: str | None = None):
    logger.info("=== Starting Sourcing Channel Ground-Truth Synchronization ===")

    applied_data = {
        "linkedin": [],
        "itviec": [],
        "topcv": [],
    }

    from playwright.sync_api import sync_playwright

    state_file = project_root / "scripts" / "state.json"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = (
            browser.new_context(storage_state=str(state_file))
            if state_file.exists()
            else browser.new_context()
        )
        page = context.new_page()

        try:
            if not channel or channel == "linkedin":
                logger.info("--- Syncing LinkedIn Applied Tracker ---")
                applied_data["linkedin"] = scrape_linkedin_applied_tracker(page)

            if not channel or channel == "itviec":
                logger.info("--- Syncing ITViec Applied Tracker ---")
                applied_data["itviec"] = scrape_itviec_applied_tracker(page)

            if not channel or channel == "topcv":
                logger.info("--- Syncing TopCV Applied History ---")
                applied_data["topcv"] = scrape_topcv_applied_tracker(page)

        finally:
            context.close()
            browser.close()

    # Save to disk as snapshot
    out_dir = Path(STORAGE_ROOT) / "trackers"
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_file = out_dir / "channel_applied_ground_truth.json"
    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump(applied_data, f, indent=2, ensure_ascii=False)
    logger.info("Saved channel ground-truth snapshot to %s", snapshot_file)

    # Reconcile DB
    reconcile_database(applied_data, dry_run=dry_run)


def reconcile_database(applied_data: dict[str, list[dict]], dry_run: bool = False):
    logger.info("=== Reconciling PostgreSQL Database against Channel Ground Truth ===")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Query all jobs currently marked as 'completed' in jobs table
            cur.execute("""
                SELECT id, company, title, url, source, status_apply
                FROM job_hunter.jobs
                WHERE status_apply = 'completed';
            """)
            completed_jobs = cur.fetchall()
            logger.info(
                "Auditing %d jobs with status_apply='completed' in DB...",
                len(completed_jobs),
            )

            demoted_count = 0
            verified_count = 0

            for job_id, company, title, url, source, status_apply in completed_jobs:
                job_dict = {
                    "id": job_id,
                    "company": company,
                    "title": title,
                    "url": url,
                    "source": source,
                }

                # Match against relevant channel ground truth
                channel_key = (
                    "linkedin"
                    if "linkedin" in (source or "").lower()
                    else (
                        "itviec"
                        if "itviec" in (source or "").lower()
                        else ("topcv" if "topcv" in (source or "").lower() else None)
                    )
                )

                if channel_key and applied_data.get(channel_key):
                    is_verified, match_reason = is_job_verified_by_channel_tracker(
                        job_dict, applied_data[channel_key]
                    )
                else:
                    is_verified = False
                    match_reason = "No tracker data available for channel"

                if is_verified:
                    verified_count += 1
                    logger.info(
                        "  [CONFIRMED VERIFIED] Job #%d (%s - %s): %s",
                        job_id,
                        company,
                        title,
                        match_reason,
                    )
                else:
                    demoted_count += 1
                    logger.warning(
                        "  [FALSE POSITIVE DETECTED] Job #%d (%s - %s) not confirmed by channel tracker. Demoting to pending for re-apply.",
                        job_id,
                        company,
                        title,
                    )
                    if not dry_run:
                        cur.execute(
                            """
                            UPDATE job_hunter.jobs
                            SET status_apply = 'pending',
                                manual_intervention_reason = 'Channel tracker reconciliation: submission not confirmed on platform, reset to pending',
                                apply_attempts = 0
                            WHERE id = %s;
                        """,
                            (job_id,),
                        )
                        cur.execute(
                            """
                            UPDATE job_hunter.applications
                            SET status = 'pending_retry',
                                manual_intervention_reason = 'Channel tracker reconciliation: submission not confirmed on platform, reset to pending'
                            WHERE job_id = %s AND status IN ('applied', 'completed');
                        """,
                            (job_id,),
                        )

            if not dry_run:
                conn.commit()
                logger.info(
                    "Reconciliation committed: %d verified confirmed, %d false-positives demoted.",
                    verified_count,
                    demoted_count,
                )
            else:
                logger.info(
                    "Reconciliation complete (DRY RUN): %d verified confirmed, %d false-positives demoted.",
                    verified_count,
                    demoted_count,
                )

    except Exception as e:
        logger.error("Database reconciliation failed: %s", e)
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sync channel trackers with PostgreSQL"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Run without modifying database"
    )
    parser.add_argument(
        "--channel",
        choices=["linkedin", "itviec", "topcv"],
        help="Specific channel to sync",
    )
    args = parser.parse_args()

    sync_trackers(dry_run=args.dry_run, channel=args.channel)
