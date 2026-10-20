r"""Windowless launcher for launch_score_agent.py.

This .pyw file is designed to be run via pythonw.exe (the windowless Python
interpreter) from Windows Task Scheduler, replacing the old .bat + wscript.exe
+ silent_run.vbs chain that created visible CMD windows.

Usage in Task Scheduler:
    Action: "C:\...\pythonw.exe"
    Arguments: "D:\...\scripts\launch_score_agent.pyw"
    Start in: "D:\...\JobHunterKit"
"""
import os
import sys
from pathlib import Path

# Set up project root (same as launch_score_agent.py)
HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent

# Redirect stdout/stderr to log files so nothing is lost
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
log_file = LOG_DIR / "flow2_launcher.log"

try:
    _fh = open(log_file, "a", encoding="utf-8")
    sys.stdout = _fh
    sys.stderr = _fh
except Exception:
    sys.stdout = open(os.devnull, "w")
    sys.stderr = sys.stdout

# Change working directory to project root
os.chdir(str(PROJECT_ROOT))

# Add project root to sys.path and import the actual launcher
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from scripts.launch_score_agent import main
    main()
except Exception as e:
    print(f"[PYW LAUNCHER] Fatal error: {e}", flush=True)
    import traceback
    traceback.print_exc()
finally:
    try:
        _fh.close()
    except Exception:
        pass
