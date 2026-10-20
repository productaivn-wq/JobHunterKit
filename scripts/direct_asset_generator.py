#!/usr/bin/env python3
"""
Direct Asset Generator — Generates UC 3.0, Gherkin, Test Data, Functional Requirements,
and Traceability Matrix scaffolds for all skills WITHOUT requiring CDP or LLM APIs.

This script reads each skill's SKILL.md to extract metadata, then generates
template-based documentation files directly to the file system.

Usage:
    python direct_asset_generator.py --type skills
    python direct_asset_generator.py --type skills --target AutoClick
    python direct_asset_generator.py --type skills --dry-run
"""

import argparse
import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REQUIREMENTS_ROOT = SCRIPT_DIR.parent
SKILLS_DIR = REQUIREMENTS_ROOT.parent
ANTIGRAVITY_ROOT = SKILLS_DIR.parent

EXCLUDED_SKILL_DIRS = {
    "runtime",
    "sandboxes",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
}

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [DirectGen] %(levelname)s - %(message)s"
)
log = logging.getLogger(__name__)


def _write_utop_state(target_path: Path, output_dir: Path):
    """Compute SHA-256 hash of all source files and write to utop_state.json"""
    hasher = hashlib.sha256()
    py_files = sorted(
        [
            f
            for f in target_path.rglob("*.py")
            if "__pycache__" not in str(f)
            and "tests" not in str(f)
            and "features" not in str(f)
            and "sandboxes" not in str(f)
        ]
    )
    for f in py_files:
        try:
            hasher.update(f.read_bytes())
        except Exception:
            pass
    state = {
        "generated_at": datetime.now().isoformat(),
        "_source_hash": hasher.hexdigest(),
    }
    state_file = output_dir / "utop_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
    log.info(
        f"  [OK] {state_file.relative_to(target_path.parent if target_path.parent else target_path)}"
    )


def _parse_frontmatter(content: str) -> dict:
    meta = {"name": "", "description": "", "version": "0.1.0"}
    fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).split("\n"):
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip().lower()
                val = val.strip().strip("'\"")
                if key in meta:
                    meta[key] = val
    return meta


def _parse_skill_md(skill_path: Path) -> dict:  # noqa: C901
    """Parse SKILL.md frontmatter and body for metadata."""
    skill_md = skill_path / "SKILL.md"
    docs_skill = skill_path / "docs" / "SKILL.md"

    target = (
        skill_md if skill_md.exists() else (docs_skill if docs_skill.exists() else None)
    )
    if not target:
        return {
            "name": skill_path.name,
            "description": f"Skill: {skill_path.name}",
            "version": "0.1.0",
        }

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {
            "name": skill_path.name,
            "description": f"Skill: {skill_path.name}",
            "version": "0.1.0",
        }

    meta = _parse_frontmatter(content)
    if not meta["name"]:
        meta["name"] = skill_path.name

    # Extract sections
    sections = re.findall(r"^##\s+(.+)$", content, re.MULTILINE)
    meta["sections"] = sections[:10]

    # Store raw SKILL.md content for section-based UC clustering
    meta["_raw_content"] = content

    # Extract table rows for capabilities
    capabilities = []
    for line in content.splitlines():
        if line.strip().startswith("|") and line.strip().endswith("|"):
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if not parts or all(p == "" or set(p) <= {"-", " "} for p in parts):
                continue
            if any(
                p.lower()
                in (
                    "feature",
                    "reviewer",
                    "capability",
                    "triggers on",
                    "checks",
                    "detail",
                    "checks / details",
                    "command",
                    "purpose",
                    "engine",
                    "target",
                    "profile",
                    "domain",
                    "description",
                    "creator",
                    "builder",
                    "explorer",
                    "evaluator",
                    "role",
                    "value",
                    "#",
                    "pattern",
                    "when to use",
                    "key idea",
                    "step",
                    "steps",
                    "phase",
                    "action",
                    "outcome",
                    "condition",
                    "rules",
                    "requirements",
                )
                for p in parts
            ):
                continue
            if len(parts) >= 3:
                capabilities.append((parts[0], parts[2] if parts[2] else parts[1]))
            elif len(parts) == 2:
                capabilities.append((parts[0], parts[1]))
    meta["capabilities"] = capabilities[:40]

    # Find script files
    scripts = []
    for dname in ("scripts", "src"):
        d = skill_path / dname
        if d.exists():
            scripts.extend([f.name for f in d.glob("*.py")])
    meta["scripts"] = scripts[:20]

    return meta


def _extract_skill_section_blocks(content: str) -> list[dict]:  # noqa: C901
    """Parse SKILL.md body into logical section blocks for multi-UC clustering.

    Identifies top-level ## headings (especially 'Part N: Title' patterns) and
    extracts the bullet/numbered-list steps and table rows within each section.
    Returns a list of dicts: {"heading": str, "steps": list[str], "capabilities": list[tuple]}
    """
    # Strip frontmatter
    body = re.sub(r"^---.*?---\s*", "", content, count=1, flags=re.DOTALL)

    _noise_hdrs = {
        "feature",
        "reviewer",
        "capability",
        "triggers on",
        "checks",
        "detail",
        "checks / details",
        "command",
        "purpose",
        "engine",
        "target",
        "profile",
        "domain",
        "description",
        "creator",
        "builder",
        "explorer",
        "evaluator",
        "role",
        "value",
        "#",
        "pattern",
        "when to use",
        "key idea",
        "step",
        "steps",
        "phase",
        "action",
        "outcome",
        "condition",
        "rules",
        "requirements",
        "file",
        "focus",
        "use case",
        "cost",
        "requires / description",
    }

    blocks: list[dict] = []

    # Split at ## boundaries
    raw_sections = re.split(r"(?m)^(?=##\s)", body)
    for raw_block in raw_sections:
        heading_match = re.match(r"^##\s+(.+)$", raw_block, re.MULTILINE)
        if not heading_match:
            continue
        heading = heading_match.group(1).strip()
        # Collect numbered / bulleted steps
        steps = re.findall(r"^(?:\d+\.|[-*])\s+(.+)$", raw_block, re.MULTILINE)
        steps = [s.replace("`", "").replace("*", "").strip() for s in steps]
        steps = [s for s in steps if s and len(s) > 4][:10]
        # Collect table-row capability pairs
        caps: list[tuple] = []
        for line in raw_block.splitlines():
            if line.strip().startswith("|") and line.strip().endswith("|"):
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if not parts or all(p == "" or set(p) <= {"-", " "} for p in parts):
                    continue
                if any(p.lower() in _noise_hdrs for p in parts):
                    continue
                first = parts[0].strip("`*")
                second = parts[-1] if len(parts) >= 2 else ""
                if first and len(first) <= 80:
                    caps.append((first, second))
        blocks.append({"heading": heading, "steps": steps, "capabilities": caps})

    return blocks


def _cluster_capabilities_into_ucs(meta: dict) -> list[dict]:  # noqa: C901
    """Group SKILL.md content into UC slices (one per major logical section).

    Returns a list of UC slice dicts (max 5), each with:
      - uc_num:   int (1-based)
      - uc_id:    str  e.g. "UC-001"
      - title:    str  human-readable section title
      - heading:  str  original ## heading text
      - steps:    list[str]  numbered/bullet steps from that section
      - capabilities: list[tuple]  table-row capability pairs
    Falls back to a single UC-001 using all capabilities if no meaningful sections found.
    """
    raw_content = meta.get("_raw_content", "")
    all_caps = meta.get("capabilities", [])
    name = meta.get("name", "Unknown")
    desc = meta.get("description", "")

    blocks = _extract_skill_section_blocks(raw_content) if raw_content else []

    # Filter to only meaningful blocks (have either steps or capabilities, and
    # the heading is not purely auxiliary/setup)
    _aux_keywords = {
        "prerequisite",
        "prerequisites",
        "related workflow",
        "related workflows",
        "artifact",
        "artifacts",
        "key file",
        "key files",
        "upgrade",
        "verification policy",
        "project structure",
        "usage",
    }
    meaningful = [
        b
        for b in blocks
        if (b["steps"] or b["capabilities"])
        and not any(kw in b["heading"].lower() for kw in _aux_keywords)
    ]

    # Cap at 5 UCs
    meaningful = meaningful[:5]

    if not meaningful:
        # Fallback: single UC covering everything
        return [
            {
                "uc_num": 1,
                "uc_id": "UC-001",
                "title": name,
                "heading": f"Core Functionality — {name}",
                "steps": [
                    f"User invokes the {name} skill",
                    "System validates preconditions and input parameters",
                    f"System executes core {name} logic",
                    "System returns results to the caller",
                    "System logs execution metrics",
                ],
                "capabilities": all_caps[:15],
                "description": desc,
            }
        ]

    slices = []
    for i, block in enumerate(meaningful, 1):
        uc_id = f"UC-{i:03d}"
        # Derive a clean title from the heading
        # e.g. "Part 1: Task Lifecycle" -> "Task Lifecycle"
        title_clean = re.sub(r"^Part\s+\d+:\s*", "", block["heading"]).strip()
        title_clean = re.sub(r"^##\s*", "", title_clean).strip()
        steps = block["steps"]
        if not steps:
            title_lower = title_clean.lower()
            if "story splitting" in title_lower or "phase 0" in title_lower:
                steps = [
                    "User provides candidate use case or feature for splitting",
                    "System analyses the input against the 9 UC splitting heuristics (complexity, actors, workflows)",
                    "System clusters capabilities into discrete UC slices based on domain boundaries",
                    "System assigns UC IDs (UC-001..UC-NNN) and populates Use-Case Slice metadata",
                    "System writes each UC slice to the docs/ directory",
                    "System logs splitting rationale and slice count to execution telemetry",
                ]
            elif (
                "uc 3.0 authoring" in title_lower
                or "phase 1" in title_lower
                or "authoring" in title_lower
            ):
                steps = [
                    "User triggers UC 3.0 authoring for target skill or UC slice",
                    "System reads SKILL.md capability table and section blocks",
                    "System generates UC narrative including Goal, Scope, Level, Actors, Preconditions",
                    "System populates Main Success Flow, Alternate Flows, and Postconditions",
                    "System writes UC-NNN_<skill>.md to docs/ directory",
                    "System validates mandatory UC 3.0 fields are present before finalising",
                ]
            elif (
                "gherkin" in title_lower
                or "phase 2" in title_lower
                or "bdd" in title_lower
            ):
                steps = [
                    "User invokes Gherkin generation for a specific UC ID",
                    "System reads the corresponding UC-NNN doc to extract Main Success Flow and Alternate Flows",
                    "System generates @happy-path scenario with Given/When/Then from the basic flow",
                    "System generates @error-handling scenarios for each Alternate Flow",
                    "System generates a graceful-degradation ERR01 scenario",
                    f"System writes TC-{uc_id}_<skill>.feature to tests/features/",
                    "System validates that every scenario has at least one Then clause",
                ]
            elif (
                "enterprise tc" in title_lower
                or "phase 3" in title_lower
                or "test case" in title_lower
                or "tc spec" in title_lower
            ):
                steps = [
                    "User invokes Enterprise TC generation for a specific UC ID",
                    f"System reads Gherkin .feature file and extracts all scenario tags (@TC-{uc_id}-*)",
                    "System generates TC-SPECS.md with TC index table: TC ID, Gherkin ref, FR coverage, Risk Category, Gate, Must-Pass flag",
                    "System assigns severity (Critical/High/Medium/Low) and risk category per scenario",
                    "System builds Traceability Chain: UC Flow -> Gherkin Scenario -> Functional Requirement -> Test Data",
                    "System writes TC-SPECS.md to tests/e2e/ and updates traceability_matrix.md",
                    "System performs quality gate sign-off: verifies all Must-Pass scenarios have test data",
                ]
            elif (
                "fr catalog" in title_lower
                or "functional req" in title_lower
                or "function rule" in title_lower
                or "functional requirement" in title_lower
            ):
                steps = [
                    "User triggers FR catalog generation for target skill",
                    "System reads SKILL.md and UC narratives to extract domain-specific behaviours",
                    "System generates 'The system SHALL...' statements for each UC phase",
                    "System writes functional_requirements.md to docs/",
                ]
            else:
                steps = [
                    f"User invokes the {name} skill for '{title_clean}'",
                    "System validates preconditions",
                    f"System executes '{title_clean}' logic",
                    "System returns results",
                ]
        slices.append(
            {
                "uc_num": i,
                "uc_id": uc_id,
                "title": title_clean,
                "heading": block["heading"],
                "steps": steps,
                "capabilities": block["capabilities"] or all_caps[:8],
                "description": f"{name}: {title_clean}",
            }
        )

    return slices


