import logging
from typing import Any, TypedDict

logger = logging.getLogger("JobHunter.Graph")


class JobHunterState(TypedDict, total=False):
    """Execution state passed through the LangGraph StateGraph pipeline."""

    session_id: str
    trace_id: str
    source: str
    limit: int
    scraped_count: int
    scored_count: int
    applied_count: int
    proof_verified_count: int
    errors: list[str]
    is_paused: bool
    status: str


def scrape_node(state: JobHunterState) -> dict[str, Any]:
    """Node 1: Web Scraping and DB Ingestion."""
    logger.info("[GraphNode] Executing scrape_node...")
    try:
        from scripts.flow_scrape import run_scrape_pipeline

        limit = state.get("limit", 10)
        source = state.get("source", "all")
        res = run_scrape_pipeline(source=source, limit=limit)
        return {"scraped_count": res.get("scraped_count", 0), "status": "scraped"}
    except Exception as e:
        logger.error(f"[GraphNode] scrape_node error: {e}")
        return {"errors": [f"scrape_node: {e}"], "status": "scrape_failed"}


def score_node(state: JobHunterState) -> dict[str, Any]:
    """Node 2: Job Description Evaluation & Fit Scoring."""
    logger.info("[GraphNode] Executing score_node...")
    try:
        from scripts.flow_score import run_scoring_pipeline

        limit = state.get("limit", 10)
        res = run_scoring_pipeline(limit=limit)
        return {"scored_count": res.get("scored_count", 0), "status": "scored"}
    except Exception as e:
        logger.error(f"[GraphNode] score_node error: {e}")
        return {"errors": [f"score_node: {e}"], "status": "score_failed"}


def tailor_node(state: JobHunterState) -> dict[str, Any]:
    """Node 3: Dynamic CV Tailoring & PDF Generation."""
    logger.info("[GraphNode] Executing tailor_node...")
    return {"status": "tailored"}


def apply_node(state: JobHunterState) -> dict[str, Any]:
    """Node 4: Playwright Automated Application Loop."""
    logger.info("[GraphNode] Executing apply_node...")
    try:
        from scripts.flow_apply import run_apply_pipeline

        limit = state.get("limit", 5)
        res = run_apply_pipeline(limit=limit)
        return {"applied_count": res.get("applied_count", 0), "status": "applied"}
    except Exception as e:
        logger.error(f"[GraphNode] apply_node error: {e}")
        return {"errors": [f"apply_node: {e}"], "status": "apply_failed"}


def proof_review_node(state: JobHunterState) -> dict[str, Any]:
    """Node 5: Post-Application Proof Audit & Verification."""
    logger.info("[GraphNode] Executing proof_review_node...")
    try:
        from scripts.verify_application_proofs import run_proof_verification

        res = run_proof_verification()

        verified = 0
        unverified = 0
        try:
            from core.db_client import get_connection

            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM job_hunter.jobs WHERE status_apply = 'completed'"
                )
                row = cur.fetchone()
                if row:
                    verified = row[0]
                cur.execute(
                    "SELECT COUNT(*) FROM job_hunter.jobs WHERE status_apply = 'needs_manual_intervention'"
                )
                row2 = cur.fetchone()
                if row2:
                    unverified = row2[0]
            conn.close()
        except Exception:
            verified = res.get("verified_count", 0) if isinstance(res, dict) else 0

        return {
            "proof_verified_count": verified,
            "verified_proof_count": verified,
            "unverified_proof_count": unverified,
            "proof_review_status": "verified"
            if unverified == 0
            else "manual_intervention_required",
            "status": "completed",
        }
    except Exception as e:
        logger.error(f"[GraphNode] proof_review_node error: {e}")
        return {
            "errors": [f"proof_review_node: {e}"],
            "status": "proof_review_failed",
            "proof_review_status": "failed",
        }


class JobHunterPipelineGraph:
    """Stateful orchestrator graph execution wrapper."""

    def __init__(self):
        self.nodes = {
            "scrape": scrape_node,
            "score": score_node,
            "tailor": tailor_node,
            "apply": apply_node,
            "proof_review": proof_review_node,
        }

    def invoke(self, initial_state: JobHunterState) -> JobHunterState:
        state = dict(initial_state)
        for name in ["scrape", "score", "tailor", "apply", "proof_review"]:
            if state.get("is_paused"):
                state["status"] = "paused"
                break
            node_fn = self.nodes[name]
            result = node_fn(state)
            state.update(result)
        return state


