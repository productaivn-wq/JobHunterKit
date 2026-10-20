# Changelog: JobHunterKit

All notable changes to this skill are documented here.

## [2026-08-21] - v1.23.1
### Fixed
- Fixed missing Telegram reports by re-enabling and modernizing Windows Scheduled Task `\JobHunterKit\Flow_Telegram_Report` to run every 2 hours headlessly via `pythonw.exe`.
- Removed restrictive battery power constraints (`DisallowStartIfOnBatteries=false`, `StopIfGoingOnBatteries=false`) to ensure regular report delivery on battery power.
- Enhanced `scripts/telegram_reporter.pyw` stream flushing and execution logging.
- Created `scripts/register_scheduled_tasks.py` for automated headless task scheduler registration.
- Added comprehensive unit test coverage in `tests/test_telegram_reporter.py`.

## [2026-08-18] - v1.23.0
### Added
- Native Antigravity CLI direct execution (`agy -p`) across `shared_platform/llm_client.py`, eliminating IPC daemon dependencies.
- Added `SAVEPOINT` transaction isolation per job in `flow_scrape.py`.
- Added `claimed_at` timestamp in `job_hunter.jobs` and `claim_next_job` for atomic row-level leasing (`FOR UPDATE SKIP LOCKED`).
- Restored `shared_platform/graph.py` LangGraph StateGraph pipeline runner and checkpointer.
- Synced UTOP 3.0 SSOT Use Cases (`UC-001` through `UC-006`) and traceability matrices.
- Upgraded Careerjet scraper from mock stub to live Playwright/HTTP extraction.

## [2026-07-13] - v1.15.1

### Changed
- Refactored launch_apply_agent.py and launch_score_agent.py loops to run procedurally in Python and use the subagent strictly as a passive IPC responder, preventing focus-stealing console windows from flashing on Windows.

## [2026-07-04] - v1.15.0
### Changed
- refactor scrapers to inherit from clean BaseScraper class and collapse duplicate preference configuration files

## [2026-07-01] - v1.14.6
### Changed
- Update UTOP state

## [2026-07-01] - v1.14.5
### Changed
- Configure headless browser mode by default based on JOBHUNTER_HEADLESS env var

## [2026-06-24] - v1.14.4
### Changed
- Add salary and seniority preference checks to the check_role_relevance filter to prevent applying to low-salary or non-manager roles like the Product Owner role at Avada Commerce

## [2026-06-24] - v1.14.3
### Changed
- Fixed wmic process warnings and UP022 linter violations in telegram_reporter.py

## [2026-06-23] - v1.14.2
### Changed
- chore: update JobHunterKit files

## [2026-06-23] - v1.14.1
### Changed
- Updated IPC daemon to Vertex AI, added silent task wrapper, Telegram reporter, and blacklisted One Mount

## [2026-06-21] - v1.14.0
### Changed
- Refactor JobHunterKit into 3 distinct DB-backed flows (Scrape, Score, Apply) with Supabase

## [2026-06-18] - v1.13.1
### Changed
- Add AI Product Director role preference

## [2026-06-18] - v1.13.0
### Changed
- Add personal preferences config and run_preferences harness

## [2026-06-18] - v1.12.7
### Changed
- Run ruff auto-fixes for formatting and cleanups

## [2026-06-17] - v1.12.6
### Changed
- Prioritize Gemini API and add 12s age check fallback in ipc_daemon

## [2026-06-17] - v1.12.5
### Changed
- Prioritize Gemini API and add 12s age check fallback in ipc_daemon

## [2026-06-17] - v1.12.4
### Changed
- Add LinkedIn collection sources support

## [2026-06-17] - v1.12.4
### Added
- Add support for six LinkedIn job collections as preconfigured sources: recommended, top-applicant, human-resources, it-services-and-it-consulting, easy-apply, and remote-jobs.
- Support direct collection/search URLs passed to the `--keyword` parameter in `live_linkedin_scrape`.

## [2026-06-16] - v1.12.3
### Changed
- Fix Easy Apply checkbox selector visibility/enabled checks and page navigation retries in pipeline.py

## [2026-06-15] - v1.12.2
### Changed
- Add dynamic_rubric_generation.md document explaining dynamic rubric specifications and weight normalization

## [2026-06-15] - v1.12.1
### Changed
- Document dynamic visual agent loop for External Apply in SKILL.md

