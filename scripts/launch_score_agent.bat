@echo off
cd /d "%~dp0.."
"C:\Users\user\AppData\Local\Programs\Python\Python312\python.exe" scripts/launch_score_agent.py > logs/flow2_launcher.log 2>&1