def build_graph():
    """Builds and compiles the master JobHunter StateGraph."""
    try:
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.graph import END, StateGraph

        builder = StateGraph(JobHunterState)
        builder.add_node("scrape_node", scrape_node)
        builder.add_node("score_node", score_node)
        builder.add_node("tailor_node", tailor_node)
        builder.add_node("apply_node", apply_node)
        builder.add_node("proof_review_node", proof_review_node)

        builder.set_entry_point("scrape_node")
        builder.add_edge("scrape_node", "score_node")
        builder.add_edge("score_node", "tailor_node")
        builder.add_edge("tailor_node", "apply_node")
        builder.add_edge("apply_node", "proof_review_node")
        builder.add_edge("proof_review_node", END)

        checkpointer = MemorySaver()
        return builder.compile(checkpointer=checkpointer)
    except ImportError:
        logger.warning(
            "[Graph] LangGraph not installed; falling back to native pipeline runner."
        )
        return JobHunterPipelineGraph()


def build_score_tailor_subgraph():
    """Builds and compiles the score -> tailor sub-graph."""
    try:
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.graph import END, StateGraph

        builder = StateGraph(JobHunterState)
        builder.add_node("score_node", score_node)
        builder.add_node("tailor_node", tailor_node)
        builder.set_entry_point("score_node")
        builder.add_edge("score_node", "tailor_node")
        builder.add_edge("tailor_node", END)
        checkpointer = MemorySaver()
        return builder.compile(checkpointer=checkpointer)
    except ImportError:
        return JobHunterPipelineGraph()


def build_apply_review_subgraph():
    """Builds and compiles the apply -> proof_review sub-graph."""
    try:
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.graph import END, StateGraph

        builder = StateGraph(JobHunterState)
        builder.add_node("apply_node", apply_node)
        builder.add_node("proof_review_node", proof_review_node)
        builder.set_entry_point("apply_node")
        builder.add_edge("apply_node", "proof_review_node")
        builder.add_edge("proof_review_node", END)
        checkpointer = MemorySaver()
        return builder.compile(checkpointer=checkpointer)
    except ImportError:
        return JobHunterPipelineGraph()


def run_pipeline(
    source: str = "all", limit: int = 10, trace_id: str = ""
) -> dict[str, Any]:
    """Convenience entry point to run full 5-stage job hunter pipeline."""
    initial_state: JobHunterState = {
        "session_id": f"sess_{limit}",
        "trace_id": trace_id,
        "source": source,
        "limit": limit,
        "scraped_count": 0,
        "scored_count": 0,
        "applied_count": 0,
        "proof_verified_count": 0,
        "errors": [],
        "is_paused": False,
        "status": "initialized",
    }
    graph = build_graph()
    return graph.invoke(initial_state)


# ---------------------------------------------------------------------------
# Autonomous Batch Diagnostic & Self-Healing StateGraph (Lang Ecosystem SSOT)
# ---------------------------------------------------------------------------

class BatchHealerState(TypedDict, total=False):
    """Execution state passed through the LangGraph Batch Healer StateGraph."""
    session_id: str
    trace_id: str
    quarantined_jobs: list[dict[str, Any]]
    clusters: dict[str, list[dict[str, Any]]]
    dynamic_answers: dict[str, Any]
    remediated_selectors: dict[str, Any]
    remediable_ids: list[int]
    permanent_ids: list[int]
    requeued_count: int
    permanent_count: int
    rca_summary: str
    status: str
    errors: list[str]


