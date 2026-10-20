# JobHunterKit 9-Layer Traceability Graph Architecture (UTOP 3.0 SSOT)

| Field | Value |
|---|---|
| **System** | **JobHunterKit** (Autonomous Job Search & Application Pipeline) |
| **Standard** | Canonical 9-Layer UTOP Model (`TraceabilityGraph` v1.3.0 & `UCBDDManager` v2.3.1) |
| **Updated** | 2026-08-16 |
| **Governance Canary** | `GEMINI.md:GOVERNED` |
| **Derivation Hierarchy** | `BMC → Capability → Goal → Epic → WorkItem → DAG/BPMN → AST Code/Doc → Gate/Test → Telemetry` |
| **Overall Verification** | **100% Verified (Production Grade SSOT)** |

---

## 1. The Canonical 9-Layer UTOP Structural DAG

```mermaid
graph TD
    subgraph Layer 1: Business Model Canvas [BMC Strategy]
        L1_BMC["Value Proposition: Autonomous Multi-Portal Job Ingestion, Fit Scoring, Resume Tailoring & Form Submission"]
    end

    subgraph Layer 2: Strategic Capabilities [capability_catalog.yaml]
        L2_CAP1["CAP-01: Multi-Portal Job Scraping & Deduplication"]
        L2_CAP2["CAP-02: LLM Candidate Fit Scoring & Dynamic Rubrics"]
        L2_CAP3["CAP-03: Dynamic HTML-to-PDF CV Tailoring"]
        L2_CAP4["CAP-04: Agentic Visual Application Automation"]
        L2_CAP5["CAP-05: Anti-Bot Stealth, Cookie Sessions & CAPTCHA Solver"]
        L2_CAP6["CAP-06: Post-Application Proof Review & Quality Gate"]
    end

    subgraph Layer 3: Strategic Goals [goal_registry.yaml]
        L3_G1["GOAL-01: 100% Application Verification & Zero Silent Submissions"]
        L3_G2["GOAL-02: Sub-500ms Local In-Process LLM Routing (Zero API Cost)"]
        L3_G3["GOAL-03: Zero-Lock Concurrency via Local PostgreSQL Queue"]
    end

    subgraph Layer 4: Initiatives & Epics [BacklogManager]
        L4_EPIC1["EPIC-01: Top-Level Skill Orchestration & System Topology (UC-001)"]
        L4_EPIC2["EPIC-02: Path Hygiene & 5-Zone Storage Isolation (UC-002)"]
        L4_EPIC3["EPIC-03: End-to-End Pipeline & Atomic Work Distribution (UC-003)"]
        L4_EPIC4["EPIC-04: Anti-Bot Evasion & Stealth Session Ingestion (UC-004)"]
        L4_EPIC5["EPIC-05: Dashboard Analytics & Automated Account Onboarding (UC-005)"]
        L4_EPIC6["EPIC-06: Post-Application Proof Review Gate (UC-006)"]
    end

    subgraph Layer 5: Sprints & WorkItems [15m Macro Boundaries]
        L5_WI1["WI-01: Continuous Scraper Pagination across 7 Portals"]
        L5_WI2["WI-02: Dynamic Rubric Synthesis & Score Persistence"]
        L5_WI3["WI-03: Playwright PDF Compilation & Template Injection"]
        L5_WI4["WI-04: Visual Agent DOM Parsing & 2-Strike Fail Fast"]
        L5_WI5["WI-05: Workday Candidate Creation & Gmail OTP Reading"]
        L5_WI6["WI-06: LLM-as-a-Judge Proof Screenshot Audit"]
    end

    subgraph Layer 6: DAG Tasks, StateGraph & BPMN Process [bpmn_process.md]
        L6_PRC01["PRC-01: invoke_graph (InitState & Checkpointers)"]
        L6_PRC02["PRC-02: scrape_node (7 Portals)"]
        L6_PRC03["PRC-03: enqueue_scraped_jobs (PostgreSQL)"]
        L6_PRC04["PRC-04: score_node (Parallel Scoring)"]
        L6_PRC05["PRC-05: score_single_job (ATS Prefilter & Rubric)"]
        L6_PRC06["PRC-06: tailor_node (CV PDF Compilation)"]
        L6_PRC07["PRC-07: apply_node (Playwright Visual Loop)"]
        L6_PRC08["PRC-08: save_application_results (Atomic Save & Alerts)"]
        L6_PRC09["PRC-09: proof_review_node (Quality Gate)"]
        L6_PRC10["PRC-10: check_flow (SkillWatcher Daemon)"]
        L6_PRC11["PRC-11: unlock_stuck_jobs (Self-Healing)"]
        L6_GW["Gateways: GW-01..GW-09 (Preflight, Pause, Score, Dedup, SigValid, Zombie)"]
        L6_EVT["Events: EVT-01..EVT-07 (Start, Pause, Watchdog, Alerts, End)"]
        L6_E["Transitions: E-01..E-24 (State Transitions)"]
    end

    subgraph Layer 7: Code & Documentation AST [docs/function_list.md: FL-001..FL-280]
        L7_DB["Local PostgreSQL Pool: core/db_client.py, shared_platform/db.py (FL-013, FL-256, FL-272, FL-273)"]
        L7_LLM["LLM Router & Model: shared_platform/lc_model.py, llm_client.py (FL-017..020, FL-228..229)"]
        L7_Scrape["Scrapers: scrapers/*.py, flow_scrape.py (FL-168..174, FL-248..249, FL-277..279)"]
        L7_Tailor["Tailoring Engine: render_pdf.py, tailor_jd.py, services/tailoring.py (FL-185..189, FL-203, FL-209, FL-280)"]
        L7_Apply["Apply Engine & Bot Evasion: services/applying.py, core/captcha_solver.py (FL-001..012, FL-261, FL-265)"]
        L7_Healer["Autonomous Self-Healing: core/autonomous_healer.py, core/company_extractor.py (FL-242, FL-243, FL-268..271)"]
        L7_Judge["LLM-as-a-Judge: shared_platform/llm_judge.py, verify_application_proofs.py (FL-236..238, FL-250..251)"]
        L7_Watcher["Process Watchdog: scripts/skill_watcher.py, watchdog_guard.py (FL-227, FL-252..254)"]
    end

    subgraph Layer 8: Review, Quality Gates & Test Suites [tests/ & go_live_audit/]
        L8_CP["11 Quality Checkpoints: CP-001..CP-011 (Structure, BDD, DB, State, Telem, Judge)"]
        L8_TD["6 Test Data Fixtures: tests/data/TC-UC-001..006_data.json (TD-01..TD-06)"]
        L8_BDD["26 Gherkin Scenarios: tests/features/TC-UC-001..006.feature (G1..G6)"]
        L8_Pytest["23 Pytest Modules: 166 Test Cases (100% Passed / Safe Fallbacks)"]
        L8_Audit["20 Go-Live Audit Documents: docs/go_live_audit/DOC-01..DOC-20"]
    end

    subgraph Layer 9: Telemetry, Observability & Provenance [LangFuse & TaskManager]
        L9_Trace["LangFuse Root Trace: jobhunter-pipeline (shared_platform/telemetry.py)"]
        L9_Spans["Node Spans: scrape_node -> score_node -> tailor_node -> apply_node -> proof_review_node"]
        L9_Scores["Trace Scores: applied_jobs_count, llm_judge_score"]
        L9_Signals["EBQC Experience Signals: Errors, Blockages, Questions, Corrections"]
        L9_Ledger["Audit Trail: task_manager.provenance_ledger"]
    end

    %% Topological Inter-Layer Derivation Edges
    L1_BMC -->|ENABLES| L2_CAP1 & L2_CAP2 & L2_CAP3 & L2_CAP4 & L2_CAP5 & L2_CAP6
    L2_CAP1 & L2_CAP2 & L2_CAP3 & L2_CAP4 & L2_CAP5 & L2_CAP6 -->|ALIGNED_WITH| L3_G1 & L3_G2 & L3_G3
    L3_G1 & L3_G2 & L3_G3 -->|DECOMPOSES_TO| L4_EPIC1 & L4_EPIC2 & L4_EPIC3 & L4_EPIC4 & L4_EPIC5 & L4_EPIC6
    L4_EPIC1 & L4_EPIC2 & L4_EPIC3 & L4_EPIC4 & L4_EPIC5 & L4_EPIC6 -->|SCHEDULED_IN| L5_WI1 & L5_WI2 & L5_WI3 & L5_WI4 & L5_WI5 & L5_WI6
    L5_WI1 & L5_WI2 & L5_WI3 & L5_WI4 & L5_WI5 & L5_WI6 -->|EXECUTES| L6_PRC01 & L6_PRC02 & L6_PRC04 & L6_PRC06 & L6_PRC07 & L6_PRC09 & L6_PRC10
    L6_PRC01 & L6_PRC02 & L6_PRC03 & L6_PRC04 & L6_PRC05 & L6_PRC06 & L6_PRC07 & L6_PRC08 & L6_PRC09 & L6_PRC10 & L6_PRC11 -->|IMPLEMENTED_BY| L7_DB & L7_LLM & L7_Scrape & L7_Tailor & L7_Apply & L7_Judge & L7_Watcher
    L7_DB & L7_LLM & L7_Scrape & L7_Tailor & L7_Apply & L7_Judge & L7_Watcher -->|GOVERNED_BY| L8_CP
    L8_CP -->|DRIVES| L8_TD -->|FEEDS| L8_BDD -->|TESTED_BY| L8_Pytest -->|CERTIFIED_BY| L8_Audit
    L8_Audit & L8_Pytest -->|OBSERVED_BY| L9_Trace & L9_Spans & L9_Scores & L9_Signals & L9_Ledger
```

