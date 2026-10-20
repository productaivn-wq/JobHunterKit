@echo off
cd /d "%~dp0.."
"C:\Users\user\AppData\Local\Programs\Python\Python312\python.exe" scripts/launch_apply_agent.py > logs/flow3_launcher.log 2>&1