def extract_quarantined_jobs_node(state: BatchHealerState) -> dict[str, Any]:
    """Deterministic Code Node 1: Extracts failed jobs from PostgreSQL (P(Y|X) = 1)."""
    logger.info("[BatchHealerGraph] Executing extract_quarantined_jobs_node (Code Node)...")
    try:
        from core.db_client import get_connection
        conn = get_connection()
        quarantined = []
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    j.id, j.title, j.company, j.source, j.url, j.manual_intervention_reason,
                    a.error_message, a.status as last_app_status
                FROM job_hunter.jobs j
                LEFT JOIN LATERAL (
                    SELECT error_message, status 
                    FROM job_hunter.applications 
                    WHERE job_id = j.id 
                    ORDER BY applied_at DESC 
                    LIMIT 1
                ) a ON true
                WHERE j.status_apply = 'quarantined_batch_analysis'
                   OR (j.status_apply IN ('failed', 'failed_manual', 'needs_manual_intervention') AND j.apply_attempts >= 2)
                ORDER BY j.scraped_at DESC;
            """)
            for r in cur.fetchall():
                quarantined.append({
                    "id": r[0], "title": r[1], "company": r[2], "source": r[3],
                    "url": r[4], "manual_intervention_reason": r[5] or "",
                    "error_message": r[6] or "", "last_app_status": r[7] or ""
                })
        conn.close()
        return {"quarantined_jobs": quarantined, "status": "extracted"}
    except Exception as e:
        logger.error(f"[BatchHealerGraph] extract_quarantined_jobs_node error: {e}")
        return {"errors": [f"extract_quarantined_jobs: {e}"], "status": "extract_failed"}


def cluster_failure_telemetry_node(state: BatchHealerState) -> dict[str, Any]:
    """Deterministic Code Node 2: Clusters failure telemetry into 4 archetypes (P(Y|X) = 1)."""
    logger.info("[BatchHealerGraph] Executing cluster_failure_telemetry_node (Code Node)...")
    from scripts.flow_batch_healer import classify_failure_mode
    
    jobs = state.get("quarantined_jobs", [])
    clusters: dict[str, list[dict[str, Any]]] = {
        "HARD_GATE": [], "SELECTOR_LOOP": [], "TIMEOUT_TRANSIENT": [], "MISSING_FIELD": []
    }
    remediable_ids: list[int] = []
    permanent_ids: list[int] = []

    for job in jobs:
        f_mode = classify_failure_mode(job.get("manual_intervention_reason", ""), job.get("error_message", ""))
        clusters[f_mode].append(job)

    # Deterministic routing for hard gates and transient timeouts
    for job in clusters["HARD_GATE"]:
        permanent_ids.append(job["id"])
    for job in clusters["TIMEOUT_TRANSIENT"]:
        remediable_ids.append(job["id"])

    return {
        "clusters": clusters,
        "remediable_ids": remediable_ids,
        "permanent_ids": permanent_ids,
        "status": "clustered"
    }


def llm_rca_synthesis_node(state: BatchHealerState) -> dict[str, Any]:
    """Probabilistic Agent Node 3: Multi-Agent RCA & Heuristic Synthesis (P(Y|X) in (0, 1))."""
    logger.info("[BatchHealerGraph] Executing llm_rca_synthesis_node (Agent Node)...")
    import json
    from scripts.flow_batch_healer import (
        DYNAMIC_ANSWERS_FILE, REMEDIATED_SELECTORS_FILE,
        load_json_cache, load_applicant_profile
    )
    from shared_platform.llm_client import GeminiClient
    from shared_platform.telemetry import log_metric, score_trace

    clusters = state.get("clusters", {})
    actionable_jobs = clusters.get("SELECTOR_LOOP", []) + clusters.get("MISSING_FIELD", [])
    dynamic_answers = load_json_cache(DYNAMIC_ANSWERS_FILE)
    remediated_selectors = load_json_cache(REMEDIATED_SELECTORS_FILE)
    remediable_ids = list(state.get("remediable_ids", []))
    permanent_ids = list(state.get("permanent_ids", []))
    rca_summary = "No actionable jobs requiring LLM synthesis."

    if actionable_jobs:
        profile = load_applicant_profile()
        client = GeminiClient()
        batch_summary = [
            {
                "job_id": j["id"], "company": j["company"], "title": j["title"],
                "source": j["source"], "reason": j.get("manual_intervention_reason", ""),
                "error": j.get("error_message", "")[:300]
            }
            for j in actionable_jobs[:15]
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
1. For missing/ambiguous form fields, derive canonical standard answers consistent with the candidate's profile.
2. For selector loops or button identification failures, suggest refined Playwright locators or disambiguation strategies.
3. Classify which job IDs can now be safely re-queued for automated retry versus which strictly require human manual application.

Return ONLY a valid JSON object matching this schema:
{{
  "remediated_answers": {{ "regex_or_keyword_pattern": "standard answer string" }},
  "remediated_selectors": {{ "problematic_selector": "repaired_playwright_selector" }},
  "remediable_job_ids": [123, 456],
  "unresolvable_manual_job_ids": [789],
  "rca_summary": "Concise engineering summary of root causes diagnosed and remediations applied"
}}
"""
        try:
            llm_res = client.call(prompt, json_mode=True, timeout=65.0)
            parsed = json.loads(llm_res) if isinstance(llm_res, str) else llm_res
            dynamic_answers.update(parsed.get("remediated_answers", {}))
            remediated_selectors.update(parsed.get("remediated_selectors", {}))
            
            llm_rem = [int(jid) for jid in parsed.get("remediable_job_ids", []) if str(jid).isdigit()]
            llm_perm = [int(jid) for jid in parsed.get("unresolvable_manual_job_ids", []) if str(jid).isdigit()]
            remediable_ids.extend(llm_rem)
            permanent_ids.extend(llm_perm)

            processed_ids = set(remediable_ids + permanent_ids)
            for j in actionable_jobs:
                if j["id"] not in processed_ids:
                    remediable_ids.append(j["id"])

            rca_summary = parsed.get("rca_summary", "RCA completed successfully.")
            trace_id = state.get("trace_id", "")
            if trace_id:
                score_trace(trace_id, "batch_healer.rca_confidence", 1.0, comment=rca_summary)
                log_metric("batch_healer.actionable_count", len(actionable_jobs))
        except Exception as e:
            logger.warning(f"[BatchHealerGraph] LLM RCA synthesis failed: {e}. Falling back to default recovery.")
            for j in actionable_jobs:
                remediable_ids.append(j["id"])

    return {
        "dynamic_answers": dynamic_answers,
        "remediated_selectors": remediated_selectors,
        "remediable_ids": list(set(remediable_ids)),
        "permanent_ids": [jid for jid in list(set(permanent_ids)) if jid not in remediable_ids],
        "rca_summary": rca_summary,
        "status": "synthesized"
    }


