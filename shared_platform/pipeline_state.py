"""
shared_platform/pipeline_state.py — Centralized pipeline pause/resume state.

Backed by a singleton row in job_hunter.pipeline_state (Postgres).
All flows check is_paused() before claiming new jobs.
The IPC daemon polls Telegram for /stop and /start commands.

Design contract:
  - is_paused() FAILS OPEN (returns False) on any DB error, so a transient
    DB hiccup can never silently wedge the entire pipeline.
  - set_paused() and update_id functions propagate exceptions to the caller
    (the daemon), which logs and continues.
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path so core.db_client is importable
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

try:
    from dotenv import load_dotenv

    load_dotenv(_project_root / ".env")
except ImportError:
    pass

from core.db_client import get_connection


def is_paused() -> bool:
    """
    Returns True if the pipeline is currently paused via /stop Telegram command.

    FAILS OPEN: any DB error returns False so a transient DB hiccup never
    silently blocks all flows.
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT is_paused FROM job_hunter.pipeline_state WHERE id = 1;")
            row = cur.fetchone()
            return bool(row[0]) if row else False
    except Exception as e:
        print(
            f"[WARNING] pipeline_state.is_paused() check failed, assuming NOT paused: {e}",
            flush=True,
        )
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def set_paused(paused: bool, actor: str = "telegram") -> None:
    """
    Set the pipeline pause state.

    Args:
        paused: True to pause, False to resume.
        actor: Who triggered the change (e.g. 'telegram:/stop').
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            if paused:
                cur.execute(
                    """
                    UPDATE job_hunter.pipeline_state
                    SET is_paused = TRUE,
                        paused_at = NOW(),
                        paused_by = %s,
                        resumed_at = NULL
                    WHERE id = 1;
                    """,
                    (actor,),
                )
            else:
                cur.execute(
                    """
                    UPDATE job_hunter.pipeline_state
                    SET is_paused = FALSE,
                        resumed_at = NOW(),
                        paused_by = %s
                    WHERE id = 1;
                    """,
                    (actor,),
                )
        conn.commit()
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        raise RuntimeError(f"pipeline_state.set_paused() failed: {e}") from e
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_last_update_id() -> int:
    """Return the last processed Telegram update_id (for offset-based polling)."""
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_update_id FROM job_hunter.pipeline_state WHERE id = 1;"
            )
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
    except Exception as e:
        print(
            f"[WARNING] pipeline_state.get_last_update_id() failed: {e}",
            flush=True,
        )
        return 0
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def set_last_update_id(update_id: int) -> None:
    """Persist the latest processed Telegram update_id to avoid re-processing."""
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE job_hunter.pipeline_state SET last_update_id = %s WHERE id = 1;",
                (update_id,),
            )
        conn.commit()
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        print(
            f"[WARNING] pipeline_state.set_last_update_id() failed: {e}",
            flush=True,
        )
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