---

## 2. Directed Inter-Layer Relationship Semantics

| Source Layer | Target Layer | Relationship Type | Semantic Definition |
|---|---|---|---|
| **Layer 1 (BMC)** | **Layer 2 (Capabilities)** | `ENABLES` | High-level business value proposition enables distinct operational capabilities. |
| **Layer 2 (Capabilities)** | **Layer 3 (Goals)** | `ALIGNED_WITH` | Capabilities are designed to fulfill explicit quantitative system goals. |
| **Layer 3 (Goals)** | **Layer 4 (Epics / UCs)** | `DECOMPOSES_TO` | Strategic goals decompose into functional Use Cases and implementation epics. |
| **Layer 4 (Epics / UCs)** | **Layer 5 (WorkItems)** | `SCHEDULED_IN` | Use cases split into prioritized, sprint-scoped vertical deliverable work items. |
| **Layer 5 (WorkItems)** | **Layer 6 (BPMN / DAG)** | `EXECUTES` | Work items execute via LangGraph state nodes, BPMN processes, and gateway decisions. |
| **Layer 6 (BPMN / DAG)** | **Layer 7 (Code AST)** | `IMPLEMENTED_BY` | Process activities map directly to public codebase functions (FL-001..FL-267). |
| **Layer 7 (Code AST)** | **Layer 8 (Gates & Tests)**| `GOVERNED_BY` | Code modules are verified against quality checkpoints, test fixtures, and BDD scenarios. |
| **Layer 8 (Gates & Tests)**| **Layer 9 (Telemetry)** | `OBSERVED_BY` | Verification results, run traces, and EBQC experience signals stream to LangFuse & ledger. |