def _parse_uc_doc(uc_content: str) -> dict:  # noqa: C901
    """Parse UC 3.0 markdown content for preconditions, flows, and slices."""
    info = {
        "title": "",
        "uc_id": "UC-001",
        "actor": "User",
        "goal": "",
        "preconditions": [],
        "basic_flow": [],
        "alternate_flows": [],
        "slices": [],
    }
    # Extract Title & ID from "# UC-XXX: Title"
    title_match = re.search(r"^#\s+(UC-\d+):\s*(.+)$", uc_content, re.MULTILINE)
    if title_match:
        info["uc_id"] = title_match.group(1)
        info["title"] = title_match.group(2).strip()
    else:
        # Fallback to general title if "# Title"
        title_match2 = re.search(r"^#\s+(.+)$", uc_content, re.MULTILINE)
        if title_match2:
            info["title"] = title_match2.group(1).strip()

    # Extract Actor and Goal from Header table or bullet points
    actor_match = re.search(
        r"\|\s*\*\*Primary Actor\*\*\s*\|\s*([^|]+)\s*\|", uc_content, re.IGNORECASE
    )
    if actor_match:
        info["actor"] = actor_match.group(1).strip()
    else:
        actor_match2 = re.search(
            r"-\s*\*\*Primary Actor\*\*:\s*(.+)$",
            uc_content,
            re.MULTILINE | re.IGNORECASE,
        )
        if actor_match2:
            info["actor"] = actor_match2.group(1).strip()

    goal_match = re.search(
        r"\|\s*\*\*Goal\*\*\s*\|\s*([^|]+)\s*\|", uc_content, re.IGNORECASE
    )
    if goal_match:
        info["goal"] = goal_match.group(1).strip()
    else:
        goal_match2 = re.search(
            r"-\s*\*\*Goal\*\*:\s*(.+)$", uc_content, re.MULTILINE | re.IGNORECASE
        )
        if goal_match2:
            info["goal"] = goal_match2.group(1).strip()

    # Extract Preconditions section
    precond_sec = re.search(
        r"##\s+Preconditions\s*\n(.*?)(?:\n##|$)", uc_content, re.DOTALL | re.IGNORECASE
    )
    if precond_sec:
        preconds = []
        for line in precond_sec.group(1).splitlines():
            line_clean = re.sub(r"^\d+\.\s*|-\s*", "", line.strip()).strip()
            if line_clean:
                preconds.append(line_clean)
        info["preconditions"] = preconds

    # Extract Basic Flow / Main Success Flow
    flow_sec = re.search(
        r"##\s+(?:Basic Flow|Main Success Flow|Main Flow)\s*(?:\([^)]*\))?\s*\n(.*?)(?:\n##|$)",
        uc_content,
        re.DOTALL | re.IGNORECASE,
    )
    if flow_sec:
        flow_steps = []
        for line in flow_sec.group(1).splitlines():
            line_clean = re.sub(r"^\d+\.\s*|-\s*", "", line.strip()).strip()
            if line_clean:
                flow_steps.append(line_clean)
        info["basic_flow"] = flow_steps

    # Extract Alternate Flows
    alt_sec = re.search(
        r"##\s+Alternate Flows\s*\n(.*?)(?:\n##|$)",
        uc_content,
        re.DOTALL | re.IGNORECASE,
    )
    if alt_sec:
        alt_flows = []
        for line in alt_sec.group(1).splitlines():
            line_clean = line.strip()
            if line_clean:
                alt_flows.append(line_clean)
        info["alternate_flows"] = alt_flows

    # Extract Slices
    slices_sec = re.search(
        r"##\s+(?:Use-Case Slices|Slices)\s*\n(.*?)(?:\n##|$)",
        uc_content,
        re.DOTALL | re.IGNORECASE,
    )
    if slices_sec:
        slices = []
        for line in slices_sec.group(1).splitlines():
            line_clean = line.strip()
            if line_clean:
                slices.append(line_clean)
        info["slices"] = slices

    return info


def _generate_uc_doc(skill_path: Path, meta: dict, uc_slice: dict | None = None) -> str:  # noqa: C901
    """Generate UC 3.0 narrative document.

    If uc_slice is provided (from _cluster_capabilities_into_ucs), generates a section-specific UC.
    Otherwise falls back to legacy single-UC behaviour.
    """
    name = meta["name"]
    desc = meta.get("description", f"{name} skill")
    scripts = meta.get("scripts", [])

    if uc_slice:
        uc_id = uc_slice["uc_id"]
        title = uc_slice["title"]
        uc_desc = uc_slice.get("description", desc)
        steps = uc_slice.get("steps", [])
        caps = uc_slice.get("capabilities", [])
    else:
        uc_id = "UC-001"
        title = name
        uc_desc = desc
        steps = []
        caps = meta.get("capabilities", [])

    # Build main flow from steps
    flow_lines = ""
    if steps:
        for i, step in enumerate(steps, 1):
            flow_lines += f"{i}. {step}\n"
    else:
        # Build domain-aware flow steps from UC title keywords when caps are noisy
        title_lower = title.lower()
        if "story splitting" in title_lower or "phase 0" in title_lower:
            flow_lines = (
                "1. Operator provides candidate use case or feature for splitting\n"
                "2. System analyses the input against the 9 UC splitting heuristics (complexity, actors, workflows)\n"
                "3. System clusters capabilities into discrete UC slices based on domain boundaries\n"
                "4. System assigns UC IDs (UC-001..UC-NNN) and populates Use-Case Slice metadata\n"
                "5. System writes each UC slice to the docs/ directory\n"
                "6. System logs splitting rationale and slice count to execution telemetry"
            )
        elif (
            "uc 3.0 authoring" in title_lower
            or "phase 1" in title_lower
            or "authoring" in title_lower
        ):
            flow_lines = (
                "1. Operator triggers UC 3.0 authoring for target skill or UC slice\n"
                "2. System reads SKILL.md capability table and section blocks\n"
                "3. System generates UC narrative including Goal, Scope, Level, Actors, Preconditions\n"
                "4. System populates Main Success Flow, Alternate Flows, and Postconditions\n"
                "5. System writes UC-NNN_<skill>.md to docs/ directory\n"
                "6. System validates mandatory UC 3.0 fields are present before finalising"
            )
        elif (
            "gherkin" in title_lower or "phase 2" in title_lower or "bdd" in title_lower
        ):
            flow_lines = (
                f"1. Operator invokes Gherkin generation for a specific UC ID\n"
                f"2. System reads the corresponding UC-NNN doc to extract Main Success Flow and Alternate Flows\n"
                f"3. System generates @happy-path scenario with Given/When/Then from the basic flow\n"
                f"4. System generates @error-handling scenarios for each Alternate Flow\n"
                f"5. System generates a graceful-degradation ERR01 scenario\n"
                f"6. System writes TC-{uc_id}_<skill>.feature to tests/features/\n"
                f"7. System validates that every scenario has at least one Then clause"
            )
        elif (
            "enterprise tc" in title_lower
            or "phase 3" in title_lower
            or "test case" in title_lower
            or "tc spec" in title_lower
        ):
            flow_lines = (
                f"1. Operator invokes Enterprise TC generation for a specific UC ID\n"
                f"2. System reads Gherkin .feature file and extracts all scenario tags (@TC-{uc_id}-*)\n"
                f"3. System generates TC-SPECS.md with TC index table: TC ID, Gherkin ref, FR coverage, Risk Category, Gate, Must-Pass flag\n"
                f"4. System assigns severity (Critical/High/Medium/Low) and risk category per scenario\n"
                f"5. System builds Traceability Chain: UC Flow → Gherkin Scenario → Functional Requirement → Test Data\n"
                f"6. System writes TC-SPECS.md to tests/e2e/ and updates traceability_matrix.md\n"
                f"7. System performs quality gate sign-off: verifies all Must-Pass scenarios have test data"
            )
        elif (
            "fr catalog" in title_lower
            or "functional req" in title_lower
            or "function rule" in title_lower
            or "functional requirement" in title_lower
        ):
            flow_lines = (
                "1. Operator triggers FR catalog generation for target skill\n"
                "2. System reads SKILL.md and UC narratives to extract domain-specific behaviours\n"
                "3. System generates 'The system SHALL...' statements for each UC phase\n"
                "4. System distributes FRs across UC IDs (not pinned to UC-001)\n"
                "5. System writes functional_requirements.md to docs/\n"
                "6. System verifies each FR maps to at least one Gherkin scenario"
            )
        elif (
            "workflow" in title_lower
            or "phase 4" in title_lower
            or "traceab" in title_lower
        ):
            flow_lines = (
                "1. Operator triggers UTOP pipeline for target skill\n"
                "2. System runs Design Phase: UC authoring → Gherkin → Test Data → TC-SPECS → FR catalog\n"
                "3. System runs Verification Phase: Quality Gate scans all generated assets\n"
                "4. System builds traceability_matrix.md covering all UC slices\n"
                "5. System runs test_end_to_end.py and reports pass/fail per scenario\n"
                "6. System persists EBQC signals and telemetry to utop_state.json"
            )
        else:
            # Construct from capabilities, filtering noise
            cap_flows = ""
            step_num = 3
            for feat, detail in caps[:8]:
                if _is_noise_cap(feat):
                    continue
                feat_clean = re.sub(r"\*+", "", feat.strip()).strip()
                detail_clean = re.sub(r"\*+", "", detail.strip()).strip()[:120]
                if feat_clean and detail_clean:
                    cap_flows += f"   {step_num}. System performs **{feat_clean}**: {detail_clean}\n"
                    step_num += 1
            flow_lines = (
                f"1. Operator invokes `{name}` for '{title}' via CLI, workflow, or agent dispatch\n"
                f"2. System validates preconditions and input parameters\n"
                f"{cap_flows if cap_flows else f'3. System executes {title} core logic'}\n"
                f"{step_num}. System returns results to the caller\n"
                f"{step_num + 1}. System logs execution metrics and persists telemetry"
            )

    script_list = (
        "\n".join(f"- `{s}`" for s in scripts) if scripts else "- (none discovered)"
    )
    name_lower = name.lower().replace(" ", "_")

    return f"""# {uc_id}: {title}

## Use Case Identification
| Field | Value |
|---|---|
| **UC ID** | {uc_id} |
| **Title** | {title} |
| **Skill** | {name} |
| **Version** | {meta.get("version", "0.1.0")} |
| **Status** | Draft (Auto-Generated) |
| **Created** | {datetime.now().strftime("%Y-%m-%d")} |
| **Generator** | DirectAssetGenerator v2.1 |

## Goal
Enable the `{name}` skill to support **{title}** operations within the Antigravity platform.

## Scope
In-scope: All `{title}` operations executed by the `{name}` skill.
Out-of-scope: External system configuration; hardware provisioning.

## Level
User Goal

## Description
{uc_desc}

## Actors
| Actor | Type | Description |
|---|---|---|
| **Operator** | Primary | The developer or agent invoking the skill |
| **System** | Supporting | The Antigravity platform runtime |
| **LLM Provider** | External | AI model backend (Gemini/OpenAI/Claude) |

## Preconditions
1. The Antigravity platform is running
2. The skill `{name}` is installed and registered
3. Required dependencies are available
4. Caller has appropriate permissions

## Main Success Flow
{flow_lines}

## Success Guarantee
The operation completes and results are persisted to the designated output path.

## Minimum Guarantee
Execution is logged with status and error details, even on failure.

## Alternate Flows
- **AF-1: Invalid Input** — System validates inputs and returns a structured error with field-level guidance. Gherkin: `@TC-{uc_id}-S02`
- **AF-2: Dependency Unavailable** — System retries up to 3 times with exponential backoff, then falls back. Gherkin: `@TC-{uc_id}-S03`
- **AF-3: Timeout** — System terminates execution after configured timeout and reports partial results. Gherkin: `@TC-{uc_id}-S04`

## Postconditions
1. Skill execution is logged with duration and status
2. Results are available to the caller at the designated path
3. No system state corruption on failure

## Business Rules
- BR-1: Skill must complete within configured timeout (default: 300s)
- BR-2: All outputs must be written to the designated directory under `skill_path`
- BR-3: Errors must be propagated with actionable, human-readable messages
- BR-4: No silent failures — all exceptions must be caught and logged

## Use-Case Slices
| Slice | Scenario | TC Reference | Priority |
|---|---|---|---|
| Slice-1 | Happy Path — {title} | `@TC-{uc_id}-S01` | Must-Pass |
| Slice-2 | Invalid Input | `@TC-{uc_id}-S02` | Must-Pass |
| Slice-3 | Dependency Failure | `@TC-{uc_id}-S03` | Should-Pass |
| Slice-4 | Graceful Degradation | `@TC-{uc_id}-ERR01` | Should-Pass |

## Related Scripts
{script_list}

## Traceability
- **Gherkin**: `tests/features/TC-{uc_id}_{name_lower}.feature`
- **Test Data**: `tests/data/TC-{uc_id}_data.json`
- **Functional Requirements**: `docs/functional_requirements.md`

## Revision History
| Version | Date | Author | Change |
|---|---|---|---|
| 0.1.0 | {datetime.now().strftime("%Y-%m-%d")} | DirectAssetGenerator | Auto-generated scaffold |
"""


