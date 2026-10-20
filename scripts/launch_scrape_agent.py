import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

try:
    from dotenv import load_dotenv

    load_dotenv(project_root / ".env")
except ImportError:
    pass

try:
    from shared_platform.pipeline_state import is_paused
except ImportError:

    def is_paused():
        return False


def touch_log():
    logs_dir = project_root / "logs"
    logs_dir.mkdir(exist_ok=True)
    log_file = logs_dir / "flow1.log"
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(
                f'{{"timestamp": "{now_str}", "level": "INFO", "message": "Flow 1 Launcher heartbeat"}}\n'
            )
    except Exception as e:
        print(f"[LAUNCHER] Failed to touch log: {e}")


def get_next_campaign():
    profile_path = project_root / "config" / "applicant_profile.json"
    if not profile_path.exists():
        return "Product Manager", "Vietnam", "all"

    try:
        with open(profile_path, encoding="utf-8") as f:
            profile_data = json.load(f)
        campaigns = profile_data.get("preferences", {}).get("campaigns", [])
        if not campaigns:
            return "Product Manager", "Vietnam", "all"

        targets = []
        for c in campaigns:
            title = c.get("job_title", "Product Manager")
            for place in c.get("places", ["Vietnam"]):
                targets.append((title, place))

        if not targets:
            return "Product Manager", "Vietnam", "all"

        state_dir = project_root / "data"
        state_dir.mkdir(exist_ok=True)
        state_file = state_dir / "scrape_rotation_state.json"

        idx = 0
        if state_file.exists():
            try:
                with open(state_file, encoding="utf-8") as sf:
                    state_data = json.load(sf)
                    idx = (state_data.get("last_index", 0) + 1) % len(targets)
            except Exception:
                idx = 0

        with open(state_file, "w", encoding="utf-8") as sf:
            json.dump(
                {
                    "last_index": idx,
                    "updated_at": datetime.datetime.now().isoformat(),
                },
                sf,
            )

        target_title, target_place = targets[idx]
        return target_title, target_place, "all"
    except Exception as e:
        print(f"[LAUNCHER] Error reading campaigns for rotation: {e}")
        return "Product Manager", "Vietnam", "all"


def main():
    parser = argparse.ArgumentParser(description="Launch Flow 1 Scraper Agent")
    parser.add_argument("--keyword", default=None, help="Job search keyword")
    parser.add_argument("--location", default=None, help="Job search location")
    parser.add_argument(
        "--source", default=None, help="Job board source (default: all)"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Max jobs to scrape"
    )
    parser.add_argument(
        "--log", action="store_true", help="Enable file logging"
    )
    args = parser.parse_args()

    touch_log()
    if is_paused():
        print("[LAUNCHER] Pipeline is paused. Skipping scrape agent run.")
        return

    if args.keyword and args.location:
        keyword = args.keyword
        location = args.location
        source = args.source or "all"
    else:
        keyword, location, source = get_next_campaign()

    print(
        f"[LAUNCHER] Starting Flow 1 scraper for '{keyword}' in '{location}' (source: {source})..."
    )

    py_exec = sys.executable.replace("pythonw.exe", "python.exe") if "pythonw" in sys.executable.lower() else sys.executable
    cmd = [
        py_exec,
        "-u",
        str(project_root / "scripts" / "flow_scrape.py"),
        "--keyword",
        keyword,
        "--location",
        location,
        "--source",
        source,
    ]
    if args.limit:
        cmd.extend(["--limit", str(args.limit)])
    # Always log to flow1.log for heartbeat and observability
    cmd.append("--log")

    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(project_root),
        env=env,
        creationflags=creationflags,
    )

    if res.stdout:
        print(res.stdout)
    if res.stderr:
        print(res.stderr, file=sys.stderr)

    print(f"[LAUNCHER] Flow 1 completed with exit code: {res.returncode}")


if __name__ == "__main__":
    main()

