# JobHunterKit Production Deployment Checklist

This document details the step-by-step pre-flight verification and launch checklist required before executing production application campaigns in `JobHunterKit`.

---

## 1. Pre-Flight Environment & SSOT Verification

- [ ] **SSOT Root Verification**: Confirm project root `.` and data root `./data` exist and have full write permissions.
- [ ] **Master CV Check**: Verify canonical Master CV text is present at `./20_ACTIVE_CONTINUOUS/cv_text.txt`.
- [ ] **Environment Configuration (`.env`)**:
  - [ ] `GEMINI_API_KEY` is configured and active.
  - [ ] `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are configured for real-time alerting.
  - [ ] `LANGFUSE_SECRET_KEY` and `LANGFUSE_PUBLIC_KEY` are configured if telemetry is enabled (`LANGFUSE_ENABLED=true`).

---

## 2. Database & Storage Initialization

- [ ] **Supabase / PostgreSQL DB Schema**: Run database initialization script:
  ```bash
  python scripts/db_setup.py
  ```
  Ensure PostgreSQL creates schema `job_hunter` and all core tables (`jobs`, `scores`, `applications`, `discovered_channels`, `pipeline_state`, `report_snapshots`) with proper indices and constraints.
- [ ] **Database Migration Verification**: Ensure `scripts/migrate_db.py` applies all schema updates without errors.

---

## 3. Cookie & Candidate Profile Freshness

- [ ] **Candidate Profile (`config/applicant_profile.json`)**: Validate candidate email (`applicant@example.com`), phone number, location, and pre-seeded screening answers.
- [ ] **Browser Session Cookies (`scripts/state.json`)**:
  - Run session refresh if cookies are expired:
    ```bash
    python scripts/login_linkedin.py
    ```
  - Verify Playwright `storageState` JSON contains active auth cookies for targeted job portals (LinkedIn, ITViec, VietnamWorks).

---

## 4. Subsystem & Daemon Service Startup

- [ ] **Socket IPC Daemon**: Launch LLM IPC daemon service:
  ```bash
  python scripts/ipc_daemon.py
  ```
  Confirm daemon logs indicate socket binding at `ipc_1/gemini_ipc.sock` (or Windows IPC named pipe/port) and Gemini API connection initialization.
- [ ] **Process Health Watcher (`scripts/skill_watcher.py`)**: Start auto-healing process watcher (note: the 15-minute threshold applies to `scripts/watchdog_guard.py` monitoring `skill_watcher.log` freshness, while individual flow heartbeats—flow_scrape: 45min, flow_score: 30min, flow_apply: 30min—use longer thresholds appropriate for their execution cycles):
  ```bash
  python scripts/skill_watcher.py
  ```

---

## 5. Verification & Dry-Run Test

- [ ] **Pytest Suite Verification**: Execute unit and integration tests to ensure 100% pass rate:
  ```bash
  pytest
  ```
- [ ] **Telegram Alerting Sanity Check**: Send test notification to verify candidate incident reporting:
  ```bash
  python scripts/telegram_reporter.py --test
  ```
- [ ] **Pipeline Dry-Run**: Run single-job dry-run campaign to verify full LangGraph workflow (`scrape_node` -> `score_node` -> `tailor_node` -> `apply_node` -> `proof_review_node`):
  ```bash
  python scripts/pipeline.py --keyword "AI System Architect" --location "Hanoi" --source "itviec" --dry-run
  ```

---

## 6. Live Production Launch

- [ ] **Trigger Production Pipeline**:
  ```bash
  python scripts/pipeline.py --keyword "AI Product Manager" --location "Hanoi" --source "itviec"
  ```
- [ ] **Monitor Telegram Channel**: Check for automated proof verification summaries and manual intervention alerts.
