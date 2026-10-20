"""Windowless launcher for telegram_reporter.py.

Run via pythonw.exe from Windows Task Scheduler to avoid CMD windows.
Passes through all command-line arguments (e.g. --log).
"""
import datetime
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
log_file = LOG_DIR / "telegram_reporter_pyw.log"

try:
    _fh = open(log_file, "a", encoding="utf-8")
    sys.stdout = _fh
    sys.stderr = _fh
except Exception:
    _fh = None
    sys.stdout = open(os.devnull, "w")
    sys.stderr = sys.stdout

os.chdir(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
print(f"[{now_str}] [TELEGRAM_REPORTER_PYW] Starting telegram_reporter...", flush=True)

try:
    import runpy
    runpy.run_path(str(HERE / "telegram_reporter.py"), run_name="__main__")
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [TELEGRAM_REPORTER_PYW] Finished successfully.", flush=True)
except SystemExit as se:
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [TELEGRAM_REPORTER_PYW] Exited with code {se.code}", flush=True)
except Exception as e:
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [TELEGRAM_REPORTER_PYW] Fatal error: {e}", flush=True)
    import traceback
    traceback.print_exc()
finally:
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        if _fh:
            _fh.flush()
            _fh.close()
    except Exception:
        pass