---

## 3. Test Data Fixtures & Verification Inventory (Layer 8 SSOT)

| Test Data Fixture | Source File | Test Cases Defined | Purpose & Input Parameters | Executing Pytest Module |
|---|---|---|---|---|
| **TD-01** | `tests/data/TC-UC-001_data.json` | `TC-001-VALID`<br>`TC-002-ALT-INVALID_INPUT`<br>`TC-003-ALT-DEPENDENCY_UNAVAILABLE`<br>`TC-004-ALT-TIMEOUT`<br>`TC-005-INVALID-INPUT`<br>`TC-006-EDGE-EMPTY`<br>`TC-007-EDGE-TIMEOUT` | Input parameters (`keyword="Product Manager"`, `location="Vietnam"`, `source="linkedin"`, `threshold=70`), timeout limits (600s), error guidance assertions. | `test_end_to_end.py`<br>`test_ats_prefilter.py` |
| **TD-02** | `tests/data/TC-UC-002_data.json` | `TC-001-VALID`<br>`TC-002-ALT-INVALID_INPUT`<br>`TC-003-ALT-DEPENDENCY_UNAVAILABLE`<br>`TC-004-ALT-TIMEOUT`<br>`TC-005-INVALID-INPUT`<br>`TC-006-EDGE-EMPTY`<br>`TC-007-EDGE-TIMEOUT` | Project and skill root paths, `get_master_cv_path()`, `get_job_dirs()`, path isolation under `STORAGE_ROOT`. | `test_TC-UC-002_jobhunterkit.py`<br>`test_path_hygiene.py` |
| **TD-03** | `tests/data/TC-UC-003_data.json` | `TC-001-VALID`<br>`TC-002-ALT-INVALID_INPUT`<br>`TC-003-ALT-DEPENDENCY_UNAVAILABLE`<br>`TC-004-ALT-TIMEOUT`<br>`TC-005-INVALID-INPUT`<br>`TC-006-EDGE-EMPTY`<br>`TC-007-EDGE-TIMEOUT` | Scraper routing (7 portals), PostgreSQL atomic query payloads, rubric scoring JSON formats, 2-strike visual loop steps. | `test_TC-UC-003_jobhunterkit.py`<br>`test_postgres_integration.py`<br>`test_flow_apply_robustness.py` |
| **TD-04** | `tests/data/TC-UC-004_data.json` | `TC-001-VALID`<br>`TC-002-ALT-INVALID_INPUT`<br>`TC-003-ALT-DEPENDENCY_UNAVAILABLE`<br>`TC-004-ALT-TIMEOUT`<br>`TC-005-INVALID-INPUT`<br>`TC-006-EDGE-EMPTY`<br>`TC-007-EDGE-TIMEOUT` | Cookie schema (`li_at`, `wday_vps_cookie`), Chrome launcher arguments, anchor link redirect URLs, CAPTCHA sitekeys. | `test_TC-UC-004_jobhunterkit.py`<br>`test_jobhunter_headless_guard.py` |
| **TD-05** | `tests/data/TC-UC-005_data.json` | `TC-001-VALID`<br>`TC-002-ALT-INVALID_INPUT`<br>`TC-003-ALT-DEPENDENCY_UNAVAILABLE`<br>`TC-004-ALT-TIMEOUT`<br>`TC-005-INVALID-INPUT`<br>`TC-006-EDGE-EMPTY`<br>`TC-007-EDGE-TIMEOUT` | Funnel metrics dataset (`status_score`, `status_apply`), Highcharts aggregation formats, offline DB fallback mocks. | `test_TC-UC-005_jobhunterkit.py`<br>`test_account_creation_flow.py` |
| **TD-06** | `tests/data/TC-UC-006_data.json` | Schema & Invariants (`verified_status: "completed"`, `unverified_status: "needs_manual_intervention"`) | Valid file patterns (`proof_submitted_{job_id}.png`), size threshold ($\ge 5000\text{ B}$), 16 invalid prefix rejection rules. | `test_TC-UC-006_jobhunterkit.py`<br>`test_proof_verification.py`<br>`test_llm_judge.py` |