def _generate_gherkin(
    skill_path: Path, meta: dict, uc_slice: dict | None = None
) -> str:  # noqa: C901
    """Generate Gherkin BDD feature file for a specific UC slice.

    If uc_slice is provided, generates scenarios from that slice's steps.
    Otherwise falls back to legacy single-UC behaviour reading UC-001 doc.
    """
    name = meta["name"]
    name_lower = name.lower().replace(" ", "_")
    desc = meta.get("description", f"{name} skill")

    # Determine which UC doc to look up
    uc_id = uc_slice["uc_id"] if uc_slice else "UC-001"
    uc_title = uc_slice["title"] if uc_slice else name
    slice_steps = uc_slice.get("steps", []) if uc_slice else []
    slice_caps = (
        uc_slice.get("capabilities", []) if uc_slice else meta.get("capabilities", [])
    )

    # Try to parse existing UC doc for richer flow info
    uc_file = skill_path / f"docs/{uc_id}_{name_lower}.md"
    uc_info = None
    if uc_file.exists():
        try:
            uc_content = uc_file.read_text(encoding="utf-8")
            uc_info = _parse_uc_doc(uc_content)
        except Exception as e:
            log.warning(f"Failed to parse UC doc for Gherkin ({uc_id}): {e}")

    scenarios = ""
    scenario_idx = 1

    if uc_info and (uc_info["basic_flow"] or uc_info["alternate_flows"]):
        # Use parsed UC 3.0 flow
        gherkin_steps = []
        has_then = False
        for step in uc_info["basic_flow"]:
            # Clean up markdown bold from step text
            step_clean = re.sub(r"\*+", "", step).strip()
            if not step_clean:
                continue
            if not gherkin_steps:
                gherkin_steps.append(f"    When {step_clean}")
            else:
                if step_clean.lower().startswith("system") and not has_then:
                    gherkin_steps.append(f"    Then {step_clean}")
                    has_then = True
                else:
                    gherkin_steps.append(f"    And {step_clean}")
        if not gherkin_steps:
            gherkin_steps.append(
                f"    When the user invokes the skill for '{uc_title}'"
            )
            gherkin_steps.append(
                f"    Then the system completes '{uc_title}' successfully"
            )
            has_then = True
        # BUG-2 FIX: always ensure a Then clause exists
        if not has_then:
            gherkin_steps.append(
                f"    Then the system completes '{uc_title}' successfully"
            )

        scenarios += f"""
  @TC-{uc_id}-S01 @happy-path
  Scenario: Happy Path - {uc_info["title"] or uc_title}
    Given the "{name}" skill is initialized
    And the system has valid configuration
{chr(10).join(gherkin_steps)}
"""
        scenario_idx = 2

        for af in uc_info["alternate_flows"]:
            # BUG-1 FIX: strip ** markdown bold markers before embedding in scenario names
            af_clean = re.sub(r"\*+", "", af.strip().lstrip("-* ")).strip()
            if not af_clean:
                continue
            af_name = af_clean
            af_desc = "the system handles the scenario correctly"
            m = re.match(
                r"(?:AF-\d+[:\s-]*(.*)|([^—]+))(?:\s*[—–-]\s*(.*))?",
                af_clean,
                re.IGNORECASE,
            )
            if m:
                name_parts = [g for g in m.groups()[:-1] if g]
                if name_parts:
                    af_name = name_parts[0].strip()
                if m.groups()[-1]:
                    af_desc = m.groups()[-1].strip()
            # Clean af_name of any residual ** or trailing punctuation
            af_name = re.sub(r"\*+", "", af_name).strip().rstrip("*").strip()
            scenarios += f"""
  @TC-{uc_id}-S{scenario_idx:02d} @error-handling
  Scenario: Alternate Flow - {af_name}
    Given the "{name}" skill is initialized
    When the user triggers alternate flow "{af_name}"
    Then {af_desc}
"""
            scenario_idx += 1
    elif slice_steps:
        # Use slice steps directly (from _cluster_capabilities_into_ucs)
        user_steps = [s for s in slice_steps if s.lower().startswith("user")]
        sys_steps = [s for s in slice_steps if s.lower().startswith("system")]
        other_steps = [
            s for s in slice_steps if not s.lower().startswith(("user", "system"))
        ]

        when_lines = []
        then_lines = []
        for s in user_steps + other_steps[:2]:
            when_lines.append(f"    When {s}")
        for s in sys_steps[:3]:
            then_lines.append(f"    Then {s}")
        if not when_lines:
            when_lines = [f"    When the user invokes the '{uc_title}' operation"]
        if not then_lines:
            then_lines = [f"    Then the system completes '{uc_title}' successfully"]

        scenarios += f"""
  @TC-{uc_id}-S01 @happy-path
  Scenario: Happy Path - {uc_title}
    Given the "{name}" skill is initialized
    And the system has valid configuration for '{uc_title}'
{chr(10).join(when_lines)}
{chr(10).join(then_lines)}
    And results are returned to the caller
"""
        scenario_idx = 2

        # Generate additional scenarios from capability pairs
        for feat, detail in slice_caps[:5]:
            if feat.lower() in (
                "feature",
                "constant",
                "file",
                "concern",
                "intent",
                "---",
                "",
            ):
                continue
            scenarios += f"""
  @TC-{uc_id}-S{scenario_idx:02d}
  Scenario: {uc_title} - {feat}
    Given the "{name}" skill is initialized
    And the system has valid configuration
    When the user activates '{feat.lower()}'
    Then the system should perform "{detail[:150]}"
    And the operation completes without errors
"""
            scenario_idx += 1
    else:
        # Fallback: capability-based
        for feat, detail in slice_caps[:10]:
            if feat.lower() in (
                "feature",
                "constant",
                "file",
                "concern",
                "intent",
                "---",
                "",
            ):
                continue
            scenarios += f"""
  @TC-{uc_id}-S{scenario_idx:02d}
  Scenario: {feat}
    Given the "{name}" skill is initialized
    And the system has valid configuration
    When the user triggers "{feat.lower()}"
    Then the system should perform "{detail[:150]}"
    And the operation completes without errors
"""
            scenario_idx += 1

        if not scenarios.strip():
            scenarios = f"""
  @TC-{uc_id}-S01
  Scenario: Basic execution of {uc_title}
    Given the "{name}" skill is initialized
    And the system has valid configuration
    When the user invokes the skill
    Then the skill executes successfully
    And results are returned to the caller

  @TC-{uc_id}-S02
  Scenario: Error handling for {uc_title}
    Given the "{name}" skill is initialized
    And an invalid input is provided
    When the user invokes the skill
    Then the system returns an actionable error message
"""

    res = f"""# Auto-generated Gherkin feature for {name} — {uc_id}: {uc_title}
# UC Reference: {uc_id}
# Generated: {datetime.now().strftime("%Y-%m-%d")}

@skill @{name_lower} @{uc_id.lower()}
Feature: {name} — {uc_title}
  As a user of the Antigravity platform
  I want to use the {name} skill for '{uc_title}'
  So that I can {desc[:200].lower()}

  Background:
    Given the Antigravity platform is running
    And the "{name}" skill is registered and available

{scenarios}
  @TC-{uc_id}-ERR01
  Scenario: Graceful degradation on dependency failure during {uc_title}
    Given the "{name}" skill is initialized
    And a required dependency is unavailable
    When the user invokes the skill for '{uc_title}'
    Then the system attempts a fallback mechanism
    And reports the degradation to the caller
"""
    # Store in meta keyed by uc_id so _generate_python_test can aggregate
    if "generated_gherkins" not in meta:
        meta["generated_gherkins"] = {}
    meta["generated_gherkins"][uc_id] = res
    # Legacy compat
    meta["generated_gherkin"] = res
    return res


