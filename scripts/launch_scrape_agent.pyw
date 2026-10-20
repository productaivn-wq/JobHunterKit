r"""Windowless launcher for launch_scrape_agent.py.

This .pyw file is designed to be run via pythonw.exe (the windowless Python
interpreter) from Windows Task Scheduler, replacing transient .bat files.

Usage in Task Scheduler:
    Action: "C:\...\pythonw.exe"
    Arguments: "C:\...\scripts\launch_scrape_agent.pyw"
    Start in: "C:\...\JobHunterKit"
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
log_file = LOG_DIR / "flow1_launcher.log"

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
    from scripts.launch_scrape_agent import main
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
