"""
flow_batch_healer.py — Autonomous Batch Diagnostic & Self-Healing Pipeline for JobHunterKit.

Analyzes jobs queued in 'quarantined_batch_analysis' (failed after 2 attempts),
clusters their failure modes via Multi-Agent Root Cause Analysis (RCA), derives targeted
fixes (dynamic form answers, selector heuristics, timeout budgets), and automatically
re-queues remediated jobs into 'pending' with reset attempt counters for fresh execution.
"""

import argparse
import json
import logging
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "scripts"))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")
load_dotenv(r".\.env")

from shared_platform.db import get_connection, with_db_transaction
from shared_platform.llm_client import GeminiClient

logger = logging.getLogger("JobHunter.BatchHealer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DYNAMIC_ANSWERS_FILE = project_root / "data" / "dynamic_field_answers.json"
REMEDIATED_SELECTORS_FILE = project_root / "data" / "remediated_selectors.json"


def load_applicant_profile() -> Dict[str, Any]:
    """Loads applicant profile from config/applicant_profile.json."""
    for cand in [
        project_root / "config" / "applicant_profile.json",
        project_root / "config" / "profile.json",
        Path(r".\config\applicant_profile.json"),
    ]:
        if cand.exists():
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


def load_json_cache(filepath: Path) -> Dict[str, Any]:
    """Loads a JSON cache file or returns an empty dict if not present."""
    if filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read cache {filepath}: {e}")
    return {}


def save_json_cache(filepath: Path, data: Dict[str, Any]) -> None:
    """Safely saves a dictionary to a JSON cache file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to write cache {filepath}: {e}")


def classify_failure_mode(reason: str, error_msg: str) -> str:
    """
    Classifies failure text into one of 4 canonical archetypes:
    1. MISSING_FIELD: Unfilled or ambiguous question/input.
    2. SELECTOR_LOOP: Repeated clicks or unresolvable DOM selectors.
    3. TIMEOUT_TRANSIENT: Network or CLI timeout.
    4. HARD_GATE: Genuine CAPTCHA or SMS/2FA verification.
    """
    text = f"{reason or ''} {error_msg or ''}".lower()
    
    if any(k in text for k in ["captcha", "turnstile", "hcaptcha", "recaptcha", "cloudflare", "sms", "2fa", "verify you are human"]):
        return "HARD_GATE"
    elif any(k in text for k in ["loop", "repeat", "maximum iterations", "infinite click", "selector"]):
        return "SELECTOR_LOOP"
    elif any(k in text for k in ["timeout", "timed out", "closed", "connection reset", "navigation"]):
        return "TIMEOUT_TRANSIENT"
    else:
        return "MISSING_FIELD"


def diagnose_and_synthesize_remediations(
    quarantined_jobs: List[Dict[str, Any]],
    profile: Dict[str, Any],
    client: GeminiClient,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[int], List[int]]:
    """
    Runs multi-agent RCA over the batch of quarantined jobs.
    Returns:
      - new_dynamic_answers: Dict of field patterns -> synthesized answer
      - new_selectors: Dict of broken selectors -> remediated target locators
      - remediable_job_ids: List of job IDs eligible for auto-retry re-queueing
      - permanent_job_ids: List of job IDs graduating to manual review
    """
    dynamic_answers = load_json_cache(DYNAMIC_ANSWERS_FILE)
    remediated_selectors = load_json_cache(REMEDIATED_SELECTORS_FILE)
    
    remediable_job_ids: List[int] = []
    permanent_job_ids: List[int] = []

    # Cluster jobs by failure mode
    clusters: Dict[str, List[Dict[str, Any]]] = {
        "HARD_GATE": [],
        "SELECTOR_LOOP": [],
        "TIMEOUT_TRANSIENT": [],
        "MISSING_FIELD": []
    }

    for job in quarantined_jobs:
        f_mode = classify_failure_mode(job.get("manual_intervention_reason", ""), job.get("error_message", ""))
        clusters[f_mode].append(job)

    logger.info(
        f"Batch Cluster Breakdown: {len(clusters['MISSING_FIELD'])} Missing Fields | "
        f"{len(clusters['SELECTOR_LOOP'])} Selector Loops | "
        f"{len(clusters['TIMEOUT_TRANSIENT'])} Timeouts | "
        f"{len(clusters['HARD_GATE'])} Hard Gates"
    )

    # 1. Process HARD_GATE jobs (graduate directly to manual intervention)
    for job in clusters["HARD_GATE"]:
        permanent_job_ids.append(job["id"])

    # 2. Process TIMEOUT_TRANSIENT jobs (immediately eligible for re-queue)
    for job in clusters["TIMEOUT_TRANSIENT"]:
        remediable_job_ids.append(job["id"])

    # 3. Process SELECTOR_LOOP & MISSING_FIELD with LLM Root Cause Remediation
    actionable_jobs = clusters["SELECTOR_LOOP"] + clusters["MISSING_FIELD"]
    if actionable_jobs:
        batch_summary = [
            {
                "job_id": j["id"],
                "company": j["company"],
                "title": j["title"],
                "source": j["source"],
                "reason": j.get("manual_intervention_reason", ""),
                "error": j.get("error_message", "")[:300]
            }
            for j in actionable_jobs[:15]  # Process in batches of up to 15
        ]

        prompt = f"""You are the Lead Systems Architect & Form Automation Engineer for an autonomous job application system.
We have collected a batch of job application failures that exhausted their initial 2 retry attempts.

Candidate Profile Summary:
{json.dumps(profile, indent=2)}

Quarantined Failure Batch:
{json.dumps(batch_summary, indent=2)}

Existing Dynamic Answers Cache:
{json.dumps(dynamic_answers, indent=2)}

Existing Remediated Selectors:
{json.dumps(remediated_selectors, indent=2)}

Analyze the root causes of these failures and formulate automated remediations:
1. For missing/ambiguous form fields (e.g. questions regarding notice period, work authorization, salary expectation, experience with specific tools), derive canonical standard answers consistent with the candidate's profile.
2. For selector loops or button identification failures, suggest refined Playwright locators or disambiguation strategies.
3. Classify which job IDs can now be safely re-queued for automated retry versus which strictly require human manual application.

Return ONLY a valid JSON object matching this schema:
{{
  "remediated_answers": {{
    "regex_or_keyword_pattern": "standard answer string"
  }},
  "remediated_selectors": {{
    "problematic_selector": "repaired_playwright_selector"
  }},
  "remediable_job_ids": [123, 456],
  "unresolvable_manual_job_ids": [789],
  "rca_summary": "Concise engineering summary of root causes diagnosed and remediations applied"
}}
"""
        try:
            llm_res = client.call(prompt, json_mode=True, timeout=65.0)
            parsed = json.loads(llm_res) if isinstance(llm_res, str) else llm_res
            
            # Merge answers
            new_answers = parsed.get("remediated_answers", {})
            dynamic_answers.update(new_answers)
            
            # Merge selectors
            new_sels = parsed.get("remediated_selectors", {})
            remediated_selectors.update(new_sels)
            
            llm_remediable = [int(jid) for jid in parsed.get("remediable_job_ids", []) if isinstance(jid, (int, str)) and str(jid).isdigit()]
            llm_manual = [int(jid) for jid in parsed.get("unresolvable_manual_job_ids", []) if isinstance(jid, (int, str)) and str(jid).isdigit()]
            
            remediable_job_ids.extend(llm_remediable)
            permanent_job_ids.extend(llm_manual)
            
            # Catch any leftover actionable jobs as remediable by default
            processed_ids = set(remediable_job_ids + permanent_job_ids)
            for j in actionable_jobs:
                if j["id"] not in processed_ids:
                    remediable_job_ids.append(j["id"])

            logger.info(f"[RCA Synthesis] {parsed.get('rca_summary', 'Remediations generated.')}")
            
        except Exception as e:
            logger.warning(f"LLM RCA batch analysis failed: {e}. Falling back to default recovery rules.")
            for j in actionable_jobs:
                remediable_job_ids.append(j["id"])

    # Persist updated caches
    save_json_cache(DYNAMIC_ANSWERS_FILE, dynamic_answers)
    save_json_cache(REMEDIATED_SELECTORS_FILE, remediated_selectors)

    # De-duplicate IDs
    remediable_job_ids = list(set(remediable_job_ids))
    permanent_job_ids = [jid for jid in list(set(permanent_job_ids)) if jid not in remediable_job_ids]

    return dynamic_answers, remediated_selectors, remediable_job_ids, permanent_job_ids


@with_db_transaction
def execute_batch_remediation(
    remediable_ids: List[int],
    permanent_ids: List[int],
    conn=None,
) -> Tuple[int, int]:
    """
    Atomically updates database records:
    - Remediated jobs: status_apply = 'pending', apply_attempts = 0, manual_intervention_reason = NULL
    - Permanent jobs: status_apply = 'needs_manual_intervention'
    """
    requeued_count = 0
    permanent_count = 0
    with conn.cursor() as cur:
        if remediable_ids:
            cur.execute("""
                UPDATE job_hunter.jobs
                SET status_apply = 'pending',
                    manual_intervention_reason = NULL,
                    apply_attempts = 0,
                    claimed_at = NULL
                WHERE id = ANY(%s);
            """, (remediable_ids,))
            requeued_count = cur.rowcount

        if permanent_ids:
            cur.execute("""
                UPDATE job_hunter.jobs
                SET status_apply = 'needs_manual_intervention',
                    claimed_at = NULL
                WHERE id = ANY(%s);
            """, (permanent_ids,))
            permanent_count = cur.rowcount

    return requeued_count, permanent_count


def run_batch_healer(trace_id: str = "") -> Dict[str, Any]:
    """
    Main orchestration loop for the Batch Diagnostic & Self-Healing Pipeline.
    Executes via the compiled LangGraph StateGraph (Lang Ecosystem SSOT).
    """
    logger.info("=" * 70)
    logger.info("STARTING BATCH DIAGNOSTIC & SELF-HEALING PIPELINE (LANGGRAPH SSOT)")
    logger.info("=" * 70)

    from shared_platform.graph import run_batch_healer_graph

    graph_state = run_batch_healer_graph(trace_id=trace_id)
    requeued_count = graph_state.get("requeued_count", 0)
    permanent_count = graph_state.get("permanent_count", 0)
    quarantined_count = len(graph_state.get("quarantined_jobs", []))

    summary = {
        "status": graph_state.get("status", "completed"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_quarantined": quarantined_count,
        "requeued_for_retry": requeued_count,
        "graduated_to_manual": permanent_count,
        "total_dynamic_answers": len(graph_state.get("dynamic_answers", {})),
        "total_remediated_selectors": len(graph_state.get("remediated_selectors", {})),
        "rca_summary": graph_state.get("rca_summary", "")
    }

    logger.info("=" * 70)
    logger.info(f"BATCH HEALER LANGGRAPH EXECUTION COMPLETE: {requeued_count} Re-queued for Auto-Retry | {permanent_count} Graduated to Manual")
    logger.info("=" * 70)

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autonomous Batch Diagnostic & Self-Healing Pipeline")
    args = parser.parse_args()
    run_batch_healer()