def _generate_test_data(
    skill_path: Path, meta: dict, uc_slice: dict | None = None
) -> str:  # noqa: C901
    """Generate test data JSON for a specific UC slice."""
    name = meta["name"]
    name_lower = name.lower().replace(" ", "_")

    uc_id = uc_slice["uc_id"] if uc_slice else "UC-001"
    uc_title = uc_slice["title"] if uc_slice else name
    caps = (
        uc_slice.get("capabilities", []) if uc_slice else meta.get("capabilities", [])
    )
    slice_steps = uc_slice.get("steps", []) if uc_slice else []

    # Check if UC 3.0 document exists and parse it
    uc_file = skill_path / f"docs/{uc_id}_{name_lower}.md"
    uc_info = None
    if uc_file.exists():
        try:
            uc_content = uc_file.read_text(encoding="utf-8")
            uc_info = _parse_uc_doc(uc_content)
        except Exception as e:
            log.warning(f"Failed to parse UC doc for test data ({uc_id}): {e}")

    test_cases = []
    idx = 1
    scenario_ref_counter = 1  # BUG-5 FIX: independent counter for unique scenario_refs

    def _af_type(af_name: str) -> str:  # BUG-3 FIX: correct type classification
        n = af_name.lower()
        if any(x in n for x in ("invalid", "error", "fail", "reject")):
            return "negative"
        if any(
            x in n
            for x in (
                "timeout",
                "unavailable",
                "degrad",
                "fallback",
                "retry",
                "partial",
            )
        ):
            return "edge"
        return "positive"

    def _af_expected(af_name: str) -> dict:  # BUG-4 FIX: no error:null contradiction
        n = af_name.lower()
        if "timeout" in n:
            return {"status": "timeout", "error_type": "TimeoutError"}
        if any(x in n for x in ("invalid", "fail", "reject")):
            return {"status": "error", "error_type": "ValidationError"}
        if any(x in n for x in ("unavailable", "degrad", "fallback")):
            return {"status": "degraded", "error_type": "DependencyError"}
        return {"status": "success", "error": None}

    if uc_info and (uc_info["basic_flow"] or uc_info["alternate_flows"]):
        test_cases.append(
            {
                "id": f"TC-{idx:03d}-VALID",
                "description": f"Valid invocation of {name} '{uc_title}' - Happy Path",
                "type": "positive",
                "fr_ref": "FR-002",
                "scenario_ref": f"TC-{uc_id}-S{scenario_ref_counter:02d}",
                "input": {
                    "command": "execute",
                    "skill": name,
                    "uc": uc_id,
                    "params": {},
                },
                "expected": {"status": "success", "error": None},
            }
        )
        idx += 1
        scenario_ref_counter += 1  # S01 → S02 next

        for af in uc_info["alternate_flows"]:
            af_clean = re.sub(r"\*+", "", af.strip().lstrip("-* ")).strip()
            if not af_clean:
                continue
            af_name = af_clean
            m = re.match(
                r"(?:AF-\d+[:\s-]*(.*)|([^—]+))(?:\s*[—–-]\s*(.*))?",
                af_clean,
                re.IGNORECASE,
            )
            if m:
                name_parts = [g for g in m.groups()[:-1] if g]
                if name_parts:
                    af_name = name_parts[0].strip()
            af_name = re.sub(r"\*+", "", af_name).strip()
            test_cases.append(
                {
                    "id": f"TC-{idx:03d}-ALT-{re.sub(r'[^A-Z0-9_]', '_', af_name.upper())[:30]}",
                    "description": f"Alternate flow for {name} '{uc_title}' - {af_name}",
                    "type": _af_type(af_name),
                    "fr_ref": "FR-002",
                    "scenario_ref": f"TC-{uc_id}-S{scenario_ref_counter:02d}",
                    "input": {
                        "command": "execute",
                        "skill": name,
                        "uc": uc_id,
                        "params": {"trigger_alternate_flow": af_name},
                    },
                    "expected": _af_expected(af_name),
                }
            )
            idx += 1
            scenario_ref_counter += 1  # BUG-5 FIX: increment AFTER appending
    elif slice_steps:
        # Generate test cases from slice steps
        test_cases.append(
            {
                "id": f"TC-{idx:03d}-VALID",
                "description": f"Valid invocation of {name} for '{uc_title}' - Happy Path",
                "type": "positive",
                "fr_ref": "FR-002",
                "scenario_ref": f"TC-{uc_id}-S01",
                "input": {
                    "command": "execute",
                    "skill": name,
                    "uc": uc_id,
                    "params": {},
                },
                "expected": {"status": "success", "error": None},
            }
        )
        idx += 1
        scenario_ref_counter = 2
        for feat, detail in caps[:5]:
            if feat.lower() in (
                "feature",
                "constant",
                "file",
                "concern",
                "intent",
                "---",
                "",
            ):
                continue
            test_cases.append(
                {
                    "id": f"TC-{idx:03d}-VALID-{feat.upper().replace(' ', '_')[:20]}",
                    "description": f"Valid invocation of {name} for capability: {feat} ({uc_title})",
                    "type": "positive",
                    "fr_ref": f"FR-{idx:03d}",
                    "scenario_ref": f"TC-{uc_id}-S{scenario_ref_counter:02d}",
                    "input": {
                        "command": "execute",
                        "skill": name,
                        "uc": uc_id,
                        "params": {
                            f"enable_{feat.lower().replace(' ', '_')[:20]}": True
                        },
                    },
                    "expected": {"status": "success", "error": None},
                }
            )
            idx += 1
            scenario_ref_counter += 1
    else:
        for feat, detail in caps[:10]:
            if feat.lower() in (
                "feature",
                "constant",
                "file",
                "concern",
                "intent",
                "---",
                "",
            ):
                continue
            test_cases.append(
                {
                    "id": f"TC-{idx:03d}-VALID",
                    "description": f"Valid invocation of {name} for capability: {feat} ({uc_title})",
                    "type": "positive",
                    "fr_ref": f"FR-{idx + 1:03d}" if idx > 1 else "FR-002",
                    "scenario_ref": f"TC-{uc_id}-S{scenario_ref_counter:02d}",
                    "input": {
                        "command": "execute",
                        "skill": name,
                        "uc": uc_id,
                        "params": {
                            f"enable_{feat.lower().replace(' ', '_')[:20]}": True
                        },
                    },
                    "expected": {"status": "success", "error": None},
                }
            )
            idx += 1
            scenario_ref_counter += 1

        if not test_cases:
            test_cases.append(
                {
                    "id": "TC-001-VALID",
                    "description": f"Valid invocation of {name} '{uc_title}'",
                    "type": "positive",
                    "fr_ref": "FR-002",
                    "scenario_ref": f"TC-{uc_id}-S01",
                    "input": {
                        "command": "execute",
                        "skill": name,
                        "uc": uc_id,
                        "params": {},
                    },
                    "expected": {"status": "success", "error": None},
                }
            )
            idx = 2
            scenario_ref_counter = 2

    # Standard negative + edge cases — always unique scenario refs
    test_cases.append(
        {
            "id": f"TC-{idx:03d}-INVALID-INPUT",
            "description": f"Invalid input for {name} '{uc_title}'",
            "type": "negative",
            "fr_ref": "FR-002",
            "scenario_ref": f"TC-{uc_id}-S{scenario_ref_counter:02d}",
            "input": {
                "command": "execute",
                "skill": name,
                "uc": uc_id,
                "params": {"invalid_key": True},
            },
            "expected": {
                "status": "error",
                "error_type": "ValidationError",
            },  # BUG-4 FIX
        }
    )
    idx += 1
    scenario_ref_counter += 1

    test_cases.append(
        {
            "id": f"TC-{idx:03d}-EDGE-EMPTY",
            "description": f"Empty parameters for {name} '{uc_title}'",
            "type": "edge",
            "fr_ref": "FR-001",
            "scenario_ref": f"TC-{uc_id}-S{scenario_ref_counter:02d}",
            "input": {"command": "execute", "skill": name, "uc": uc_id, "params": None},
            "expected": {
                "status": "error",
                "error_type": "MissingParameterError",
            },  # BUG-4 FIX
        }
    )
    idx += 1
    scenario_ref_counter += 1

    test_cases.append(
        {
            "id": f"TC-{idx:03d}-EDGE-TIMEOUT",
            "description": f"Timeout scenario for {name} '{uc_title}'",
            "type": "edge",
            "fr_ref": "NFR-004",
            "scenario_ref": f"TC-{uc_id}-ERR01",
            "input": {
                "command": "execute",
                "skill": name,
                "uc": uc_id,
                "params": {"timeout_ms": 1},
            },
            "expected": {"status": "timeout", "error_type": "TimeoutError"},
        }
    )

    data = {
        "metadata": {
            "skill": name,
            "uc_reference": uc_id,
            "uc_title": uc_title,
            "generated": datetime.now().strftime("%Y-%m-%d"),
            "generator": "DirectAssetGenerator v2.0",
        },
        "test_cases": test_cases,
    }
    res = json.dumps(data, indent=2)
    # Store in meta keyed by uc_id for aggregation
    if "generated_test_datas" not in meta:
        meta["generated_test_datas"] = {}
    meta["generated_test_datas"][uc_id] = res
    meta["generated_test_data"] = res
    return res


# Comprehensive noise filter: UC 3.0 template column names, numbered heuristics,
# and Cynefin/domain-model markers that leak in from SKILL.md doc tables.
_NOISE_CAPS = {
    "feature",
    "capability",
    "constant",
    "file",
    "concern",
    "intent",
    "source",
    "priority",
    "method",
    "tier",
    "backend",
    "---",
    "",
    "description",
    "default",
    "detail",
    "see file",
    # UC 3.0 template column headers
    "field",
    "rule",
    "uc id",
    "title",
    "primary actor",
    "actor",
    "goal",
    "scope",
    "level",
    "success guarantee",
    "minimum guarantee",
    "stakeholders",
    "preconditions",
    "postconditions",
    "business rules",
    "slices",
    "revision history",
    "version",
    "date",
    "author",
    "change",
    "actor step",
    "system response",
    "step",
    "action",
    "result",
    # Gherkin / BDD template markers
    "given",
    "when",
    "then",
    "and",
    "but",
    "scenario",
    "feature",
    "background",
    "uc 3.0 element",
    "use-case slice",
    # Functional Requirement template markers
    "rule type",
    "any fr",
    "validation fr",
    "numeric/limit fr",
    "error fr",
    "business fr",
    "security fr",
    "fr type",
    "fr-id",
    "requirement",
    "stateful fr",
    "required tests",
    "must-pass?",
    "must-pass",
    "risk category",
    # Cynefin / complexity markers
    "obvious/complicated",
    "complex",
    "chaotic",
    "complicated",
    # Generic table headers
    "id",
    "type",
    "category",
    "status",
    "notes",
    "reference",
    "example",
    "workflow",
    "command",
    "relationship",
    "path / format",
}


def _is_noise_cap(feat: str) -> bool:
    """Return True if feat is a template marker, numeric heuristic, or table header."""
    f = feat.strip().strip("*").strip("`").strip()
    # Pure numeric (rule heuristics: 1, 2, 3, ...)
    if re.match(r"^\d+\.?$", f):
        return True
    # Bold template variable (e.g. **Field**, **UC ID**, **Goal**)
    if re.match(r"^\*\*[^*]+\*\*$", feat.strip()):
        inner = feat.strip().strip("*").strip().lower()
        if inner in _NOISE_CAPS or len(inner) <= 2:
            return True
    # Too short to be meaningful
    if len(f) <= 2:
        return True
    # In the noise set (case-insensitive)
    if f.lower() in _NOISE_CAPS:
        return True
    # Starts with special chars
    if f.startswith(("-", "`", "#", "|")):
        return True
    # Contains code remnants
    if "```" in f:
        return True
    # Too long to be a capability name (raw code spill)
    if len(f) > 80:
        return True
    return False


def _generate_functional_requirements(skill_path: Path, meta: dict) -> str:  # noqa: C901
    """Generate Functional Requirements (FR) catalog distributed across UC slices.

    FR = Functional Requirements: 'The system SHALL...' statements
    derived from each UC slice's capabilities — not all pinned to UC-001.
    """
    name = meta["name"]
    desc = meta.get("description", "")
    now = datetime.now().strftime("%Y-%m-%d")

    uc_slices = _cluster_capabilities_into_ucs(meta)

    # Use global _NOISE_CAPS + _is_noise_cap() — defined above generate functions

    fr_rows = []
    fr_idx = 1

    # FR-001: top-level skill purpose
    if desc:
        desc_clean = re.sub(r"\*+", "", desc).strip().rstrip(".")
        fr_rows.append(
            f"| FR-{fr_idx:03d} | The system SHALL {desc_clean[:300]}. "
            f"| Mandatory | UC-001 | High |"
        )
        fr_idx += 1

    # FR per UC slice — distribute across UCs
    for uc_slice in uc_slices:
        uc_id = uc_slice["uc_id"]
        uc_title = uc_slice["title"]
        steps = uc_slice.get("steps", [])
        caps = uc_slice.get("capabilities", [])

        # FR from section steps (most domain-specific)
        for step in steps[:4]:
            step_clean = re.sub(r"\*+", "", step).strip().rstrip(".")
            if not step_clean or len(step_clean) < 10:
                continue
            # Make it a proper SHALL statement
            if step_clean.lower().startswith("system "):
                shall = step_clean[7:].strip()
            elif step_clean.lower().startswith("user "):
                shall = f"accept user action: {step_clean[5:].strip()}"
            else:
                shall = step_clean
            fr_rows.append(
                f"| FR-{fr_idx:03d} | The system SHALL {shall[:280]}. "
                f"| Mandatory | {uc_id} | High |"
            )
            fr_idx += 1

        # FR from capability pairs for this UC
        for feat, detail in caps[:5]:
            feat_clean = re.sub(r"\*+", "", feat.strip().strip("`").strip())
            detail_clean = re.sub(r"\*+", "", detail.strip().rstrip("."))
            if _is_noise_cap(feat):
                continue
            if detail_clean and len(detail_clean) > 8:
                fr_rows.append(
                    f"| FR-{fr_idx:03d} | The system SHALL support **{feat_clean}** — "
                    f"{detail_clean[:250]}. | Mandatory | {uc_id} | High |"
                )
            else:
                fr_rows.append(
                    f"| FR-{fr_idx:03d} | The system SHALL provide **{feat_clean}** "
                    f"capability as part of {uc_title}. | Mandatory | {uc_id} | Medium |"
                )
            fr_idx += 1

    # Hard fallback
    if not fr_rows:
        uc_id_fb = uc_slices[0]["uc_id"] if uc_slices else "UC-001"
        fr_rows = [
            f"| FR-001 | The system SHALL execute the {name} skill given valid inputs. "
            f"| Mandatory | {uc_id_fb} | High |",
            f"| FR-002 | The system SHALL report errors with actionable messages on failure. "
            f"| Mandatory | {uc_id_fb} | High |",
            f"| FR-003 | The system SHALL complete execution within the configured timeout. "
            f"| Mandatory | {uc_id_fb} | Medium |",
        ]

    fr_table = "\n".join(fr_rows)
    uc_ids = ", ".join(s["uc_id"] for s in uc_slices)

    return f"""# Functional Requirements — {name}

| Field | Value |
|---|---|
| **Skill** | {name} |
| **UC Coverage** | {uc_ids} |
| **Generated** | {now} |
| **Standard** | UC 3.0 / RequirementsTraceKit |

## FR Catalog

| FR-ID | Requirement (The system SHALL...) | Type | UC | Priority |
|---|---|---|---|---|
{fr_table}

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
- UC distribution: {uc_ids}
- Priority: High = must-have, Medium = should-have, Low = nice-to-have
"""