---

## 4. Gherkin Scenarios & Pytest Execution Catalog (Layer 8 SSOT)

| Scenario ID | Gherkin Feature File | Scenario Title & Tag | Target Function / Subsystem | Executing Pytest Test |
|---|---|---|---|---|
| **TC-UC-001-S01** | `tests/features/TC-UC-001_jobhunterkit.feature` | `@happy-path` JobHunterKit top-level execution | `shared_platform/graph.py:invoke_graph` | `test_end_to_end.py::test_e2e_pipeline_execution` |
| **TC-UC-001-S02** | `tests/features/TC-UC-001_jobhunterkit.feature` | `@error-handling` Invalid Input Validation | `shared_platform/graph.py:_validate_inputs` | `test_end_to_end.py::test_invalid_inputs` |
| **TC-UC-001-S03** | `tests/features/TC-UC-001_jobhunterkit.feature` | `@error-handling` Dependency Unavailable 3x Retry | `shared_platform/llm_client.py:call` | `test_adversarial_jobhunter.py::test_retry_backoff` |
| **TC-UC-001-S04** | `tests/features/TC-UC-001_jobhunterkit.feature` | `@error-handling` Timeout & Partial Results | `shared_platform/graph.py:invoke_graph` | `test_adversarial_jobhunter.py::test_timeout_handling` |
| **TC-UC-001-ERR01**| `tests/features/TC-UC-001_jobhunterkit.feature` | Graceful degradation on dependency failure | `shared_platform/telemetry.py` | `test_notify.py::test_telemetry_graceful_fallback` |
| **TC-UC-002-S01** | `tests/features/TC-UC-002_jobhunterkit.feature` | `@happy-path` Path Conventions & Hygiene | `shared_platform/paths.py:get_master_cv_path` | `test_TC-UC-002_jobhunterkit.py::test_ssot_paths` |
| **TC-UC-002-S02..S04** | `tests/features/TC-UC-002_jobhunterkit.feature` | `@error-handling` Invalid/Missing path handling | `shared_platform/paths.py:get_job_dirs` | `test_TC-UC-002_jobhunterkit.py::test_path_resolution` |
| **TC-UC-003-S01** | `tests/features/TC-UC-003_jobhunterkit.feature` | `@happy-path` Workflow Overview | `scripts/flow_score.py`, `scripts/flow_apply.py` | `test_TC-UC-003_jobhunterkit.py::test_e2e_flow` |
| **TC-UC-003-S07** | `tests/features/TC-UC-003_jobhunterkit.feature` | External Apply Agentic Loop with 2-Strike Fail Fast | `services/applying.py:_agentic_external_apply` | `test_flow_apply_robustness.py::test_2strike_failfast` |
| **TC-UC-004-S01** | `tests/features/TC-UC-004_jobhunterkit.feature` | `@happy-path` Anti-Bot Evasion Architecture | `core/captcha_solver.py`, `scripts/state.json` | `test_TC-UC-004_jobhunterkit.py::test_stealth_cookies` |
| **TC-UC-004-S04** | `tests/features/TC-UC-004_jobhunterkit.feature` | CAPTCHA Token Injection (Turnstile/hCaptcha/GeeTest) | `core/captcha_solver.py:_try_resolve_captcha` | `test_TC-UC-004_jobhunterkit.py::test_captcha_injection` |
| **TC-UC-005-S01** | `tests/features/TC-UC-005_jobhunterkit.feature` | `@happy-path` Funnel Dashboard & Score Filters | `dashboard/app.py:load_dashboard_data` | `test_TC-UC-005_jobhunterkit.py::test_dashboard_data` |
| **TC-UC-005-S02** | `tests/features/TC-UC-005_jobhunterkit.feature` | `@error-handling` DB Connection Failure Fallback | `core/db_client.py:get_connection` | `test_TC-UC-005_jobhunterkit.py::test_db_offline_mode` |
| **TC-UC-006-S01** | `tests/features/TC-UC-006_jobhunterkit.feature` | Verified proof screenshot confirms application | `scripts/verify_application_proofs.py` | `test_TC-UC-006_jobhunterkit.py::test_verified_proof` |
| **TC-UC-006-ERR01**| `tests/features/TC-UC-006_jobhunterkit.feature` | Missing proof triggers manual intervention | `scripts/verify_application_proofs.py` | `test_TC-UC-006_jobhunterkit.py::test_unverified_fallback` |

---

## 5. Invariants & Zero-Orphan Rules

1. **Zero-Orphan Invariant**: Every node $v \in V$ must satisfy $\text{InDegree}(v) > 0 \land \text{OutDegree}(v) > 0$ unless it is an external entrypoint (Layer 1) or terminal trace (Layer 9).
2. **State Transition Completeness**: All 13 keys of `JobHunterState` must be initialized at entrypoint `invoke_graph()` and checked across node transitions.
3. **BPMN-Code 1:1 Parity**: Every gateway decision (`GW-01`..`GW-09`) must have a corresponding conditional branch in Python source code.
4. **100% Test Traceability**: Every Gherkin scenario in `tests/features/` must be backed by a JSON test fixture in `tests/data/` and an active test assertion in `tests/`.
