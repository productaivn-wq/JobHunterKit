# JobHunterKit Operations & Infrastructure Runbook

This document describes the operational procedures, infrastructure setup, runtime artifacts, and self-healing mechanisms for the JobHunterKit project.

## 1. Secrets & Credentials Setup

The `.env` file located at `.\.env` defines the necessary credentials for system operations. **Do not commit actual values to version control.**

### 1.1 Workflow (.env.example -> .env)

1. A template file `.env.example` is maintained in version control.
2. When setting up a new environment, copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
3. Open `.env` and replace all `YOUR_*_HERE` placeholders with actual secret values.
4. The `.env` file is explicitly ignored in `.gitignore` to prevent accidental credential leakage.

### 1.2 Required Variables

| Variable Name | Required? | Purpose | Example Format |
|---------------|-----------|---------|----------------|
| `TWOCAPTCHA_API_KEY` | Yes | API key for 2Captcha service used in solving CAPTCHAs. | `32-character hex string` |
| `2CAPTCHA_API_KEY` | Yes | Fallback alias for the 2Captcha key. | `32-character hex string` |
| `GMAIL_USER` | Yes | Target Gmail account for receiving communications or reports. | `email@gmail.com` |
| `GOOGLE_CLIENT_ID` | Yes | OAuth Client ID for Google API authentication. | `string.apps.googleusercontent.com` |
| `GOOGLE_CLIENT_SECRET` | Yes | OAuth Client Secret for Google API authentication. | `Alphanumeric string` |
| `GMAIL_REFRESH_TOKEN` | Yes | Long-lived token to generate new access tokens. | `1//...` |
| `GMAIL_ACCESS_TOKEN` | Yes | Short-lived token for immediate API requests. | `ya29....` |
| `GMAIL_TOKEN_URI` | Yes | Endpoint to refresh tokens. | `https://oauth2.googleapis.com/token` |

Note: Pre-flight checks (`health_check.py`) will automatically warn if critical environment variables are missing during startup.

## 2. PostgreSQL Infrastructure & Database Setup

The primary production environment relies on a **native PostgreSQL service** running directly on the host machine (listening on `localhost:5432` or the host configured in `DB_URL`).

### 2.1 Native PostgreSQL Setup (Primary)
- **Service Name:** Standard PostgreSQL service (e.g. `postgresql-x64-16` on Windows or `postgresql` systemd service on Linux).
- **Default Port:** `5432`
- **Configuration:** Set `DB_URL` in `.env` to point to the native instance (e.g., `postgresql://postgres:<password>@localhost:5432/postgres`).
- **Initialization:** Database schema and table structures are initialized via `python scripts/db_setup.py`.

