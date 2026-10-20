@echo off
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0.."
"C:\Users\user\AppData\Local\Programs\Python\Python312\python.exe" scripts/launch_scrape_agent.py > logs/flow1_launcher.log 2>&1
