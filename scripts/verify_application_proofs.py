import argparse
import os
import sys
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Add project root to python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "scripts"))

from core.db_client import get_connection
from shared_platform.llm_judge import evaluate_application_proof
from shared_platform.logging_setup import checkpointed_function
from shared_platform.paths import STORAGE_ROOT, get_job_dirs


def verify_proof_file(filepath, job_dict=None):
    if not os.path.exists(filepath):
        return False
    if not job_dict:
        job_dict = {"id": "unknown", "company": "Unknown", "title": "Job"}

    verdict = evaluate_application_proof(job_dict, proof_path=filepath)
    return verdict.get("is_valid_submission", False)


@checkpointed_function("FL-237", use_case_id="UC-006", stage_name="run_verification")
def run_verification(dry_run=False):
    print(
        "=== Starting Post-Application LLM-as-a-Judge Proof Review & Verification ==="
    )
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, company, title, scraped_at, source, keyword, search_location
                FROM job_hunter.jobs
                WHERE status_apply IN ('completed', 'needs_manual_intervention')
            """)
            jobs = cur.fetchall()

            invalid_count = 0
            valid_count = 0
            recovered_count = 0

            for (
                job_id,
                company,
                title,
                scraped_at,
                source,
                keyword,
                search_location,
            ) in jobs:
                job_dict = {
                    "id": job_id,
                    "company": company,
                    "title": title,
                    "scraped_at": scraped_at,
                    "source": source,
                    "keyword": keyword,
                    "search_location": search_location,
                }
                dirs = get_job_dirs(job_dict)
                proof_dir = dirs.get("proof_dir")

                target_proof_path = None
                def matches_job_proof(filename, j_id):
                    return (
                        filename == f"proof_submitted_{j_id}.png"
                        or filename.endswith(f"__{j_id}.png")
                        or filename.endswith(f"_{j_id}.png")
                        or filename.endswith(f"_{j_id}_proof.png")
                    )

                if proof_dir and os.path.exists(proof_dir):
                    png_files = [f for f in os.listdir(proof_dir) if f.endswith(".png")]
                    for f in png_files:
                        if matches_job_proof(f, job_id):
                            target_proof_path = os.path.join(proof_dir, f)
                            break

                if not target_proof_path:
                    search_candidates = [
                        os.path.join(STORAGE_ROOT, "campaigns"),
                        r".\data\campaigns",
                        os.path.join(str(project_root), "data", "campaigns"),
                    ]
                    for campaigns_dir in search_candidates:
                        if os.path.exists(campaigns_dir):
                            for root, _, files in os.walk(campaigns_dir):
                                for f in files:
                                    if f.endswith(".png") and matches_job_proof(f, job_id):
                                        target_proof_path = os.path.join(root, f)
                                        print(
                                            f"[RECOVERED PROOF FILE] Job {job_id} ({company}): Found proof file at {target_proof_path}"
                                        )
                                        break
                                if target_proof_path:
                                    break
                        if target_proof_path:
                            break

                # Evaluate via LLM Judge
                verdict = evaluate_application_proof(
                    job_dict, proof_path=target_proof_path
                )
                is_valid = verdict.get("is_valid_submission", False)
                reasoning = verdict.get("reasoning", "LLM Judge Evaluation")
                detected_status = verdict.get(
                    "detected_status", "needs_manual_intervention"
                )

                if not is_valid or detected_status != "applied":
                    invalid_count += 1
                    print(f"[LLM JUDGE REJECT] Job {job_id} ({company}): {reasoning}")
                    if not dry_run:
                        cur.execute(
                            "SELECT apply_attempts FROM job_hunter.jobs WHERE id = %s;",
                            (job_id,),
                        )
                        att_row = cur.fetchone()
                        try:
                            curr_att = (
                                int(att_row[0])
                                if att_row and att_row[0] is not None
                                else 0
                            )
                        except (ValueError, TypeError):
                            curr_att = 0
                        if curr_att < 3:
                            new_status = "pending"
                            reason_msg = f"Auto-retry queued ({curr_att}/3): Proof rejected by LLM Judge ({reasoning[:100]})"
                            print(
                                f"  [AUTO RETRY QUEUED] Re-queuing Job {job_id} for automated retry pass ({curr_att}/3)."
                            )
                        else:
                            new_status = "needs_manual_intervention"
                            reason_msg = f"LLM Judge rejected proof: {reasoning}"
                            print(
                                f"  [MAX RETRIES EXCEEDED] Job {job_id}: 3/3 attempts failed. Escalating to 'needs_manual_intervention'."
                            )

                        cur.execute(
                            """
                            UPDATE job_hunter.jobs
                            SET status_apply = %s, manual_intervention_reason = %s
                            WHERE id = %s
                        """,
                            (new_status, reason_msg, job_id),
                        )
                        cur.execute(
                            """
                            UPDATE job_hunter.applications
                            SET status = %s, manual_intervention_reason = %s
                            WHERE job_id = %s AND status IN ('applied', 'completed', 'dry_run')
                        """,
                            (new_status, reason_msg, job_id),
                        )
                else:
                    valid_count += 1
                    # If this was previously marked as needs_manual_intervention, recover it to completed!
                    cur.execute(
                        "SELECT status_apply FROM job_hunter.jobs WHERE id = %s",
                        (job_id,),
                    )
                    current_status = cur.fetchone()[0]
                    if current_status == "needs_manual_intervention":
                        recovered_count += 1
                        print(
                            f"[RECOVERED BY LLM JUDGE] Job {job_id} ({company}): Restoring to 'completed' (Confidence: {verdict.get('confidence')})"
                        )
                        if not dry_run:
                            cur.execute(
                                """
                                UPDATE job_hunter.jobs
                                SET status_apply = 'completed', manual_intervention_reason = NULL
                                WHERE id = %s
                            """,
                                (job_id,),
                            )
                            cur.execute(
                                """
                                UPDATE job_hunter.applications
                                SET status = 'applied', manual_intervention_reason = NULL
                                WHERE job_id = %s AND status = 'needs_manual_intervention'
                            """,
                                (job_id,),
                            )

            if not dry_run:
                conn.commit()

            return {
                "verified_count": valid_count,
                "invalid_count": invalid_count,
                "recovered_count": recovered_count,
            }
    except Exception as e:
        print(f"Error during LLM Judge verification: {e}")
        if conn:
            conn.rollback()
        return {
            "verified_count": 0,
            "invalid_count": 0,
            "recovered_count": 0,
            "error": str(e),
        }
    finally:
        if conn:
            conn.close()


def run_proof_verification(dry_run=False):
    """Wrapper entry point for graph execution node."""
    return run_verification(dry_run=dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Verify application proofs via LLM as a Judge"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Run without modifying the database"
    )
    args = parser.parse_args()
    run_verification(args.dry_run)
