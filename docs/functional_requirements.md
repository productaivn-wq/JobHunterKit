# Functional Requirements — JobHunterKit

| Field | Value |
|---|---|
| **Skill** | JobHunterKit |
| **UC Coverage** | UC-001, UC-002, UC-003, UC-004, UC-005 |
| **Generated** | 2026-08-27 |
| **Standard** | UC 3.0 / RequirementsTraceKit |

## FR Catalog

| FR-ID | Requirement (The system SHALL...) | Type | UC | Priority |
|---|---|---|---|---|
| FR-001 | The system SHALL Use when searching job postings across Vietnam job boards, evaluating resume-JD fit scores, generating tailored CV PDFs, automating application submissions, or monitoring pipeline yield anomalies. | Mandatory | UC-001 | High |
| FR-002 | The system SHALL Automatic scraping of recent job board JDs across 7 major portals (LinkedIn, ITviec, CareerJet, VietnamWorks, Glints, TopCV, Indeed) and Gmail digests. | Mandatory | UC-001 | High |
| FR-003 | The system SHALL Fit evaluation via LangChain GeminiIPCChatModel routed in-process to TaskManager.LLMProviderRouter with [AntigravityCLITier(), LocalIPCTier()] executing agy -p - --dangerously-skip-permissions over stdin. | Mandatory | UC-001 | High |
| FR-004 | The system SHALL Local PostgreSQL persistence layer (core/db_client.py, shared_platform/db.py) utilizing atomic SELECT ... FOR UPDATE SKIP LOCKED transactions and stale-claim recovery. | Mandatory | UC-001 | High |
| FR-005 | The system SHALL Semantic Pipeline Yield Sentry (scripts/skill_watcher.py, FL-701..FL-703) for statistical anomaly detection (zero-yield alarms, intervention spikes, false-skip spikes, checkpointer dropoff analysis, and closed-loop auto-recovery via scripts/recover_all_pipeline_jobs.py). | Mandatory | UC-001 | High |
| FR-006 | The system SHALL Canonical Location: . (Skill/Code Root), while . is the Data & Project SSOT Root (PROJECT_ROOT). | Mandatory | UC-002 | High |
| FR-007 | The system SHALL Data & Campaign Storage Root: .\data (STORAGE_ROOT), storing all campaign runs, tailored CV PDFs, proof screenshots, and score logs (data/campaigns/<campaign>/<date>/). | Mandatory | UC-002 | High |
| FR-008 | The system SHALL Master CV SSOT: .\20_ACTIVE_CONTINUOUS\cv_text.txt (resolved via shared_platform/paths.py:get_master_cv_path()). | Mandatory | UC-002 | High |
| FR-009 | The system SHALL Workspace Link: .\.agents\skills\JobHunterKit (Real directory copy, not a junction). | Mandatory | UC-002 | High |
| FR-010 | The system SHALL LinkedIn (Direct Web Scraping): Guest mode search & extraction. | Mandatory | UC-003 | High |
| FR-011 | The system SHALL ITviec: Tech-focused Vietnam job portal scraper (scripts/scrapers/itviec.py). | Mandatory | UC-003 | High |
| FR-012 | The system SHALL CareerJet: Aggregator scraper (scripts/scrapers/careerjet.py). | Mandatory | UC-003 | High |
| FR-013 | The system SHALL VietnamWorks: General Vietnam employment portal scraper (scripts/scrapers/vietnamworks.py). | Mandatory | UC-003 | High |
| FR-014 | The system SHALL Anonymous Guest Mode Scraping Isolation: All LinkedIn search and JD scraping operations execute in anonymous Guest Mode (no session cookies attached). This keeps your personal account activity at 0 during heavy job discovery runs. | Mandatory | UC-004 | High |
| FR-015 | The system SHALL Logged-In Scope Containment: Session cookies (scripts/state.json) are attached only during active Easy Apply form submissions. | Mandatory | UC-004 | High |
| FR-016 | The system SHALL Automated CAPTCHA Solving: Integrates 2captcha and CapSolver API solving with DOM token injection for hCaptcha, Cloudflare Turnstile, and GeeTest, preventing bot blockades during form submission. | Mandatory | UC-004 | High |
| FR-017 | The system SHALL Daily Quota Enforcement: Tracks and caps daily LinkedIn Easy Apply actions (default 15/day) via data/daily_apply_tracker.json to prevent application flood detection. | Mandatory | UC-004 | High |
| FR-018 | The system SHALL run_jobhunter.ps1 -Phase scrape|score|apply|report|all -Headless true|false: Main CLI launcher managing IPC daemon lifecycle and executing flow phases. | Mandatory | UC-005 | High |
| FR-019 | The system SHALL launch_parallel_apply.ps1 -WorkerCount N: Launches $N$ parallel application worker swarms. | Mandatory | UC-005 | High |
| FR-020 | The system SHALL python shared_platform/health_check.py: System health and readiness diagnostics. | Mandatory | UC-005 | High |
| FR-021 | The system SHALL python scripts/fast_filter.py: Executes fast rules-based pre-screening filter. | Mandatory | UC-005 | High |

## Non-Functional Requirements

| NFR-ID | Requirement | Category |
|---|---|---|
| NFR-001 | The system SHALL complete within the configured timeout. | Performance |
| NFR-002 | The system SHALL log all execution events for auditability. | Observability |
| NFR-003 | The system SHALL NOT modify state without explicit user approval where required. | Safety |
| NFR-004 | The system SHALL degrade gracefully when dependencies are unavailable. | Resilience |
| NFR-005 | The system SHALL implement strict validation on all input payloads. | Security |

## Verification
- Each FR maps to at least one Gherkin scenario in the corresponding `.feature` file
- UC distribution: UC-001, UC-002, UC-003, UC-004, UC-005
- Priority: High = must-have, Medium = should-have, Low = nice-to-have