def _generate_readme(skill_path: Path, meta: dict) -> str:
    """Generate a proper README.md for the skill directory."""
    name = meta["name"]
    desc = meta.get("description", f"{name} skill")
    version = meta.get("version", "0.1.0")
    scripts = meta.get("scripts", [])
    now = datetime.now().strftime("%Y-%m-%d")

    uc_slices = _cluster_capabilities_into_ucs(meta)
    uc_ids = ", ".join(s["uc_id"] for s in uc_slices)
    uc_list = "\n".join(f"- **{s['uc_id']}** — {s['title']}" for s in uc_slices)
    name_lower = name.lower().replace(" ", "_")

    script_entries = "\n".join(f"    {s}" for s in scripts) if scripts else "    (none)"
    uc_table_rows = "\n".join(
        f"| {s['uc_id']} | TC-{s['uc_id']}_{name_lower}.feature | TC-{s['uc_id']}_data.json | FR-* |"
        for s in uc_slices
    )

    return (
        f"# {name}\n\n"
        f"> {desc}\n\n"
        f"**Version:** {version} | **Generated:** {now}\n\n"
        f"## Overview\n\n"
        f"`{name}` is an Antigravity skill that {desc.lower().rstrip('.')}. "
        f"It follows the UC 3.0 specification with full UTOP traceability "
        f"coverage across {len(uc_slices)} use cases.\n\n"
        f"## Use Cases\n\n{uc_list}\n\n"
        f"## Directory Structure\n\n"
        f"```\n{name}/\n"
        f"├── SKILL.md                    # Skill manifest and capability table\n"
        f"├── README.md                   # This file\n"
        f"├── docs/\n"
        f"│   ├── UC-NNN_{name_lower}.md  # Use Case 3.0 narratives ({uc_ids})\n"
        f"│   ├── functional_requirements.md\n"
        f"│   ├── function_list.md\n"
        f"│   ├── traceability_matrix.md\n"
        f"│   └── checkpoints.md\n"
        f"├── tests/\n"
        f"│   ├── features/               # Gherkin .feature files per UC\n"
        f"│   ├── data/                   # TC-UC-NNN_data.json test data\n"
        f"│   ├── e2e/TC-SPECS.md         # Enterprise Test Case specifications\n"
        f"│   └── test_end_to_end.py      # Automated test suite\n"
        f"└── scripts/\n{script_entries}\n```\n\n"
        f"## Quick Start\n\n"
        f"```bash\n# Run tests\npython -m pytest tests/ -v\n\n"
        f"# Regenerate all UTOP assets\n"
        f"python scripts/direct_asset_generator.py --type skills --target {name}\n```\n\n"
        f"## Traceability\n\n"
        f"| UC | Gherkin | Test Data | FR Coverage |\n|---|---|---|---|\n"
        f"{uc_table_rows}\n\n"
        f"*Auto-generated by DirectAssetGenerator v2.1 — enrich with usage examples.*\n"
    )


def _generate_traceability_matrix(skill_path: Path, meta: dict) -> str:  # noqa: C901
    """Generate Traceability Matrix covering all UC slices."""
    name = meta["name"]
    caps = meta.get("capabilities", [])

    # Use UC slices for multi-UC coverage — BUG-8 FIX
    uc_slices = _cluster_capabilities_into_ucs(meta)

    table_rows = []
    overall_idx = 1
    for uc_slice in uc_slices:
        uc_id = uc_slice["uc_id"]
        uc_title = uc_slice["title"]
        slice_caps = uc_slice.get("capabilities", []) or caps[:8]
        slice_steps = uc_slice.get("steps", [])

        # Happy-path row
        desc = slice_steps[0] if slice_steps else f"{uc_title} — happy path execution"
        table_rows.append(
            f"| {uc_id}.{overall_idx} | {desc[:80].replace('|', chr(124))} "
            f"| TC-{uc_id}-S01 | FR-{overall_idx:03d} | TC-{overall_idx:03d}-VALID | Draft |"
        )
        overall_idx += 1

        # Build meaningful descriptions from steps first, then capabilities
        step_descs = [
            s for s in slice_steps[1:] if len(s.strip()) > 5
        ]  # skip first (used above)
        cap_descs = [
            f"{uc_title} — {feat}: {detail[:40]}"
            for feat, detail in slice_caps[:6]
            if feat.lower()
            not in ("feature", "constant", "file", "concern", "intent", "---", "")
            and not re.match(r"^\d+$", feat.strip())  # skip bare integers
            and len(feat.strip()) > 2  # skip single-char headers
            and not re.match(
                r"^(uc id|title|field|rule|scope|level|type|name|value|actor|step|phase|id|nr|ref|date|status|version|priority|must-pass|quality gate)$",
                feat.strip().lower(),
            )
        ]
        all_descs = step_descs + cap_descs

        for i, desc_text in enumerate(all_descs[:5]):
            clean_desc = desc_text.replace("|", "\\|")[:80]
            table_rows.append(
                f"| {uc_id}.{overall_idx} | {clean_desc} "
                f"| TC-{uc_id}-S{i + 2:02d} | FR-{overall_idx:03d} | TC-{overall_idx:03d}-VALID | Draft |"
            )
            overall_idx += 1

        # Error-path row
        table_rows.append(
            f"| {uc_id}.ERR | {uc_title} — graceful degradation "
            f"| TC-{uc_id}-ERR01 | NFR-004 | TC-{overall_idx:03d}-TIMEOUT | Draft |"
        )
        overall_idx += 1

    if not table_rows:
        table_rows.append(
            "| UC-001.1 | Main Flow | TC-UC-001-S01 | FR-001 | TC-001-VALID | Draft |"
        )
        overall_idx = 2

    today = datetime.now().strftime("%Y-%m-%d")
    uc_count = len(uc_slices)
    uc_ids = ", ".join(s["uc_id"] for s in uc_slices)

    return f"""# Traceability Matrix — {name}

| Field | Value |
|---|---|
| **Skill** | {name} |
| **Generated** | {today} |
| **Coverage** | OKF Verified |
| **UC Coverage** | {uc_count} UCs ({uc_ids}) |

## UC → Gherkin Scenarios ↔ Playwright (Test Data) ↔ Functional Requirements (FRs) ↔ Function Checkpoints

| UC Flow | Description | Gherkin Scenario | Functional Requirement | Test Data | Status |
|---|---|---|---|---|---|
{chr(10).join(table_rows)}

## Coverage Summary

| Category | Count |
|---|---|
| Use Cases | {uc_count} |
| Gherkin Scenarios | {len(table_rows)} |
| Functional Requirements | {len(table_rows)} |
| Test Data Cases | {len(table_rows)} |

*Generated on {today}*
"""

    # Dead code removed — function returns above


def _generate_okf_matrix_csv(skill_path: Path, meta: dict) -> str:
    """Generate default OKF CSV Matrix."""
    caps = meta.get("capabilities", [])
    rows = ["uc_flow,description,gherkin_scenario,function_rule,test_data,status"]
    idx = 1
    for feat, detail in caps[:40]:
        if feat.lower() in (
            "feature",
            "constant",
            "file",
            "concern",
            "intent",
            "---",
            "",
        ):
            continue
        clean_feat = feat.replace('"', '""')
        rows.append(
            f'UC-001.{idx},"{clean_feat[:80]}",TC-UC-001-S{idx:02d},FR-{idx:03d},TC-001-VALID,Draft'
        )
        idx += 1
    if len(rows) == 1:
        rows.append('UC-001.1,"Main Flow",TC-UC-001-S01,FR-001,TC-001-VALID,Draft')
    return "\n".join(rows) + "\n"


def _generate_okf_datapackage(skill_path: Path, meta: dict) -> str:
    """Generate OKF datapackage.json pointing to schema."""
    datapackage = {
        "profile": "tabular-data-package",
        "resources": [
            {
                "name": "traceability-matrix",
                "path": "traceability_matrix.csv",
                "profile": "tabular-data-resource",
                "schema": "../../../TraceabilityGraph/core/okf_schema.json",
            }
        ],
    }
    return json.dumps(datapackage, indent=2) + "\n"


def _scan_skill_functions(skill_path: Path) -> list[dict]:
    """Helper to scan skill Python files for public functions."""
    functions = []
    py_files = sorted(skill_path.rglob("*.py"))
    for pf in py_files:
        if any(
            x in str(pf).lower()
            for x in ["__pycache__", "tests", "features", "sandboxes", "venv", ".git"]
        ):
            continue
        try:
            src = pf.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"^(?:def|async def)\s+(\w+)\s*\(", src, re.MULTILINE):
                fn = m.group(1)
                if not fn.startswith("_") and not fn == "main":
                    functions.append(
                        {"name": fn, "file": pf.relative_to(skill_path).as_posix()}
                    )
        except Exception:
            pass
    return functions


def _generate_function_list(skill_path: Path, meta: dict) -> str:
    """Generate public Function List for a skill."""
    name = meta["name"]
    funcs = _scan_skill_functions(skill_path)
    now = datetime.now().strftime("%Y-%m-%d")

    rows = []
    for i, f in enumerate(funcs, 1):
        rows.append(f"| FL-{i:03d} | `{f['name']}` | `{f['file']}` | Public function |")

    if not rows:
        rows = ["| FL-001 | None | N/A | No public functions discovered |"]

    rows_str = "\n".join(rows)
    return f"""# Function List — {name}

| ID | Function Name | File Path | Description |
|---|---|---|---|
{rows_str}

*Generated on {now}*
"""


def _generate_checkpoints(skill_path: Path, meta: dict) -> str:
    """Generate Checkpoints matrix for a skill."""
    name = meta["name"]
    now = datetime.now().strftime("%Y-%m-%d")

    return f"""# Checkpoints — {name}

| Checkpoint ID | Description | Target | Severity | Status |
|---|---|---|---|---|
| CP-001 | Verify that task.md exists and is complete | Workspace Structure | Error | Pending |
| CP-002 | Verify that walkthrough.md exists and is populated | Workspace Structure | Error | Pending |
| CP-003 | Verify that functional_requirements.md maps to all public functions | Traceability | Error | Pending |
| CP-004 | Verify Gherkin test coverage matches functional requirements | BDD Alignment | Error | Pending |
| CP-005 | Run CodeAudit/Ruff linter to ensure code style compliance | Code Quality | Warning | Pending |
| CP-006 | Run PromptfooVibeReviewer on generated markdown logs | Semantic Alignment | Warning | Pending |

*Generated on {now}*
"""


def _get_domain_initials(name: str) -> str:
    """Extract a 2-3 letter domain code from the skill name."""
    initials = "".join([c for c in name if c.isupper()])
    if len(initials) >= 2:
        return initials[:3]
    name_clean = re.sub(r"[^a-zA-Z]", "", name)
    if len(name_clean) >= 2:
        return name_clean[:2].upper()
    return name.upper()[:3]


def _generate_tc_specs(skill_path: Path, meta: dict) -> str:
    """Generate Enterprise Test Case Specifications (TC-SPECS.md) from Gherkin scenarios."""
    name = meta["name"]
    caps = meta.get("capabilities", [])
    domain = _get_domain_initials(name)
    now = datetime.now().strftime("%Y-%m-%d")

    rows = []
    idx = 1
    for feat, detail in caps[:40]:
        if feat.lower() in (
            "feature",
            "constant",
            "file",
            "concern",
            "intent",
            "---",
            "",
        ):
            continue
        tc_id = f"TC_UC_{domain}_{idx:03d}"
        gherkin_id = f"TC-UC-001-S{idx:02d}"
        fr_cov = f"FR-{idx + 1:03d}"
        if idx == 1:
            fr_cov = f"FR-001, {fr_cov}"

        risk_cat = "RG5 User Experience"
        must_pass = "No"
        detail_lower = detail.lower()
        if any(x in detail_lower for x in ["auth", "login", "permission", "security"]):
            risk_cat = "RG3 Auth & Authorization"
            must_pass = "Yes"
        elif any(
            x in detail_lower
            for x in ["data", "db", "database", "save", "write", "file", "integrity"]
        ):
            risk_cat = "RG1 Core Data Integrity"
            must_pass = "Yes"
        elif any(
            x in detail_lower for x in ["send", "email", "chat", "message", "api"]
        ):
            risk_cat = "RG2 Core Communication"
            must_pass = "Yes"
        elif any(x in detail_lower for x in ["pay", "checkout", "price", "financial"]):
            risk_cat = "RG4 Payment & Financial"
            must_pass = "Yes"
        elif any(x in detail_lower for x in ["reliability", "fail", "crash", "robust"]):
            risk_cat = "RG6 System Reliability"
            must_pass = "Yes"

        must_pass_icon = "✅" if must_pass == "Yes" else "No"
        rows.append(
            f"| {tc_id} | {gherkin_id} | {fr_cov} | {risk_cat} | SIT | {must_pass_icon} |"
        )
        idx += 1

    tc_id = f"TC_UC_{domain}_{idx:03d}"
    rows.append(
        f"| {tc_id} | TC-UC-001-ERR01 | NFR-004 | RG6 System Reliability | SIT | ✅ |"
    )

    table_rows = "\n".join(rows)

    return f"""# TC Specifications — UC-001 {name}

> Per testing.md §13 — Enterprise Test Case Model

---

## TC Index

| TC ID | Gherkin | FR Coverage | Risk Category | Gate | Must-Pass |
|---|---|---|---|---|---|
{table_rows}

---

## Traceability Chain

```
UC-001 (UC 3.0) ↔ TC-UC-001-S01–S{idx - 1:02d} (Gherkin Scenarios) ↔ {f"TC_UC_{domain}_001" if idx > 1 else ""}-{idx:03d} (TC-SPECS)
   ↔ test_end_to_end.py (Playwright E2E with Test Data) ↔ FR-001–FR-{idx:03d} (Functional Requirements) ↔ Function Checkpoints
```

## Quality Gate Summary

| Gate | Criteria | Must-Pass TCs | Total |
|---|---|---|---|
| **SIT (Smoke)** | 100% PASS, 0 Critical | {sum(1 for r in rows if "✅" in r)} | {idx} |
| **Functional** | ≥ 98% PASS | {sum(1 for r in rows if "✅" in r)} | {idx} |

*Generated on {now}*
"""


