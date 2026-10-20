"""Windowless launcher for watchdog_guard.py.

Run via pythonw.exe from Windows Task Scheduler to avoid CMD windows.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
log_file = LOG_DIR / "watchdog_guard_pyw.log"

try:
    _fh = open(log_file, "a", encoding="utf-8")
    sys.stdout = _fh
    sys.stderr = _fh
except Exception:
    sys.stdout = open(os.devnull, "w")
    sys.stderr = sys.stdout

os.chdir(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import runpy
    runpy.run_path(str(HERE / "watchdog_guard.py"), run_name="__main__")
except SystemExit:
    pass
except Exception as e:
    print(f"[PYW LAUNCHER] Fatal error: {e}", flush=True)
    import traceback
    traceback.print_exc()
finally:
    try:
        _fh.close()
    except Exception:
        pass
