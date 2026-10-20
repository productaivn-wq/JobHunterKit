import os
import subprocess
import sys
from pathlib import Path

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

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

try:
    from dotenv import load_dotenv

    load_dotenv(project_root / ".env")
except ImportError:
    pass

from shared_platform.pipeline_state import is_paused


def touch_log():
    import datetime

    logs_dir = project_root / "logs"
    logs_dir.mkdir(exist_ok=True)
    log_file = logs_dir / "flow2.log"
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(
                f'{{"timestamp": "{now_str}", "level": "INFO", "message": "Flow 2 Launcher heartbeat"}}\n'
            )
    except Exception as e:
        print(f"[LAUNCHER] Failed to touch log: {e}")


def main():
    touch_log()
    if is_paused():
        print("[LAUNCHER] Pipeline is paused. Skipping scoring agent run.")
        return

    print(f"[LAUNCHER] Starting Flow 2 scorer in {project_root}...")

    py_exec = sys.executable.replace("pythonw.exe", "python.exe") if "pythonw" in sys.executable.lower() else sys.executable
    cmd = [
        py_exec,
        "-u",
        str(project_root / "scripts" / "flow_score.py"),
        "--log",
    ]

    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.run(
        cmd,
        cwd=str(project_root),
        creationflags=creationflags,
    )
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()