## [2026-06-15] - v1.12.0
### Changed
- Fix scoring timeout and optimize parallel matching by running scoring in-process with IPC lock serialization.

## [2026-06-08] - v1.11.0
### Changed
- Major pipeline overhaul with over 4,000 lines of code changed.
- Refactored `pipeline.py`, `score_jd.py`, and `setup_profile.py` for massive improvements to the job hunting pipeline.

## [2026-06-01] - v1.10.3
### Changed
- Execute complete UTOP design and verification pipeline, confirming Quality Gate compliance
- Conduct full security pen-testing and threat modeling audit
- Implement robust Playwright headed visible anti-bot evasion and SSL bypass controls
- Verify Gemini dynamic easy-apply screening answers and 90-second client timeouts

## [2026-05-29] - v1.10.2
### Changed
- Refactored pipeline.py to resolve all CodeAudit High/Medium complexity and length findings

## [2026-05-27] - v1.10.1
### Changed
- Implement automated high-fidelity blocker debugging with descriptive reasons, raw HTML DOM dumps, and screenshot logging

## [2026-05-27] - v1.10.0
### Changed
- Decouple campaign pipeline into a decentralized, Multi-Agent architecture with concurrent scoring/tailoring subprocesses and sequential Playwright headed auto-applying

## [2026-05-26] - v1.9.0

### Added (Telegram-Gate Human-in-the-Loop Integration)
- **Interactive Verification Gate**: Implemented `_notify_telegram_approval` to send screenshot proofs and approval options directly to the user's Telegram bot when verification blocker states are reached:
  - **CAPTCHAs**: Pings user with a screenshot, pauses the thread, and waits for user confirmation once the CAPTCHA is solved.
  - **Login Walls**: Pauses execution and alerts the user to log in manually before continuing auto-fill.
  - **Vision Loop Blocks**: Sends screenshot and blocks thread when the Gemini Vision loop is explicitly stuck or blocked.
  - **Vision Loop Step Exceeded**: Sends screenshot when the interaction reaches the maximum step threshold (18 steps), allowing the user to mark it as successful if completed manually.
- **Config Sync**: Paired with `MessagingGateway` setup config to seamlessly load secrets/chat IDs.

## [2026-05-26] - v1.8.5

### Fixed (Evasion Robustness & HTTPS/SSL Hardening)
- **Robust Navigation Fallback**: Wrapped LinkedIn direct job navigation (`/jobs/view/...`) in a try/except block. If direct navigation is blocked or intercepted by aggressive TLS fingerprinting (triggering `net::ERR_CONNECTION_CLOSED` or `net::ERR_CONNECTION_RESET`), it automatically and transparently falls back to the human-mimicking search-based card-click navigation flow.
- **SSL Certificate Hardening**: Integrated `ignore_https_errors=True` into all Playwright contexts (`_boot_playwright_context`, `_apply_to_job`, and `auto_apply`). Bypasses corporate proxies, Zscaler interceptors, and local firewall SSL inspection failures (e.g., `net::ERR_CERT_AUTHORITY_INVALID`) that prevent external ATS form rendering.

## [2026-05-26] - v1.8.4

### Added (Vision Fallback Loop Integration)
- **RCA-B14 (RCA Follow-up)**: Integrated the `_vision_guided_apply` fallback loop in `_handle_external_apply`. When standard HTML/CSS selector form-filling and submit logic fail (resulting in `'External (Manual Required)'`), the pipeline now automatically launches the Gemini 2.5 Flash Vision loop: taking screenshots, sending them to the Vision API, receiving action steps (click, fill, upload, submit), and executing them dynamically to achieve automated applications across arbitrary external ATS landing pages.

## [2026-05-26] - v1.8.3

### Fixed (Hotfix — RC-B13 Unicode-safe trigger)
- **RC-B13 (revised)**: CSS `has-text("I'm interested")` failed because SmartRecruiters renders the apostrophe as Unicode U+2019 (`’`), not ASCII `'`. Replaced ATS trigger detection with a **JavaScript `innerText.toLowerCase()` keyword scan** — encoding-agnostic and immune to curly/straight quote differences. Matches: `"i'm interested"`, `"apply now"`, `"apply"`, `"quick apply"`, `"submit application"`. Fires only on confirmed external ATS domains.

## [2026-05-26] - v1.8.2

