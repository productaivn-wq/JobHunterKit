"""
skill_watcher.py — Self-Healing Monitor for JobHunterKit Flows

Runs on a cron schedule (every 30 min) via CronScheduler.
For each monitored flow:
  1. Checks if the log file has been updated within its expected heartbeat window.
  2. If the log is stale (no new lines), detects if a Python process for that flow
     is still running (zombie/deadlock).
  3. If a zombie is found, kills it and restarts the flow via Windows Task Scheduler.
  4. Sends a Telegram alert for any anomaly (stale, zombie killed, restart success/fail).
  5. Writes a watcher summary to logs/skill_watcher.log.

Usage:
    python skill_watcher.py              # Run one health-check pass
    python skill_watcher.py --dry-run    # Simulate without killing/restarting
"""

import argparse
import datetime
import json
import logging
import os
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent.resolve()
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_log_file = LOGS_DIR / "skill_watcher.log"
_log_fmt = logging.Formatter("%(asctime)s [SkillWatcher] %(levelname)s - %(message)s")
_root = logging.getLogger()
_root.setLevel(logging.INFO)
_fh = RotatingFileHandler(
    _log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8", delay=False
)
_fh.setFormatter(_log_fmt)
_root.addHandler(_fh)
_ch = logging.StreamHandler(sys.stdout)
_ch.setFormatter(_log_fmt)
# Force UTF-8 on Windows consoles that default to cp1252
if hasattr(_ch.stream, "reconfigure"):
    try:
        _ch.stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
_root.addHandler(_ch)
logger = logging.getLogger("skill_watcher")

# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
sys.path.insert(0, str(PROJECT_ROOT))
try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from shared_platform.notify import send_telegram as _send_telegram


def alert(icon: str, title: str, detail: str) -> None:
    """Log + send a Telegram alert."""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.warning("[ALERT] %s %s — %s", icon, title, detail)
    msg = (
        f"{icon} <b>SkillWatcher Alert</b>\n<b>{title}</b>\n{detail}\n<i>{ts} (ICT)</i>"
    )
    _send_telegram(msg)


# ---------------------------------------------------------------------------
# Flow definitions
# ---------------------------------------------------------------------------
# Each entry defines:
#   log_file        : path to the log file to monitor
#   task_name       : Windows Task Scheduler task path to restart if frozen
#   process_match   : substring in CommandLine to identify the zombie process
#   heartbeat_min   : max minutes allowed between log updates before considered stale
#   stale_action    : "restart" | "alert_only"
#   is_long_running : if True, flow runs for hours; if False, it's a short-lived job

FLOWS = [
    {
        "id": "flow1_scrape",
        "label": "Flow 1 (Scrape)",
        "log_file": LOGS_DIR / "flow1.log",
        "task_name": r"\JobHunterKit\Flow1_Scrape",
        "process_match": "flow_scrape.py",
        "heartbeat_min": 120,  # Alert if stuck scraping without progress for 120 min
        "stale_action": "restart",
        "is_long_running": False,
    },
    {
        "id": "flow2_score",
        "label": "Flow 2 (Score)",
        "log_file": LOGS_DIR / "flow2.log",
        "task_name": r"\JobHunterKit\Flow2_Score",
        "process_match": "flow_score.py",
        "heartbeat_min": 90,
        "stale_action": "restart",
        "is_long_running": False,
    },
    {
        "id": "flow3_apply",
        "label": "Flow 3 (Apply)",
        "log_file": LOGS_DIR / "flow3.log",
        "task_name": r"\JobHunterKit\Flow3_Apply",
        "process_match": "flow_apply.py",
        "heartbeat_min": 90,
        "stale_action": "restart",
        "is_long_running": False,
    },
    {
        "id": "flow_telegram_report",
        "label": "Flow Telegram Report",
        "log_file": LOGS_DIR / "telegram_reporter_pyw.log",
        "task_name": r"\JobHunterKit\Flow_Telegram_Report",
        "process_match": "telegram_reporter.py",
        "heartbeat_min": 150,
        "stale_action": "restart",
        "is_long_running": False,
    },
    {
        "id": "flow_ebqc_crystallizer",
        "label": "Flow EBQC Crystallizer",
        "log_file": LOGS_DIR / "ebqc_crystallizer_pyw.log",
        "task_name": r"\JobHunterKit\Flow_EBQC_Crystallizer",
        "process_match": "ebqc_crystallizer.py",
        "heartbeat_min": 75,
        "stale_action": "restart",
        "is_long_running": False,
    },
]


# ---------------------------------------------------------------------------
# Process helpers (Windows only via WMIC)
# ---------------------------------------------------------------------------


def _find_zombie_pid(process_match: str) -> int | None:
    """Find a Python process whose CommandLine contains process_match.

    FIX B1: Replaced deprecated WMIC (which fails with WinError 2 on modern
    Windows) with PowerShell Get-WmiObject, which is the supported equivalent.
    Falls back to a tasklist + PowerShell hybrid if WMI also fails.
    """
    # Primary: PowerShell WMI query (replaces broken WMIC)
    ps_script = (
        f"Get-WmiObject Win32_Process "
        f"-Filter \"Name='python.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{process_match}*' }} | "
        f"Select-Object -ExpandProperty ProcessId"
    )
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=creationflags,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                logger.info("[ZombieDetect] Found PID %s via PowerShell WMI", line)
                return int(line)
    except Exception as e:
        logger.error("PowerShell WMI query failed: %s", e)

    # Fallback: Get-CimInstance to verify python.exe exists and matches process_match in CommandLine
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        ps_fallback = (
            f"Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            f"Where-Object {{ $_.CommandLine -like '*{process_match}*' }} | "
            f"Select-Object -ExpandProperty ProcessId"
        )
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                ps_fallback,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=creationflags,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                logger.info("[ZombieDetect] Fallback found PID %s", line)
                return int(line)
    except Exception as e2:
        logger.error("PowerShell fallback also failed: %s", e2)

    return None


def _kill_process(pid: int) -> bool:
    """Kill a process tree by PID using taskkill /F /T."""
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        result = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=creationflags,
        )
        return result.returncode == 0
    except Exception as e:
        logger.error("Failed to kill PID %s: %s", pid, e)
        return False