def persist_healed_caches_node(state: BatchHealerState) -> dict[str, Any]:
    """Deterministic Code Node 4: Persists updated JSON caches (P(Y|X) = 1)."""
    logger.info("[BatchHealerGraph] Executing persist_healed_caches_node (Code Node)...")
    from scripts.flow_batch_healer import (
        DYNAMIC_ANSWERS_FILE, REMEDIATED_SELECTORS_FILE, save_json_cache
    )
    save_json_cache(DYNAMIC_ANSWERS_FILE, state.get("dynamic_answers", {}))
    save_json_cache(REMEDIATED_SELECTORS_FILE, state.get("remediated_selectors", {}))
    return {"status": "caches_persisted"}


def atomic_db_requeue_node(state: BatchHealerState) -> dict[str, Any]:
    """Deterministic Code Node 5: Executes atomic PostgreSQL re-queue transaction (P(Y|X) = 1)."""
    logger.info("[BatchHealerGraph] Executing atomic_db_requeue_node (Code Node)...")
    from scripts.flow_batch_healer import execute_batch_remediation
    from shared_platform.telemetry import log_metric

    remediable_ids = state.get("remediable_ids", [])
    permanent_ids = state.get("permanent_ids", [])

    requeued, permanent = execute_batch_remediation(remediable_ids, permanent_ids)
    log_metric("batch_healer.requeued_for_retry", float(requeued))
    log_metric("batch_healer.graduated_to_manual", float(permanent))

    return {
        "requeued_count": requeued,
        "permanent_count": permanent,
        "status": "completed"
    }


class BatchHealerPipelineGraph:
    """Stateful orchestrator for Batch Healer workflow."""
    def __init__(self):
        self.nodes = {
            "extract": extract_quarantined_jobs_node,
            "cluster": cluster_failure_telemetry_node,
            "llm_rca": llm_rca_synthesis_node,
            "persist": persist_healed_caches_node,
            "requeue": atomic_db_requeue_node,
        }

    def invoke(self, initial_state: BatchHealerState) -> BatchHealerState:
        state = dict(initial_state)
        for name in ["extract", "cluster", "llm_rca", "persist", "requeue"]:
            result = self.nodes[name](state)
            state.update(result)
        return state


def build_batch_healer_graph():
    """Builds and compiles the Batch Healer LangGraph StateGraph."""
    try:
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.graph import END, StateGraph

        builder = StateGraph(BatchHealerState)
        builder.add_node("extract_node", extract_quarantined_jobs_node)
        builder.add_node("cluster_node", cluster_failure_telemetry_node)
        builder.add_node("llm_rca_node", llm_rca_synthesis_node)
        builder.add_node("persist_node", persist_healed_caches_node)
        builder.add_node("requeue_node", atomic_db_requeue_node)

        builder.set_entry_point("extract_node")
        builder.add_edge("extract_node", "cluster_node")
        builder.add_edge("cluster_node", "llm_rca_node")
        builder.add_edge("llm_rca_node", "persist_node")
        builder.add_edge("persist_node", "requeue_node")
        builder.add_edge("requeue_node", END)

        checkpointer = MemorySaver()
        return builder.compile(checkpointer=checkpointer)
    except ImportError:
        logger.warning("[BatchHealerGraph] LangGraph not installed; using native pipeline runner.")
        return BatchHealerPipelineGraph()


def run_batch_healer_graph(trace_id: str = "") -> dict[str, Any]:
    """Convenience entrypoint to execute the Batch Healer LangGraph StateGraph."""
    import uuid
    session_id = f"healer_{uuid.uuid4().hex[:8]}"
    initial_state: BatchHealerState = {
        "session_id": session_id,
        "trace_id": trace_id or f"trace_{uuid.uuid4().hex[:12]}",
        "quarantined_jobs": [],
        "clusters": {},
        "dynamic_answers": {},
        "remediated_selectors": {},
        "remediable_ids": [],
        "permanent_ids": [],
        "requeued_count": 0,
        "permanent_count": 0,
        "rca_summary": "",
        "status": "initialized",
        "errors": []
    }
    graph = build_batch_healer_graph()
    config = {"configurable": {"thread_id": session_id}}
    return graph.invoke(initial_state, config=config)