### Fixed (Hotfix — RC-B13)
- **RC-B13**: SmartRecruiters job pages use **"I'm interested"** as the primary CTA button instead of "Apply". Added `button:has-text("I'm interested")`, `"Apply Now"`, `"Quick Apply"`, and `[class*="interested" i]` to the ATS-aware external trigger selectors (only fires when already on a non-LinkedIn domain).

## [2026-05-26] - v1.8.1

### Fixed (Hotfix — RC-B11 + RC-B12)
- **RC-B11**: Detect same-tab redirect — LinkedIn's `NOT_ELIGIBLE_FOR_CHARGING` aggregator listings navigate the *current page* to the external ATS instead of opening a new tab. The code now checks if `page.url` left `linkedin.com` after the apply button click and treats that page as the external target directly.
- **RC-B12**: SmartRecruiters (and Lever) landing pages show a job description first — the actual application form only appears after clicking their own "Apply" button. Re-added `button:has-text("Apply")` to trigger selectors **only when already on an external ATS domain** (URL-guarded), with post-click URL check to abort if it navigates to a login page.

## [2026-05-26] - v1.8.0

### Fixed (Redirect Apply Pipeline Hardening — 15 Root Causes)

Root cause analysis performed by two parallel RCA agents (apply button detection + external apply flow), findings merged and applied.

