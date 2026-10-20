"""
Migration script to add manual_intervention_reason to database tables.
"""

import sys
from pathlib import Path

# Add project root to python path to import core.db_client
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.db_client import get_connection


def migrate():
    print("Connecting to Supabase PostgreSQL database for migration...")
    try:
        conn = get_connection()
    except Exception as e:
        print(f"[CRITICAL ERROR] Failed to connect: {e}")
        sys.exit(1)

    try:
        with conn.cursor() as cur:
            # 1. Add column to applications
            print(
                "Checking/Adding column 'manual_intervention_reason' to 'job_hunter.applications'..."
            )
            cur.execute("""
                ALTER TABLE job_hunter.applications
                ADD COLUMN IF NOT EXISTS manual_intervention_reason VARCHAR(500);
            """)

            # 2. Add column to jobs
            print(
                "Checking/Adding column 'manual_intervention_reason' to 'job_hunter.jobs'..."
            )
            cur.execute("""
                ALTER TABLE job_hunter.jobs
                ADD COLUMN IF NOT EXISTS manual_intervention_reason VARCHAR(500);
            """)

            conn.commit()
            print("Database migration completed successfully.")

    except Exception as e:
        print(f"[ERROR] Database migration failed: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
