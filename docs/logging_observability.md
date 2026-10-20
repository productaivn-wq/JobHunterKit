# JobHunterKit: Logging & Observability Guide

This guide documents the logging, telemetry, and health-checking mechanisms of JobHunterKit, bridging the gap between design requirements and the actual production implementation.

## 1. Log Format & Structure

The system uses a centralized logging architecture defined in [`shared_platform/logging_setup.py`](file:///C:/Users/user/.gemini/antigravity/skills/JobHunterKit/shared_platform/logging_setup.py).

All executed flows wrapped by the `@flow_entrypoint` decorator automatically capture standard output, standard error, and exceptions, converting them into structured JSON events. 

### JSON Event Structure
Each log entry is a JSON object with the following baseline fields:
* `timestamp`: ISO 8601 UTC string appended with "Z" (e.g., `"2026-08-13T01:01:53Z"`). Note that the flow entrypoint messages use `"YYYY-MM-DD HH:MM:SS"` format for timestamps.
* `level`: Uppercase string representing the severity (`INFO`, `ERROR`, `FATAL`).
* `message`: Human-readable description of the event.
* Additional arbitrary key-value pairs (e.g., `traceback`, `error`) depending on the context.

## 2. Log File Locations

Logs are stored in the project's `logs/` directory, resolved relative to the kit's root folder.

* **File Naming**: Logs are named dynamically based on the flow being executed: `logs/<flow_name>.log`.
* **Writing Strategy**: Handled by the `TeeStream` class, logs are teed to both the standard console (stdout/stderr) and the log file.
* **Buffering**: Files are opened with `buffering=1` (line-buffered) ensuring immediate real-time flushing to disk, which is vital for heartbeats.
* **Retention/Rotation**: Log files are automatically rotated when they reach 10 MB in size. Up to 5 backup files are kept, enforcing a maximum storage cap of roughly 60 MB (1 active + 5 backups) per flow.

## 3. Log Level Conventions

Based on the usage in `logging_setup.py`, the following log levels are standardized:
* **INFO**: Used for general lifecycle events, such as starting a phase/flow and reporting successful completion.
* **ERROR**: Used when a flow crashes. It automatically captures and includes the stack trace (`traceback`).
* **FATAL**: Used at the end of a flow lifecycle if the exit code is non-zero, indicating failure of the entire process.

*(DEBUG and WARNING are not explicitly mandated by the central logger, though underlying libraries may emit them).*

## 4. LangFuse Telemetry Integration

Pipeline telemetry is handled in [`shared_platform/telemetry.py`](file:///C:/Users/user/.gemini/antigravity/skills/JobHunterKit/shared_platform/telemetry.py), compatible with LangFuse SDK v4.x (OTEL-based API). It provides full observability into scraping, scoring, and applying nodes. 

* **Graceful Degradation**: Telemetry gracefully degrades if `LANGFUSE_ENABLED=false`, API keys are missing, or the `langfuse` package is uninstalled.
* **Trace Creation (`create_trace`)**: Generates a top-level `jobhunter-pipeline` trace for a run. Captures inputs (`keyword`, `location`, `source`) and metadata (`conversation_id`, `trace_id`).
* **Scoring (`score_trace`)**: Records custom metrics and model evaluations against a specific `trace_id` (e.g., CV match scores, LLM Judge proof verification scores `llm_judge_score`).
* **LLM-as-a-Judge Review (`shared_platform/llm_judge.py`)**: Uses Gemini to evaluate application submission proofs and screenshots, outputting structured JSON logs (`is_valid_submission`, `confidence`, `detected_status`, `reasoning`) and recording score metrics on LangFuse.
* **Finalization (`end_trace`)**: Concludes a trace, recording the final output and status (`completed` or otherwise).

## 5. Health Check System

The Pre-Flight Health Validator (`shared_platform/health_check.py`) ensures that infrastructure and authentication are valid prior to executing a pipeline.

### Validations Performed:
1. **Database Health**: Connects to the database and verifies it can run a basic `SELECT COUNT(*)` on the `job_hunter.jobs` table.
2. **LinkedIn Authentication**: Parses `scripts/state.json` to verify the presence of the `li_at` cookie and checks that it is not expired.
3. **IPC Daemon Health**: Checks via PowerShell (`Get-CimInstance Win32_Process`) if `ipc_daemon.py` is actively running.

### Enforcement Rules:
* `flow1_scrape` and `flow2_score`: Strictly require a healthy Database connection.
* `flow3_apply`: Requires Database connection. If LinkedIn authentication is invalid, it raises a **warning** and proceeds, flagging applications for manual intervention instead of crashing.

## 6. Alerting & Watchdog Guard

Log freshness is monitored by `scripts/watchdog_guard.py` to prevent silent failures or deadlocks.

* **Target**: Monitors `logs/skill_watcher.log`.
* **Threshold**: 15 minutes. (Aligned with the DEPLOYMENT_CHECKLIST.md requirements).
* **Action**: If the log file is missing or its modification time exceeds 15 minutes, it prints an alert and triggers a Telegram notification via `shared_platform.notify.send_telegram`.
* **Root Causes Addressed**: Protects against scenarios where the main Windows Task Scheduler task (`SkillWatcher`) fails to trigger (e.g., error `0x800710E0`) or deadlocks.

## 7. Querying & Analysis

Since the core events are output in JSON format, they are easily queried from the terminal.

* **Search for Errors**: `grep '"level": "ERROR"' logs/<flow_name>.log`
* **Search for Fatal crashes**: `grep '"level": "FATAL"' logs/<flow_name>.log`
* **Extract specific flow runs via JQ**: `cat logs/pipeline.log | jq 'select(.level=="ERROR")'`

For LangFuse tracing, navigate to the LangFuse dashboard UI to search by `conversation_id` or `trace_id` attached to the pipeline runs.
