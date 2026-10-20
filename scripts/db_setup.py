"""
Database setup script for JobHunterKit.
Initializes the schema, tables, and indices in Supabase/PostgreSQL.
"""

import sys
from pathlib import Path

# Add project root to python path to import core.db_client
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.db_client import get_connection


def setup_database():
    print("Connecting to Supabase PostgreSQL database...")
    try:
        conn = get_connection()
    except Exception as e:
        print(f"[CRITICAL ERROR] Failed to connect: {e}")
        sys.exit(1)

    try:
        with conn.cursor() as cur:
            # 1. Create Schema
            print("Creating schema 'job_hunter' if not exists...")
            cur.execute("CREATE SCHEMA IF NOT EXISTS job_hunter;")

            # 2. Create jobs table
            print("Creating table 'job_hunter.jobs' if not exists...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS job_hunter.jobs (
                    id SERIAL PRIMARY KEY,
                    job_key VARCHAR(512) UNIQUE NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    company VARCHAR(255) NOT NULL,
                    location VARCHAR(255),
                    url TEXT NOT NULL,
                    source VARCHAR(100) NOT NULL,
                    jd_text TEXT,
                    scraped_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    status_score VARCHAR(50) DEFAULT 'pending',
                    status_apply VARCHAR(50) DEFAULT 'pending',
                    keyword VARCHAR(255),
                    search_location VARCHAR(255),
                    manual_intervention_reason VARCHAR(500),
                    claimed_at TIMESTAMP WITH TIME ZONE
                );
                ALTER TABLE job_hunter.jobs ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMP WITH TIME ZONE;
            """)

            # 3. Create scores table
            print("Creating table 'job_hunter.scores' if not exists...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS job_hunter.scores (
                    id SERIAL PRIMARY KEY,
                    job_id INTEGER REFERENCES job_hunter.jobs(id) ON DELETE CASCADE,
                    match_score INTEGER NOT NULL,
                    reasoning TEXT,
                    rubric_used JSONB,
                    top_strengths JSONB,
                    key_gaps JSONB,
                    scored_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 4. Create applications table
            print("Creating table 'job_hunter.applications' if not exists...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS job_hunter.applications (
                    id SERIAL PRIMARY KEY,
                    job_id INTEGER REFERENCES job_hunter.jobs(id) ON DELETE CASCADE,
                    status VARCHAR(50) NOT NULL,
                    tailored_cv_path TEXT,
                    screener_answers JSONB,
                    error_message TEXT,
                    applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    manual_intervention_reason VARCHAR(500)
                );
            """)

            # 5. Create discovered_channels table
            print("Creating table 'job_hunter.discovered_channels' if not exists...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS job_hunter.discovered_channels (
                    id SERIAL PRIMARY KEY,
                    domain VARCHAR(255) UNIQUE NOT NULL,
                    example_url TEXT,
                    first_detected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    source_job_id INTEGER REFERENCES job_hunter.jobs(id) ON DELETE SET NULL
                );
            """)

            # 6. Create indices
            print("Creating indices...")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_status_score ON job_hunter.jobs(status_score);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_status_apply ON job_hunter.jobs(status_apply);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_job_key ON job_hunter.jobs(job_key);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_discovered_channels_domain ON job_hunter.discovered_channels(domain);"
            )

            # 7. Create pipeline_state table (singleton row for Telegram /stop//start control)
            print("Creating table 'job_hunter.pipeline_state' if not exists...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS job_hunter.pipeline_state (
                    id SMALLINT PRIMARY KEY DEFAULT 1,
                    is_paused BOOLEAN NOT NULL DEFAULT FALSE,
                    paused_at TIMESTAMP WITH TIME ZONE,
                    paused_by TEXT,
                    resumed_at TIMESTAMP WITH TIME ZONE,
                    last_update_id BIGINT DEFAULT 0,
                    CONSTRAINT pipeline_state_singleton CHECK (id = 1)
                );
            """)
            cur.execute(
                "INSERT INTO job_hunter.pipeline_state (id, is_paused) "
                "VALUES (1, FALSE) ON CONFLICT (id) DO NOTHING;"
            )

            conn.commit()

            print("Database setup completed successfully.")

    except Exception as e:
        print(f"[ERROR] Database setup failed: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    setup_database()
