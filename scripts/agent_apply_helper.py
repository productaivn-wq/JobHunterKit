import argparse
import json
import sys
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.db_client import get_connection

SCRATCH_DIR = project_root / "scratch"
CONTEXT_FILE = SCRATCH_DIR / "apply_context.json"
RESULT_FILE = SCRATCH_DIR / "apply_result.json"
CV_FILE = Path("./cv_text.txt")


def get_next():
    SCRATCH_DIR.mkdir(exist_ok=True)

    # 1. Fetch and claim next pending job atomically using FOR UPDATE SKIP LOCKED
    conn = get_connection()
    job = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, company, location, url, source, jd_text
                FROM job_hunter.jobs
                WHERE status_apply = 'pending' AND status_score = 'completed'
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
                # Update status to 'applying' in the same locked transaction
                cur.execute(
                    "UPDATE job_hunter.jobs SET status_apply = 'applying' WHERE id = %s;",
                    (job["id"],),
                )
            conn.commit()
    except Exception as e:
        print(f"ERROR: Database atomic claim failed: {e}", file=sys.stderr)
        if conn:
            conn.rollback()
            conn.close()
        sys.exit(1)
    finally:
        if conn:
            conn.close()

    if not job:
        print("NO_PENDING")
        return

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


def save():
    if not RESULT_FILE.exists():
        print("ERROR: apply_result.json not found", file=sys.stderr)
        sys.exit(1)

    # 1. Read result file
    try:
        result = json.loads(RESULT_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: Failed to read result file: {e}", file=sys.stderr)
        sys.exit(1)

    job_id = result.get("job_id")
    app_status = result.get("status")
    tailored_path = result.get("tailored_cv_path")
    error_msg = result.get("error_message")

    if not job_id:
        print("ERROR: job_id missing in result file", file=sys.stderr)
        sys.exit(1)

    # 2. Update DB
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Insert application record
            cur.execute(
                """
                INSERT INTO job_hunter.applications (job_id, status, tailored_cv_path, error_message)
                VALUES (%s, %s, %s, %s);
                """,
                (job_id, app_status, tailored_path, error_msg),
            )

            # Update job status
            job_status = (
                "completed" if app_status in ("applied", "dry_run") else "failed_manual"
            )
            if app_status == "skipped":
                job_status = "skipped"

            cur.execute(
                "UPDATE job_hunter.jobs SET status_apply = %s WHERE id = %s;",
                (job_status, job_id),
            )
            conn.commit()
            print("SAVED")
    except Exception as e:
        print(f"ERROR: Database update failed: {e}", file=sys.stderr)
        conn.rollback()
        # Fallback: mark job as failed
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE job_hunter.jobs SET status_apply = 'failed_manual' WHERE id = %s;",
                    (job_id,),
                )
                conn.commit()
        except:
            pass
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


def main():
    parser = argparse.ArgumentParser(description="JobHunterKit Subagent Apply Helper")
    parser.add_argument("action", choices=["get_next", "save"])
    args = parser.parse_args()

    if args.action == "get_next":
        get_next()
    elif args.action == "save":
        save()


if __name__ == "__main__":
    main()
