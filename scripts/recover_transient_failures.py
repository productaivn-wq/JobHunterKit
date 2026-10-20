import json
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv


def recover():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    # Load environment variables
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    env_path = project_root / ".env"

    if env_path.exists():
        print(f"Loading environment from {env_path}")
        load_dotenv(env_path)
    else:
        print(f"Error: .env file not found at {env_path}")
        sys.exit(1)

    db_url = os.getenv("DB_URL")
    if not db_url:
        print("Error: DB_URL is not set.")
        sys.exit(1)

    # 1. Connect to PostgreSQL and fetch failed jobs to recover
    print("Connecting to Supabase PostgreSQL database...")
    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        print(f"Database connection failed: {e}")
        sys.exit(1)

    failed_job_keys = []
    try:
        with conn.cursor() as cur:
            # Get failed applications (Only recover genuine transient network/closed errors, NOT infinite loops or permanent manual states)
            # Cap at < 2 attempts to strictly prevent zombie retry loops
            cur.execute("""
                SELECT id, title, company 
                FROM job_hunter.jobs 
                WHERE status_apply IN ('failed', 'failed_manual')
                  AND scraped_at >= NOW() - INTERVAL '7 days'
                  AND (apply_attempts IS NULL OR apply_attempts < 2)
                  AND (
                      manual_intervention_reason IS NULL 
                      OR (
                          (manual_intervention_reason ILIKE '%error%' 
                           OR manual_intervention_reason ILIKE '%timeout%' 
                           OR manual_intervention_reason ILIKE '%closed%' 
                           OR manual_intervention_reason ILIKE '%network%')
                          AND manual_intervention_reason NOT ILIKE '%maximum iterations%'
                          AND manual_intervention_reason NOT ILIKE '%loop%'
                          AND manual_intervention_reason NOT ILIKE '%stuck%'
                          AND manual_intervention_reason NOT ILIKE '%captcha%'
                      )
                  )
                  AND id NOT IN (SELECT job_id FROM job_hunter.applications WHERE status IN ('applied', 'completed', 'dry_run'));
            """)
            failed_apply = cur.fetchall()
            print(f"Found {len(failed_apply)} recoverable failed application jobs in DB.")
            for row in failed_apply:
                job_key = f"{row[1].strip()} @ {row[2].strip()}".lower()
                print(f"  - DB Job ID: {row[0]} | Job Key: '{job_key}'")
                failed_job_keys.append(job_key)

            # Also get failed scoring jobs
            cur.execute(
                "SELECT id, title, company FROM job_hunter.jobs WHERE status_score = 'failed';"
            )
            failed_score = cur.fetchall()
            print(f"Found {len(failed_score)} failed scoring jobs in DB.")
            for row in failed_score:
                print(f"  - DB Job ID: {row[0]} | Title: {row[1]} | Company: {row[2]}")

            if failed_apply or failed_score:
                # Reset status in DB with incremented attempt counter
                if failed_apply:
                    apply_ids = [r[0] for r in failed_apply]
                    cur.execute(
                        "UPDATE job_hunter.jobs SET status_apply = 'pending', manual_intervention_reason = NULL, apply_attempts = COALESCE(apply_attempts, 0) + 1 WHERE id = ANY(%s);",
                        (apply_ids,),
                    )
                    print(f"Reset {cur.rowcount} status_apply states to 'pending'.")
                if failed_score:
                    cur.execute(
                        "UPDATE job_hunter.jobs SET status_score = 'pending' WHERE status_score = 'failed';"
                    )
                    print(f"Reset {cur.rowcount} status_score states to 'pending'.")
                conn.commit()
            else:
                print("No failed states to reset in DB.")

    except Exception as e:
        print(f"DB update error: {e}")
        conn.rollback()
        conn.close()
        sys.exit(1)
    finally:
        conn.close()

    # 2. Update local history file applied_history.json
    history_file = project_root / "data" / "applied_history.json"
    if history_file.exists() and failed_job_keys:
        print(f"Reading local history file: {history_file}")
        try:
            with open(history_file, encoding="utf-8") as hf:
                history = json.load(hf)
        except Exception as e:
            print(f"Failed to read/parse applied_history.json: {e}")
            sys.exit(1)

        if isinstance(history, list):
            new_history = []
            pruned_count = 0
            for record in history:
                job_key = record.get("job_key", "").strip().lower()
                if job_key in failed_job_keys:
                    status = record.get("status", "")
                    if any(
                        s in status
                        for s in ("Failed", "Stuck", "Error", "Manual Required")
                    ):
                        print(
                            f"  Pruning local history record for job key: '{record.get('job_key')}' (status: {status})"
                        )
                        pruned_count += 1
                        continue
                new_history.append(record)

            if pruned_count > 0:
                tmp_history_file = history_file.with_suffix(".tmp")
                try:
                    with open(tmp_history_file, "w", encoding="utf-8") as tf:
                        json.dump(new_history, tf, ensure_ascii=False, indent=2)
                    os.replace(tmp_history_file, history_file)
                    print(
                        f"Successfully updated applied_history.json: pruned {pruned_count} entries."
                    )
                except Exception as e:
                    print(f"Failed to write history file: {e}")
                    if tmp_history_file.exists():
                        try:
                            tmp_history_file.unlink()
                        except Exception:
                            pass
            else:
                print(
                    "No matching failed records found in applied_history.json to prune."
                )
        else:
            print("applied_history.json is not a JSON list as expected.")
    else:
        print("applied_history.json not found or no jobs to prune.")

    print("\nRecovery Completed Successfully!")


if __name__ == "__main__":
    recover()