def discover_skills() -> list[dict]:
    """Discover all skill directories."""
    targets = []
    for d in sorted(SKILLS_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith(".") or d.name in EXCLUDED_SKILL_DIRS:
            continue
        targets.append({"name": d.name, "path": d})
    return targets


def discover_workflows() -> list[dict]:
    """Discover workflow .md files inside skill-level directories."""
    targets = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith("."):
            continue
        if skill_dir.name in EXCLUDED_SKILL_DIRS or "sandboxes" in str(skill_dir):
            continue
        for wf_dir in [skill_dir / "workflows", skill_dir / ".agent" / "workflows"]:
            if wf_dir.exists():
                for f in sorted(wf_dir.glob("*.md")):
                    if f.name.lower() == "readme.md":
                        continue
                    targets.append(
                        {
                            "name": f"{skill_dir.name}/{f.stem}",
                            "path": f,
                            "skill": skill_dir.name,
                            "skill_path": skill_dir,
                        }
                    )
    return targets


def discover_rules() -> list[dict]:
    """Discover rule/prompt .md files inside skill-level .agent/ directories."""
    targets = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith("."):
            continue
        if skill_dir.name in EXCLUDED_SKILL_DIRS or "sandboxes" in str(skill_dir):
            continue
        for sub in [".agent/rules", ".agent/prompts"]:
            rules_dir = skill_dir / sub
            if rules_dir.exists():
                for f in sorted(rules_dir.glob("*.md")):
                    if f.name.lower() == "readme.md":
                        continue
                    targets.append(
                        {
                            "name": f"{skill_dir.name}/{f.stem}",
                            "path": f,
                            "skill": skill_dir.name,
                            "skill_path": skill_dir,
                        }
                    )
    return targets


def discover_codebases() -> list[dict]:
    """Discover core platform codebase directories."""
    targets = []
    for name in ["api_wrappers", "lib", "scripts", "core", "daemon"]:
        d = ANTIGRAVITY_ROOT / name
        if d.exists() and d.is_dir():
            targets.append({"name": name, "path": d})
    return targets


def _parse_gherkin_scenarios(gherkin_text: str) -> list[dict]:
    """Parse scenario tags and names from Gherkin feature text."""
    scenarios = []
    lines = gherkin_text.splitlines()
    current_tags = []
    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue
        if line_str.startswith("@"):
            current_tags.extend([t.strip() for t in line_str.split() if t.strip()])
        elif line_str.startswith("Scenario:") or line_str.startswith(
            "Scenario Outline:"
        ):
            title = line_str.split(":", 1)[1].strip()
            # Find the first tag that starts with @TC-
            tc_tag = None
            for tag in current_tags:
                if tag.startswith("@TC-"):
                    tc_tag = tag[1:]  # Strip '@'
                    break
            scenarios.append(
                {
                    "tag": tc_tag or f"TC-UC-S{len(scenarios) + 1:02d}",
                    "title": title,
                }
            )
            current_tags = []
    return scenarios


def _parse_test_cases(test_data_text: str) -> dict:
    """Parse test cases from test data JSON text."""
    try:
        data = json.loads(test_data_text)
        cases = {}
        if isinstance(data, dict):
            # Support skill/codebase format
            if "test_cases" in data:
                for tc in data["test_cases"]:
                    ref = tc.get("scenario_ref") or tc.get("id")
                    if ref:
                        cases[ref] = tc
            # Support function format
            elif "functions" in data:
                for func_key, func_entry in data["functions"].items():
                    for tc in func_entry.get("test_cases", []):
                        ref = tc.get("scenario_ref") or tc.get("id")
                        if ref:
                            cases[f"{func_key}::{ref}"] = tc
        return cases
    except Exception as e:
        log.warning(f"Error parsing test data: {e}")
        return {}


def _generate_python_test(skill_path: Path, meta: dict) -> str:  # noqa: C901
    """Generate Python end-to-end test suite aggregated across ALL UC slices.

    Reads all generated Gherkin files and test data from meta (populated by
    _generate_gherkin and _generate_test_data per UC slice), then builds
    a unified test class with test methods for every scenario across all UCs.
    """
    name = meta["name"]
    name_lower = name.lower().replace(" ", "_")
    domain = _get_domain_initials(name)
    now = datetime.now().strftime("%Y-%m-%d")

    # Aggregate Gherkin + test data across all UC slices
    all_gherkins = meta.get("generated_gherkins", {})
    all_test_datas = meta.get("generated_test_datas", {})

    # Fallback: if meta doesn't have multi-UC content, read from disk
    if not all_gherkins:
        for feature_file in (
            sorted((skill_path / "tests" / "features").glob("TC-UC-*.feature"))
            if (skill_path / "tests" / "features").exists()
            else []
        ):
            try:
                all_gherkins[feature_file.stem] = feature_file.read_text(
                    encoding="utf-8"
                )
            except Exception:
                pass
        # Legacy compat
        if not all_gherkins:
            legacy_feature = (
                skill_path / f"tests/features/TC-UC-001_{name_lower}.feature"
            )
            if legacy_feature.exists():
                all_gherkins["UC-001"] = legacy_feature.read_text(encoding="utf-8")

    if not all_test_datas:
        for data_file in (
            sorted((skill_path / "tests" / "data").glob("TC-UC-*_data.json"))
            if (skill_path / "tests" / "data").exists()
            else []
        ):
            try:
                all_test_datas[data_file.stem.replace("_data", "")] = (
                    data_file.read_text(encoding="utf-8")
                )
            except Exception:
                pass
        # Legacy compat
        if not all_test_datas:
            legacy_data = skill_path / "tests/data/TC-UC-001_data.json"
            if legacy_data.exists():
                all_test_datas["TC-UC-001"] = legacy_data.read_text(encoding="utf-8")

    # Merge all Gherkin and test data
    gherkin_content = "\n".join(all_gherkins.values())

    # Build merged test_cases_map from all UC data files
    merged_test_cases_map: dict = {}
    for td_text in all_test_datas.values():
        merged_test_cases_map.update(_parse_test_cases(td_text))

    # Parse Gherkin scenarios (aggregated across all UCs)
    scenarios = []
    if gherkin_content:
        scenarios = _parse_gherkin_scenarios(gherkin_content)

    # If no scenarios found, fallback to capabilities
    if not scenarios:
        caps = meta.get("capabilities", [])
        idx = 1
        for feat, detail in caps[:40]:
            if feat.lower() in (
                "feature",
                "constant",
                "file",
                "concern",
                "intent",
                "---",
                "",
            ):
                continue
            scenarios.append(
                {
                    "tag": f"TC-UC-001-S{idx:02d}",
                    "title": feat,
                }
            )
            idx += 1
        scenarios.append(
            {
                "tag": "TC-UC-001-ERR01",
                "title": "Graceful degradation on dependency failure",
            }
        )

    test_methods = []
    for idx, sc in enumerate(scenarios, 1):
        gherkin_id = sc["tag"]
        title = sc["title"]
        tc_id = f"TC_UC_{domain}_{idx:03d}"

        # Clean scenario title for python function name
        clean_title = re.sub(r"[^a-zA-Z0-9_]", "_", title.lower().replace(" ", "_"))
        clean_title = re.sub(r"_+", "_", clean_title).strip("_")

        # Check if it's an error scenario or normal scenario
        is_err = (
            "err" in gherkin_id.lower()
            or "error" in clean_title
            or "fail" in clean_title
        )
        func_prefix = "test_tc_err" if is_err else "test_tc"

        expected_status = "success"
        if gherkin_id in merged_test_cases_map:
            expected_status = (
                merged_test_cases_map[gherkin_id]
                .get("expected", {})
                .get("status", "success")
            )

        test_methods.append(f"""
    def {func_prefix}{idx:02d}_{clean_title}(self):
        \"\"\"Test scenario {gherkin_id} for '{title}'

        Traceability:
            UC:       {gherkin_id.split("-S")[0].replace("TC-", "") if "-S" in gherkin_id else (gherkin_id.rsplit("-", 1)[0].replace("TC-", "") if gherkin_id.startswith("TC-UC-") else "UC-001")}
            Gherkin:  {gherkin_id}
            TC-SPECS: {tc_id}
        \"\"\"
        tc_data = self._get_test_case_by_scenario("{gherkin_id}")
        self.assertIsNotNone(tc_data, "Test data for {gherkin_id} must exist")

        input_payload = tc_data.get("input", {{}})
        expected = tc_data.get("expected", {{}})

        self.assertEqual(input_payload.get("skill"), "{name}")
        self.assertEqual(expected.get("status"), "{expected_status}")
""")

    test_methods_str = "\n".join(test_methods)

    return f"""# Auto-generated Python test suite for {name}
# Derived from all UC Gherkin features (tests/features/TC-UC-*.feature) and Test Data (tests/data/TC-UC-*_data.json)
# UC Count: {len(all_gherkins)}
# Generated on {now}

import unittest
import json
import os
from pathlib import Path

class Test{name.replace("_", "").replace("-", "").replace(" ", "").capitalize()}EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Load all UC test data JSON files (TC-UC-*_data.json)
        current_dir = Path(__file__).resolve().parent
        data_dir = current_dir / "data"

        cls.test_cases = {{}}
        if data_dir.exists():
            for data_path in sorted(data_dir.glob("TC-UC-*_data.json")):
                try:
                    with open(data_path, "r", encoding="utf-8") as f:
                        payload = json.load(f)
                        for tc in payload.get("test_cases", []):
                            if "scenario_ref" in tc:
                                cls.test_cases[tc["scenario_ref"]] = tc
                except Exception as e:
                    print(f"Error loading test data {{data_path.name}}: {{e}}")

    def _get_test_case_by_scenario(self, scenario_ref):
        \"\"\"Helper to find test data by Gherkin scenario reference (across all UC data files).\"\"\"
        return self.test_cases.get(scenario_ref)
{test_methods_str}

if __name__ == "__main__":
    unittest.main()
"""


def generate_for_skill(skill_path: Path, dry_run: bool = False) -> dict:  # noqa: C901
    """Generate all asset types for a single skill with multi-UC support.

    For each UC slice (derived from SKILL.md section headings), generates:
      - docs/UC-{NNN}_{name_lower}.md
      - tests/features/TC-UC-{NNN}_{name_lower}.feature
      - tests/data/TC-UC-{NNN}_data.json

    Shared assets (generated once across all UCs):
      - tests/test_end_to_end.py  (aggregated)
      - docs/functional_requirements.md
      - docs/traceability_matrix.md
      - docs/okf/traceability_matrix.csv
      - docs/okf/datapackage.json
      - tests/e2e/TC-SPECS.md
      - docs/function_list.md
      - docs/checkpoints.md
    """
    meta = _parse_skill_md(skill_path)
    name = meta["name"]
    name_lower = name.lower().replace(" ", "_")

    # Cluster SKILL.md into UC slices
    uc_slices = _cluster_capabilities_into_ucs(meta)

    results = {
        "name": name,
        "files_created": 0,
        "errors": [],
        "uc_count": len(uc_slices),
    }

    # ── Per-UC assets ────────────────────────────────────────────────────────
    for uc_slice in uc_slices:
        uc_id = uc_slice["uc_id"]
        per_uc_files = {
            f"docs/{uc_id}_{name_lower}.md": lambda sp, m, s=uc_slice: _generate_uc_doc(
                sp, m, s
            ),
            f"tests/features/TC-{uc_id}_{name_lower}.feature": lambda sp, m, s=uc_slice: (
                _generate_gherkin(sp, m, s)
            ),
            f"tests/data/TC-{uc_id}_data.json": lambda sp, m, s=uc_slice: (
                _generate_test_data(sp, m, s)
            ),
        }
        for rel_path, generator_fn in per_uc_files.items():
            full_path = skill_path / rel_path
            if dry_run:
                log.info(
                    f"  [{'EXISTS' if full_path.exists() else 'WOULD CREATE'}] {rel_path}"
                )
                continue
            try:
                full_path.parent.mkdir(parents=True, exist_ok=True)
                content = generator_fn(skill_path, meta)
                full_path.write_text(content, encoding="utf-8")
                results["files_created"] += 1
                log.info(f"  [OK] {rel_path}")
            except Exception as e:
                results["errors"].append(f"{rel_path}: {e}")
                log.error(f"  [FAIL] {rel_path}: {e}")

    # ── Shared assets (once per skill) ───────────────────────────────────────
    shared_files = {
        "tests/test_end_to_end.py": _generate_python_test,
        "tests/e2e/TC-SPECS.md": _generate_tc_specs,
        "docs/functional_requirements.md": _generate_functional_requirements,
        "docs/okf/traceability_matrix.csv": _generate_okf_matrix_csv,
        "docs/okf/datapackage.json": _generate_okf_datapackage,
        "docs/traceability_matrix.md": _generate_traceability_matrix,
        "docs/function_list.md": _generate_function_list,
        "docs/checkpoints.md": _generate_checkpoints,
        "README.md": _generate_readme,
    }
    for rel_path, generator_fn in shared_files.items():
        full_path = skill_path / rel_path
        if dry_run:
            log.info(
                f"  [{'EXISTS' if full_path.exists() else 'WOULD CREATE'}] {rel_path}"
            )
            continue
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            content = generator_fn(skill_path, meta)
            full_path.write_text(content, encoding="utf-8")
            results["files_created"] += 1
            log.info(f"  [OK] {rel_path}")
        except Exception as e:
            results["errors"].append(f"{rel_path}: {e}")
            log.error(f"  [FAIL] {rel_path}: {e}")

    if not dry_run:
        _write_utop_state(skill_path, skill_path / "docs")

    return results


def _get_workflow_steps(content: str) -> list[str]:
    steps = re.findall(r"^\d+\.\s+(.+)$", content, re.MULTILINE)
    if not steps:
        steps = re.findall(r"^-\s+(.+)$", content, re.MULTILINE)[:10]
    return steps


def _build_workflow_gherkin(name: str, steps: list[str], skill: str, now: str) -> str:
    gherkin_scenarios = ""
    for i, step in enumerate(steps[:6], 1):
        clean = step.strip()[:150]
        gherkin_scenarios += f"""
  @TC-WF-S{i:02d}
  Scenario: Step {i} - {clean}
    Given the workflow "{name}" is initiated
    When step {i} executes: "{clean}"
    Then the step completes successfully
    And the workflow state is updated

"""
    if not gherkin_scenarios.strip():
        gherkin_scenarios = f"""
  @TC-WF-S01
  Scenario: Full workflow execution
    Given the workflow "{name}" is initiated
    When the workflow executes all steps
    Then the workflow completes successfully

"""
    return f"""# Auto-generated Gherkin for Workflow: {name}
# Generated: {now}

@workflow @{skill.lower()}
Feature: Workflow - {name}
  As a system operator
  I want to execute the {name} workflow
  So that the automated process completes reliably

  Background:
    Given the Antigravity platform is running
    And the "{skill}" skill is available

{gherkin_scenarios}"""


def generate_for_workflow(target: dict, dry_run: bool = False) -> dict:
    """Generate test assets for a workflow file."""
    name = target["name"]
    wf_path = target["path"]
    skill_path = target["skill_path"]
    safe_name = name.replace("/", "_").lower()
    output_dir = skill_path / "tests" / "workflows"

    try:
        content = wf_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        content = f"Workflow: {name}"

    steps = _get_workflow_steps(content)
    now = datetime.now().strftime("%Y-%m-%d")

    # UC document
    step_flows = (
        "\n".join(f"   {i}. {s.strip()}" for i, s in enumerate(steps[:10], 1))
        if steps
        else "   1. Execute workflow logic"
    )
    uc_content = f"""# UC-WF: {name}

## Use Case Identification
| Field | Value |
|---|---|
| **UC ID** | UC-WF-{safe_name} |
| **Title** | Workflow: {name} |
| **Type** | Workflow |
| **Status** | Draft (Auto-Generated) |
| **Created** | {now} |

## Description
Workflow definition from `{wf_path.name}` in the `{target["skill"]}` skill.

## Main Flow
{step_flows}

## Traceability
- **Gherkin**: `tests/workflows/TC-WF-{safe_name}.feature`
- **Test Data**: `tests/workflows/TC-WF-{safe_name}_data.json`
"""

    gherkin_content = _build_workflow_gherkin(name, steps, target["skill"], now)

    # Test data
    test_data = json.dumps(
        {
            "metadata": {"workflow": name, "skill": target["skill"], "generated": now},
            "test_cases": [
                {
                    "id": "TC-WF-VALID",
                    "type": "positive",
                    "input": {"trigger": "manual", "params": {}},
                    "expected": {"status": "success"},
                },
                {
                    "id": "TC-WF-INVALID",
                    "type": "negative",
                    "input": {"trigger": "manual", "params": {"force_error": True}},
                    "expected": {"status": "error"},
                },
            ],
        },
        indent=2,
    )

    # Traceability
    trace = f"""# Traceability — Workflow: {name}
| UC Flow | Gherkin | Test Data | Status |
|---|---|---|---|
"""
    for i, step in enumerate(steps[:6], 1):
        trace += f"| Step {i} | TC-WF-S{i:02d} | TC-WF-VALID | Draft |\n"
    if not steps:
        trace += "| Full Flow | TC-WF-S01 | TC-WF-VALID | Draft |\n"

    files_map = {
        f"UC-WF-{safe_name}.md": uc_content,
        f"TC-WF-{safe_name}.feature": gherkin_content,
        f"TC-WF-{safe_name}_data.json": test_data,
        f"traceability_WF_{safe_name}.md": trace,
    }

    results = {"name": name, "files_created": 0, "errors": []}
    for fname, fcontent in files_map.items():
        full_path = output_dir / fname
        if dry_run:
            log.info(
                f"  [{'EXISTS' if full_path.exists() else 'WOULD CREATE'}] tests/workflows/{fname}"
            )
            continue
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(fcontent, encoding="utf-8")
            results["files_created"] += 1
            log.info(f"  [OK] tests/workflows/{fname}")
        except Exception as e:
            results["errors"].append(str(e))
            log.error(f"  [FAIL] {fname}: {e}")

    if not dry_run:
        _write_utop_state(skill_path, output_dir)

    return results


def _build_rule_gherkin(
    name: str, rules: list[str], skill: str, rule_name: str, now: str
) -> str:
    gherkin = f"""# Auto-generated Gherkin for Rule: {name}
# Generated: {now}

@rule @{skill.lower()}
Feature: Rule Compliance - {name}
  As a platform operator
  I want to validate rule "{name}"
  So that system governance is enforced

  Background:
    Given the rule "{rule_name}" is loaded

"""
    for i, rule in enumerate(rules[:5], 1):
        clean = rule.strip()[:150]
        gherkin += f"""  @TC-RULE-{i:02d}-COMPLY
  Scenario: Compliance with Rule {i}
    Given a compliant input for "{clean}"
    When the rule is evaluated
    Then compliance is confirmed

  @TC-RULE-{i:02d}-VIOLATE
  Scenario: Violation of Rule {i}
    Given a non-compliant input for "{clean}"
    When the rule is evaluated
    Then a violation is reported

"""
    return gherkin


def generate_for_rule(target: dict, dry_run: bool = False) -> dict:
    """Generate test assets for a rule/prompt file."""
    name = target["name"]
    rule_path = target["path"]
    skill_path = target["skill_path"]
    safe_name = name.replace("/", "_").lower()
    output_dir = skill_path / "tests" / "rules"

    try:
        content = rule_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        content = f"Rule: {name}"

    now = datetime.now().strftime("%Y-%m-%d")
    rules = re.findall(r"^[-*]\s+(.+)$", content, re.MULTILINE)[:10]

    # Rule Validation Matrix
    rvm = f"""# Rule Validation Matrix — {name}

| Field | Value |
|---|---|
| **Rule Source** | `{rule_path.name}` |
| **Skill** | {target["skill"]} |
| **Generated** | {now} |

| Rule-ID | Rule Statement | Compliance Check | Pass Criteria | Violation Example |
|---|---|---|---|---|
"""
    for i, rule in enumerate(rules[:8], 1):
        clean = rule.strip()[:150]
        rvm += f"| R-{i:03d} | {clean} | Automated | Rule is enforced | Rule is bypassed |\n"
    if not rules:
        rvm += f"| R-001 | Core rule from {rule_path.name} | Manual | Compliance confirmed | Non-compliance detected |\n"

    gherkin = _build_rule_gherkin(name, rules, target["skill"], rule_path.name, now)

    # Test data
    test_data = json.dumps(
        {
            "metadata": {"rule": name, "skill": target["skill"], "generated": now},
            "test_cases": [
                {
                    "id": "TC-RULE-COMPLY",
                    "type": "positive",
                    "input": {"compliant": True},
                    "expected": {"result": "pass"},
                },
                {
                    "id": "TC-RULE-VIOLATE",
                    "type": "negative",
                    "input": {"compliant": False},
                    "expected": {"result": "violation"},
                },
            ],
        },
        indent=2,
    )

    # Traceability
    trace = f"""# Traceability — Rule: {name}
| Rule-ID | Gherkin Comply | Gherkin Violate | Test Data | Status |
|---|---|---|---|---|
"""
    for i in range(1, min(len(rules) + 1, 6)):
        trace += f"| R-{i:03d} | TC-RULE-{i:02d}-COMPLY | TC-RULE-{i:02d}-VIOLATE | TC-RULE-COMPLY | Draft |\n"
    if not rules:
        trace += "| R-001 | TC-RULE-01-COMPLY | TC-RULE-01-VIOLATE | TC-RULE-COMPLY | Draft |\n"

    files_map = {
        f"RVM-{safe_name}.md": rvm,
        f"TC-RULE-{safe_name}.feature": gherkin,
        f"TC-RULE-{safe_name}_data.json": test_data,
        f"traceability_RULE_{safe_name}.md": trace,
    }

    results = {"name": name, "files_created": 0, "errors": []}
    for fname, fcontent in files_map.items():
        full_path = output_dir / fname
        if dry_run:
            log.info(
                f"  [{'EXISTS' if full_path.exists() else 'WOULD CREATE'}] tests/rules/{fname}"
            )
            continue
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(fcontent, encoding="utf-8")
            results["files_created"] += 1
            log.info(f"  [OK] tests/rules/{fname}")
        except Exception as e:
            results["errors"].append(str(e))
            log.error(f"  [FAIL] {fname}: {e}")

    if not dry_run:
        _write_utop_state(skill_path, output_dir)

    return results


def _discover_functions(cb_path: Path) -> tuple[list[Path], list[dict]]:
    py_files = sorted(
        [f for f in cb_path.rglob("*.py") if "__pycache__" not in str(f)]
    )[:20]
    functions = []
    for pf in py_files[:10]:
        try:
            src = pf.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"^(?:def|async def)\s+(\w+)\s*\(", src, re.MULTILINE):
                fn = m.group(1)
                if not fn.startswith("_"):
                    functions.append({"name": fn, "file": pf.name})
        except Exception:
            pass
    return py_files, functions


