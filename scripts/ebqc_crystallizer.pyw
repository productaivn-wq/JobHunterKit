r"""Windowless launcher for ebqc_crystallizer.py.

This .pyw file is designed to be run via pythonw.exe (the windowless Python
interpreter) from Windows Task Scheduler every 1 hour.
"""
import os
import sys
from pathlib import Path

# Set up project root
HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent

# Redirect stdout/stderr to log files
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
log_file = LOG_DIR / "ebqc_crystallizer_pyw.log"

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
    from scripts.ebqc_crystallizer import run_crystallization
    run_crystallization(window_hours=1.0, notify=True)
except Exception as e:
    print(f"[PYW LAUNCHER] Fatal error: {e}", flush=True)
    import traceback
    traceback.print_exc()
finally:
    try:
        _fh.close()
    except Exception:
        pass