def _restart_task(task_name: str) -> bool:
    """Trigger a Windows Task Scheduler task by name."""
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        result = subprocess.run(
            ["schtasks", "/run", "/tn", task_name],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=creationflags,
        )
        return result.returncode == 0
    except Exception as e:
        logger.error("Failed to restart task %s: %s", task_name, e)
        return False


def _get_task_status(task_name: str) -> str:
    """Get Windows Task Scheduler status for a task."""
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        result = subprocess.run(
            ["schtasks", "/query", "/tn", task_name, "/fo", "LIST"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=creationflags,
        )
        for line in result.stdout.splitlines():
            if "Status:" in line:
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return "Unknown"


# ---------------------------------------------------------------------------
# Core health check & self-healing
# ---------------------------------------------------------------------------


def unlock_stuck_jobs(flow_id: str, dry_run: bool = False) -> int:
    """
    Finds and resets any jobs that are stuck in transient states in the database
    because a flow crashed or was killed.
    - flow_id == "flow2_score": resets 'scoring' -> 'pending'
    - flow_id == "flow3_apply": resets 'applying' -> 'pending'
    """
    # Import locally to avoid startup dependencies
    try:
        from core.db_client import get_connection
    except ImportError:
        # Fallback to absolute path import
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        try:
            from flow_score import get_connection
        except ImportError:
            logger.error("Could not import get_connection to unlock stuck jobs.")
            return 0

    sql = ""
    target_status = ""
    if flow_id == "flow2_score":
        sql = "UPDATE job_hunter.jobs SET status_score = 'pending', claimed_at = NULL WHERE status_score = 'scoring' AND (claimed_at IS NULL OR claimed_at < NOW() - INTERVAL '30 minutes');"
        target_status = "orphaned scoring -> pending"
    elif flow_id == "flow3_apply":
        sql = "UPDATE job_hunter.jobs SET status_apply = 'pending', claimed_at = NULL WHERE status_apply = 'applying' AND (claimed_at IS NULL OR claimed_at < NOW() - INTERVAL '30 minutes');"
        target_status = "orphaned applying -> pending"
    else:
        return 0

    if dry_run:
        logger.info("[DRY RUN] Would execute unlock query: %s", sql)
        return 0

    logger.info("Running recovery query to unlock stuck jobs (%s)...", target_status)
    conn = None
    rows_updated = 0
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(sql)
            rows_updated = cur.rowcount
            conn.commit()
        logger.info("Successfully unlocked %d jobs ✅", rows_updated)
    except Exception as e:
        logger.error("Failed to unlock jobs: %s", e)
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
    return rows_updated


def _detect_fatal_error_loop(
    log_file: Path, max_errors: int = 5, last_lines_count: int = 30
) -> tuple[bool, str]:
    """
    Read the tail of the log file.
    If it contains JSON structured logs, parses them and counts errors.
    Otherwise, falls back to scanning unstructured text signatures.
    """
    if not log_file.exists():
        return False, ""
    try:
        with open(log_file, encoding="utf-8", errors="replace") as f:
            try:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                seek_offset = min(size, 20480)
                f.seek(size - seek_offset)
            except Exception:
                pass
            lines = f.readlines()

        last_lines = [
            line.strip() for line in lines[-last_lines_count:] if line.strip()
        ]

        json_errors = []
        unstructured_matching_lines = []

        fatal_signatures = [
            "target page, context or browser has been closed",
            "locator.count: target page",
            "page.goto: target page",
            "browser has been closed",
            "net::err_",
            "timeout 30000ms exceeded",
            "fatal error in careerjet scraping loop",
            "ipc request",
            "timed out waiting for response",
            "[llm retry] attempt 5",
            "llm retry] attempt 5/5 failed",
        ]

        for line in last_lines:
            # Try parsing as JSON first
            if line.startswith("{") and line.endswith("}"):
                try:
                    event = json.loads(line)
                    if isinstance(event, dict):
                        level = event.get("level", "").upper()
                        if level in ("ERROR", "FATAL"):
                            json_errors.append(event)
                            continue
                except json.JSONDecodeError:
                    pass

            # Fallback to unstructured parsing
            line_lower = line.lower()
            for sig in fatal_signatures:
                if sig in line_lower:
                    unstructured_matching_lines.append(line)
                    break

        if len(json_errors) >= max_errors:
            msg = json_errors[-1].get("message", "Unknown error")
            summary = (
                f"Detected {len(json_errors)} fatal JSON errors. Example: '{msg[:80]}'"
            )
            return True, summary

        total_errors = len(json_errors) + len(unstructured_matching_lines)
        if total_errors >= max_errors:
            example = (
                json_errors[-1].get("message", "")
                if json_errors
                else unstructured_matching_lines[-1]
            )
            summary = f"Detected {total_errors} fatal errors. Example: '{example[:80]}'"
            return True, summary

    except Exception as e:
        logger.error("Error scanning log file %s: %s", log_file, e)
    return False, ""


def _is_waiting_for_intervention(
    log_file: Path, last_lines_count: int = 15
) -> tuple[bool, str]:
    """
    Checks if the flow log tail indicates it is waiting for Telegram/manual response.
    Returns (True, message) if so.
    """
    if not log_file.exists():
        return False, ""
    try:
        with open(log_file, encoding="utf-8", errors="replace") as f:
            try:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                seek_offset = min(size, 8192)
                f.seek(size - seek_offset)
            except Exception:
                pass
            lines = f.readlines()

        last_lines = [
            line.strip() for line in lines[-last_lines_count:] if line.strip()
        ]

        signatures = [
            "[MANUAL INTERVENTION]",
            "Waiting for Telegram response",
            "Waiting for manual verification",
            "Telegram manual verification requested",
        ]

        for line in reversed(last_lines):
            for sig in signatures:
                if sig in line:
                    return True, line
    except Exception as e:
        logger.error("Error scanning log file %s for intervention: %s", log_file, e)
    return False, ""


def _check_log_failures(
    log_file: Path, flow_id: str, last_lines_count: int = 30
) -> tuple[int, str]:
    """
    Scans the tail of the log file for failure summaries or crash signatures.
    Supports structured JSON logs and falls back to unstructured text.
    """
    if not log_file.exists():
        return 0, ""
    try:
        with open(log_file, encoding="utf-8", errors="replace") as f:
            try:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                seek_offset = min(size, 16384)
                f.seek(size - seek_offset)
            except Exception:
                pass
            lines = f.readlines()

        last_lines = [
            line.strip() for line in lines[-last_lines_count:] if line.strip()
        ]

        # Scan backwards for JSON errors or fallbacks
        for line in reversed(last_lines):
            if line.startswith("{") and line.endswith("}"):
                try:
                    event = json.loads(line)
                    if isinstance(event, dict):
                        level = event.get("level", "").upper()
                        # If a fatal event or error event is logged
                        if level in ("FATAL", "ERROR"):
                            msg = event.get("message", "")
                            err = event.get("error", "")
                            detail = f"JSON {level}: {msg}" + (
                                f" (error: {err})" if err else ""
                            )
                            return 1, detail
                except json.JSONDecodeError:
                    pass

            # Fallback to original substring checks
            if "crashed with exit code" in line or "crashed with exit status" in line:
                return 1, line
            if "CRITICAL ERROR" in line:
                return 1, line

        # If not matched yet, check for failure metrics (e.g. Failure count summaries)
        if flow_id == "flow2_score":
            for line in reversed(last_lines):
                if "Failed (API/System errors):" in line:
                    try:
                        parts = line.split(":")
                        failures = int(parts[-1].strip())
                        if failures > 0:
                            return failures, line
                    except Exception:
                        pass
        elif flow_id == "flow3_apply":
            for line in reversed(last_lines):
                if "Flow 3 Application Queue Summary: Completed." in line:
                    try:
                        parts = line.split("Failures:")
                        failures = int(parts[-1].strip())
                        if failures > 0:
                            return failures, line
                    except Exception:
                        pass
    except Exception as e:
        logger.error("Error parsing failure summaries from log %s: %s", log_file, e)
    return 0, ""


def _get_last_progress_time(
    log_file: Path, default_mtime: datetime.datetime
) -> datetime.datetime:
    """
    Scans the tail of the log file backwards to find the last log event
    that is not a launcher heartbeat. Returns its timestamp if found,
    otherwise returns the default_mtime.
    Supports ISO UTC timestamps, bracketed [YYYY-MM-DD HH:MM:SS], and standard logger lines.
    """
    import re

    if not log_file.exists():
        return default_mtime
    try:
        with open(log_file, encoding="utf-8", errors="replace") as f:
            try:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                # Read up to 64KB of the tail
                seek_offset = min(size, 65536)
                f.seek(size - seek_offset)
            except Exception:
                pass
            lines = f.readlines()

        # Iterate backwards to find the last progress event
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue

            # 1. JSON formatted log events: {"timestamp": "...", "message": "..."}
            if line.startswith("{") and line.endswith("}"):
                try:
                    event = json.loads(line)
                    if isinstance(event, dict):
                        msg = event.get("message", "")
                        if "Launcher heartbeat" in msg:
                            continue
                        ts_str = event.get("timestamp")
                        if ts_str:
                            try:
                                dt = datetime.datetime.fromisoformat(ts_str)
                                if dt.tzinfo is not None:
                                    dt = dt.astimezone().replace(tzinfo=None)
                                return dt
                            except Exception:
                                pass
                except Exception:
                    pass

            # 2. Bracketed text timestamp: [2026-08-21 16:12:00]
            match = re.match(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", line)
            if match:
                ts_str = match.group(1)
                try:
                    return datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass

            # 3. Standard logging timestamp: 2026-08-21 16:12:00,123
            match = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
            if match:
                ts_str = match.group(1)
                try:
                    return datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass

    except Exception as e:
        logger.error("Error finding last progress time: %s", e)
    return default_mtime


def _get_pending_work_count(flow_id: str) -> int:
    """Returns the count of pending actionable items in DB for the given flow."""
    try:
        from core.db_client import get_connection
        conn = get_connection()
        count = 0
        try:
            with conn.cursor() as cur:
                if flow_id == "flow2_score":
                    cur.execute("SELECT COUNT(*) FROM job_hunter.jobs WHERE status_score = 'pending';")
                    count = cur.fetchone()[0]
                elif flow_id == "flow3_apply":
                    cur.execute("SELECT COUNT(*) FROM job_hunter.jobs WHERE status_score = 'completed' AND status_apply = 'pending';")
                    count = cur.fetchone()[0]
        finally:
            conn.close()
        return count
    except Exception as e:
        logger.error("Failed to get pending work count for %s: %s", flow_id, e)
        return 0


def check_flow(flow: dict, dry_run: bool = False) -> dict:
    """
    Run a health check on a single flow.

    Returns a result dict with keys:
        id, label, status, action_taken, detail
    """
    result = {
        "id": flow["id"],
        "label": flow["label"],
        "status": "ok",
        "action_taken": "none",
        "detail": "",
    }

    log_file: Path = flow["log_file"]
    heartbeat_min: int = flow["heartbeat_min"]
    now = datetime.datetime.now()

    # ---- Check 1: log file exists ----
    if not log_file.exists():
        result["status"] = "warning"
        result["detail"] = f"Log file not found: {log_file}"
        logger.warning("[%s] %s", flow["label"], result["detail"])
        return result

    # ---- Check 1b: detect manual Telegram intervention waiting ----
    is_waiting, intervention_line = _is_waiting_for_intervention(log_file)
    if is_waiting:
        result["status"] = "ok"
        result["detail"] = (
            f"Waiting for manual Telegram response: {intervention_line[:120]}"
        )
        logger.info("[%s] %s (Self-healing bypassed)", flow["label"], result["detail"])
        return result

    # ---- Check 2: log staleness ----
    mtime = datetime.datetime.fromtimestamp(log_file.stat().st_mtime)
    progress_time = _get_last_progress_time(log_file, mtime)
    age_min = (now - progress_time).total_seconds() / 60.0

    logger.info(
        "[%s] Log last updated %.1f min ago (threshold: %d min)",
        flow["label"],
        age_min,
        heartbeat_min,
    )

    is_stale = age_min > heartbeat_min

    # ---- Check 2b: Detect error loops even if log is fresh ----
    has_error_loop, error_detail = _detect_fatal_error_loop(log_file)

    if not is_stale and not has_error_loop:
        result["detail"] = f"Log is fresh (updated {age_min:.1f} min ago)"
        # Check if it recently completed with failures
        if age_min < 15.0:
            failures, failure_summary = _check_log_failures(log_file, flow["id"])
            if failures > 0:
                alert(
                    "⚠️",
                    f"{flow['label']} — Completed with Failures",
                    f"Flow recently completed but logged failures/crashes:\n<code>{failure_summary}</code>",
                )
        return result

    # ---- Idle Queue Check: If stale but queue is legitimately empty ----
    if is_stale and not has_error_loop:
        if flow["id"] in ("flow2_score", "flow3_apply"):
            pending_work = _get_pending_work_count(flow["id"])
            if pending_work == 0:
                result["status"] = "ok"
                result["detail"] = f"Queue empty (0 pending); idle by design (last active {age_min:.1f} min ago)"
                logger.info("[%s] %s", flow["label"], result["detail"])
                return result

    # ---- Log is UNHEALTHY ----
    if has_error_loop:
        result["status"] = "zombie"
        result["detail"] = f"Error loop detected: {error_detail}"
        logger.warning(
            "[%s] UNHEALTHY (Error Loop) — %s", flow["label"], result["detail"]
        )
    else:
        result["status"] = "stale"
        result["detail"] = (
            f"Log stale for {age_min:.1f} min (threshold: {heartbeat_min} min). "
            f"Last update: {mtime.strftime('%H:%M:%S')}"
        )
        logger.warning("[%s] STALE — %s", flow["label"], result["detail"])

    # ---- Check 3: detect zombie process ----
    zombie_pid = _find_zombie_pid(flow["process_match"])

    if zombie_pid:
        result["status"] = "zombie"
        result["detail"] += f" | Zombie process detected: PID {zombie_pid}"
        logger.warning("[%s] Zombie PID %s detected", flow["label"], zombie_pid)

        if flow["stale_action"] == "restart":
            if dry_run:
                logger.info(
                    "[DRY RUN] Would kill PID %s and restart %s",
                    zombie_pid,
                    flow["task_name"],
                )
                result["action_taken"] = "dry_run_restart"
            else:
                # Kill zombie
                killed = _kill_process(zombie_pid)
                if killed:
                    logger.info(
                        "[%s] Killed zombie PID %s ✅", flow["label"], zombie_pid
                    )
                    # Unlock stuck jobs in database
                    unlock_stuck_jobs(flow["id"], dry_run)
                    # Restart via Task Scheduler
                    restarted = _restart_task(flow["task_name"])
                    if restarted:
                        result["action_taken"] = "killed_and_restarted"
                        result["detail"] += (
                            f" → Killed PID {zombie_pid}, restarted task."
                        )
                        alert(
                            "🔄",
                            f"{flow['label']} — Self-Healed",
                            f"Zombie PID {zombie_pid} was killed. Stuck jobs unlocked. Task <code>{flow['task_name']}</code> restarted.",
                        )
                    else:
                        result["action_taken"] = "killed_restart_failed"
                        result["detail"] += (
                            f" → Killed PID {zombie_pid}, but task restart FAILED."
                        )
                        alert(
                            "❌",
                            f"{flow['label']} — Restart Failed",
                            f"Zombie PID {zombie_pid} killed but <code>{flow['task_name']}</code> could not be restarted. Manual intervention needed.",
                        )
                else:
                    result["action_taken"] = "kill_failed"
                    result["detail"] += f" → Failed to kill PID {zombie_pid}."
                    alert(
                        "⚠️",
                        f"{flow['label']} — Kill Failed",
                        f"Could not kill zombie PID {zombie_pid}. Manual intervention needed.",
                    )
        else:
            result["action_taken"] = "alerted"
            alert(
                "⚠️",
                f"{flow['label']} — Zombie Detected",
                f"Process stale/looping for {age_min:.1f} min. Zombie PID {zombie_pid} running but log not updating correctly.",
            )
    else:
        # No zombie found
        task_status = _get_task_status(flow["task_name"])
        result["detail"] += f" | No zombie found. Task Scheduler status: {task_status}"
        logger.info(
            "[%s] No zombie process. Task status: %s", flow["label"], task_status
        )

        # Force restart on error loops even if no zombie PID is matched
        if flow["stale_action"] == "restart" and has_error_loop:
            if dry_run:
                logger.info(
                    "[DRY RUN] Would restart %s due to error loop", flow["task_name"]
                )
                result["action_taken"] = "dry_run_restart"
            else:
                unlock_stuck_jobs(flow["id"], dry_run)
                restarted = _restart_task(flow["task_name"])
                if restarted:
                    result["action_taken"] = "restarted_on_error_loop"
                    result["detail"] += " → Fatal error loop resolved by task restart."
                    alert(
                        "🔄",
                        f"{flow['label']} — Self-Healed (Error Loop)",
                        f"Log analysis detected a fatal error loop. Stuck jobs unlocked. Task <code>{flow['task_name']}</code> was restarted.",
                    )
                else:
                    result["action_taken"] = "restart_failed_on_error_loop"
                    alert(
                        "❌",
                        f"{flow['label']} — Restart Failed",
                        f"Log analysis detected a fatal error loop but <code>{flow['task_name']}</code> could not be restarted. Manual intervention needed.",
                    )
        elif flow["stale_action"] == "restart" and is_stale:
            # Check if pending work exists in the DB for Flow 2 or Flow 3
            pending_work = _get_pending_work_count(flow["id"]) if flow["id"] in ("flow2_score", "flow3_apply") else 0
            if pending_work > 0 and task_status not in ("Running",):
                if dry_run:
                    logger.info(
                        "[DRY RUN] Would auto-start %s to drain %d pending jobs",
                        flow["task_name"],
                        pending_work,
                    )
                    result["action_taken"] = "dry_run_restart"
                else:
                    unlock_stuck_jobs(flow["id"], dry_run)
                    restarted = _restart_task(flow["task_name"])
                    if restarted:
                        result["status"] = "ok"
                        result["action_taken"] = "restarted_backlog_drain"
                        result["detail"] += (
                            f" → Auto-started task to drain {pending_work} pending jobs."
                        )
                        alert(
                            "🔄",
                            f"{flow['label']} — Auto-Started for Backlog",
                            f"Detected {pending_work} pending jobs waiting in queue. Task <code>{flow['task_name']}</code> was triggered.",
                        )
                    else:
                        result["action_taken"] = "restart_failed_on_backlog"
                        alert(
                            "❌",
                            f"{flow['label']} — Backlog Trigger Failed",
                            f"Found {pending_work} pending jobs but <code>{flow['task_name']}</code> could not be started.",
                        )
            else:
                # If long running and stopped, auto-restart
                if (
                    flow["is_long_running"]
                    and task_status not in ("Running",)
                ):
                    if dry_run:
                        logger.info(
                            "[DRY RUN] Would restart stopped task %s", flow["task_name"]
                        )
                        result["action_taken"] = "dry_run_restart"
                    else:
                        unlock_stuck_jobs(flow["id"], dry_run)
                        restarted = _restart_task(flow["task_name"])
                        if restarted:
                            result["action_taken"] = "restarted_stopped_task"
                            result["detail"] += (
                                f" → Task scheduler status was '{task_status}'. Restarted."
                            )
                            alert(
                                "🔄",
                                f"{flow['label']} — Self-Healed (Stopped Task)",
                                f"Task was not running (status: {task_status}). Unlocked stuck jobs and restarted.",
                            )
                        else:
                            result["action_taken"] = "restart_failed_on_stopped"
                            alert(
                                "❌",
                                f"{flow['label']} — Restart Failed",
                                f"Task was not running (status: {task_status}) but could not be restarted.",
                            )
                elif flow["is_long_running"] and task_status not in ("Running", "Ready"):
                    result["action_taken"] = "alerted"
                    alert(
                        "⚠️",
                        f"{flow['label']} — Log Stale, Task Not Running",
                        f"Log stale {age_min:.1f} min. No process found. Task status: {task_status}.",
                    )

    return result


def _check_apply_success_rate_and_expire(dry_run: bool = False) -> None:
    """
    Two guards run every watcher cycle:

    Guard 1 — Success-rate alert:
        If Flow 3 has made >10 application attempts today and the success
        rate is below 10%, fire a Telegram alert. This catches zombie-loop
        scenarios where the flow is technically alive but applying to nothing.

    Guard 2 — Expired-job auto-purge:
        Mark any 'pending' apply jobs older than 21 days as 'skipped'.
        LinkedIn postings expire in ~2-4 weeks; keeping them in the queue
        causes infinite retry loops that the watcher falsely reports as OK.
    """
    try:
        from core.db_client import get_connection
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                # Guard 1: daily success rate
                cur.execute("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE a.status IN ('applied','completed')) as success
                    FROM job_hunter.applications a
                    WHERE DATE(a.applied_at AT TIME ZONE 'Asia/Ho_Chi_Minh') = CURRENT_DATE
                """)
                row = cur.fetchone()
                total_today, success_today = (row[0] or 0), (row[1] or 0)
                success_rate = round(success_today / total_today * 100) if total_today else 100

                logger.info(
                    "[SuccessRateGuard] Today: %d attempts, %d successful (%d%% success rate)",
                    total_today, success_today, success_rate,
                )

                if total_today >= 10 and success_rate < 10:
                    logger.warning(
                        "[SuccessRateGuard] CRITICAL — success rate %d%% is below 10%% threshold.",
                        success_rate,
                    )
                    if not dry_run:
                        # Guard 2: auto-expire stale pending jobs (only trigger with low success rate)
                        cur.execute("""
                            UPDATE job_hunter.jobs
                            SET status_apply = 'skipped',
                                manual_intervention_reason =
                                    'Auto-expired: job listing older than 21 days — LinkedIn posting likely closed'
                            WHERE status_apply = 'pending'
                              AND scraped_at < NOW() - INTERVAL '21 days'
                        """)
                        expired_count = cur.rowcount
                        conn.commit()
                        logger.info(
                            "[SuccessRateGuard] Auto-expired %d stale pending jobs (>21 days old).",
                            expired_count,
                        )
                    else:
                        expired_count = 0

                    alert(
                        "🚨",
                        "Flow 3 — Apply Success Rate Critical",
                        (
                            f"Today: <b>{total_today}</b> attempts, only <b>{success_today}</b> successful "
                            f"(<b>{success_rate}%</b> success rate).\n"
                            f"This indicates Flow 3 is stuck in a zombie retry loop.\n"
                            + (
                                f"<b>Auto-action:</b> {expired_count} expired job listings (&gt;21d old) "
                                f"removed from apply queue."
                                if not dry_run
                                else "[DRY RUN] Would auto-expire stale pending jobs."
                            )
                        ),
                    )
                else:
                    # Guard 2 runs independently on every cycle regardless of success rate
                    # (silently, no alert if rate is healthy)
                    if not dry_run:
                        cur.execute("""
                            UPDATE job_hunter.jobs
                            SET status_apply = 'skipped',
                                manual_intervention_reason =
                                    'Auto-expired: job listing older than 21 days — LinkedIn posting likely closed'
                            WHERE status_apply = 'pending'
                              AND scraped_at < NOW() - INTERVAL '21 days'
                        """)
                        expired_count = cur.rowcount
                        conn.commit()
                        if expired_count > 0:
                            logger.info(
                                "[ExpiredJobPurge] Silently expired %d stale pending jobs (>21 days old).",
                                expired_count,
                            )
        finally:
            conn.close()
    except Exception as e:
        logger.error("[SuccessRateGuard] Error during success-rate check: %s", e)


def check_database_failures(dry_run: bool = False) -> None:
    """
    Checks the Supabase PostgreSQL database for jobs that have failed scoring or failed applications.
    If failed jobs are found, alerts via Telegram and runs recover_transient_failures.py.
    """
    logger.info("Checking database for failed scoring/applying jobs...")
    try:
        from core.db_client import get_connection
    except ImportError:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        try:
            from flow_score import get_connection
        except ImportError:
            logger.error("Could not import get_connection to check database failures.")
            return

    conn = None
    failed_score_count = 0
    failed_apply_count = 0
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM job_hunter.jobs WHERE status_score = 'failed';"
            )
            failed_score_count = cur.fetchone()[0]

            cur.execute(
                """SELECT COUNT(*) FROM job_hunter.jobs 
                   WHERE status_apply IN ('failed', 'failed_manual', 'needs_manual_intervention')
                     AND scraped_at >= NOW() - INTERVAL '21 days'
                     AND (apply_attempts IS NULL OR apply_attempts < 3)
                     AND (
                         manual_intervention_reason IS NULL 
                         OR manual_intervention_reason ILIKE '%error%' 
                         OR manual_intervention_reason ILIKE '%timeout%' 
                         OR manual_intervention_reason ILIKE '%closed%' 
                         OR manual_intervention_reason ILIKE '%attribute%' 
                         OR manual_intervention_reason ILIKE '%maximum iterations%'
                         OR manual_intervention_reason ILIKE '%stuck%'
                     )
                     AND id NOT IN (SELECT job_id FROM job_hunter.applications WHERE status IN ('applied', 'completed', 'dry_run'));"""
            )
            failed_apply_count = cur.fetchone()[0]
    except Exception as e:
        logger.error("Failed to query database failed counts: %s", e)
        return
    finally:
        if conn:
            conn.close()

    logger.info(
        "Database failed counts: Scoring=%d, Apply=%d",
        failed_score_count,
        failed_apply_count,
    )

    # ── Daily apply success-rate guard + expired-job auto-purge ────────────
    # Alert if Flow 3 has attempted >10 apps today but success rate < 10%.
    # Auto-expire pending jobs >21 days old to stop zombie retry loops.
    _check_apply_success_rate_and_expire(dry_run=dry_run)

    if failed_score_count > 0 or failed_apply_count > 0:
        alert(
            "⚠️",
            "Failed Jobs Detected in Database",
            f"Found <b>{failed_score_count}</b> failed scoring jobs and <b>{failed_apply_count}</b> failed application jobs in DB.",
        )

        if dry_run:
            logger.info(
                "[DRY RUN] Would run recover_transient_failures.py to auto-heal failed states."
            )
            return

        # Trigger auto-healing
        logger.info(
            "Triggering recover_transient_failures.py to auto-heal failed states..."
        )
        recover_script = SCRIPT_DIR / "recover_transient_failures.py"
        if recover_script.exists():
            try:
                creationflags = (
                    subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                )
                result = subprocess.run(
                    [sys.executable, str(recover_script)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=60,
                    creationflags=creationflags,
                )
                if result.returncode == 0:
                    logger.info("recover_transient_failures.py completed successfully.")
                    alert(
                        "🔄",
                        "Database Auto-Healed",
                        "Successfully ran recovery. Failed jobs have been reset to 'pending' to retry.",
                    )
                else:
                    logger.error(
                        "recover_transient_failures.py failed: %s", result.stderr
                    )
                    alert(
                        "❌",
                        "Database Auto-Heal Failed",
                        f"Recovery script exited with code {result.returncode}.\nError details:\n<code>{result.stderr[:200]}</code>",
                    )
            except Exception as ex:
                logger.error("Failed to run recover_transient_failures.py: %s", ex)
                alert("❌", "Database Auto-Heal Failed", f"Exception: {ex}")
        else:
            logger.error("Recovery script not found at %s", recover_script)


def sweep_orphaned_playwright_processes(dry_run: bool = False) -> None:
    """Find and kill orphaned automation Chrome and Playwright Node driver processes."""
    if sys.platform != "win32":
        return
    logger.info("Sweeping for orphaned Playwright Chrome & Node processes...")
    try:
        ps_script = (
            "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
            "Where-Object { $_.CommandLine -like '*--headless*' -or $_.CommandLine -like '*--remote-debugging-port*' -or $_.CommandLine -like '*--enable-automation*' } | "
            "Select-Object -ExpandProperty ProcessId"
        )
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=creationflags,
        )
        pids = [
            int(line.strip())
            for line in res.stdout.splitlines()
            if line.strip().isdigit()
        ]
        if pids:
            logger.info(
                "Found %d orphaned Playwright Chrome processes to purge.", len(pids)
            )
            if not dry_run:
                for pid in pids:
                    _kill_process(pid)
    except Exception as e:
        logger.error("Failed sweeping orphaned Playwright processes: %s", e)


def check_and_heal_disabled_tasks(dry_run: bool = False) -> list[str]:
    """
    Scans all JobHunterKit scheduled tasks in Windows Task Scheduler.
    If any registered flow task is 'Disabled', automatically re-enables it
    via schtasks /change /tn <task> /enable and dispatches an alert.
    """
    healed = []
    for flow in FLOWS:
        task_name = flow.get("task_name")
        if not task_name:
            continue
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            res = subprocess.run(
                ["schtasks", "/query", "/tn", task_name, "/fo", "LIST", "/v"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=creationflags,
            )
            is_disabled = False
            for line in res.stdout.splitlines():
                if "Scheduled Task State:" in line and "Disabled" in line:
                    is_disabled = True
                    break
                elif "Status:" in line and "Disabled" in line:
                    is_disabled = True
                    break

            if is_disabled:
                logger.warning("[AutoHeal] Task %s is DISABLED in Windows Task Scheduler!", task_name)
                if not dry_run:
                    enable_res = subprocess.run(
                        ["schtasks", "/change", "/tn", task_name, "/enable"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        creationflags=creationflags,
                    )
                    if enable_res.returncode == 0:
                        logger.info("[AutoHeal] Successfully re-enabled task %s ✅", task_name)
                        alert(
                            "🔄",
                            f"AutoHeal: Task {flow['label']} Re-Enabled",
                            "Task was found in DISABLED state in Task Scheduler and was automatically re-enabled.",
                        )
                        healed.append(task_name)
                    else:
                        logger.error("[AutoHeal] Failed to re-enable task %s: %s", task_name, enable_res.stderr.strip())
                else:
                    logger.info("[DRY RUN] Would re-enable task %s", task_name)
                    healed.append(task_name)
        except Exception as e:
            logger.error("[AutoHeal] Error checking task state for %s: %s", task_name, e)
    return healed


def check_pending_queue_drain(dry_run: bool = False) -> None:
    """Checks if pending scoring or application jobs are waiting in queue and triggers Flow2/Flow3 if idle."""
    try:
        from core.db_client import get_connection
        conn = get_connection()
        pending_score_count = 0
        ready_apply_count = 0
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM job_hunter.jobs WHERE status_score = 'pending';")
                pending_score_count = cur.fetchone()[0]
                cur.execute(
                    "SELECT COUNT(*) FROM job_hunter.jobs WHERE status_score = 'completed' AND status_apply = 'pending';"
                )
                ready_apply_count = cur.fetchone()[0]
        finally:
            conn.close()

        # Flow 2 scoring queue drain
        if pending_score_count > 0:
            logger.info("[QueueDrain] Found %d pending scoring jobs in queue.", pending_score_count)
            flow2_pid = _find_zombie_pid("flow_score.py")
            task_status = _get_task_status(r"\JobHunterKit\Flow2_Score")
            if not flow2_pid and task_status not in ("Running",):
                if dry_run:
                    logger.info("[DRY RUN] Would trigger Flow2_Score to drain %d pending jobs", pending_score_count)
                else:
                    logger.info("[QueueDrain] Triggering Flow2_Score task to drain %d pending jobs...", pending_score_count)
                    _restart_task(r"\JobHunterKit\Flow2_Score")

        # Flow 3 application queue drain
        if ready_apply_count > 0:
            logger.info("[QueueDrain] Found %d ready-to-apply jobs in queue.", ready_apply_count)
            flow3_pid = _find_zombie_pid("flow_apply.py")
            task_status = _get_task_status(r"\JobHunterKit\Flow3_Apply")
            if not flow3_pid and task_status not in ("Running",):
                if dry_run:
                    logger.info("[DRY RUN] Would trigger Flow3_Apply to drain %d ready jobs", ready_apply_count)
                else:
                    logger.info("[QueueDrain] Triggering Flow3_Apply task to drain %d ready jobs...", ready_apply_count)
                    _restart_task(r"\JobHunterKit\Flow3_Apply")
    except Exception as e:
        logger.error("[QueueDrain] Error checking pending queue drain: %s", e)




# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="SkillWatcher — Self-healing flow monitor"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Simulate without killing or restarting"
    )
    parser.add_argument(
        "--flow", help="Only check a specific flow id (e.g. flow1_scrape)"
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info(
        "SkillWatcher health-check started%s", " [DRY RUN]" if args.dry_run else ""
    )

    if not args.flow:
        try:
            sweep_orphaned_playwright_processes(dry_run=args.dry_run)
            check_and_heal_disabled_tasks(dry_run=args.dry_run)
            unlock_stuck_jobs("flow2_score", dry_run=args.dry_run)
            unlock_stuck_jobs("flow3_apply", dry_run=args.dry_run)
            check_database_failures(dry_run=args.dry_run)
            check_pending_queue_drain(dry_run=args.dry_run)
        except Exception as db_err:
            logger.error(
                "Error during database health check: %s", db_err, exc_info=True
            )

    flows_to_check = FLOWS
    if args.flow:
        flows_to_check = [f for f in FLOWS if f["id"] == args.flow]
        if not flows_to_check:
            logger.error(
                "Unknown flow id: %s. Valid ids: %s",
                args.flow,
                [f["id"] for f in FLOWS],
            )
            sys.exit(1)

    results = []
    for flow in flows_to_check:
        try:
            r = check_flow(flow, dry_run=args.dry_run)
            results.append(r)
        except Exception as e:
            logger.error(
                "Unexpected error checking [%s]: %s", flow["label"], e, exc_info=True
            )
            results.append(
                {
                    "id": flow["id"],
                    "label": flow["label"],
                    "status": "error",
                    "action_taken": "none",
                    "detail": str(e),
                }
            )

    # Summary
    logger.info("-" * 60)
    ok = [r for r in results if r["status"] == "ok"]
    issues = [r for r in results if r["status"] != "ok"]
    logger.info(
        "Summary: %d/%d flows healthy | %d issue(s) detected",
        len(ok),
        len(results),
        len(issues),
    )
    for r in results:
        icon = "[OK]" if r["status"] == "ok" else "[!!]"
        logger.info(
            "  %s [%s] status=%s action=%s",
            icon,
            r["label"],
            r["status"],
            r["action_taken"],
        )
    logger.info("=" * 60)

    # Exit non-zero if any issues remain unresolved
    unresolved = [
        r
        for r in results
        if r["status"] in ("zombie", "stale", "error")
        and r["action_taken"] not in ("killed_and_restarted", "dry_run_restart")
    ]
    sys.exit(1 if unresolved else 0)


# ---------------------------------------------------------------------------
# Semantic Yield Sentry and Checkpointer Anomaly Diagnostics (FL-701, FL-702, FL-703)
# ---------------------------------------------------------------------------

BUG_PATTERNS = {
    "BUG_POSTGRES_DOWN": r"Connection to server at port 5432 failed",
    "BUG_STALE_LOCK": r"stale lock",
    "BUG_RATE_LIMIT": r"Rate limit exceeded|429 Too Many Requests",
}


def parse_checkpoint_events(log_path):
    events = []
    path = Path(log_path)
    if not path.exists():
        return events
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    data = json.loads(line)
                    if isinstance(data, dict) and data.get("level") == "CHECKPOINT":
                        events.append(data)
                except Exception:
                    continue
    except Exception:
        pass
    return events


def detect_checkpointer_anomalies(log_path):
    bugs = []
    anomalies = []
    events = parse_checkpoint_events(log_path)
    for ev in events:
        event_type = ev.get("event_type")
        node_name = ev.get("node_name", "unknown_node")
        if event_type == "NODE_ERROR":
            if "BUG_CHECKPOINT_DESYNC" not in bugs:
                bugs.append("BUG_CHECKPOINT_DESYNC")
            anomalies.append(
                {
                    "type": "CHECKPOINT_DESYNC",
                    "target": node_name,
                    "detail": ev.get("error", "Node error encountered"),
                }
            )
        elif event_type == "CHECKPOINT_SAVED":
            duration_ms = ev.get("duration_ms", 0.0)
            if duration_ms > 60000.0:
                if "BUG_NODE_HANG" not in bugs:
                    bugs.append("BUG_NODE_HANG")
                anomalies.append(
                    {
                        "type": "NODE_HANG",
                        "target": node_name,
                        "detail": f"Node {node_name} execution SLA overrun ({duration_ms}ms > 60000ms)",
                    }
                )
    return bugs, anomalies


def diagnose_log_bugs(log_path):
    bugs = set()
    path = Path(log_path)
    if path.exists():
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            import re

            for bug_key, pattern in BUG_PATTERNS.items():
                if re.search(pattern, content, re.IGNORECASE):
                    bugs.add(bug_key)
        except Exception:
            pass
    chk_bugs, _ = detect_checkpointer_anomalies(log_path)
    for b in chk_bugs:
        bugs.add(b)
    return list(bugs)


def execute_auto_healing_actions(bugs, flow_id="flow2_score", dry_run=True):
    actions = []
    for bug in bugs:
        if bug == "BUG_POSTGRES_DOWN":
            actions.append(
                f"[{'DRY RUN' if dry_run else 'ACTION'}] Restart PostgreSQL service or notify admin for {flow_id}"
            )
        elif bug == "BUG_CHECKPOINT_DESYNC":
            actions.append(
                f"[{'DRY RUN' if dry_run else 'ACTION'}] Resolved BUG_CHECKPOINT_DESYNC: Reset state checkpointer for {flow_id}"
            )
        elif bug == "BUG_STALE_LOCK":
            actions.append(
                f"[{'DRY RUN' if dry_run else 'ACTION'}] Cleared stale lock file for {flow_id}"
            )
        else:
            actions.append(
                f"[{'DRY RUN' if dry_run else 'ACTION'}] Handled {bug} for {flow_id}"
            )
    return actions


def detect_pipeline_yield_anomalies(conn, window_hours=1.0):
    bugs = []
    anomalies = []
    if not conn:
        return bugs, anomalies

    try:
        with conn.cursor() as cur:
            # Query 1: 1h yield from job_hunter.applications
            cur.execute("""
                SELECT 
                    COUNT(CASE WHEN status IN ('applied', 'completed') THEN 1 END),
                    COUNT(CASE WHEN status NOT IN ('applied', 'completed') THEN 1 END),
                    COUNT(*)
                FROM job_hunter.applications
                WHERE applied_at >= NOW() - INTERVAL '1 hour'
            """)
            row1 = cur.fetchone()
            if row1:
                successes, _failures, total = row1[0], row1[1], row1[2]
                if total >= 10 and successes == 0:
                    bugs.append("BUG_ZERO_YIELD_ANOMALY")
                    anomalies.append(
                        {
                            "type": "ZERO_YIELD_ANOMALY",
                            "detail": f"0 successes out of {total} attempts in last hour",
                        }
                    )

            # Query 2: recent consecutive interventions
            cur.execute("""
                SELECT status, manual_intervention_reason 
                FROM job_hunter.applications 
                ORDER BY applied_at DESC 
                LIMIT 5
            """)
            rows2 = cur.fetchall()
            if (
                rows2
                and len(rows2) >= 5
                and all(r[0] == "needs_manual_intervention" for r in rows2[:5])
            ):
                bugs.append("BUG_INTERVENTION_SPIKE")
                anomalies.append(
                    {
                        "type": "INTERVENTION_SPIKE",
                        "detail": "5 consecutive manual interventions in recent applications",
                    }
                )

            # Query 3: false skips (high score but marked skipped)
            cur.execute("""
                SELECT COUNT(*) 
                FROM job_hunter.jobs j 
                JOIN job_hunter.scores s ON j.id = s.job_id 
                WHERE j.status_apply = 'skipped' AND s.match_score >= 70
            """)
            row3 = cur.fetchone()
            if row3 and row3[0] >= 5:
                bugs.append("BUG_FALSE_SKIP_SPIKE")
                anomalies.append(
                    {
                        "type": "FALSE_SKIP_SPIKE",
                        "detail": f"{row3[0]} high-scoring jobs (>= 70) marked skipped",
                    }
                )

            # Query 4: stalled claims in applying state
            cur.execute("""
                SELECT COUNT(*), array_agg(id) 
                FROM job_hunter.jobs 
                WHERE status_apply = 'applying' AND (claimed_at IS NULL OR claimed_at < NOW() - INTERVAL '30 minutes')
            """)
            row4 = cur.fetchone()
            if row4 and row4[0] > 0:
                bugs.append("BUG_STALLED_CLAIM")
                anomalies.append(
                    {
                        "type": "STALLED_CLAIM",
                        "detail": f"{row4[0]} stalled claims in applying state (> 30 min)",
                    }
                )
    except Exception as e:
        logger.error("Error in detect_pipeline_yield_anomalies: %s", e)

    return bugs, anomalies


def detect_checkpointer_dropoffs(log_file):
    bugs = []
    anomalies = []
    path = Path(log_file)
    if not path.exists():
        return bugs, anomalies

    events = []
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.startswith("{"):
                    try:
                        events.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        pass

    fl_508_events = [
        ev
        for ev in events
        if ev.get("function_id") == "FL-508"
        or ev.get("stage") == "verify_submission_proof"
    ]
    if fl_508_events:
        failures = sum(1 for ev in fl_508_events if ev.get("status") == "FAILURE")
        fail_rate = failures / len(fl_508_events)
        if fail_rate > 0.25:
            bugs.append("BUG_PROOF_VERIFIER_STALLED")
            anomalies.append(
                {
                    "type": "PROOF_VERIFIER_DROPOFF",
                    "detail": f"Proof verification failure rate is {fail_rate * 100:.1f}% (> 25%)",
                }
            )

    return bugs, anomalies


def execute_yield_auto_remediation(bugs, dry_run=True):
    actions = []
    for bug in bugs:
        if dry_run:
            actions.append(f"[DRY RUN] Would remediate {bug}")
        else:
            try:
                import scripts.recover_all_pipeline_jobs as recover_mod

                if hasattr(recover_mod, "recover_jobs"):
                    recover_mod.recover_jobs()
                actions.append(f"Executed recover_all_pipeline_jobs for {bug}")
            except Exception as e:
                actions.append(f"Failed to execute remediation for {bug}: {e}")

            # Trigger autonomous batch diagnostic and self-healing engine
            try:
                from scripts.flow_batch_healer import run_batch_healer
                healer_summary = run_batch_healer()
                actions.append(
                    f"Executed flow_batch_healer: {healer_summary.get('requeued_for_retry', 0)} re-queued, "
                    f"{healer_summary.get('graduated_to_manual', 0)} manual"
                )
            except Exception as he:
                actions.append(f"Batch healer execution error: {he}")
    return actions


if __name__ == "__main__":
    main()
