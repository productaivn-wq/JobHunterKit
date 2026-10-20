import datetime
import html
import os
import sys
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path)

from core.db_client import get_connection
from shared_platform.notify import send_telegram as send_telegram_msg


def get_stats():
    conn = get_connection()
    stats = {}
    try:
        with conn.cursor() as cur:
            # Total jobs
            cur.execute("SELECT COUNT(*) FROM job_hunter.jobs")
            stats["total_jobs"] = cur.fetchone()[0]

            # Scored status
            cur.execute(
                "SELECT status_score, COUNT(*) FROM job_hunter.jobs GROUP BY status_score"
            )
            score_stats = dict(cur.fetchall())
            stats["score_completed"] = score_stats.get("completed", 0)
            stats["score_failed"] = score_stats.get("failed", 0)
            stats["score_pending"] = score_stats.get("pending", 0) + score_stats.get("scoring", 0)
            stats["score_prefiltered"] = score_stats.get("skipped_prefilter", 0) + score_stats.get("skipped_excluded_company", 0)

            # Apply status
            cur.execute(
                "SELECT status_apply, COUNT(*) FROM job_hunter.jobs GROUP BY status_apply"
            )
            apply_stats = dict(cur.fetchall())
            stats["apply_completed"] = apply_stats.get("completed", 0)
            stats["apply_failed"] = apply_stats.get("failed", 0) + apply_stats.get("failed_manual", 0)
            stats["apply_applying"] = apply_stats.get("applying", 0)
            stats["apply_manual_required"] = apply_stats.get(
                "manual_required", 0
            ) + apply_stats.get("needs_manual_intervention", 0)
            stats["apply_skipped"] = apply_stats.get("skipped", 0)
            stats["apply_standby"] = apply_stats.get("standby", 0)

            # True ready-to-apply (scored and approved)
            cur.execute(
                "SELECT COUNT(*) FROM job_hunter.jobs WHERE status_score = 'completed' AND status_apply = 'pending'"
            )
            stats["apply_ready"] = cur.fetchone()[0]

            # Applied today (UTC+7 timezone offset check)
            local_midnight = datetime.datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            utc_midnight = local_midnight - datetime.timedelta(hours=7)
            cur.execute(
                """
                SELECT j.company, j.title, a.applied_at
                FROM job_hunter.applications a
                JOIN job_hunter.jobs j ON a.job_id = j.id
                WHERE a.status IN ('applied', 'completed')
                  AND a.applied_at >= %s
                ORDER BY a.applied_at DESC
            """,
                (utc_midnight,),
            )
            raw_applied = cur.fetchall()
            seen = set()
            applied_today = []
            for company, title, applied_at in raw_applied:
                comp_norm = (company or "").strip().lower()
                title_norm = (title or "").strip().lower()
                key = (comp_norm, title_norm)
                if key not in seen:
                    seen.add(key)
                    applied_today.append((company, title, applied_at))
            stats["applied_today"] = applied_today
    finally:
        conn.close()
    return stats


