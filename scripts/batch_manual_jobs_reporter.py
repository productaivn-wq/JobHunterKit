"""
scripts/batch_manual_jobs_reporter.py — 30-Minute Batched Manual Job Application Digest.

Gathers all jobs flagged for manual intervention across the last 30 minutes,
performs multimodal screenshot and application route pre-analysis using Gemini Vision,
auto-resolves closed/already applied jobs, and sends a single consolidated, actionable
Telegram digest every 30 minutes instead of per-job alert spam.
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv

load_dotenv(_project_root / ".env")

from core.db_client import get_connection
from core.screenshot_apply_analyzer import (
    analyze_manual_job_screenshot,
    format_manual_job_digest_entry,
)
from shared_platform.logging_setup import checkpointed_function
from shared_platform.notify import send_telegram
from shared_platform.paths import get_job_dirs

logger = logging.getLogger("batch_manual_jobs_reporter")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

DEFAULT_WINDOW_MINUTES = 60
DEFAULT_MAX_JOBS = 20
THROTTLE_FILE = _project_root / "logs" / "last_manual_batch_time.json"


def is_throttled(min_interval_seconds: int = 3600, force: bool = False) -> bool:
    """Checks if less than min_interval_seconds (1 hour) has passed since last dispatch."""
    if force:
        return False
    if THROTTLE_FILE.exists():
        try:
            import json

            with open(THROTTLE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            last_time = data.get("last_dispatched_at", 0)
            elapsed = time.time() - last_time
            if elapsed < min_interval_seconds:
                remaining = int(min_interval_seconds - elapsed)
                logger.info(
                    "Hourly throttling active: %ds remaining until next 1-hour digest window.",
                    remaining,
                )
                return True
        except Exception:
            pass
    return False


def record_dispatch():
    """Records the timestamp of successful batch digest dispatch."""
    try:
        import json

        THROTTLE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(THROTTLE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "last_dispatched_at": time.time(),
                    "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
                f,
            )
    except Exception as e:
        logger.warning("Failed to write batch throttle file: %s", e)


def ensure_manual_queue_table(conn):
    """Ensures manual_application_queue table exists in PostgreSQL."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS job_hunter.manual_application_queue (
                id SERIAL PRIMARY KEY,
                job_id INTEGER REFERENCES job_hunter.jobs(id) ON DELETE CASCADE,
                status VARCHAR(50) DEFAULT 'pending_batch',
                screenshot_path TEXT,
                apply_route VARCHAR(100),
                instructions TEXT,
                detected_email VARCHAR(255),
                detected_url TEXT,
                queued_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                analyzed_at TIMESTAMP WITH TIME ZONE,
                notified_at TIMESTAMP WITH TIME ZONE,
                CONSTRAINT unique_manual_job_id UNIQUE (job_id)
            );
            CREATE INDEX IF NOT EXISTS idx_manual_queue_status_queued ON job_hunter.manual_application_queue(status, queued_at);
            CREATE INDEX IF NOT EXISTS idx_manual_queue_job_id ON job_hunter.manual_application_queue(job_id);
        """)
        conn.commit()


def sync_untracked_manual_jobs(
    conn, window_minutes: int = DEFAULT_WINDOW_MINUTES
) -> int:
    """
    Syncs any jobs from job_hunter.jobs where status_apply = 'needs_manual_intervention'
    that are not yet tracked in job_hunter.manual_application_queue.
    """
    added_count = 0
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO job_hunter.manual_application_queue (job_id, status, queued_at)
            SELECT j.id, 'pending_batch', COALESCE(j.claimed_at, j.scraped_at, NOW())
            FROM job_hunter.jobs j
            WHERE j.status_apply IN ('needs_manual_intervention', 'failed_manual', 'manual_required')
              AND NOT EXISTS (
                  SELECT 1 FROM job_hunter.manual_application_queue q WHERE q.job_id = j.id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM job_hunter.applications a
                  WHERE a.job_id = j.id AND a.status IN ('applied', 'completed', 'dry_run')
              )
            ON CONFLICT (job_id) DO NOTHING;
            """
        )
        rc = cur.rowcount
        added_count = rc if isinstance(rc, int) else 0
        conn.commit()
    return added_count


