"""
watchdog_guard.py — Watchdog-of-the-watchdog for JobHunterKit.

Verifies that skill_watcher.log was updated within the last 90 minutes.
Sends a Telegram alert if stale. Runs as its own SkillWatcherGuard Scheduled
Task (every 2 hours, MultipleInstances=StopExisting) so it is completely
independent of SkillWatcher's own scheduling health.

Usage:
    python watchdog_guard.py              # Production check
    python watchdog_guard.py --dry-run    # Simulate (no Telegram send)
"""

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from shared_platform.notify import send_telegram

LOG_FILE = PROJECT_ROOT / "logs" / "skill_watcher.log"
STALE_THRESHOLD_SECS = 90 * 60  # 90 minutes


def main() -> None:
    """Verifies watcher freshness and sends alerts if heartbeat is stale."""
    parser = argparse.ArgumentParser(
        description="WatchdogGuard: checks skill_watcher.log freshness"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Do not actually send Telegram alert"
    )
    args = parser.parse_args()

    if not LOG_FILE.exists():
        msg = (
            "⚠️ <b>WatchdogGuard Alert</b>\n"
            "<b>skill_watcher.log does not exist.</b>\n"
            "SkillWatcher may never have run or the log path changed."
        )
        print(f"[GUARD] MISSING — {LOG_FILE} does not exist.", flush=True)
        if not args.dry_run:
            send_telegram(msg)
        sys.exit(1)

    age_secs = time.time() - LOG_FILE.stat().st_mtime
    age_min = int(age_secs // 60)

    if age_secs > STALE_THRESHOLD_SECS:
        msg = (
            "🚨 <b>WatchdogGuard Alert</b>\n"
            f"<b>skill_watcher.log is stale</b> ({age_min} min since last update).\n"
            f"Threshold: 90 min. SkillWatcher is likely deadlocked or not triggering.\n"
            f"<i>Check Task Scheduler → \\JobHunterKit\\SkillWatcher for 0x800710E0 errors.</i>"
        )
        print(
            f"[GUARD] STALE — log is {age_min} min old (threshold: 90 min).", flush=True
        )
        if not args.dry_run:
            send_telegram(msg)
        sys.exit(1)
    else:
        print(
            f"[GUARD] OK — skill_watcher.log is {age_min} min old (threshold: 90 min).",
            flush=True,
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
