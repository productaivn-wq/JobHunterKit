"""
register_cron.py — Automated scheduler registration for JobHunterKit.

Registers the daily JobHunterKit discovery and applying pipeline job
with CronScheduler at 08:00 AM daily.
"""

import os
import sys

# Get user home directory to avoid hardcoding local profile names
home_dir = os.path.expanduser("~")

# Add CronScheduler to path to import it
cron_dir = os.path.join(
    home_dir,
    ".gemini",
    "antigravity",
    "skills",
    "CronScheduler",
    "scripts",
)
sys.path.append(cron_dir)


def register_daily_job() -> bool:
    """Registers the daily JobHunterKit automated pipeline with CronScheduler."""
    try:
        from scheduler import CronScheduler

        # Initialize scheduler pointing to its skill root
        scheduler = CronScheduler(
            os.path.join(home_dir, ".gemini", "antigravity", "skills", "CronScheduler"),
        )

        print("[UTOP|func|register_cron|cp-fr-017]")
        pipeline_path = os.path.join(
            home_dir,
            ".gemini",
            "antigravity",
            "skills",
            "JobHunterKit",
            "scripts",
            "pipeline.py",
        )
        cv_path = os.path.join(
            home_dir,
            ".gemini",
            "antigravity",
            "config",
            "applicant_cv.md",
        )

        cmd = f'python "{pipeline_path}" --keyword "Product Manager AI" --location "Hanoi" --cv "{cv_path}"'

        scheduler.add_job(
            job_id="jobhunter-daily",
            cron_expr="0 8 * * *",  # 8:00 AM Daily
            command=cmd,
            description="Run daily automated job search and apply pipeline for JobHunterKit",
        )

        print("Successfully registered daily cron job 'jobhunter-daily' for 8:00 AM!")
        return True

    except ImportError as e:
        print(f"Failed to import CronScheduler: {e}")
        return False
    except Exception as exc:
        print(f"Error registering cron job: {exc}")
        return False


def main() -> None:
    """CLI entry point for cron registration."""
    success = register_daily_job()
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
