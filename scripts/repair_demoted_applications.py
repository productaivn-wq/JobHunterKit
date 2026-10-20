"""
Data Repair: Recover applications that were wrongly demoted from 'applied' to
'needs_manual_intervention' due to the proof path resolution bug.

The bug: save_application_results() used job_dict = {"id": job_id} (missing source,
keyword, search_location), causing get_job_dirs() to resolve proof_dir to
data/campaigns/default_default_default/ instead of the actual campaign folder.
Proof verification found nothing there and demoted all successful applications.

This script:
1. Finds all applications with status='needs_manual_intervention' and
   manual_intervention_reason containing 'Proof review failed'
2. Re-checks proof using the CORRECT job metadata from the jobs table
3. If valid proof is found, restores status to 'applied' in both tables
"""

import os
import sys

os.environ["PYTHONIOENCODING"] = "utf-8"
from pathlib import Path

skill_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(skill_root))
sys.path.insert(0, str(skill_root / "scripts"))

from core.db_client import get_connection
from scripts.verify_application_proofs import verify_proof_file
from shared_platform.paths import get_job_dirs

DRY_RUN = "--apply" not in sys.argv

if DRY_RUN:
    print("=" * 70)
    print("DRY RUN MODE — pass --apply to actually fix the data")
    print("=" * 70)

conn = get_connection()
cur = conn.cursor()

# Find wrongly demoted applications
cur.execute("""
    SELECT a.id, a.job_id, j.source, j.keyword, j.search_location, j.scraped_at,
           j.company, j.title, j.status_apply
    FROM job_hunter.applications a
    JOIN job_hunter.jobs j ON a.job_id = j.id
    WHERE a.status = 'needs_manual_intervention'
      AND (a.manual_intervention_reason LIKE '%Proof review failed%'
           OR a.error_message LIKE '%Proof review failed%')
    ORDER BY a.applied_at DESC;
""")
candidates = cur.fetchall()
print(f"\nFound {len(candidates)} applications demoted by proof verification.\n")

recovered = 0
still_invalid = 0

for (
    app_id,
    job_id,
    source,
    keyword,
    search_location,
    scraped_at,
    company,
    title,
    job_status_apply,
) in candidates:
    # Build correct job_dict with full metadata
    job_dict = {
        "id": job_id,
        "source": source,
        "keyword": keyword,
        "search_location": search_location,
        "scraped_at": scraped_at,
    }
    dirs = get_job_dirs(job_dict)
    proof_dir = dirs.get("proof_dir")

    has_valid_proof = False
    proof_file_found = None

    # Match this job's proof only. Two filename conventions:
    #   services/applying.py:     proof_submitted_{job_id}.png
    #   core/apply_mechanics.py:  *__{job_id}.png
    exact_name = f"proof_submitted_{job_id}.png"
    dunder_suffix = f"__{job_id}.png"

    # Check actual campaign proof directory
    if proof_dir and os.path.exists(proof_dir):
        png_files = [f for f in os.listdir(proof_dir) if f.endswith(".png")]
        for f in png_files:
            fp = os.path.join(proof_dir, f)
            is_this_job = f == exact_name or f.endswith(dunder_suffix)
            if is_this_job and verify_proof_file(fp):
                has_valid_proof = True
                proof_file_found = fp
                break

    # Fallback: search across all campaign folders
    if not has_valid_proof:
        search_dirs = [
            os.path.join(str(skill_root), "data", "campaigns"),
            r".\data\campaigns",
        ]
        for campaigns_dir in search_dirs:
            if os.path.exists(campaigns_dir):
                for root, _, files in os.walk(campaigns_dir):
                    for f in files:
                        is_this_job = f == exact_name or f.endswith(dunder_suffix)
                        if is_this_job and verify_proof_file(os.path.join(root, f)):
                            has_valid_proof = True
                            proof_file_found = os.path.join(root, f)
                            break
                    if has_valid_proof:
                        break
            if has_valid_proof:
                break

    if has_valid_proof:
        recovered += 1
        safe_company = (company or "?").encode("ascii", "replace").decode()
        safe_title = (title or "?").encode("ascii", "replace").decode()
        print(
            f"  [RECOVER] app_id={app_id} job_id={job_id} | {safe_company} - {safe_title}"
        )
        print(f"            Proof found: {proof_file_found}")
        if not DRY_RUN:
            cur.execute(
                "UPDATE job_hunter.applications SET status = 'applied', "
                "manual_intervention_reason = NULL, error_message = NULL "
                "WHERE id = %s;",
                (app_id,),
            )
            # Also fix jobs table if still stuck
            if job_status_apply == "needs_manual_intervention":
                cur.execute(
                    "UPDATE job_hunter.jobs SET status_apply = 'completed', "
                    "manual_intervention_reason = NULL WHERE id = %s;",
                    (job_id,),
                )
    else:
        still_invalid += 1

print(f"\n{'=' * 70}")
print(f"Results: {recovered} recoverable | {still_invalid} genuinely invalid")
print(f"{'=' * 70}")

if not DRY_RUN and recovered > 0:
    conn.commit()
    print(f"COMMITTED: {recovered} applications restored to 'applied'.")
else:
    if DRY_RUN:
        print("DRY RUN complete. Run with --apply to commit fixes.")
    conn.rollback()

cur.close()
conn.close()