### 2.2 Docker Container Setup (Development / CI Fallback)
For development or automated testing environments without a local native PostgreSQL instance, the helper script [`start_database.ps1`](file:///./10_ACTIVE_TIMEBOUND/Project/app/scripts/start_database.ps1) can be used.
- **Container Name:** `pg-local`
- **Image:** `postgres:latest`
- **Port Mapping:** `5432:5432`
- **Authentication:** `POSTGRES_PASSWORD=postgres_local`
- **Startup Sequence:** Verifies Docker daemon status, launches or starts container `pg-local`, and runs a health check via `psycopg2`.

## 3. Launcher Scripts Reference

Launcher scripts are located in [`.\10_ACTIVE_TIMEBOUND\Project\launchers\`](file:///./10_ACTIVE_TIMEBOUND/Project/launchers/).

| Script | Purpose | Arguments |
|--------|---------|-----------|
| `run_jobhunter.ps1` | Primary CLI entrypoint. Runs phases without stealing IDE focus. Ensures the IPC daemon is running. | `-Phase [scrape, score, apply, report, all]` (default: apply)<br>`-Headless [true/false/1/0]` (default: true) |
| `run_jobhunter.bat` | Windows batch wrapper for `run_jobhunter.ps1`. | Forwards arguments directly. |
| `run_preferences.py` | Python CLI runner for parallel campaign scraping and scoring. | `--profile [path]`, `--dry-run`, `--force`, `--threshold [int]`, `--cv [path]`, `--parallel`, `--max-workers [int]` |
| `launch_parallel_apply.ps1` | Launches multiple parallel workers for Flow 3 (Auto-Apply) in hidden background processes. Expects active IPC daemon or launched via `run_jobhunter.ps1`. | `-Workers [int]` (default: 3) |
| `run_mass_markets.bat` | *Deprecated*. Now calls `run_jobhunter.ps1 -Phase apply`. | None |
| `run_tcb.bat` | *Deprecated*. Now calls `run_jobhunter.ps1 -Phase apply`. | None |

## 4. Runtime Artifact Layout

The active continuous operations data resides in [`.\20_ACTIVE_CONTINUOUS\Operations\runtime\`](file:///./20_ACTIVE_CONTINUOUS/Operations/runtime/).

- `antigravity_registry.db`: SQLite database for tracking registry and state.
- `jobright_cookies.json`: Session cookies for maintaining authentication across scraping/apply runs.
- `jobright_auth_test.png`: Debug screenshot output.
- `ipc/`: Inter-Process Communication buffers for sharing state between agents and daemons.
- `Diagnostics/`: Logs and debug output traces.
- `jobright_batch/`, `scratch/`, `tmp/`: Temporary processing and staging directories.

## 5. Monitoring & Watchdog Infrastructure

The system employs a two-tier self-healing watchdog architecture.

### Tier 1: Skill Watcher (`skill_watcher.py`)
- **Role:** Primary self-healing daemon.
- **Schedule:** Triggered every 30 minutes via Windows Task Scheduler (`\JobHunterKit\SkillWatcher`).
- **Operation:**
  1. Checks log timestamps for monitored flows (`flow1_scrape`, `flow2_score`, `flow3_apply`, `ipc_daemon`).
  2. If logs are stale (e.g., >45 min for flow1) or detect fatal JSON error loops, it searches for zombie Python processes via PowerShell WMI.
  3. Uses `taskkill /F /T` to terminate zombies.
  4. Unlocks stuck DB states (`scoring -> pending`, `applying -> pending`) to prevent dropped queue items.
  5. Restarts the failed Task Scheduler jobs automatically.
  6. Sends Telegram alerts for anomalies, failures, and recoveries.

### Tier 2: Watchdog Guard (`watchdog_guard.py`)
- **Role:** Monitors the monitor. Independent of `SkillWatcher` task schedule.
- **Schedule:** Runs every 2 hours as Task `SkillWatcherGuard`.
- **Operation:** 
  1. Checks if `logs/skill_watcher.log` has been updated in the last 15 minutes.
  2. If stale, the main watcher is dead/deadlocked. It sends a critical Telegram alert.

## 6. Cold Start Sequence

To bring up the entire environment from a stopped state:
1. Ensure `.env` is populated with valid credentials and correct `DB_URL`.
2. Ensure the native PostgreSQL service is running on the host system (or run `start_database.ps1` if using a local Docker dev container).
3. If using the UI/IDE, start the Antigravity system.
4. Run `run_jobhunter.ps1 -Phase all` for a full run, or `launch_parallel_apply.ps1` if prioritizing queue processing. 
   - Note: Launchers automatically verify and start the background IPC Daemon (`ipc_daemon.py`) if not already running.

## 7. Troubleshooting Guide

- **PostgreSQL Connection Failed:** Verify the native PostgreSQL OS service is running (`Get-Service postgresql*` in PowerShell or `systemctl status postgresql` in Linux) and listening on port 5432. If using the Docker dev environment, verify Docker Desktop is running (`docker ps`).
- **Stuck Jobs (Scoring/Applying indefinitely):** Run `python skill_watcher.py` manually to invoke self-healing, which executes the SQL reset scripts and kills zombie processes.
- **Telegram Wait Timeouts:** If a process asks for manual Telegram verification, the self-healing monitor will ignore it for a maximum of 5 minutes before treating it as stalled.
- **SkillWatcher Fails to Kill PID:** Task might be running under an elevated profile while `skill_watcher.py` isn't. Ensure both share execution scopes. Check for `0x800710E0` errors in Windows Task Scheduler.

## 8. Pre-Flight Health Checks

The pipeline utilizes a pre-flight health checker (`health_check.py`) to verify system readiness before executing runs.
- **Database:** Validates connectivity and verifies query execution.
- **LinkedIn Auth:** Validates `state.json` for `li_at` cookie presence and expiration.
- **IPC Daemon:** Verifies the `ipc_daemon.py` background process is active. The check is cross-platform: it uses PowerShell (WMI) on Windows, and falls back to standard `ps aux` on Linux/macOS environments.

