# Project traceability

| Concern | Authoritative location | Status |
|---|---|---|
| Active JobHunterKit | `.\` | Active |
| Master CV input | `20_ACTIVE_CONTINUOUS/cv_text.txt` | Active |
| Application documents | `10_ACTIVE_TIMEBOUND/` | Active |
| Project implementation | `10_ACTIVE_TIMEBOUND/Project/app/` | Active |
| Runtime state | `20_ACTIVE_CONTINUOUS/Operations/runtime/` | Continuous |
| Reference material | `30_REFERENCE/` | Reference |
| Master Traceability Matrix (BPMN, UCs, FRs, FLs, CPs, Tests) | `30_REFERENCE/traceability_matrix.md` | Verified SSOT |
| 7-Layer Structural Traceability Graph (DAG) | `30_REFERENCE/traceability_graph.md` | Verified SSOT |
| BPMN 2.0 Process Model SSOT | `30_REFERENCE/bpmn_process.md` | Verified SSOT |
| Legacy copies | `40_ARCHIVE/Legacy/snapshots/` | Read-only |

| Unresolved content | `00_INBOX/Quarantine/` | Needs review |
| Managed-document depth | Project → lifecycle zone → document | Enforced |
| Curated software documentation | `30_REFERENCE/` | Direct zone files |
| Skill catalog | `30_REFERENCE/skill_catalog.json` | Direct zone file |
| Opaque exception: Quarantine | `00_INBOX/Quarantine/` | Exact subtree |
| Opaque exception: HR agency transformation | `10_ACTIVE_TIMEBOUND/human_agency_director_ai_transformation/` | Exact subtree |
| Opaque exception: App config | `10_ACTIVE_TIMEBOUND/Project/app/config/` | Exact subtree |
| Opaque exception: Test data | `10_ACTIVE_TIMEBOUND/Project/app/scripts/tests/data/` | Exact subtree |
| Opaque exception: Test specifications | `10_ACTIVE_TIMEBOUND/Project/app/scripts/tests/e2e/` | Exact subtree |
| Opaque exception: CV renderer root | `10_ACTIVE_TIMEBOUND/Project/app/tailored_cv_renderer/` | Exact subtree |
| Opaque exception: Runtime operations | `20_ACTIVE_CONTINUOUS/Operations/runtime/` | Exact subtree |
| Opaque exception: Git history | `40_ARCHIVE/Legacy/JobHunterKit_git_history/` | Exact subtree |
| Opaque exception: Legacy snapshots | `40_ARCHIVE/Legacy/snapshots/` | Exact subtree |
| Opaque exception: Abandoned CV renderer prototype | `40_ARCHIVE/tailored_cv_renderer_abandoned_prototype/` | Exact subtree |
| Depth validator | `10_ACTIVE_TIMEBOUND/Project/app/scripts/validate_project_organization.py` | Active |
| Depth regression tests | `10_ACTIVE_TIMEBOUND/Project/app/scripts/tests/test_depth_policy.py` | Active |
| Depth policy | `30_REFERENCE/DEPTH_POLICY.md` | Authoritative |
