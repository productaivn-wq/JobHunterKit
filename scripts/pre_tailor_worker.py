import os
import re
import subprocess
import sys
import traceback
from pathlib import Path

import psycopg2
import psycopg2.extras

# Force stdout/stderr to use UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "scripts"))

from flow_apply import get_job_dirs

from core.db_client import get_connection


def main():
    print("=== CV Pre-Tailoring Worker Started ===", flush=True)

    # 1. Query pending jobs from database with query retry logic
    import time

    pending_jobs = []
    max_query_attempts = 3
    for attempt in range(max_query_attempts):
        conn = None
        try:
            conn = get_connection()
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    "SELECT id, job_key, title, company, location, url, source, jd_text, scraped_at, keyword, search_location "
                    "FROM job_hunter.jobs "
                    "WHERE status_apply = 'pending' AND status_score = 'completed' "
                    "ORDER BY id DESC;"
                )
                for row in cur.fetchall():
                    j = dict(row)
                    j["id"] = str(j["id"])
                    pending_jobs.append(j)
            break  # Success!
        except Exception as e:
            print(f"[WARNING] Query attempt {attempt + 1} failed: {e}", flush=True)
            if attempt == max_query_attempts - 1:
                print(
                    f"[ERROR] Failed to query pending jobs after {max_query_attempts} attempts: {e}",
                    flush=True,
                )
                sys.exit(1)
            time.sleep(2)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    if not pending_jobs:
        print("No pending applications found. Exiting.", flush=True)
        return

    print(f"Found {len(pending_jobs)} jobs to check for pre-tailoring...", flush=True)

    cv_file = r"d:\WORK\\01_PROJECTS\\46_JOB_HUNTER\cv_and_profiles\cv_text.txt"
    python_exe = sys.executable or "python"

    for job in pending_jobs:
        try:
            dirs = get_job_dirs(job)
            company_safe = re.sub(r"[^\w]", "_", job["company"])
            pdf_name = f"{company_safe}__{job['id']}.pdf"
            pdf_path = os.path.join(dirs["tailored_dir"], pdf_name)

            # Check if PDF already exists and is non-empty
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                print(
                    f"[CACHED] Job ID {job['id']} already has tailored CV at {pdf_path}",
                    flush=True,
                )
                continue

            print(
                f"\n--- Pre-tailoring Job ID {job['id']}: {job['title']} @ {job['company']} ---",
                flush=True,
            )

            # Write JD text to temp scratch file
            scratch_dir = project_root / "scratch"
            scratch_dir.mkdir(exist_ok=True)
            jd_file = scratch_dir / f"{job['id']}_jd.txt"
            with open(jd_file, "w", encoding="utf-8") as f:
                f.write(job["jd_text"] or "")

            # Execute tailor_jd.py
            tailor_script = project_root / "scripts" / "tailor_jd.py"
            cmd = [
                python_exe,
                str(tailor_script),
                "--job-id",
                str(job["id"]),
                "--jd-file",
                str(jd_file),
                "--cv-file",
                cv_file,
                "--output-pdf",
                pdf_path,
            ]
            print(f"Running command: {' '.join(cmd)}", flush=True)

            # Run tailoring subprocess
            creationflags = (
                subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                creationflags=creationflags,
            )
            print(f"Stdout:\n{result.stdout}", flush=True)
            if result.stderr:
                print(f"Stderr:\n{result.stderr}", flush=True)

            if result.returncode == 0:
                print(f"[SUCCESS] Pre-tailored CV for job {job['id']}", flush=True)
            else:
                print(
                    f"[ERROR] Failed to pre-tailor job {job['id']} (Exit code {result.returncode})",
                    flush=True,
                )

            # Cleanup temp JD file
            try:
                if jd_file.exists():
                    jd_file.unlink()
            except Exception:
                pass

        except Exception as e:
            print(f"[ERROR] Exception processing job {job['id']}: {e}", flush=True)
            traceback.print_exc()

    print("\n=== CV Pre-Tailoring Worker Finished ===", flush=True)


if __name__ == "__main__":
    main()
