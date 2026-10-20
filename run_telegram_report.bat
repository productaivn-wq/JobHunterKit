@echo off
cd /d "%~dp0"
"C:\Users\user\AppData\Local\Programs\Python\Python312\python.exe" -u "scripts\telegram_reporter.py" >> logs\telegram_report.log 2>&1