@checkpointed_function(
    function_id="FL-521", use_case_id="UC-003", node_name="batch_manual_processor"
)
def process_manual_batch(
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
    max_jobs: int = DEFAULT_MAX_JOBS,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """
    Main batch processing workflow:
    1. Synchronize untracked manual intervention jobs into queue.
    2. Fetch pending manual jobs.
    3. Run multimodal screenshot pre-analysis on each.
    4. Auto-resolve closed / already-applied jobs.
    5. Aggregate remaining manual jobs into a consolidated Telegram digest.
    6. Update notification timestamps.
    """
    if is_throttled(force=force):
        logger.info(
            "Skipping batch manual digest: Hourly throttle active (<3600s since last run)."
        )
        return {"status": "throttled", "reported_count": 0, "auto_healed_count": 0}

    conn = get_connection()
    try:
        ensure_manual_queue_table(conn)
        synced = sync_untracked_manual_jobs(conn, window_minutes=window_minutes)
        if synced > 0:
            logger.info(
                "Synced %d untracked manual intervention jobs into queue.", synced
            )

        # Query pending manual jobs
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    q.id AS queue_id,
                    j.id AS job_id,
                    j.company,
                    j.title,
                    j.url,
                    j.source,
                    j.jd_text,
                    j.keyword,
                    j.search_location,
                    j.scraped_at,
                    q.screenshot_path,
                    q.apply_route,
                    q.instructions,
                    q.detected_email,
                    q.detected_url,
                    q.analyzed_at,
                    s.match_score,
                    a.tailored_cv_path
                FROM job_hunter.manual_application_queue q
                JOIN job_hunter.jobs j ON q.job_id = j.id
                LEFT JOIN job_hunter.scores s ON s.job_id = j.id
                LEFT JOIN LATERAL (
                    SELECT tailored_cv_path FROM job_hunter.applications
                    WHERE job_id = j.id ORDER BY id DESC LIMIT 1
                ) a ON true
                WHERE q.status = 'pending_batch'
                ORDER BY q.queued_at ASC
                LIMIT %s;
                """,
                (max_jobs,),
            )
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()

        pending_items = [dict(zip(columns, row)) for row in rows]
        if not pending_items:
            logger.info(
                "No pending manual application jobs to report in this 1-hour cycle."
            )
            return {"status": "empty", "reported_count": 0, "auto_healed_count": 0}

        logger.info(
            "Found %d pending manual job(s) for 1-hour batch processing.",
            len(pending_items),
        )

        actionable_jobs = []
        auto_healed_count = 0
        skipped_closed_count = 0

        for item in pending_items:
            job_dict = {
                "id": item["job_id"],
                "company": item["company"],
                "title": item["title"],
                "url": item["url"],
                "source": item["source"],
                "jd_text": item["jd_text"],
                "keyword": item["keyword"],
                "search_location": item["search_location"],
                "scraped_at": item["scraped_at"],
            }
            dirs = get_job_dirs(job_dict)

            # Step 0: Fast Text-based Expired Pre-Check
            from core.company_extractor import is_jd_text_expired

            is_expired_text, exp_text_reason = is_jd_text_expired(
                item.get("jd_text") or "", item.get("title") or ""
            )
            if is_expired_text:
                logger.info(
                    "Job ID %s (%s @ %s) was detected as CLOSED/EXPIRED (%s). Skipping...",
                    item["job_id"],
                    item["title"],
                    item["company"],
                    exp_text_reason,
                )
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE job_hunter.jobs SET status_apply = 'skipped', status_score = 'skipped_expired' WHERE id = %s;",
                        (item["job_id"],),
                    )
                    cur.execute(
                        "UPDATE job_hunter.manual_application_queue SET status = 'skipped', analyzed_at = NOW(), instructions = %s WHERE id = %s;",
                        (f"Closed/expired: {exp_text_reason}", item["queue_id"]),
                    )
                    conn.commit()
                skipped_closed_count += 1
                continue

            # Step 1: Pre-analyze screenshot if not already analyzed
            needs_analysis = not item.get("analyzed_at") or not item.get("instructions")
            if needs_analysis:
                logger.info(
                    "Analyzing screenshot for Job ID %s (%s @ %s)...",
                    item["job_id"],
                    item["title"],
                    item["company"],
                )
                analysis = analyze_manual_job_screenshot(
                    job_dict, screenshot_path=item.get("screenshot_path"), dirs=dirs
                )

                # Update item fields from analysis
                item["screenshot_path"] = analysis.get("screenshot_path")
                item["apply_route"] = analysis.get("route_type")
                item["instructions"] = analysis.get("actionable_instructions")
                item["detected_email"] = (
                    ", ".join(analysis.get("detected_emails", [])) or None
                )
                item["detected_url"] = analysis.get("detected_url")

                # Check for auto-healing resolutions
                if analysis.get("is_already_applied"):
                    logger.info(
                        "Job ID %s was auto-detected as ALREADY APPLIED via screenshot. Resolving...",
                        item["job_id"],
                    )
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE job_hunter.jobs SET status_apply = 'completed' WHERE id = %s;",
                            (item["job_id"],),
                        )
                        cur.execute(
                            "UPDATE job_hunter.manual_application_queue SET status = 'auto_healed', analyzed_at = NOW(), instructions = %s WHERE id = %s;",
                            (analysis.get("actionable_instructions"), item["queue_id"]),
                        )
                        conn.commit()
                    auto_healed_count += 1
                    continue

                if (
                    analysis.get("is_job_closed")
                    or analysis.get("route_type") == "JOB_CLOSED"
                ):
                    logger.info(
                        "Job ID %s was auto-detected as JOB CLOSED via screenshot. Skipping...",
                        item["job_id"],
                    )
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE job_hunter.jobs SET status_apply = 'skipped', status_score = 'skipped_expired' WHERE id = %s;",
                            (item["job_id"],),
                        )
                        cur.execute(
                            "UPDATE job_hunter.manual_application_queue SET status = 'skipped', analyzed_at = NOW(), instructions = %s WHERE id = %s;",
                            (analysis.get("actionable_instructions"), item["queue_id"]),
                        )
                        conn.commit()
                    skipped_closed_count += 1
                    continue

                # Save analysis back to DB
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE job_hunter.manual_application_queue
                        SET screenshot_path = %s,
                            apply_route = %s,
                            instructions = %s,
                            detected_email = %s,
                            detected_url = %s,
                            analyzed_at = NOW()
                        WHERE id = %s;
                        """,
                        (
                            item["screenshot_path"],
                            item["apply_route"],
                            item["instructions"],
                            item["detected_email"],
                            item["detected_url"],
                            item["queue_id"],
                        ),
                    )
                    conn.commit()
            else:
                analysis = {
                    "company": item["company"],
                    "title": item["title"],
                    "url": item["url"],
                    "route_type": item["apply_route"],
                    "actionable_instructions": item["instructions"],
                    "detected_emails": [
                        e.strip() for e in item["detected_email"].split(",")
                    ]
                    if item.get("detected_email")
                    else [],
                    "detected_url": item.get("detected_url"),
                }

            # Add to actionable list
            item["analysis"] = analysis
            actionable_jobs.append(item)

        if not actionable_jobs:
            logger.info(
                "All %d jobs were auto-resolved (healed: %d, closed: %d). No manual digest needed.",
                len(pending_items),
                auto_healed_count,
                skipped_closed_count,
            )
            return {
                "status": "auto_resolved",
                "reported_count": 0,
                "auto_healed_count": auto_healed_count,
                "skipped_closed_count": skipped_closed_count,
            }

        # Step 2: Format aggregated Telegram digest
        header = (
            f"📋 <b>JobHunterKit — Hourly Manual Application Digest</b>\n"
            f"⏱ <i>Gathered across the last 1 hour ({len(actionable_jobs)} jobs need manual action)</i>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        entries = []
        for idx, item in enumerate(actionable_jobs, start=1):
            entry = format_manual_job_digest_entry(
                idx=idx,
                analysis=item["analysis"],
                tailored_cv_path=item.get("tailored_cv_path"),
            )
            entries.append(entry)

        footer = (
            "\n━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>All jobs pre-screened with descriptive & diagnostic screenshot analysis. Next batch in 1 hour.</i>"
        )

        # Check message length and chunk if necessary (Telegram 4096 character limit)
        full_message = header + "\n\n".join(entries) + footer
        messages_to_send = []
        if len(full_message) <= 3900:
            messages_to_send.append(full_message)
        else:
            # Chunk entries across multiple messages
            current_entries = []
            current_len = len(header)
            part_num = 1
            for entry in entries:
                if current_len + len(entry) + 50 > 3800:
                    part_header = header.replace(
                        "Digest</b>", f"Digest (Part {part_num})</b>"
                    )
                    messages_to_send.append(part_header + "\n\n".join(current_entries))
                    current_entries = [entry]
                    current_len = len(header) + len(entry)
                    part_num += 1
                else:
                    current_entries.append(entry)
                    current_len += len(entry) + 2
            if current_entries:
                part_header = header.replace(
                    "Digest</b>", f"Digest (Part {part_num})</b>"
                )
                messages_to_send.append(
                    part_header + "\n\n".join(current_entries) + footer
                )

        # Step 3: Send via Telegram
        if dry_run:
            logger.info(
                "[DRY RUN] Would send %d Telegram message chunk(s):",
                len(messages_to_send),
            )
            for i, msg in enumerate(messages_to_send, start=1):
                print(f"\n--- [MESSAGE CHUNK {i}] ---\n{msg}\n")
        else:
            for msg in messages_to_send:
                send_telegram(msg)
                time.sleep(1.0)

            # Step 4: Mark queue items as notified
            queue_ids = [item["queue_id"] for item in actionable_jobs]
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE job_hunter.manual_application_queue
                    SET status = 'notified', notified_at = NOW()
                    WHERE id = ANY(%s);
                    """,
                    (queue_ids,),
                )
                conn.commit()
            record_dispatch()

        logger.info(
            "Successfully processed manual batch: %d reported, %d auto-healed, %d closed.",
            len(actionable_jobs),
            auto_healed_count,
            skipped_closed_count,
        )

        return {
            "status": "success",
            "reported_count": len(actionable_jobs),
            "auto_healed_count": auto_healed_count,
            "skipped_closed_count": skipped_closed_count,
        }

    except Exception as e:
        logger.error("Error in process_manual_batch: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        conn.close()


def _parse_args():
    parser = argparse.ArgumentParser(
        description="30-Minute Batched Manual Job Application Digest with Screenshot Analysis"
    )
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=DEFAULT_WINDOW_MINUTES,
        help=f"Aggregation window in minutes (default: {DEFAULT_WINDOW_MINUTES})",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=DEFAULT_MAX_JOBS,
        help=f"Maximum manual jobs per batch (default: {DEFAULT_MAX_JOBS})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate and print batch digest without sending Telegram or updating DB",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force execution regardless of schedule",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    process_manual_batch(
        window_minutes=args.window_minutes,
        max_jobs=args.max_jobs,
        dry_run=args.dry_run,
        force=args.force,
    )