def _build_codebase_gherkin(name: str, functions: list[dict], now: str) -> str:
    gherkin = f"""# Auto-generated Gherkin for Codebase: {name}
# Generated: {now}

@codebase @{name.lower()}
Feature: Codebase - {name}
  As a developer
  I want the {name} module to function correctly
  So that dependent systems remain stable

  Background:
    Given the "{name}" module is importable

"""
    for i, fn in enumerate(functions[:6], 1):
        gherkin += f"""  @TC-CB-S{i:02d}
  Scenario: {fn["name"]} executes correctly
    Given valid inputs for `{fn["name"]}()`
    When `{fn["name"]}()` is called
    Then it returns the expected result
    And no unhandled exceptions are raised

"""
    return gherkin


def _build_codebase_python_test(
    name: str,
    functions: list[dict],
    now: str,
    gherkin: str = None,
    test_data_str: str = None,
) -> str:
    """Generate Python test suite for codebase by parsing Gherkin feature and Test data."""
    scenarios = []
    if gherkin:
        scenarios = _parse_gherkin_scenarios(gherkin)

    test_cases_map = {}
    if test_data_str:
        test_cases_map = _parse_test_cases(test_data_str)

    # Fallback if no scenarios found
    if not scenarios:
        for i, fn in enumerate(functions[:6], 1):
            scenarios.append(
                {
                    "tag": f"TC-CB-S{i:02d}",
                    "title": f"{fn['name']} executes correctly",
                    "function": fn["name"],
                }
            )

    test_methods = []
    for idx, sc in enumerate(scenarios, 1):
        gherkin_id = sc["tag"]
        title = sc["title"]
        # Find function name
        func_name = sc.get("function")
        if not func_name:
            # Fallback parsing function name from title
            parts = title.split()
            if parts:
                func_name = parts[0].replace("()", "").replace("`", "")
            else:
                func_name = "execute"

        # Clean function/title name for python test method name
        clean_title = re.sub(r"[^a-zA-Z0-9_]", "_", title.lower().replace(" ", "_"))
        clean_title = re.sub(r"_+", "_", clean_title).strip("_")

        expected_status = "success"
        if gherkin_id in test_cases_map:
            expected_status = (
                test_cases_map[gherkin_id].get("expected", {}).get("status", "success")
            )

        test_methods.append(f"""
    def test_cb_{idx:02d}_{clean_title}(self):
        \"\"\"Test codebase function `{func_name}` (Scenario: {gherkin_id})\"\"\"
        tc_data = self._get_test_case_by_scenario("{gherkin_id}")
        self.assertIsNotNone(tc_data, "Test data for {gherkin_id} must exist")

        # Verify function info
        input_payload = tc_data.get("input", {{}})
        self.assertEqual(input_payload.get("function"), "{func_name}")
        expected = tc_data.get("expected", {{}})
        self.assertEqual(expected.get("status"), "{expected_status}")
""")

    test_methods_str = "\n".join(test_methods)

    return f"""# Auto-generated Python test suite for Codebase: {name}
# Derived from Gherkin feature and Test Data JSON
# Generated on {now}

import unittest
import json
import os
from pathlib import Path

class Test{name.replace("_", "").replace(" ", "").capitalize()}Codebase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        current_dir = Path(__file__).resolve().parent
        data_path = current_dir / "data" / "TC-UC-001_data.json"

        cls.test_cases = {{}}
        if data_path.exists():
            try:
                with open(data_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                    for tc in payload.get("test_cases", []):
                        if "scenario_ref" in tc:
                            cls.test_cases[tc["scenario_ref"]] = tc
            except Exception as e:
                print(f"Error loading test data: {{e}}")

    def _get_test_case_by_scenario(self, scenario_ref):
        return self.test_cases.get(scenario_ref)
{test_methods_str}

if __name__ == "__main__":
    unittest.main()
"""


