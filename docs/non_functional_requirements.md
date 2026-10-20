# JobHunterKit Non-Functional Requirements & Load Test Specification

This document defines the non-functional requirements (NFRs) for JobHunterKit based on the active production configuration and architectural constraints.

## 1. Performance and Scalability

### 1.1 Concurrency and Scaling Limits
Based on production settings in the orchestration layers, the system is designed to handle the following concurrency limits:
*   **Flow 2 (Scoring - `flow_score.py`)**: Max 10 concurrent threads (`ThreadPoolExecutor(max_workers=10)`).
*   **Flow 3 (CV Tailoring - `services/tailoring.py`)**: Max 5 concurrent threads (`ThreadPoolExecutor(max_workers=5)`) for parallel PDF rendering.
*   **Flow 3 (Auto-Apply - `flow_apply.py`)**: Max 10 concurrent Playwright application threads (`ThreadPoolExecutor(max_workers=10)`).

### 1.2 Expected Throughput Targets
Assuming nominal external service performance:
*   **Scoring (LLM)**: With 10 workers, assuming ~10s per API call, expect ~3,600 jobs scored per hour.
*   **CV Tailoring**: With 5 workers, assuming ~3s per LaTeX/PDF render, expect ~6,000 CVs tailored per hour.
*   **Auto-Apply (Playwright)**: With 10 workers and up to a 600-second timeout, throughput heavily depends on the target ATS. Assuming ~45s per successful application, expect ~800 applications per hour. 

## 2. Reliability and Recovery

### 2.1 Watchdog & Recovery Thresholds
*   **Skill Watcher Liveness (`watchdog_guard.py`)**: The `SkillWatcherGuard` task runs every 2 hours and checks if `skill_watcher.log` is older than **15 minutes** (900 seconds). If stale, the system alerts via Telegram.
*   **Application Timeout (`flow_apply.py`)**: The system enforces a rigid **600-second (10-minute) maximum** duration per Playwright job application (`JOB_TIMEOUT_SECONDS = 600`). If a single thread exceeds this, the worker is unblocked and the job is marked `failed_manual` to prevent permanent ThreadPool deadlocks.
*   **Database Retry (`flow_score.py`)**: Claiming a job from the DB retries up to **5 times** with a 2-second sleep between attempts upon transient errors to handle contention during high throughput.

### 2.2 Observability
*   **Telemetry (`shared_platform/telemetry.py`)**: Uses LangFuse for OTEL-based span tracing. Telemetry degrades gracefully (does not crash the worker) if LangFuse is unreachable or disabled via `LANGFUSE_ENABLED=false`.

## 3. Resource Limits & Quotas

*   **Browser Instances**: A maximum of 10 concurrent Playwright browser sessions are spawned during Flow 3 application.
*   **LLM API Limits**: Governed by the Gemini API quotas (RPM/RPD). At max throughput (10 threads), the scraper/scorer can push up to 10 RPS, which may trigger rate limits on lower tiers.
*   **Memory Footprint**: 10 concurrent Playwright instances (Flow 3) dictate the peak memory usage. Assuming ~300MB per headless Chromium instance, expect up to ~3GB memory overhead exclusively for browser processes.

## 4. Load & Stress Test Scenarios

### 4.1 Load Test Specifications (1x Normal Load)
*   **Scenario 1: Large Campaign Injection**
    *   *Setup*: Inject 1,000 pending jobs into the database.
    *   *Execution*: Run Flow 2 and Flow 3.
    *   *Pass Criteria*: 
        *   Flow 2 evaluates 1,000 jobs in under 20 minutes (no DB deadlock errors).
        *   Flow 3 tailors passing CVs with max 5 concurrent processes.
        *   Memory usage stays below 4GB.

### 4.2 Stress Test Specifications (5x - 10x Load)
*   **Scenario 2: DB Contention (10x Load)**
    *   *Setup*: Artificially inflate the queue to 10,000 jobs. Force 3 separate pipeline instances to start simultaneously.
    *   *Expected Behavior*: `SELECT FOR UPDATE SKIP LOCKED` should prevent duplicate processing. DB claim retries (5 max) will absorb transient lock contention.
*   **Scenario 3: Widespread ATS Hangs**
    *   *Setup*: Mock the apply script to sleep infinitely for 50% of jobs.
    *   *Expected Behavior*: Flow 3 threads will block until exactly 600 seconds, after which the watchdog will forcefully mark them `failed_manual` and free the worker slot. Total throughput will plummet but the pipeline will not permanently freeze.

## 5. Bottleneck Analysis

Based on code review, known systemic bottlenecks include:
1.  **Playwright Concurrency (`flow_apply.py`)**: Limited to 10 workers. Because a hung page takes 10 minutes to time out, if 10 ATS applications hang simultaneously, the entire apply queue stalls for 10 minutes.
2.  **PDF Tailoring (`services/tailoring.py`)**: `subprocess.run` is used to spawn Python processes for PDF generation. The cap of 5 workers prevents CPU starvation, but spawning full Python subprocesses per CV introduces high overhead compared to in-memory rendering.
3.  **Database Connection Model**: Worker threads rapidly acquire/release individual DB connections. Under extreme stress, this could exhaust connection pools if not properly tuned on the database side.
