"""
Shared Database Platform Layer for JobHunterKit.
Provides decorators and helpers to handle transaction life cycles and atomic queue operations.
"""

import functools

import psycopg2
import psycopg2.extras

from core.db_client import get_connection


def with_db_transaction(func):
    """
    Decorator that injects a database connection 'conn' into the function's keyword arguments.
    Automatically commits the transaction upon successful return, or rolls back upon an exception.
    Always closes the connection.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        conn = None
        try:
            conn = get_connection()
            kwargs["conn"] = conn
            result = func(*args, **kwargs)
            conn.commit()
            return result
        except Exception as e:
            if conn and not getattr(conn, "closed", False):
                try:
                    conn.rollback()
                except Exception as rb_err:
                    print(f"[WARNING] Database rollback failed: {rb_err}")
            raise e
        finally:
            if conn:
                try:
                    conn.close()
                except Exception as close_err:
                    print(f"[WARNING] Database connection close failed: {close_err}")

    return wrapper


def claim_next_job(
    status_column: str,
    pending_value: str,
    active_value: str,
    extra_where_clause: str = "",
    order_by_clause: str = "",
    job_id: str | None = None,
) -> dict:
    """
    Atomically claims the next job in the queue using SELECT ... FOR UPDATE SKIP LOCKED.
    Returns the job dict, or None if no pending job is available.
    """
    conn = None
    job = None

    where_parts = [
        f"({status_column} = '{pending_value}' OR ({status_column} = '{active_value}' AND claimed_at < NOW() - INTERVAL '30 minutes'))"
    ]
    if extra_where_clause:
        where_parts.append(extra_where_clause)
    if job_id:
        where_parts.append(f"id = '{job_id}'")
    where_sql = " AND ".join(where_parts)

    order_sql = order_by_clause if order_by_clause else "scraped_at ASC"

    query = f"""
        WITH next_job AS (
            SELECT id FROM job_hunter.jobs
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        UPDATE job_hunter.jobs
        SET {status_column} = '{active_value}', claimed_at = NOW()
        FROM next_job
        WHERE job_hunter.jobs.id = next_job.id
        RETURNING job_hunter.jobs.id, job_hunter.jobs.job_key, job_hunter.jobs.title,
                  job_hunter.jobs.company, job_hunter.jobs.location, job_hunter.jobs.url,
                  job_hunter.jobs.source, job_hunter.jobs.jd_text, job_hunter.jobs.scraped_at,
                  job_hunter.jobs.keyword, job_hunter.jobs.search_location, job_hunter.jobs.claimed_at;

    """

    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(query)
            row = cur.fetchone()
            if row:
                job = dict(row)
                job["id"] = str(job["id"])
            conn.commit()
    except Exception as e:
        print(f"[ERROR] Failed to claim next job on {status_column}: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
    return job
