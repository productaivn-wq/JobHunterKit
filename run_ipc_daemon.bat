@echo off
REM IPC Daemon launcher - keeps LLM routing bridge alive for JobHunterKit (AGY CLI via LLMProviderRouter)
cd /d "d:\WORK\\01_PROJECTS\\46_JOB_HUNTER\cv_and_profiles\skills\JobHunterKit"
mkdir logs 2>nul
echo [%date% %time%] Starting IPC Daemon >> logs\ipc_daemon.log
:loop
"C:\Users\user\AppData\Local\Programs\Python\Python312\python.exe" -u "d:\WORK\\01_PROJECTS\\46_JOB_HUNTER\cv_and_profiles\skills\JobHunterKit\scripts\ipc_daemon.py" >> logs\ipc_daemon.log 2>&1
echo [%date% %time%] [IPC DAEMON] Crashed or exited. Restarting in 5s... >> logs\ipc_daemon.log
ping -n 6 127.0.0.1 >nul
goto loop