**Apply Button Detection (`_apply_to_job`)**
- **RC-A2**: Added redirect-specific button text patterns (`"Apply on company website"`, `"Apply on employer site"`); added `[DEBUG]` logging of resolved `btn_text`; handles empty `btn_text` by defaulting to external flow
- **RC-A3**: Separated `try/except` scope — button detection failure (selector timeout → `Skipped`) is now isolated from apply execution failure (preserves `_handle_external_apply`'s own status)
- **RC-A4**: Added anchor `<a>` tag selectors (`a.jobs-apply-button`, `a[aria-label*="Apply"]`, `a:has-text("Apply on company website")`) — LinkedIn renders redirect buttons as `<a>` elements, not `<button>`
- **RC-A5**: Added `wait_for_load_state('domcontentloaded')` after `wait_until='commit'` to prevent race condition with page render

**External Apply Flow**
- **RC-B1+B2**: Fixed LinkedIn "Share your profile?" modal timing — click button first (non-blocking), settle 1.5s, *then* check modal; widened Continue selector to cover all LinkedIn modal action button variants
- **RC-B3**: Replaced unreliable `context.pages[-1]` fallback with `_wait_for_external_page()` — URL-domain-based page scan that skips `linkedin.com` and `about:blank`
- **RC-B4**: Expanded `_trigger_external_form_visibility` visibility selectors to cover Workday (`data-automation-id`), Greenhouse (`#first_name`), SmartRecruiters/BambooHR (`id*="firstName"`), Taleo/iCIMS (`id*="FirstName"`, `id*="fname"`), and a generic form catch-all
- **RC-B5**: Removed dangerous broad `button:has-text("Apply")` from trigger selector (could navigate away from ATS form); added post-click verification that form actually appeared
- **RC-B6**: Moved proof screenshot to *after* submit confirmation; pre-fill state saved as `debug_prefill_*.png` only
- **RC-B7**: Expanded `_submit_external_form` selectors with Workday (`data-automation-id="bottom-navigation-finish-button"`), SmartRecruiters (`data-role="submit"`), BambooHR (`#submitButton`), iCIMS (`data-icims="btn-save-submit"`), Taleo (`#submitBtn`)
- **RC-B8**: Added post-submit success confirmation signal check; status is now `Success (Submitted)` only if a confirmation DOM element is detected; otherwise `External (Unconfirmed Submit)`
- **RC-B9**: Added `_detect_blocker(page)` — detects reCAPTCHA/hCaptcha and login walls before form fill; sets status to `External (CAPTCHA Blocked)` or `External (Login Wall)` with screenshot proof
- **RC-B10**: Upgraded load-wait to `domcontentloaded` + `networkidle` + 2s settle to handle React/Angular/Vue SPA ATS platforms

## [2026-05-23] - v1.8.3 (Platform Stability)
### Changed
- Fix background Chrome hangs by using standard Chromium, resolve virtual list occlusion by scrolling each item gradually, and prevent early pagination exit when page 1 has duplicate jobs

## [2026-05-22] - v1.8.2 (Exclusion Rules)
### Changed
- Exclude jobs from past/current employers dynamically based on CV work experience

## [2026-05-22] - v1.8.1 (Penalty Calculations)
### Changed
- Fix mathematical inconsistency in match score calculations by deducting total global penalties from base match score

## [2026-05-22] - v1.8.0 (Single-Agent & Timeout Hardening)
### Added
- Highly optimized Single-Agent consolidated evaluation mode (1 agent call per job card instead of expensive 3-agent debate) to dramatically reduce cost and latency.
- Robust 90-second socket timeouts on all `requests.post` Gemini API calls across all pipeline components (`pipeline.py`, `score_jd.py`, `setup_profile.py`, `tailor_jd.py`) to prevent indefinite socket freezes.
- Updated default job search/scraping limit to 50 in `pipeline.py`.

## [2026-05-22] - v1.7.0
### Changed
- Implement robust form auto-fill fixes & Evidenced Deduction-based scoring mechanism

## [2026-05-22] - v1.6.1
### Changed
- Configure sys.stdout and sys.stderr to use UTF-8 on Windows to resolve console UnicodeEncodeErrors

## [2026-05-21] - v1.6.0
### Changed
- Implement Multi-Perspective Duel Evaluation (Recruiter vs Career Coach) with 3-agent dialectic debate and intermediate logs.

## [2026-05-21] - v1.5.0
### Added
- Fully Dynamic, Domain-Aware Rubric Categories: Prompt-driven job family classification (e.g., Sales, Marketing, Graphic Design) formulating 4 domain-tailored category names and snake_case IDs instead of hardcoded Engineering defaults.
- End-to-End Campaign Runs: Verified robust execution on mock Sales and Marketing JDs, resulting in highly precise, candidate-agnostic, mathematically deterministic evaluation scores with zero API parsing issues.

## [2026-05-21] - v1.4.0
### Added
- Evidenced Deduction-Based Evaluation framework (modeled after the `PRD Reviewer` architecture) replacing qualitative 0-5 LLM ratings.
- Candidate-Agnostic Dynamic Rubric Generator analyzing the Job Description (JD) exclusively to create objective, reusable evaluation rubrics.

## [2026-05-21] - v1.3.0
### Changed
- Introduce quantitative scoring rubrics, asymmetrical weight redistribution, and paginated deep multi-keyword scraping.

## [2026-05-21] - v1.2.1
### Changed
- Fixed dry-run deduplication bug and refactored load_applied_history to reduce cyclomatic complexity under Quality Gate threshold

## [2026-05-20] - v1.2.0

### Added
- **PlantUML Work Breakdown Structure (WBS) Workflow**: Added [wbs_workflow.puml](file:///C:/Users/user/.gemini/antigravity/skills/JobHunterKit/docs/wbs_workflow.puml) to visualize the exact decomposition of Use Cases down to code components, functions, BDD Gherkin scenarios, test data, and functional requirements.
- **Dynamic Rubric Generation Specification**: Created [dynamic_rubric_generation.md](file:///C:/Users/user/.gemini/antigravity/skills/JobHunterKit/docs/dynamic_rubric_generation.md) to define standard dynamic grading architectures and prompt-weighting normalization algorithms.

### Changed
- **Unified Traceability Matrix**: Upgraded [traceability_matrix.md](file:///C:/Users/user/.gemini/antigravity/skills/JobHunterKit/docs/traceability_matrix.md) to reference and embed the PlantUML WBS steps for visual verification.
- **100% MECE Requirements Catalog**: Established exactly 19 Functional Requirements and 5 Non-Functional Requirements in [function_rules.md](file:///C:/Users/user/.gemini/antigravity/skills/JobHunterKit/docs/function_rules.md).

## [2026-05-20] - v1.1.0
### Added
- **LLM-Based Screening Question Resolver**: Added dynamic answering of complex/custom LinkedIn Easy Apply screening questions using Gemini LLM (via CV and Profile context).
- **Continuous Learning**: Answers resolved by AI or confirmed by user are saved in `applicant_profile.json` under `"learned_answers"` so they are remembered forever.
- **Interactive Prompts Fallback**: Added console prompt fallbacks for screening questions when running interactively, giving the user full control.
- **Friend-friendly Shareability**: Cleaned all personal values (phone, salary, name, email) from generic code, replacing them with generic profile lookups.
- **Onboarding Setup Documentation**: Added detailed setup guides in `SKILL.md` for easy onboarding of friends.

## [2026-05-19] - v1.0.0
### Added
- Initial changelog created for `JobHunterKit` at v1.0.0.
