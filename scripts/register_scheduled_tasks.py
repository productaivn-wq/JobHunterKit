"""
register_scheduled_tasks.py — Automated Windows Task Scheduler registration for JobHunterKit.

Registers and manages Windows Scheduled Tasks for JobHunterKit:
- Flow_Telegram_Report (every 2 hours, headless via pythonw.exe)
- SkillWatcher (every 30 minutes, headless via pythonw.exe)
- SkillWatcherGuard (every 2 hours, headless via pythonw.exe)
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
PYTHONW_PATH = sys.executable.replace("python.exe", "pythonw.exe")
if not os.path.exists(PYTHONW_PATH):
    PYTHONW_PATH = sys.executable


def build_task_xml(task_name: str, exec_path: str, arguments: str, interval: str = "PT2H") -> str:
    xml_content = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <URI>\\JobHunterKit\\{task_name}</URI>
  </RegistrationInfo>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
    </Principal>
  </Principals>
  <Settings>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <Enabled>true</Enabled>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <StartWhenAvailable>true</StartWhenAvailable>
    <IdleSettings>
      <Duration>PT10M</Duration>
      <WaitTimeout>PT1H</WaitTimeout>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <UseUnifiedSchedulingEngine>true</UseUnifiedSchedulingEngine>
  </Settings>
  <Triggers>
    <TimeTrigger>
      <StartBoundary>2026-08-21T08:00:00</StartBoundary>
      <Repetition>
        <Interval>{interval}</Interval>
        <Duration>P3650D</Duration>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </TimeTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>{exec_path}</Command>
      <Arguments>{arguments}</Arguments>
    </Exec>
  </Actions>
</Task>"""
    return xml_content


def register_task(task_name: str, script_name: str, interval: str) -> bool:
    """Registers or updates a \\JobHunterKit\\<task_name> scheduled task."""
    script_path = str(HERE / script_name)
    xml = build_task_xml(
        task_name=task_name,
        exec_path=PYTHONW_PATH,
        arguments=f'"{script_path}"',
        interval=interval,
    )

    with tempfile.NamedTemporaryFile("w", encoding="utf-16", suffix=".xml", delete=False) as tf:
        tf.write(xml)
        temp_xml_path = tf.name

    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        cmd = ["schtasks", "/create", "/tn", f"\\JobHunterKit\\{task_name}", "/xml", temp_xml_path, "/f"]
        result = subprocess.run(cmd, capture_output=True, text=True, errors="ignore", creationflags=creationflags)
        if result.returncode == 0:
            print(f"[SUCCESS] Registered scheduled task \\JobHunterKit\\{task_name} (interval: {interval})")
            return True
        else:
            print(f"[ERROR] Failed to register task \\JobHunterKit\\{task_name}: {result.stderr.strip() or result.stdout.strip()}")
            return False
    finally:
        try:
            os.remove(temp_xml_path)
        except Exception:
            pass


def main():
    print("[*] Registering JobHunterKit Windows Scheduled Tasks...")
    tasks = [
        ("Flow1_Scrape", "launch_scrape_agent.pyw", "PT2H"),
        ("Flow2_Score", "launch_score_agent.pyw", "PT30M"),
        ("Flow3_Apply", "launch_apply_agent.pyw", "PT30M"),
        ("Flow_Telegram_Report", "telegram_reporter.pyw", "PT2H"),
        ("Flow_EBQC_Crystallizer", "ebqc_crystallizer.pyw", "PT1H"),
        ("SkillWatcher", "skill_watcher.pyw", "PT15M"),
        ("SkillWatcherGuard", "watchdog_guard.pyw", "PT2H"),
    ]

    all_ok = True
    for task_name, script_name, interval in tasks:
        ok = register_task(task_name, script_name, interval)
        if not ok:
            all_ok = False

    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