def check_daemon_health():
    log_path = project_root / "logs" / "ipc_daemon.log"
    if not log_path.exists():
        return "❌ Not Installed/No Log"

    # Check if modified in the last 15 minutes
    mtime = log_path.stat().st_mtime
    dt_mtime = datetime.datetime.fromtimestamp(mtime)
    dt_now = datetime.datetime.now()
    delta = (dt_now - dt_mtime).total_seconds()

    # Check if process is running
    import subprocess

    daemon_running = False
    if sys.platform == "win32":
        try:
            creationflags = (
                subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            output = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_Process | Where-Object Name -eq python.exe | Select-Object -ExpandProperty CommandLine",
                ],
                capture_output=True,
                text=True,
                errors="ignore",
                creationflags=creationflags,
            ).stdout
            if "ipc_daemon.py" in output and "ipc_daemon_vertex.py" not in output:
                daemon_running = True
        except Exception:
            pass
    else:
        try:
            output = subprocess.run(
                ["ps", "aux"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                errors="ignore",
            ).stdout
            if "ipc_daemon.py" in output and "ipc_daemon_vertex.py" not in output:
                daemon_running = True
        except Exception:
            pass

    if daemon_running:
        return "🟢 Active (Process Running)"
    elif delta < 900:  # 15 minutes
        return "🟡 Active (Recent Log Activity)"
    else:
        return "🔴 Inactive (Stale)"


def generate_report():
    try:
        stats = get_stats()
    except Exception as db_err:
        print(f"[ERROR] Database error: {db_err}")
        escaped_err = html.escape(str(db_err))
        send_telegram_msg(
            f"<b>⚠️ Job Hunter Kit System Alert</b>\n\nDatabase connection failed:\n<code>{escaped_err}</code>"
        )
        return

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    msg_parts = [
        "🤖 <b>Job Hunter Kit - Progress & Health Report</b>",
        f"<i>Local Time: {now_str}</i>\n",
        "<b>📊 Database Queue Statistics:</b>",
        f"• Total Jobs: <b>{stats.get('total_jobs', 0)}</b>",
        f"• Scoring: <b>{stats.get('score_completed', 0)}</b> completed | <b>{stats.get('score_pending', 0)}</b> pending | <b>{stats.get('score_prefiltered', 0)}</b> pre-filtered",
        "• Applications:",
        f"  - ✅ Applied: <b>{stats.get('apply_completed', 0)}</b>",
        f"  - 🔄 Applying: <b>{stats.get('apply_applying', 0)}</b>",
        f"  - ⏳ Ready to Apply: <b>{stats.get('apply_ready', 0)}</b>",
        f"  - 💤 Awaiting Score: <b>{stats.get('apply_standby', 0)}</b>",
        f"  - ⚠️ Manual Intervention: <b>{stats.get('apply_manual_required', 0)}</b>",
        f"  - ❌ Failed: <b>{stats.get('apply_failed', 0)}</b>",
        f"  - ⏭️ Skipped / Ineligible: <b>{stats.get('apply_skipped', 0)}</b>\n",
        "<b>🚀 Successful Applications Today:</b>",
    ]

    applied_today = stats["applied_today"]
    if applied_today:
        limit = 15
        for idx, (company, title, applied_at) in enumerate(applied_today[:limit], 1):
            escaped_company = html.escape(company or "Unknown Company")
            escaped_title = html.escape(title or "Unknown Title")
            msg_parts.append(f" {idx}. <b>{escaped_company}</b> - {escaped_title}")
        if len(applied_today) > limit:
            msg_parts.append(
                f" <i>... and {len(applied_today) - limit} more successful applications today.</i>"
            )
    else:
        msg_parts.append(" <i>None yet today.</i>")

    msg_parts.extend(
        [
            "\n<b>🔌 System Health Check:</b>",
            "• Database Connection: <b>🟢 Connected</b>",
        ]
    )

    full_message = "\n".join(msg_parts)
    print("Sending report to Telegram...")
    success = send_telegram_msg(full_message)
    if success:
        print("Telegram report sent successfully.")
    else:
        print("Telegram report sending failed.")


def setup_log_redirection(flow_name):
    import atexit
    import datetime
    import sys

    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    logs_dir = os.path.join(project_root, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_file = os.path.join(logs_dir, f"{flow_name}.log")

    f = open(log_file, "a", encoding="utf-8")
    now_str = datetime.datetime.now().strftime("%m/%d/%Y %I:%M:%S %p")
    f.write(f"[{now_str}] Starting {flow_name.upper()} \n")
    f.flush()
    sys.stdout = f
    sys.stderr = f

    def exit_handler():
        now_str = datetime.datetime.now().strftime("%m/%d/%Y %I:%M:%S %p")
        f.write(f"[{now_str}] {flow_name.upper()} finished with exit code 0\n")
        f.close()

    atexit.register(exit_handler)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="JobHunterKit Telegram Reporter")
    parser.add_argument(
        "--log",
        action="store_true",
        help="Enable file logging instead of console output",
    )
    args = parser.parse_args()
    if args.log:
        setup_log_redirection("telegram_report")
    generate_report()
