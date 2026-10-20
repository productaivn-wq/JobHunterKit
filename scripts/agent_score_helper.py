"""
agent_score_helper.py — Subagent Scoring Helper for JobHunterKit.

Provides atomic job claiming (`get_next`) and scoring outcome persistence (`save`)
with transactional PostgreSQL status transitions.
"""

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.db_client import get_connection

SCRATCH_DIR = project_root / "scratch"
suffix = os.environ.get("SCORE_SUFFIX", "")
CONTEXT_FILE = SCRATCH_DIR / f"scoring_context{suffix}.json"
RESULT_FILE = SCRATCH_DIR / f"score_result{suffix}.json"
CV_FILE = Path(os.environ.get("JOB_HUNTER_CV_PATH", str(project_root / "cv_text.txt")))
if not CV_FILE.exists():
    fallback_cv = Path("./cv_text.txt")
    if fallback_cv.exists():
        CV_FILE = fallback_cv


def log_progress(message: str, level: str = "INFO") -> None:
    """Logs progress events as structured JSON lines to logs/flow2.log."""
    logs_dir = project_root / "logs"
    logs_dir.mkdir(exist_ok=True)
    log_file = logs_dir / "flow2.log"
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    event = {"timestamp": now_str, "level": level.upper(), "message": message}
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception as e:
        print(f"Failed to write progress log: {e}", file=sys.stderr)


def get_next() -> None:
    """Claims the next pending job from PostgreSQL and prepares context file."""
    SCRATCH_DIR.mkdir(exist_ok=True)

    # 1. Fetch next pending job
    conn = get_connection()
    job = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, company, location, url, source, jd_text
                FROM job_hunter.jobs
                WHERE status_score = 'pending'
                ORDER BY scraped_at DESC
                LIMIT 1
                FOR UPDATE SKIP LOCKED;
                """
            )
            row = cur.fetchone()
            if row:
                job = {
                    "id": str(row[0]),
                    "title": row[1],
                    "company": row[2],
                    "location": row[3],
                    "url": row[4],
                    "source": row[5],
                    "jd_text": row[6],
                }
    except Exception as e:
        print(f"ERROR: Failed to fetch next job: {e}", file=sys.stderr)
        log_progress(f"Scoring helper: Failed to fetch next job: {e}", level="ERROR")
        conn.close()
        sys.exit(1)

    if not job:
        print("NO_PENDING")
        log_progress("Scoring helper: NO_PENDING")
        conn.close()
        return

    # 2. Update status to 'scoring'
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE job_hunter.jobs SET status_score = 'scoring' WHERE id = %s;",
                (job["id"],),
            )
            conn.commit()
            log_progress(
                f"Scoring helper claimed job: ID {job['id']} - {job['title']} at {job['company']}"
            )
    except Exception as e:
        print(f"ERROR: Failed to update job status to scoring: {e}", file=sys.stderr)
        log_progress(
            f"Scoring helper: Failed to update job status to scoring for job ID {job['id']}: {e}",
            level="ERROR",
        )
        conn.rollback()
        conn.close()
        sys.exit(1)
    finally:
        conn.close()

    # 3. Read CV text
    cv_text = ""
    if CV_FILE.exists():
        try:
            cv_text = CV_FILE.read_text(encoding="utf-8")
        except Exception as e:
            print(f"ERROR: Failed to read CV file: {e}", file=sys.stderr)
    else:
        print(f"ERROR: CV file not found at {CV_FILE}", file=sys.stderr)

    # 4. Write context file
    context = {"job": job, "cv_text": cv_text}
    try:
        CONTEXT_FILE.write_text(
            json.dumps(context, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print("GOT_JOB")
    except Exception as e:
        print(f"ERROR: Failed to write context file: {e}", file=sys.stderr)
        sys.exit(1)


def save() -> None:
    """Persists scoring outcomes to the database and cleans up scratch files."""
    if not RESULT_FILE.exists():
        print("ERROR: score_result.json not found", file=sys.stderr)
        sys.exit(1)

    # 1. Read result file
    try:
        result = json.loads(RESULT_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: Failed to read result file: {e}", file=sys.stderr)
        sys.exit(1)

    job_id = result.get("job_id")
    match_score = result.get("match_score", 0)
    reasoning = result.get("overall_reasoning", "")
    top_strengths = result.get("top_strengths", [])
    key_gaps = result.get("key_gaps", [])
    rubric_used = result.get("rubric_used", {})
    pass_threshold = result.get("pass_threshold", 70)

    if not job_id:
        print("ERROR: job_id missing in result file", file=sys.stderr)
        sys.exit(1)

    # 2. Update DB
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Delete existing score for the job if any
            cur.execute("DELETE FROM job_hunter.scores WHERE job_id = %s;", (job_id,))

            # Insert score record
            cur.execute(
                """
                INSERT INTO job_hunter.scores (job_id, match_score, reasoning, rubric_used, top_strengths, key_gaps)
                VALUES (%s, %s, %s, %s, %s, %s);
                """,
                (
                    job_id,
                    match_score,
                    reasoning,
                    json.dumps(rubric_used),
                    json.dumps(top_strengths),
                    json.dumps(key_gaps),
                ),
            )

            # Update job status
            success = match_score >= pass_threshold
            status_score = "completed"
            status_apply = "pending" if success else "skipped"

            cur.execute(
                "UPDATE job_hunter.jobs SET status_score = %s, status_apply = %s WHERE id = %s;",
                (status_score, status_apply, job_id),
            )
            conn.commit()
            print("SAVED")
            log_progress(
                f"Scoring helper saved result for job ID {job_id}: score={match_score}"
            )
    except Exception as e:
        print(f"ERROR: Database update failed: {e}", file=sys.stderr)
        log_progress(
            f"Scoring helper: Database update failed for job ID {job_id}: {e}",
            level="ERROR",
        )
        conn.rollback()
        # Fallback: mark job as failed
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE job_hunter.jobs SET status_score = 'failed' WHERE id = %s;",
                    (job_id,),
                )
                conn.commit()
        except Exception as fb_err:
            log_progress(f"Fallback failure: {fb_err}", level="ERROR")
        conn.close()
        sys.exit(1)
    finally:
        conn.close()

    # 3. Clean up files
    try:
        if CONTEXT_FILE.exists():
            CONTEXT_FILE.unlink()
        if RESULT_FILE.exists():
            RESULT_FILE.unlink()
    except Exception as e:
        print(f"WARNING: Failed to clean up files: {e}", file=sys.stderr)


def main() -> None:
    """CLI dispatcher for subagent scoring helper actions."""
    parser = argparse.ArgumentParser(description="JobHunterKit Subagent Scoring Helper")
    parser.add_argument("action", choices=["get_next", "save"])
    args = parser.parse_args()

    if args.action == "get_next":
        get_next()
    elif args.action == "save":
        save()


if __name__ == "__main__":
    main()