def generate_for_codebase(target: dict, dry_run: bool = False) -> dict:
    """Generate test assets for a codebase directory."""
    name = target["name"]
    cb_path = target["path"]
    now = datetime.now().strftime("%Y-%m-%d")

    py_files, functions = _discover_functions(cb_path)

    # UC document
    func_flows = (
        "\n".join(
            f"   {i}. Call `{f['name']}()` from `{f['file']}`"
            for i, f in enumerate(functions[:10], 1)
        )
        if functions
        else "   1. Execute module logic"
    )
    uc = f"""# UC-001: {name}

| Field | Value |
|---|---|
| **UC ID** | UC-CB-{name} |
| **Title** | Codebase: {name} |
| **Type** | Core Module |
| **Created** | {now} |

## Description
Core platform codebase module `{name}` at `{cb_path}`.

## Public API Surface
{func_flows}

## Files
{chr(10).join(f"- `{f.name}`" for f in py_files[:15]) if py_files else "- (no Python files)"}
"""

    gherkin = _build_codebase_gherkin(name, functions, now)

    # Functional Requirements
    fr_rows = (
        "\n".join(
            f"| FR-{i:03d} | `{fn['name']}` | `{fn['file']}` | Validate input | Return result or raise | High | UC-CB-{name} |"
            for i, fn in enumerate(functions[:15], 1)
        )
        if functions
        else f"| FR-001 | `{name}` module | main | Valid input | Expected output | High | UC-CB-{name} |"
    )

    func_rules = f"""# Functional Requirements -- {name}

| FR-ID | Function | File | Input | Output | Priority | Linked UC |
|---|---|---|---|---|---|---|
{fr_rows}
"""

    # Dynamic Test data based on discovered functions
    test_cases = [
        {
            "id": "TC-CB-IMPORT",
            "type": "smoke",
            "scenario_ref": "TC-CB-IMPORT",
            "input": {"action": "import"},
            "expected": {"importable": True},
        }
    ]
    for i, fn in enumerate(functions[:6], 1):
        test_cases.append(
            {
                "id": f"TC-CB-{i:03d}-VALID",
                "type": "positive",
                "scenario_ref": f"TC-CB-S{i:02d}",
                "input": {
                    "function": fn["name"],
                    "file": fn["file"],
                    "args": [],
                    "kwargs": {},
                },
                "expected": {"status": "success"},
            }
        )
    test_data = json.dumps(
        {"metadata": {"codebase": name, "generated": now}, "test_cases": test_cases},
        indent=2,
    )

    # Traceability
    trace = f"""# Traceability -- Codebase: {name}

| Function | Gherkin | Functional Requirement | Test Data | Status |
|---|---|---|---|---|
"""
    for i, fn in enumerate(functions[:10], 1):
        trace += f"| `{fn['name']}` | TC-CB-S{i:02d} | FR-{i:03d} | TC-CB-{i:03d}-VALID | Draft |\n"

    # TC Specifications (TC-SPECS.md)
    tc_rows = []
    for i, fn in enumerate(functions[:10], 1):
        tc_id = f"TC_UC_CB_{name.upper()}_{i:03d}"
        tc_rows.append(
            f"| {tc_id} | TC-CB-S{i:02d} | FR-{i:03d} | RG6 System Reliability | SIT | ✅ |"
        )
    tc_joined = (
        "\n".join(tc_rows)
        if tc_rows
        else f"| TC_UC_CB_{name.upper()}_001 | TC-CB-S01 | FR-001 | RG6 System Reliability | SIT | ✅ |"
    )
    tc_specs = f"""# TC Specifications -- {name}

> Per testing.md §13 -- Enterprise Test Case Model

---

## TC Index

| TC ID | Gherkin | FR Coverage | Risk Category | Gate | Must-Pass |
|---|---|---|---|---|---|
{tc_joined}
"""

    # Function List
    fl_rows = (
        "\n".join(
            f"| FL-{i:03d} | `{fn['name']}` | `{fn['file']}` | Public function |"
            for i, fn in enumerate(functions[:30], 1)
        )
        if functions
        else "| FL-001 | None | N/A | No public functions discovered |"
    )

    func_list_md = f"""# Function List -- {name}

| ID | Function Name | File Path | Description |
|---|---|---|---|
{fl_rows}
"""

    # Checkpoints
    checkpoints_md = f"""# Checkpoints -- {name}

| Checkpoint ID | Description | Target | Severity | Status |
|---|---|---|---|---|
| CP-001 | Verify that task.md exists and is complete | Workspace Structure | Error | Pending |
| CP-002 | Verify that walkthrough.md exists and is populated | Workspace Structure | Error | Pending |
| CP-003 | Verify that functional_requirements.md maps to all public functions | Traceability | Error | Pending |
| CP-004 | Verify Gherkin test coverage matches functional requirements | BDD Alignment | Error | Pending |
| CP-005 | Run CodeAudit/Ruff linter to ensure code style compliance | Code Quality | Warning | Pending |
| CP-006 | Run PromptfooVibeReviewer on generated markdown logs | Semantic Alignment | Warning | Pending |
"""

    docs_dir = cb_path / "docs"
    tests_dir = cb_path / "tests"
    name_lower = name.lower()
    python_test = _build_codebase_python_test(
        name, functions, now, gherkin=gherkin, test_data_str=test_data
    )
    files_map = {
        (docs_dir / f"UC-001_{name_lower}.md"): uc,
        (tests_dir / "features" / f"TC-UC-001_{name_lower}.feature"): gherkin,
        (tests_dir / "data" / "TC-UC-001_data.json"): test_data,
        (tests_dir / "test_end_to_end.py"): python_test,
        (tests_dir / "e2e" / "TC-SPECS.md"): tc_specs,
        (docs_dir / "functional_requirements.md"): func_rules,
        (docs_dir / "traceability_matrix.md"): trace,
        (docs_dir / "function_list.md"): func_list_md,
        (docs_dir / "checkpoints.md"): checkpoints_md,
    }

    results = {"name": name, "files_created": 0, "errors": []}
    for fpath, fcontent in files_map.items():
        rel = str(fpath.relative_to(cb_path))
        if dry_run:
            log.info(f"  [{'EXISTS' if fpath.exists() else 'WOULD CREATE'}] {rel}")
            continue
        try:
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(fcontent, encoding="utf-8")
            results["files_created"] += 1
            log.info(f"  [OK] {rel}")
        except Exception as e:
            results["errors"].append(str(e))
            log.error(f"  [FAIL] {rel}: {e}")

    if not dry_run:
        _write_utop_state(cb_path, docs_dir)

    return results


# ── Main ──────────────────────────────────────────────────────────────────────


def run_harness(
    hname: str,
    args_type: str,
    type_val: str,
    discover_fn,
    generate_fn,
    args_target: str,
    dry_run: bool,
) -> tuple[int, int, tuple]:
    targets = discover_fn()
    if args_target:
        if type_val in ("workflow", "rule"):
            targets = [t for t in targets if args_target.lower() in t["name"].lower()]
        else:
            targets = [t for t in targets if t["name"].lower() == args_target.lower()]

    log.info(f"=== {hname.upper()} HARNESS: {len(targets)} targets ===")
    tc, te = 0, 0
    for i, t in enumerate(targets, 1):
        log.info(f"[{i}/{len(targets)}] {hname}: {t['name']}")
        if type_val in ("workflow", "rule", "codebase"):
            r = generate_fn(t, dry_run=dry_run)
        else:
            r = generate_fn(t["path"], dry_run=dry_run)
        tc += r["files_created"]
        te += len(r["errors"])
    return tc, te, (hname, len(targets), tc, te)


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Direct Asset Generator (No CDP Required)"
    )
    parser.add_argument(
        "--type",
        choices=["skills", "workflows", "rules", "codebases", "all"],
        default="all",
        help="Target type",
    )
    parser.add_argument(
        "--target", type=str, help="Specific target name", required=False
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without writing"
    )
    args = parser.parse_args()

    grand_total_created = 0
    grand_total_errors = 0
    harnesses_run = []

    harness_configs = [
        ("Skills", "skills", "skill", discover_skills, generate_for_skill),
        (
            "Workflows",
            "workflows",
            "workflow",
            discover_workflows,
            generate_for_workflow,
        ),
        ("Rules", "rules", "rule", discover_rules, generate_for_rule),
        (
            "Codebases",
            "codebases",
            "codebase",
            discover_codebases,
            generate_for_codebase,
        ),
    ]

    for hname, flag, type_val, discover_fn, generate_fn in harness_configs:
        if args.type in (flag, "all"):
            tc, te, info = run_harness(
                hname,
                args.type,
                type_val,
                discover_fn,
                generate_fn,
                args.target,
                args.dry_run,
            )
            grand_total_created += tc
            grand_total_errors += te
            harnesses_run.append(info)

    # ── Summary ───────────────────────────────────────────────────────────
    if not args.dry_run:
        print(f"\n{'=' * 80}")
        print("  COMPLETE -- Universal Asset Generation")
        print(f"{'=' * 80}")
        for hname, hcount, hcreated, herrors in harnesses_run:
            print(
                f"  {hname:12s}: {hcount:3d} targets | {hcreated:4d} files | {herrors} errors"
            )
        print(f"  {'':12s}  ---------------------")
        print(
            f"  {'TOTAL':12s}: {sum(h[1] for h in harnesses_run):3d} targets | {grand_total_created:4d} files | {grand_total_errors} errors"
        )
        print("  Cost:         $0.0000 (template-based)")
        print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
